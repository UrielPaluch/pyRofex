# -*- coding: utf-8 -*-
"""Offline codec, logon, and market-data request tests. No sockets."""

import unittest

from pyRofex.fix.codec import (
    body_length_ok,
    body_length_parts,
    checksum_ok,
    checksum_value,
    encode_pairs,
    parse_frame,
)
from pyRofex.fix.constants import ALLOWED_OUTBOUND_MSG_TYPES
from pyRofex.fix.errors import FixMarketDataOnlyError
from pyRofex.fix.messages import (
    build_frame,
    check_depth,
    logon_body,
    market_data_request_body,
)

from fixutil import SENDING_TIME, first, values


def _tags(pairs):
    return [tag for tag, _value in pairs]


class CodecTests(unittest.TestCase):
    def test_checksum_and_body_length_match_the_fix_definition(self):
        raw = encode_pairs([
            (8, "FIXT.1.1"),
            (35, "0"),
            (34, "1"),
            (49, "U"),
            (52, SENDING_TIME),
            (56, "ROFX"),
            (1128, "9"),
        ])
        self.assertTrue(raw.endswith(b"\x01"))
        marker = b"\x0110="
        index = raw.rfind(marker)
        covered = raw[:index + 1]
        declared = raw[index + 4:index + 7]
        self.assertEqual(declared, "{:03d}".format(sum(covered) % 256).encode("ascii"))
        self.assertEqual(int(declared), checksum_value(raw))
        self.assertTrue(checksum_ok(raw))

        first_soh = raw.find(b"\x01")
        second_soh = raw.find(b"\x01", first_soh + 1)
        declared_length, actual = body_length_parts(raw)
        self.assertEqual(declared_length, actual)
        self.assertEqual(actual, index - second_soh)
        self.assertTrue(body_length_ok(raw))

        broken = bytearray(raw)
        broken[-2] = ord("0") if broken[-2] != ord("0") else ord("1")
        self.assertFalse(checksum_ok(bytes(broken)))

    def test_logon_carries_fixt_credentials_and_no_order_fields(self):
        encoded, pairs = build_frame(
            "A",
            logon_body("demo-user", "p@ss=word", 30),
            seq=1,
            sender="demo-user",
            target="ROFX",
            sending_time=SENDING_TIME,
        )
        self.assertTrue(checksum_ok(encoded))
        self.assertTrue(body_length_ok(encoded))
        self.assertEqual(_tags(pairs)[:8], [8, 9, 35, 34, 49, 52, 56, 1128])
        self.assertEqual(first(pairs, 8), "FIXT.1.1")
        self.assertEqual(first(pairs, 35), "A")
        self.assertEqual(first(pairs, 49), "demo-user")
        self.assertEqual(first(pairs, 56), "ROFX")
        self.assertEqual(first(pairs, 98), "0")
        self.assertEqual(first(pairs, 108), "30")
        self.assertEqual(first(pairs, 553), "demo-user")
        self.assertEqual(first(pairs, 554), "p@ss=word")
        self.assertEqual(first(pairs, 1137), "9")
        self.assertEqual(first(pairs, 1128), "9")
        self.assertIsNone(first(pairs, 141))
        for order_tag in (11, 38, 40, 54, 59):
            self.assertIsNone(first(pairs, order_tag))
        self.assertEqual(len(first(pairs, 10)), 3)

    def test_logon_reset_seq_is_opt_in(self):
        _encoded, pairs = build_frame(
            "A",
            logon_body("demo-user", "secret", 10, reset_seq_num=True),
            seq=1,
            sender="demo-user",
            target="ROFX",
            sending_time=SENDING_TIME,
        )
        self.assertEqual(first(pairs, 141), "Y")
        self.assertEqual(first(pairs, 108), "10")

    def test_heartbeat_interval_below_roe_minimum_is_rejected(self):
        with self.assertRaises(ValueError):
            logon_body("user", "secret", 9)

    def test_market_data_request_snapshot_plus_full_refresh(self):
        encoded, pairs = build_frame(
            "V",
            market_data_request_body(
                "md1", ["DLR/NOV26"], ["0", "1", "2"], 5, "1", aggregated=True
            ),
            seq=2,
            sender="demo-user",
            target="ROFX",
            sending_time=SENDING_TIME,
        )
        self.assertTrue(checksum_ok(encoded))
        self.assertTrue(body_length_ok(encoded))
        self.assertEqual(first(pairs, 35), "V")
        self.assertEqual(first(pairs, 262), "md1")
        self.assertEqual(first(pairs, 263), "1")
        self.assertEqual(first(pairs, 264), "5")
        self.assertEqual(first(pairs, 265), "0")
        self.assertEqual(first(pairs, 266), "Y")
        self.assertEqual(first(pairs, 267), "3")
        self.assertEqual(values(pairs, 269), ["0", "1", "2"])
        self.assertEqual(first(pairs, 146), "1")
        self.assertEqual(values(pairs, 55), ["DLR/NOV26"])
        self.assertEqual(first(pairs, 207), "ROFX")
        # ROE order: request fields, then entry types, then symbols.
        self.assertLess(pairs.index((262, "md1")), pairs.index((269, "0")))
        self.assertLess(pairs.index((269, "2")), pairs.index((55, "DLR/NOV26")))

    def test_snapshot_only_omits_md_update_type(self):
        _encoded, pairs = build_frame(
            "V",
            market_data_request_body("md1", ["DLR/NOV26", "DLR/DIC26"], ["0"], 1, "0"),
            seq=2,
            sender="demo-user",
            target="ROFX",
            sending_time=SENDING_TIME,
        )
        self.assertEqual(first(pairs, 263), "0")
        self.assertIsNone(first(pairs, 265))
        self.assertEqual(values(pairs, 55), ["DLR/NOV26", "DLR/DIC26"])
        self.assertEqual(first(pairs, 146), "2")

    def test_unsubscribe_reuses_md_req_id(self):
        _encoded, pairs = build_frame(
            "V",
            market_data_request_body("md1", ["DLR/NOV26"], ["2"], 5, "2"),
            seq=3,
            sender="demo-user",
            target="ROFX",
            sending_time=SENDING_TIME,
        )
        self.assertEqual(first(pairs, 263), "2")
        self.assertEqual(first(pairs, 262), "md1")
        self.assertIsNone(first(pairs, 265))

    def test_depth_limits(self):
        self.assertEqual(check_depth(0), 0)
        self.assertEqual(check_depth(5), 5)
        with self.assertRaises(ValueError):
            check_depth(6)
        with self.assertRaises(ValueError):
            check_depth(True)
        with self.assertRaises(ValueError):
            market_data_request_body("md1", ["DLR/NOV26"], ["0"], 6, "1")

    def test_order_message_types_cannot_be_built(self):
        for msg_type in ("D", "F", "G", "H", "q", "AF", "8", "9", "J"):
            self.assertNotIn(msg_type, ALLOWED_OUTBOUND_MSG_TYPES)
            with self.assertRaises(FixMarketDataOnlyError):
                build_frame(
                    msg_type,
                    [(55, "DLR/NOV26"), (54, "1")],
                    seq=1,
                    sender="demo-user",
                    target="ROFX",
                    sending_time=SENDING_TIME,
                )

    def test_round_trip_preserves_unknown_tags(self):
        raw = encode_pairs([
            (8, "FIXT.1.1"),
            (35, "W"),
            (34, "2"),
            (49, "ROFX"),
            (52, SENDING_TIME),
            (56, "demo-user"),
            (9999, "kept"),
        ])
        pairs = parse_frame(raw)
        self.assertEqual(first(pairs, 9999), "kept")
        self.assertTrue(checksum_ok(raw))
        self.assertTrue(body_length_ok(raw))


if __name__ == "__main__":
    unittest.main()
