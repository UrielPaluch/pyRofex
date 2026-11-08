# -*- coding: utf-8 -*-
"""One FIXT.1.1 session that only sends market-data and session messages.

Sequence handling follows the session protocol without a replay store:

* an inbound gap produces a single Resend Request
* further messages received while that gap is open are buffered, not
  another Resend Request
* a Resend Request aimed at us is answered with one Sequence Reset-GapFill
  (market data is not replayed)
* a second Resend Request for a range already gap-filled logs out

Reconnect is not done here. The client opts into that.
"""

import socket
import ssl

from simplefix import FixParser

from .codec import body_length_ok, checksum_ok, pairs_from_message
from .errors import FixConnectionError, FixMarketDataOnlyError, FixSessionError
from .messages import (
    build_frame,
    heartbeat_body,
    logon_body,
    logout_body,
    market_data_request_body,
    reject_body,
    resend_request_body,
    sequence_reset_body,
    test_request_body,
)
from .parser import parse_message


_MAX_BUFFERED = 20


class FixMdSession(object):
    """FIX session state machine over a caller-supplied socket-like transport."""

    def __init__(self, username, password, sender, target, heartbeat_interval,
                 transport, clock, reset_seq_num=False, on_message=None):
        self.username = username
        self.password = password
        self.sender = sender
        self.target = target
        self.heartbeat_interval = heartbeat_interval
        self.transport = transport
        self.clock = clock
        self.reset_seq_num = reset_seq_num
        self.on_message = on_message

        self.parser = FixParser()
        self.out_seq = 1
        self.in_expected = 1
        self.state = "disconnected"
        self.last_rx = None
        self.last_tx = None
        self.test_req_id = None
        self.test_req_deadline = None
        self._test_counter = 0
        self._logout_sent = False
        self._resend_outstanding = False
        self._gapfill_ranges = set()
        self._buffer = {}
        self.logout_text = None
        self.closed = False

    def start(self):
        """Send Logon. The caller pumps until ``state == 'logged_on'``."""
        if self.transport is None:
            raise FixConnectionError("no transport")
        self.state = "connecting"
        self.out_seq = 1
        self.in_expected = 1
        self._logout_sent = False
        self._resend_outstanding = False
        self._buffer = {}
        body = logon_body(
            self.username,
            self.password,
            self.heartbeat_interval,
            reset_seq_num=self.reset_seq_num,
        )
        self._send("A", body)

    def send_market_data_request(self, md_req_id, symbols, entry_types, depth,
                                 subscription, aggregated=True):
        if self.state != "logged_on":
            raise FixSessionError("market data requires a logged-on session")
        body = market_data_request_body(
            md_req_id, symbols, entry_types, depth, subscription, aggregated
        )
        self._send("V", body)

    def logout(self, text=None):
        """Send Logout once. The caller keeps pumping until the peer answers."""
        if self.state == "disconnected" or self.closed:
            self.close()
            return
        if text:
            self.logout_text = text
        if not self._logout_sent:
            try:
                self._send("5", logout_body(text))
                self._logout_sent = True
            except FixConnectionError:
                self.close()
                return
        self.state = "logging_out"

    def close(self):
        if self.closed:
            self.state = "disconnected"
            return
        self.closed = True
        self.state = "disconnected"
        transport = self.transport
        self.transport = None
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

    def pump(self):
        """Read whatever is available and run heartbeat timers on idle."""
        if self.closed or self.transport is None:
            raise FixConnectionError("FIX connection closed")
        try:
            data = self.transport.recv(65536)
        except (socket.timeout, TimeoutError):
            self.clock.on_idle()
            self.on_timer()
            return
        except ssl.SSLWantReadError:
            self.clock.on_idle()
            self.on_timer()
            return
        if data is None:
            self.clock.on_idle()
            self.on_timer()
            return
        if isinstance(data, bytearray):
            data = bytes(data)
        if data == b"":
            self.close()
            raise FixConnectionError("peer closed the connection")
        for raw in self._frames(data):
            self._on_frame(raw)
        if self.state != "disconnected":
            self.on_timer()

    def on_timer(self):
        """Heartbeat / Test Request schedule. Safe to call from tests."""
        if self.state != "logged_on" or self.closed:
            return
        now = self.clock.monotonic()
        interval = self.heartbeat_interval
        if self.last_tx is None or now - self.last_tx >= interval:
            self._send("0", heartbeat_body())
        if self.test_req_deadline is not None and now >= self.test_req_deadline:
            self.logout("no response to TestRequest")
            return
        if (
            self.last_rx is not None
            and now - self.last_rx >= interval
            and self.test_req_id is None
        ):
            self._test_counter += 1
            self.test_req_id = "TR{}".format(self._test_counter)
            self._send("1", test_request_body(self.test_req_id))
            self.test_req_deadline = now + interval

    def _frames(self, data):
        try:
            from .codec import parse_stream
            return list(parse_stream(self.parser, data))
        except Exception as exc:
            self.logout("could not frame inbound FIX data")
            raise FixSessionError("could not frame inbound FIX data") from exc

    def _on_frame(self, raw):
        try:
            pairs = pairs_from_message(_message_from_raw(raw))
        except Exception:
            self.logout("undecodable FIX frame")
            return
        if not checksum_ok(raw) or not body_length_ok(raw):
            self._send_reject(pairs, "5", "checksum or body length failure")
            return
        msg_type = _first(pairs, 35)
        if msg_type == "4":
            self._on_sequence_reset(pairs, raw)
            return
        if not self._comp_ids_ok(pairs):
            return
        try:
            seq = int(_first(pairs, 34))
        except (TypeError, ValueError):
            self._send_reject(pairs, "1", "MsgSeqNum missing")
            return
        if seq < self.in_expected:
            if _first(pairs, 43) == "Y":
                return
            self.logout("inbound sequence number too low")
            return
        if seq > self.in_expected:
            self._on_gap(seq, pairs, raw)
            return
        self._accept(pairs, raw)

    def _on_gap(self, seq, pairs, raw):
        self._buffer[seq] = (pairs, raw)
        if len(self._buffer) > _MAX_BUFFERED:
            self.logout("inbound sequence gap was not filled")
            return
        if self._resend_outstanding:
            return
        self._resend_outstanding = True
        end = seq - 1
        self._send("2", resend_request_body(self.in_expected, end))

    def _on_sequence_reset(self, pairs, raw):
        if not self._comp_ids_ok(pairs):
            return
        try:
            new_seq = int(_first(pairs, 36))
            seq = int(_first(pairs, 34))
        except (TypeError, ValueError):
            self._send_reject(pairs, "1", "SequenceReset is missing NewSeqNo")
            return
        if new_seq < self.in_expected:
            self.logout("NewSeqNo is lower than the expected sequence")
            return
        gap_fill = (_first(pairs, 123) or "N") == "Y"
        if gap_fill and seq > self.in_expected and not self._resend_outstanding:
            self._on_gap(seq, pairs, raw)
            return
        if gap_fill and seq < self.in_expected and _first(pairs, 43) != "Y":
            self.logout("inbound sequence number too low")
            return
        if gap_fill and seq < self.in_expected:
            return
        self.in_expected = new_seq
        self._resend_outstanding = False
        self.last_rx = self.clock.monotonic()
        self._emit(pairs, raw)
        self._drop_stale_buffer()
        self._drain()

    def _accept(self, pairs, raw):
        self.in_expected += 1
        self._resend_outstanding = False
        self.last_rx = self.clock.monotonic()
        self._dispatch(pairs, raw)
        self._drain()

    def _drain(self):
        while self.in_expected in self._buffer and self.state != "disconnected":
            pairs, raw = self._buffer.pop(self.in_expected)
            self._accept(pairs, raw)

    def _drop_stale_buffer(self):
        for seq in list(self._buffer):
            if seq < self.in_expected:
                del self._buffer[seq]

    def _dispatch(self, pairs, raw):
        msg_type = _first(pairs, 35)
        if self.state == "connecting":
            self._during_logon(msg_type, pairs, raw)
            return
        if msg_type == "5":
            self._emit(pairs, raw)
            self.logout_text = _first(pairs, 58) or self.logout_text
            if not self._logout_sent:
                self._logout_sent = True
                try:
                    self._send("5", logout_body())
                except FixConnectionError:
                    pass
            self.close()
            return
        if msg_type == "1":
            test_req_id = _first(pairs, 112)
            self._send("0", heartbeat_body(test_req_id))
            self._emit(pairs, raw)
            return
        if msg_type == "0":
            echoed = _first(pairs, 112)
            if echoed and echoed == self.test_req_id:
                self.test_req_id = None
                self.test_req_deadline = None
            self._emit(pairs, raw)
            return
        if msg_type == "2":
            self._answer_resend(pairs, raw)
            return
        if msg_type == "3" and self.state == "logging_out":
            self._emit(pairs, raw)
            return
        self._emit(pairs, raw)
        if msg_type == "3":
            self.logout(_first(pairs, 58) or "session reject")

    def _during_logon(self, msg_type, pairs, raw):
        self._emit(pairs, raw)
        if msg_type == "A":
            self.state = "logged_on"
            return
        self.logout_text = _first(pairs, 58) or "logon failed"
        self.close()

    def _answer_resend(self, pairs, raw):
        try:
            begin = int(_first(pairs, 7))
            end = int(_first(pairs, 16))
        except (TypeError, ValueError):
            self._send_reject(pairs, "1", "ResendRequest is missing sequence range")
            self._emit(pairs, raw)
            return
        key = (begin, end)
        if key in self._gapfill_ranges:
            self._emit(pairs, raw)
            self.logout("repeated ResendRequest; not looping")
            return
        # No application-message store: skip the requested range with one
        # GapFill. A request that starts at or beyond our next sequence has
        # nothing to skip.
        if end < 0 or (end != 0 and end < begin) or begin >= self.out_seq:
            self._emit(pairs, raw)
            return
        self._gapfill_ranges.add(key)
        if end == 0:
            new_seq = self.out_seq
        else:
            new_seq = max(end + 1, self.out_seq)
        if new_seq <= begin:
            new_seq = self.out_seq
        now = self.clock.sending_time()
        # GapFill uses the sequence being skipped and does not consume out_seq
        # except to jump it forward to NewSeqNo.
        self._transmit(
            "4",
            sequence_reset_body(new_seq, gap_fill=True),
            seq=begin,
            poss_dup=True,
            orig_sending_time=now,
            advance=False,
        )
        if new_seq > self.out_seq:
            self.out_seq = new_seq
        self._emit(pairs, raw)

    def _comp_ids_ok(self, pairs):
        sender = _first(pairs, 49)
        target = _first(pairs, 56)
        if sender == self.target and target == self.sender:
            return True
        self._send_reject(pairs, "9", "CompID does not match this session")
        self.logout("CompID does not match this session")
        return False

    def _send_reject(self, pairs, reason, text):
        ref = _first(pairs, 34) or "0"
        ref_type = _first(pairs, 35) or "0"
        try:
            ref_int = int(ref)
        except ValueError:
            ref_int = 0
        try:
            self._send("3", reject_body(ref_int, ref_type, reason, text))
        except (FixConnectionError, FixSessionError):
            return

    def _send(self, msg_type, body):
        self._transmit(msg_type, body, seq=self.out_seq, advance=True)

    def _transmit(self, msg_type, body, seq, poss_dup=False, orig_sending_time=None, advance=True):
        if self.closed or self.transport is None:
            raise FixConnectionError("FIX connection closed")
        try:
            encoded, _pairs = build_frame(
                msg_type,
                body,
                seq=seq,
                sender=self.sender,
                target=self.target,
                sending_time=self.clock.sending_time(),
                poss_dup=poss_dup,
                orig_sending_time=orig_sending_time,
            )
        except FixMarketDataOnlyError:
            raise
        self.transport.sendall(encoded)
        self.last_tx = self.clock.monotonic()
        if advance:
            self.out_seq = int(seq) + 1

    def _emit(self, pairs, raw):
        if self.on_message is None:
            return
        record = {
            "received_at": self.clock.received_at(),
            "raw": raw.decode("latin-1"),
            "parsed": parse_message(pairs),
        }
        self.on_message(record)


def _message_from_raw(raw):
    parser = FixParser()
    parser.append_buffer(raw)
    message = parser.get_message()
    if message is None:
        raise ValueError("incomplete frame")
    return message


def _first(pairs, tag):
    for item_tag, value in pairs:
        if item_tag == tag:
            return value
    return None
