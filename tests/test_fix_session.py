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

        def connector(host, port, use_tls, tls_verify, timeout):
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

        def connector(host, port, use_tls, tls_verify, timeout):
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

        def connector(host, port, use_tls, tls_verify, timeout):
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
