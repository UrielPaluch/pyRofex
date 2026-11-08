# -*- coding: utf-8 -*-
"""Session behavior against an in-memory transport. No sockets."""

import unittest
import warnings

import pyRofex
from pyRofex.components.enums import MarketDataEntry
from pyRofex.fix.client import FixMarketDataClient, in_fix_session_hours
from pyRofex.fix.constants import REMARKETS_FIX_HOST, REMARKETS_FIX_PORT
from pyRofex.fix.errors import FixConnectionError, FixMarketDataOnlyError
from pyRofex.fix.session import FixMdSession

from fixutil import (
    FakeClock,
    ScriptedExchange,
    first,
    frame,
    frames_of,
    outside_hours_clock,
    remarkets_smoke_snapshot_body,
    values,
)


def _logged_on(exchange=None, clock=None, **client_kwargs):
    exchange = exchange or ScriptedExchange()
    clock = clock or FakeClock()
    client = FixMarketDataClient(
        "demo-user",
        "s3cret",
        connector=lambda *args, **kwargs: exchange,
        clock=clock,
        sleeper=lambda _seconds: None,
        warn_outside_session_hours=False,
        **client_kwargs,
    )
    client.connect()
    return client, exchange, clock


class SessionTests(unittest.TestCase):
    def test_logon_heartbeat_test_request_and_logout(self):
        client, exchange, clock = _logged_on()
        records = []
        client.on_message = records.append
        client._session.on_message = records.append
        md_req_id = client.subscribe(
            "DLR/NOV26",
            [MarketDataEntry.BIDS, MarketDataEntry.OFFERS, MarketDataEntry.LAST],
            depth=5,
            updates=True,
        )
        self.assertEqual(md_req_id, "md1")
        client._session.pump()
        self.assertEqual(records[-1]["parsed"]["entries"][0]["trade_side"], "BUY")

        # Peer Test Request must be answered with one Heartbeat echoing tag 112.
        exchange.push(frame(
            "1", [(112, "ABC")], 3, "ROFX", "demo-user"
        ))
        sent_before = len(frames_of(exchange.sent))
        client._session.pump()
        heartbeats = [
            pairs for pairs in frames_of(exchange.sent)[sent_before:]
            if first(pairs, 35) == "0"
        ]
        self.assertEqual(len(heartbeats), 1)
        self.assertEqual(first(heartbeats[0], 112), "ABC")

        # Outbound silence with fresh inbound traffic: Heartbeat only.
        clock.advance(30)
        client._session.last_rx = clock.monotonic()
        client._session.on_timer()
        outbound = frames_of(exchange.sent)
        self.assertEqual(first(outbound[-1], 35), "0")
        self.assertIsNone(first(outbound[-1], 112))

        # Inbound silence after that: one Test Request, not a second one.
        clock.advance(30)
        client._session.last_rx = clock.monotonic() - 30
        client._session.on_timer()
        self.assertEqual(first(frames_of(exchange.sent)[-1], 35), "1")
        clock.advance(30)
        client._session.on_timer()
        self.assertEqual(client._session.state, "logging_out")
        self.assertEqual(first(frames_of(exchange.sent)[-1], 35), "5")

    def test_sequence_gap_sends_one_resend_then_stops(self):
        client, exchange, _clock = _logged_on()
        session = client._session
        seen = []
        session.on_message = seen.append
        exchange.push(frame("0", [], 4, "ROFX", "demo-user"))
        session.pump()
        resends = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "2"]
        self.assertEqual(len(resends), 1)
        self.assertEqual(first(resends[0], 7), "2")
        self.assertEqual(first(resends[0], 16), "3")
        self.assertEqual(seen, [])

        exchange.push(frame("0", [], 5, "ROFX", "demo-user"))
        session.pump()
        resends = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "2"]
        self.assertEqual(len(resends), 1)

        exchange.push(frame(
            "4", [(123, "Y"), (36, "4")], 2, "ROFX", "demo-user"
        ))
        session.pump()
        self.assertEqual(session.in_expected, 6)
        self.assertEqual(
            [record["parsed"]["msg_seq_num"] for record in seen],
            ["2", "4", "5"],
        )

    def test_inbound_resend_is_one_gap_fill_and_does_not_loop(self):
        client, exchange, _clock = _logged_on()
        session = client._session
        client.subscribe("DLR/NOV26", ["LA"], depth=1, updates=False)
        session.pump()  # take the snapshot so it does not sit ahead of the resend
        exchange.push(frame(
            "2", [(7, "2"), (16, "0")], 3, "ROFX", "demo-user"
        ))
        session.pump()
        gap_fills = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "4"]
        self.assertEqual(len(gap_fills), 1)
        self.assertEqual(first(gap_fills[0], 123), "Y")
        self.assertEqual(first(gap_fills[0], 43), "Y")
        self.assertEqual(first(gap_fills[0], 34), "2")
        new_seq = int(first(gap_fills[0], 36))
        self.assertGreater(new_seq, 2)
        self.assertEqual(session.out_seq, new_seq)

        exchange.push(frame(
            "2", [(7, "2"), (16, "0")], 4, "ROFX", "demo-user"
        ))
        session.pump()
        gap_fills = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "4"]
        self.assertEqual(len(gap_fills), 1)
        self.assertEqual(session.state, "logging_out")

    def test_bad_checksum_is_rejected_and_not_delivered(self):
        client, exchange, _clock = _logged_on()
        session = client._session
        seen = []
        session.on_message = seen.append
        good = frame("0", [], 2, "ROFX", "demo-user")
        broken = bytearray(good)
        broken[-2] = ord("0") if broken[-2] != ord("0") else ord("1")
        exchange.push(bytes(broken))
        session.pump()
        self.assertEqual(seen, [])
        rejects = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "3"]
        self.assertEqual(len(rejects), 1)
        self.assertEqual(first(rejects[0], 45), "2")
        self.assertEqual(session.in_expected, 2)

    def test_order_send_is_refused_without_writing(self):
        client, exchange, _clock = _logged_on()
        before = bytes(exchange.sent)
        with self.assertRaises(FixMarketDataOnlyError):
            client._session._send("D", [(11, "abc"), (55, "DLR/NOV26"), (54, "1")])
        self.assertEqual(bytes(exchange.sent), before)
        self.assertFalse(hasattr(client, "send_order"))

    def test_partial_tcp_chunks_reassemble(self):
        client, exchange, _clock = _logged_on()
        seen = []
        client._session.on_message = seen.append
        raw = frame("0", [], 2, "ROFX", "demo-user")
        exchange.push(raw[:10])
        client._session.pump()
        self.assertEqual(seen, [])
        exchange.push(raw[10:])
        client._session.pump()
        self.assertEqual(seen[0]["parsed"]["msg_type"], "0")

    def test_default_host_is_remarkets_and_reconnect_is_off(self):
        created = []

        def connector(host, port, use_tls, tls_verify, timeout, cafile=None):
            created.append((host, port, use_tls, tls_verify))
            return ScriptedExchange()

        client = FixMarketDataClient(
            "demo-user",
            "s3cret",
            connector=connector,
            clock=FakeClock(),
            warn_outside_session_hours=False,
        )
        self.assertEqual(client.host, REMARKETS_FIX_HOST)
        self.assertEqual(client.port, REMARKETS_FIX_PORT)
        self.assertFalse(client.reconnect)
        self.assertTrue(client.use_tls)
        client.connect()
        self.assertEqual(created, [(REMARKETS_FIX_HOST, REMARKETS_FIX_PORT, True, True)])
        explicit = FixMarketDataClient(
            "demo-user",
            "s3cret",
            host="fix.example.invalid",
            port=443,
            connector=connector,
            clock=FakeClock(),
            warn_outside_session_hours=False,
        )
        explicit.connect()
        self.assertEqual(created[-1][0], "fix.example.invalid")
        self.assertEqual(created[-1][1], 443)

    def test_peer_drop_does_not_reconnect_unless_asked(self):
        exchange = ScriptedExchange(eof_when_idle=True)
        client, _exchange, clock = _logged_on(exchange)
        client.subscribe("DLR/NOV26", ["BI", "OF", "LA"], depth=5)
        with self.assertRaises(FixConnectionError):
            client.run(5)
        self.assertEqual(client.reconnect, False)

        calls = {"n": 0}

        def connector(host, port, use_tls, tls_verify, timeout, cafile=None):
            calls["n"] += 1
            # First session ends as soon as it is idle. The second stays up.
            return ScriptedExchange(eof_when_idle=calls["n"] == 1)

        clock = FakeClock()
        client = FixMarketDataClient(
            "demo-user",
            "s3cret",
            reconnect=True,
            reconnect_attempts=1,
            connector=connector,
            clock=clock,
            sleeper=lambda _seconds: None,
            warn_outside_session_hours=False,
        )
        client.connect()
        client.subscribe("DLR/NOV26", ["LA"], depth=1)
        client.run(1)
        self.assertEqual(calls["n"], 2)

    def test_reconnect_restores_the_market_data_request(self):
        transports = []

        def connector(host, port, use_tls, tls_verify, timeout, cafile=None):
            exchange = ScriptedExchange(eof_when_idle=len(transports) == 0)
            transports.append(exchange)
            return exchange

        client = FixMarketDataClient(
            "demo-user",
            "s3cret",
            reconnect=True,
            reconnect_attempts=1,
            connector=connector,
            clock=FakeClock(),
            sleeper=lambda _seconds: None,
            warn_outside_session_hours=False,
        )
        client.connect()
        client.subscribe("DLR/NOV26", ["BI", "OF"], depth=5, updates=True)
        client.run(1)
        self.assertEqual(len(transports), 2)
        first_requests = [
            pairs for pairs in frames_of(transports[0].sent) if first(pairs, 35) == "V"
        ]
        second_requests = [
            pairs for pairs in frames_of(transports[1].sent) if first(pairs, 35) == "V"
        ]
        self.assertEqual(len(first_requests), 1)
        self.assertEqual(len(second_requests), 1)
        self.assertEqual(first(first_requests[0], 262), first(second_requests[0], 262))
        self.assertEqual(first(second_requests[0], 263), "1")
        self.assertEqual(values(second_requests[0], 269), ["0", "1"])

    def test_unsubscribe_sends_disable(self):
        client, exchange, _clock = _logged_on()
        md_req_id = client.subscribe("DLR/NOV26", ["LA"], depth=1, updates=True)
        client.unsubscribe(md_req_id)
        requests = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "V"]
        self.assertEqual(first(requests[0], 263), "1")
        self.assertEqual(first(requests[1], 263), "2")
        self.assertEqual(first(requests[0], 262), first(requests[1], 262))

    def test_reference_entries_and_reject_is_not_retried(self):
        client, exchange, _clock = _logged_on()
        md_req_id = client.subscribe(
            "DLR/NOV26",
            [MarketDataEntry.BIDS, "OF", "LA", MarketDataEntry.OPENING_PRICE,
             "CL", "SE", "HI", "LO", "TV", "OI"],
            depth=1,
        )
        requests = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "V"]
        self.assertEqual(
            values(requests[-1], 269),
            ["0", "1", "2", "4", "5", "6", "7", "8", "B", "C"],
        )
        seen = []
        client.on_message = seen.append
        exchange.push(frame(
            "Y",
            [(262, md_req_id), (281, "8"), (58, "Unsupported MDEntryType")],
            3,
            "ROFX",
            "demo-user",
        ))
        client._session.pump()
        client._session.pump()
        reject = seen[-1]["parsed"]
        self.assertEqual(reject["msg_type"], "Y")
        self.assertEqual(reject["md_req_rej_reason"], "8")
        self.assertEqual(reject["md_req_rej_reason_name"], "UNSUPPORTED_MD_ENTRY_TYPE")
        self.assertTrue(reject["rejected"])
        self.assertTrue(client._subscriptions[md_req_id]["rejected"])
        client._session.pump()
        requests = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "V"]
        self.assertEqual(len(requests), 1)

    def test_rejected_subscription_is_not_restored(self):
        transports = []

        def connector(host, port, use_tls, tls_verify, timeout, cafile=None):
            exchange = ScriptedExchange(eof_when_idle=len(transports) == 0)
            transports.append(exchange)
            return exchange

        client = FixMarketDataClient(
            "demo-user",
            "s3cret",
            reconnect=True,
            reconnect_attempts=1,
            connector=connector,
            clock=FakeClock(),
            sleeper=lambda _seconds: None,
            warn_outside_session_hours=False,
        )
        client.connect()
        md_req_id = client.subscribe("DLR/NOV26", ["OP", "SE", "OI"], depth=1)
        transports[0].push(frame(
            "Y",
            [(262, md_req_id), (281, "8"), (58, "Unsupported MDEntryType")],
            3,
            "ROFX",
            "demo-user",
        ))
        client.run(1)
        restored = [
            pairs for pairs in frames_of(transports[1].sent) if first(pairs, 35) == "V"
        ]
        self.assertEqual(restored, [])
        self.assertEqual(
            values(next(pairs for pairs in frames_of(transports[0].sent) if first(pairs, 35) == "V"), 269),
            ["4", "6", "C"],
        )

    def test_comp_id_mismatch_logs_out(self):
        client, exchange, _clock = _logged_on()
        exchange.push(frame("0", [], 2, "OTHER", "demo-user"))
        client._session.pump()
        self.assertEqual(client._session.state, "logging_out")
        rejects = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "3"]
        self.assertTrue(rejects)
        self.assertEqual(first(rejects[0], 373), "9")

    def test_outside_session_hours_warns_but_still_connects(self):
        clock = outside_hours_clock()
        self.assertFalse(in_fix_session_hours(clock.wall()))
        exchange = ScriptedExchange()

        def connector(*_args, **_kwargs):
            return exchange

        client = FixMarketDataClient(
            "demo-user",
            "s3cret",
            connector=connector,
            clock=clock,
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            client.connect()
        self.assertTrue(any("09:00-19:00" in str(item.message) for item in caught))
        self.assertEqual(client._session.state, "logged_on")

    def test_password_is_not_in_repr(self):
        client = FixMarketDataClient(
            "demo-user",
            "s3cret-value",
            connector=lambda *a, **k: ScriptedExchange(),
            clock=FakeClock(),
            warn_outside_session_hours=False,
        )
        self.assertNotIn("s3cret-value", repr(client))

    def test_trading_session_status_burst_is_logged_and_tr1_echo_clears(self):
        client, exchange, clock = _logged_on()
        session = client._session
        seen = []
        session.on_message = seen.append
        exchange.push(frame(
            "W", remarkets_smoke_snapshot_body(), 2, "ROFX", "demo-user"
        ))
        statuses = b"".join(
            frame("h", [(325, "Y"), (336, "1"), (340, "2")], seq, "ROFX", "demo-user")
            for seq in range(3, 53)
        )
        exchange.push(statuses)
        session.pump()
        session.pump()
        self.assertEqual(session.state, "logged_on")
        self.assertEqual(session.in_expected, 53)
        types = [record["parsed"]["msg_type"] for record in seen]
        self.assertEqual(types[0], "W")
        self.assertEqual(types[1:], ["h"] * 50)
        trade = seen[0]["parsed"]["entries"][2]
        self.assertEqual(trade["trade_side"], "BUY")
        self.assertEqual(trade["trade_condition"], "U")

        session.last_tx = clock.monotonic()
        session.last_rx = clock.monotonic() - session.heartbeat_interval
        exchange.out_seq = session.in_expected
        session.on_timer()
        test_requests = [
            pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "1"
        ]
        self.assertEqual(first(test_requests[-1], 112), "TR1")
        session.pump()
        self.assertIsNone(session.test_req_id)
        self.assertEqual(session.state, "logged_on")
        self.assertEqual(seen[-1]["parsed"]["msg_type"], "0")
        echoed = [
            item["value"] for item in seen[-1]["parsed"]["tags"] if item["tag"] == 112
        ]
        self.assertEqual(echoed, ["TR1"])

    def test_execution_report_does_not_set_trade_side(self):
        # Live sequence: a snapshot with two trade entries, then an
        # unsolicited Execution Report for the account order on that print.
        client, exchange, _clock = _logged_on()
        session = client._session
        seen = []
        session.on_message = seen.append
        snapshot = [
            (55, "DLR/NOV26"),
            (207, "ROFX"),
            (262, "md1"),
            (268, "2"),
            (269, "2"), (273, "17:35:33.974"), (277, "U"), (7201, "2"),
            (269, "2"), (828, "0"),
        ]
        exchange.push(frame("W", snapshot, 2, "ROFX", "demo-user"))
        exchange.push(frame(
            "8",
            [(37, "118697268"), (39, "2"), (54, "1")],
            3,
            "ROFX",
            "demo-user",
        ))
        session.pump()
        session.pump()

        self.assertEqual([item["parsed"]["msg_type"] for item in seen], ["W", "8"])
        trades = [
            entry for entry in seen[0]["parsed"]["entries"]
            if entry["md_entry_type"] == "2"
        ]
        self.assertEqual(len(trades), 2)
        exchange_last, reported = trades
        self.assertEqual(exchange_last["md_entry_time"], "17:35:33.974")
        self.assertEqual(exchange_last["trade_condition"], "U")
        self.assertEqual(exchange_last["trade_side"], "SELL")
        self.assertIsNone(exchange_last["trd_type"])
        self.assertTrue(any(
            tag["tag"] == 7201 and tag["value"] == "2" for tag in exchange_last["tags"]
        ))
        self.assertIsNone(reported["trade_side"])
        self.assertIsNone(reported["trade_condition"])
        self.assertEqual(reported["trd_type"], "0")
        self.assertFalse(any(tag["tag"] == 7201 for tag in reported["tags"]))
        self.assertNotEqual(exchange_last["tags"], reported["tags"])

        execution = seen[1]["parsed"]
        self.assertTrue(execution["unsolicited"])
        self.assertNotIn("trade_side", execution)
        self.assertNotIn("entries", execution)
        self.assertEqual(execution["order_id"], "118697268")
        self.assertEqual(execution["ord_status"], "2")
        self.assertEqual(execution["order_side"], "1")
        self.assertIn({"tag": 54, "value": "1"}, execution["tags"])
        self.assertEqual(seen[0]["parsed"]["entries"][0]["trade_side"], "SELL")

    def test_peer_logout_is_answered_once(self):
        client, exchange, _clock = _logged_on()
        exchange.push(frame("5", [(58, "session ended")], 2, "ROFX", "demo-user"))
        client._session.pump()
        logouts = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "5"]
        self.assertEqual(len(logouts), 1)
        self.assertTrue(exchange.closed)


