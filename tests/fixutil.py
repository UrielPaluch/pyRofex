# -*- coding: utf-8 -*-
"""Offline FIX fixtures. Nothing in here opens a socket."""

import socket
from datetime import datetime, timedelta, timezone

from pyRofex.fix.codec import encode_pairs, parse_frame
from pyRofex.fix.messages import format_sending_time


SENDING_TIME = "20261108-15:00:00.000"


class FakeClock(object):
    def __init__(self, step=0.5, wall=None):
        self.t = 1_000.0
        self.step = step
        self._wall = wall or datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc)

    def monotonic(self):
        return self.t

    def on_idle(self):
        self.t += self.step

    def sending_time(self):
        return format_sending_time(self._wall)

    def received_at(self):
        return "2026-11-08T13:00:00.000000-03:00"

    def wall(self):
        return self._wall

    def advance(self, seconds):
        self.t += seconds


def outside_hours_clock():
    """22:30 in Buenos Aires (UTC-3), outside 09:00-19:00."""
    wall = datetime(2026, 11, 8, 22, 30, tzinfo=timezone(timedelta(hours=-3)))
    return FakeClock(wall=wall.astimezone(timezone.utc))


def frame(msg_type, body, seq, sender, target, sending_time=SENDING_TIME):
    """Encode a frame without the market-data-only allow list.

    Tests use this to build exchange messages such as snapshot ``W``, which
    the client is not allowed to send.
    """
    pairs = [
        (8, "FIXT.1.1"),
        (35, msg_type),
        (34, str(seq)),
        (49, sender),
        (52, sending_time),
        (56, target),
        (1128, "9"),
    ]
    pairs.extend(body)
    return encode_pairs(pairs)


def frames_of(raw):
    """Split a concatenation of FIX frames into pair lists."""
    from simplefix import FixParser

    parser = FixParser()
    # simplefix only treats a real bytes object as wire data. A bytearray
    # would be stringified.
    parser.append_buffer(bytes(raw))
    found = []
    while True:
        message = parser.get_message()
        if message is None:
            break
        found.append(parse_frame(message.encode(raw=True)))
    return found


def first(pairs, tag):
    for item_tag, value in pairs:
        if item_tag == tag:
            return value
    return None


def values(pairs, tag):
    return [value for item_tag, value in pairs if item_tag == tag]


class ScriptedExchange(object):
    """Socket stand-in that answers Logon, Market Data Request, and Logout."""

    def __init__(self, eof_when_idle=False, snapshot_body=None):
        self.inbox = []
        self.sent = bytearray()
        self.eof_when_idle = eof_when_idle
        self.snapshot_body = snapshot_body
        self.closed = False
        self.user = None
        self.out_seq = 1

    def sendall(self, data):
        if self.closed:
            raise OSError("closed")
        self.sent.extend(data)
        for pairs in frames_of(data):
            self._respond(pairs)

    def _respond(self, pairs):
        msg_type = first(pairs, 35)
        self.user = first(pairs, 49) or self.user
        if msg_type == "A":
            heart = first(pairs, 108) or "30"
            self._queue("A", [
                (98, "0"),
                (108, heart),
                (1137, "9"),
            ])
        elif msg_type == "V":
            body = self.snapshot_body
            if body is None:
                body = default_snapshot_body(first(pairs, 262), first(pairs, 55) or "DLR/NOV26")
            self._queue("W", body)
        elif msg_type == "5":
            self._queue("5", [(58, "bye")])
        elif msg_type == "1":
            test_req = first(pairs, 112)
            body = [(112, test_req)] if test_req else []
            self._queue("0", body)

    def _queue(self, msg_type, body):
        encoded = frame(msg_type, body, self.out_seq, "ROFX", self.user)
        self.out_seq += 1
        self.inbox.append(encoded)

    def push(self, encoded):
        self.inbox.append(encoded)

    def recv(self, _size):
        if self.closed:
            return b""
        if self.inbox:
            return self.inbox.pop(0)
        if self.eof_when_idle:
            return b""
        raise socket.timeout()

    def close(self):
        self.closed = True


def remarkets_smoke_snapshot_body(md_req_id="md1", symbol="DLR/NOV26"):
    """Sanitized ``35=W`` from the reMarkets demo smoke test.

    Username is not in this body (the test frame uses ``demo-user`` as
    TargetCompID). Price, size, date, and time stand in for digits that
    were not copied out of the live message. The tag set matches the
    report: empty bid and offer carry only ``290=0``; the trade carries
    ``277=U``, ``288=*``, ``289=*``, ``7201=1``, and neither 828 nor 54.
    """
    return [
        (55, symbol),
        (207, "ROFX"),
        (262, md_req_id),
        (264, "5"),
        (268, "3"),
        (269, "0"), (290, "0"),
        (269, "1"), (290, "0"),
        (269, "2"),
        (270, "1000.25"),
        (271, "1"),
        (272, "20261108"),
        (273, "16:40:00.000"),
        (277, "U"),
        (288, "*"),
        (289, "*"),
        (7201, "1"),
    ]


def default_snapshot_body(md_req_id, symbol):
    return [
        (55, symbol),
        (207, "ROFX"),
        (262, md_req_id or "md1"),
        (264, "5"),
        (268, "1"),
        (269, "2"),
        (270, "100.5"),
        (271, "3"),
        (272, "20261108"),
        (273, "15:00:02.422"),
        (277, "U"),
        (290, "1"),
        (828, "0"),
        (7201, "1"),
    ]


def article_snapshot_pairs():
    """Snapshot shaped like the public reMarkets capture (no tag 7201)."""
    body = [
        (8, "FIXT.1.1"),
        (9, "0"),
        (35, "W"),
        (34, "12"),
        (49, "ROFX"),
        (52, "20191227-15:00:02.422"),
        (56, "USER"),
        (55, "RFX20Dic19"),
        (207, "ROFX"),
        (262, "sikwu"),
        (264, "5"),
        (268, "11"),
        (269, "0"), (270, "57815"), (271, "3"), (290, "1"),
        (269, "0"), (270, "57710"), (271, "5"), (290, "2"),
        (269, "0"), (270, "57520"), (271, "21"), (290, "3"),
        (269, "0"), (270, "57300"), (271, "1"), (290, "4"),
        (269, "0"), (270, "57279"), (271, "10"), (290, "5"),
        (269, "1"), (270, "57850"), (271, "16"), (290, "1"),
        (269, "1"), (270, "57999"), (271, "14"), (290, "2"),
        (269, "1"), (270, "58118"), (271, "6"), (290, "3"),
        (269, "1"), (270, "58361"), (271, "6"), (290, "4"),
        (269, "1"), (270, "58482"), (271, "10"), (290, "5"),
        (269, "B"), (271, "474"),
    ]
    # Tag 9 is recalculated by the encoder; drop the placeholder before encoding.
    wire_pairs = [(tag, value) for tag, value in body if tag != 9]
    return parse_frame(encode_pairs(wire_pairs))
