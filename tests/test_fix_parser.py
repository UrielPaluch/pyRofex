# -*- coding: utf-8 -*-
"""Offline Market Data Snapshot / Incremental parser tests. No sockets."""

import json
import unittest

from pyRofex.fix.codec import encode_pairs, parse_frame
from pyRofex.fix.parser import parse_message

from fixutil import SENDING_TIME, article_snapshot_pairs, first, remarkets_smoke_snapshot_body


def _encode(body):
    pairs = [
        (8, "FIXT.1.1"),
        (35, "W"),
        (34, "2"),
        (49, "ROFX"),
        (52, SENDING_TIME),
        (56, "demo-user"),
    ]
    pairs.extend(body)
    return parse_frame(encode_pairs(pairs))


class ParserTests(unittest.TestCase):
    def test_sanitized_remarkets_snapshot_empty_book_and_trade_side(self):
        pairs = [
            (8, "FIXT.1.1"),
            (35, "W"),
            (34, "2"),
            (49, "ROFX"),
            (52, SENDING_TIME),
            (56, "demo-user"),
        ]
        pairs.extend(remarkets_smoke_snapshot_body())
        parsed = parse_message(parse_frame(encode_pairs(pairs)))
        self.assertEqual(parsed["symbol"], "DLR/NOV26")
        self.assertEqual(parsed["no_md_entries"], "3")
        self.assertEqual(len(parsed["entries"]), 3)
        bid, offer, trade = parsed["entries"]
        self.assertEqual(
            [(item["tag"], item["value"]) for item in bid["tags"]],
            [(269, "0"), (290, "0")],
        )
        self.assertEqual(
            [(item["tag"], item["value"]) for item in offer["tags"]],
            [(269, "1"), (290, "0")],
        )
        self.assertIsNone(bid["md_entry_px"])
        self.assertIsNone(bid["md_entry_size"])
        self.assertIsNone(bid["trade_side"])
        self.assertEqual(bid["md_entry_position_no"], "0")
        self.assertIsNone(offer["trade_side"])
        self.assertEqual(trade["md_entry_type"], "2")
        self.assertEqual(trade["trade_condition"], "U")
        self.assertEqual(trade["trade_side"], "BUY")
        self.assertEqual(trade["md_entry_buyer"], "*")
        self.assertEqual(trade["md_entry_seller"], "*")
        self.assertIsNone(trade["trd_type"])
        self.assertFalse(any(item["tag"] == 54 for item in trade["tags"]))
        self.assertFalse(any(item["tag"] == 828 for item in parsed["tags"]))
        self.assertNotIn("aggressor", json.dumps(parsed))
    def test_trade_side_buy_and_sell_come_only_from_tag_7201(self):
        pairs = _encode([
            (55, "DLR/NOV26"),
            (207, "ROFX"),
            (262, "md1"),
            (268, "3"),
            (269, "2"), (270, "100.5"), (271, "3"), (277, "U"), (828, "0"), (7201, "1"),
            (269, "2"), (270, "100.5"), (271, "1"), (277, "U"), (7201, "2"),
            (269, "0"), (270, "100.0"), (271, "8"), (290, "1"), (54, "1"),
        ])
        parsed = parse_message(pairs)
        self.assertEqual(parsed["msg_type"], "W")
        self.assertEqual(parsed["symbol"], "DLR/NOV26")
        self.assertEqual(len(parsed["entries"]), 3)
        buy, sell, bid = parsed["entries"]
        self.assertEqual(buy["trade_side"], "BUY")
        self.assertEqual(buy["trade_condition"], "U")
        self.assertEqual(buy["trd_type"], "0")
        self.assertEqual(buy["md_entry_px"], "100.5")
        self.assertEqual(sell["trade_side"], "SELL")
        self.assertEqual(sell["trade_condition"], "U")
        # Tag 54 on a bid is not a trade side, and a bid is not inferred as BUY.
        self.assertIsNone(bid["trade_side"])
        self.assertEqual(bid["md_entry_type"], "0")
        self.assertIn({"tag": 54, "value": "1"}, bid["tags"])
        blob = json.dumps(parsed)
        self.assertNotIn("aggressor", blob)

    def test_missing_7201_is_none_on_every_entry(self):
        parsed = parse_message(article_snapshot_pairs())
        self.assertEqual(parsed["no_md_entries"], "11")
        self.assertEqual(len(parsed["entries"]), 11)
        self.assertFalse(parsed["md_entries_count_mismatch"])
        self.assertEqual(
            [entry["md_entry_type"] for entry in parsed["entries"]],
            ["0", "0", "0", "0", "0", "1", "1", "1", "1", "1", "B"],
        )
        self.assertEqual(parsed["entries"][0]["md_entry_px"], "57815")
        self.assertEqual(parsed["entries"][0]["md_entry_position_no"], "1")
        self.assertEqual(parsed["entries"][5]["md_entry_px"], "57850")
        self.assertEqual(parsed["entries"][10]["md_entry_size"], "474")
        self.assertIsNone(parsed["entries"][10]["md_entry_px"])
        for entry in parsed["entries"]:
            self.assertIsNone(entry["trade_side"])
            self.assertIsNone(entry["trade_condition"])
            self.assertIsNone(entry["trd_type"])
            self.assertFalse(any(tag["tag"] == 7201 for tag in entry["tags"]))

    def test_unknown_tags_are_kept_raw_on_the_message_and_the_entry(self):
        pairs = _encode([
            (55, "DLR/NOV26"),
            (5555, "header-extra"),
            (262, "md1"),
            (268, "1"),
            (269, "2"),
            (270, "10"),
            (7201, "9"),
            (7210, "entry-extra"),
        ])
        parsed = parse_message(pairs)
        self.assertEqual(parsed["unknown_tags"], [{"tag": 5555, "value": "header-extra"}])
        entry = parsed["entries"][0]
        self.assertEqual(entry["unknown_tags"], [{"tag": 7210, "value": "entry-extra"}])
        self.assertIsNone(entry["trade_side"])
        self.assertIn({"tag": 7201, "value": "9"}, entry["tags"])
        self.assertEqual(
            [(item["tag"], item["value"]) for item in parsed["tags"]],
            pairs,
        )

    def test_repeating_group_count_mismatch_is_flagged(self):
        pairs = _encode([
            (55, "DLR/NOV26"),
            (262, "md1"),
            (268, "2"),
            (269, "0"), (270, "1"), (271, "1"),
        ])
        parsed = parse_message(pairs)
        self.assertEqual(len(parsed["entries"]), 1)
        self.assertTrue(parsed["md_entries_count_mismatch"])

    def test_incremental_x_is_parsed_when_present(self):
        # Primary's ROE does not list MsgType X. The parser still accepts a
        # standard incremental frame so a capture can be read if one appears.
        pairs = [
            (8, "FIXT.1.1"),
            (35, "X"),
            (34, "3"),
            (49, "ROFX"),
            (52, SENDING_TIME),
            (56, "demo-user"),
            (262, "md1"),
            (268, "2"),
            (279, "0"), (269, "2"), (270, "10"), (271, "1"), (277, "U"),
            (7201, "2"), (55, "DLR/NOV26"), (828, "1"),
            (279, "0"), (269, "0"), (270, "9"), (271, "4"), (290, "1"), (9988, "zz"),
        ]
        parsed = parse_message(parse_frame(encode_pairs(pairs)))
        self.assertEqual(parsed["msg_type"], "X")
        self.assertEqual(len(parsed["entries"]), 2)
        trade, bid = parsed["entries"]
        self.assertEqual(trade["trade_side"], "SELL")
        self.assertEqual(trade["md_update_action"], "0")
        self.assertEqual(trade["symbol"], "DLR/NOV26")
        self.assertEqual(trade["trade_condition"], "U")
        self.assertEqual(trade["trd_type"], "1")
        self.assertIsNone(bid["trade_side"])
        self.assertEqual(bid["unknown_tags"], [{"tag": 9988, "value": "zz"}])
        self.assertIsNone(first(
            [(item["tag"], item["value"]) for item in bid["tags"]],
            7201,
        ))

    def test_market_data_reject(self):
        pairs = parse_frame(encode_pairs([
            (8, "FIXT.1.1"),
            (35, "Y"),
            (34, "2"),
            (49, "ROFX"),
            (52, SENDING_TIME),
            (56, "demo-user"),
            (262, "md1"),
            (281, "0"),
            (58, "Unknown symbol"),
        ]))
        parsed = parse_message(pairs)
        self.assertEqual(parsed["md_req_id"], "md1")
        self.assertEqual(parsed["md_req_rej_reason"], "0")
        self.assertEqual(parsed["text"], "Unknown symbol")


if __name__ == "__main__":
    unittest.main()