class ImportTests(unittest.TestCase):
    def test_public_rest_api_is_unchanged_and_fix_is_not_imported_with_it(self):
        import sys
        sys.modules.pop("pyRofex.fix", None)
        sys.modules.pop("pyRofex.fix.client", None)
        import importlib
        importlib.reload(pyRofex)
        self.assertTrue(hasattr(pyRofex, "initialize"))
        self.assertTrue(hasattr(pyRofex, "get_market_data"))
        self.assertTrue(hasattr(pyRofex, "market_data_subscription"))
        self.assertFalse(hasattr(pyRofex, "FixMarketDataClient"))
        self.assertEqual(pyRofex.MarketDataEntry.BIDS.value, "BI")
        self.assertEqual(pyRofex.MarketDataEntry.OFFERS.value, "OF")
        self.assertEqual(pyRofex.MarketDataEntry.LAST.value, "LA")
        self.assertNotIn("pyRofex.fix.client", sys.modules)
        from pyRofex.service import _validate_handler
        _validate_handler(lambda message: None)

    def test_socket_create_connection_is_not_used_by_these_tests(self):
        # The default connector is the only network entry point. Constructing
        # the client and parsing messages must not call it.
        import pyRofex.fix.client as client_module
        original = client_module.socket.create_connection

        def boom(*_args, **_kwargs):
            raise AssertionError("network")

        client_module.socket.create_connection = boom
        try:
            FixMarketDataClient(
                "demo-user",
                "s3cret",
                connector=lambda *a, **k: ScriptedExchange(),
                clock=FakeClock(),
                warn_outside_session_hours=False,
            ).connect()
        finally:
            client_module.socket.create_connection = original


if __name__ == "__main__":
    unittest.main()
