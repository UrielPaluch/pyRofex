# -*- coding: utf-8 -*-
"""Parse Market Data Snapshot (W) and, if one arrives, Incremental (X).

Every tag on the wire is kept, in order, as ``{"tag", "value"}``. Named
fields are copies of tags the ROE defines. Tag 7201 is exposed as
``trade_side`` with values ``BUY``, ``SELL``, or ``None``, and only on a
``269=2`` entry of a snapshot (``35=W``) or incremental (``35=X``). A missing
7201 stays ``None``. Tag 54 on an Execution Report (``35=8``) is the account
order side and is never copied into ``trade_side``.
"""

from .constants import (
    FIX_ENTRY_NAMES,
    KNOWN_ENTRY_TAGS,
    KNOWN_MESSAGE_TAGS,
    MD_REQ_REJ_REASONS,
    TRADE_SIDE_BY_VALUE,
    TRADING_SESSION_SUB_ID,
    TRAD_SES_STATUS,
)


def parse_message(pairs):
    """Parse one decoded FIX message into a JSON-ready dict.

    ``pairs`` is an ordered list of ``(tag: int, value: str)``.
    """
    tags = [{"tag": tag, "value": value} for tag, value in pairs]
    msg_type = _first(pairs, 35)
    parsed = {
        "msg_type": msg_type,
        "msg_seq_num": _first(pairs, 34),
        "sender_comp_id": _first(pairs, 49),
        "target_comp_id": _first(pairs, 56),
        "sending_time": _first(pairs, 52),
        "tags": tags,
    }
    if msg_type == "W":
        parsed.update(_market_data(pairs, delimiter=269))
    elif msg_type == "X":
        parsed.update(_market_data(pairs, delimiter=_incremental_delimiter(pairs)))
    elif msg_type == "Y":
        reason = _first(pairs, 281)
        parsed.update({
            "md_req_id": _first(pairs, 262),
            "md_req_rej_reason": reason,
            "md_req_rej_reason_name": MD_REQ_REJ_REASONS.get(reason),
            "text": _first(pairs, 58),
            "rejected": True,
            "unknown_tags": _message_unknowns(pairs, entry_spans=[]),
        })
    elif msg_type == "h":
        parsed.update(_trading_session_status(pairs))
    elif msg_type == "8":
        # Unsolicited account execution report. Tag 54 stays the raw order
        # side. It is not trade_side and there is no market-data entry list.
        parsed.update({
            "unsolicited": True,
            "order_id": _first(pairs, 37),
            "ord_status": _first(pairs, 39),
            "order_side": _first(pairs, 54),
            "unknown_tags": _message_unknowns(pairs, entry_spans=[]),
        })
    else:
        parsed["unknown_tags"] = _message_unknowns(pairs, entry_spans=[])
    return parsed


def trade_side_from_value(value):
    """Map tag 7201, "Side of the trade", to ``BUY`` / ``SELL`` / ``None``.

    The ROE does not call this an aggressor flag. On 2026-11-08, reMarkets
    demo prints matched the passive order's side in 6 of 6 trades, in both
    role configurations. This function does not invert that value. Any value
    other than ``1`` or ``2``, including a missing value, is ``None``. The
    raw tag is still kept by the caller. Tag 54 is not an input.
    """
    if value is None:
        return None
    return TRADE_SIDE_BY_VALUE.get(value)


def _trading_session_status(pairs):
    """Named fields for ``35=h`` from the ROE (p.31). Raw values stay put."""
    status = _first(pairs, 340)
    sub_id = _first(pairs, 625)
    return {
        "text": _first(pairs, 58),
        "trad_ses_req_id": _first(pairs, 335),
        "trading_session_id": _first(pairs, 336),
        "trading_session_sub_id": sub_id,
        "trading_session_sub_id_name": TRADING_SESSION_SUB_ID.get(sub_id),
        "trad_ses_status": status,
        "trad_ses_status_name": TRAD_SES_STATUS.get(status),
        "market_segment_id": _first(pairs, 1300),
        "market_id": _first(pairs, 1301),
        "unsolicited_indicator": _first(pairs, 325),
        "unknown_tags": _message_unknowns(pairs, entry_spans=[]),
    }


def _market_data(pairs, delimiter):
    declared, entry_pairs, entry_spans = _split_entries(pairs, delimiter)
    entries = [_entry(group) for group in entry_pairs]
    declared_count = _int_or_none(declared)
    return {
        "md_req_id": _first(pairs, 262),
        "symbol": _first(pairs, 55),
        "security_exchange": _first(pairs, 207),
        "market_depth": _first(pairs, 264),
        "no_md_entries": declared,
        "md_entries_count_mismatch": (
            declared_count is not None and declared_count != len(entries)
        ),
        "entries": entries,
        "unknown_tags": _message_unknowns(pairs, entry_spans),
    }


def _incremental_delimiter(pairs):
    """Standard FIX ``X`` groups start with tag 279. Fall back to 269."""
    _declared, body, _spans = _group_body(pairs)
    for tag, _value in body:
        if tag == 279:
            return 279
    return 269


def _entry(group):
    """One repeating-group member. 7201 is the only source of trade_side."""
    side_raw = _first(group, 7201)
    entry_type = _first(group, 269)
    # 7201 is meaningful on a trade entry (269=2). Anywhere else, including
    # a bid or an Execution Report, it is not this field.
    return {
        "tags": [{"tag": tag, "value": value} for tag, value in group],
        "unknown_tags": [
            {"tag": tag, "value": value}
            for tag, value in group
            if tag not in KNOWN_ENTRY_TAGS
        ],
        "md_entry_type": entry_type,
        "md_entry_type_name": FIX_ENTRY_NAMES.get(entry_type),
        "md_entry_px": _first(group, 270),
        "md_entry_size": _first(group, 271),
        "md_entry_date": _first(group, 272),
        "md_entry_time": _first(group, 273),
        "trade_condition": _first(group, 277),
        "md_entry_buyer": _first(group, 288),
        "md_entry_seller": _first(group, 289),
        "md_entry_position_no": _first(group, 290),
        "trd_type": _first(group, 828),
        "md_update_action": _first(group, 279),
        "symbol": _first(group, 55),
        "security_exchange": _first(group, 207),
        "trade_side": trade_side_from_value(side_raw) if entry_type == "2" else None,
    }


def _split_entries(pairs, delimiter):
    declared, body, body_start = _group_body(pairs)
    entries = []
    spans = []
    current = []
    current_start = None
    for offset, (tag, value) in enumerate(body):
        index = body_start + offset
        if tag == delimiter:
            if current:
                entries.append(current)
                spans.append((current_start, index))
            current = [(tag, value)]
            current_start = index
        elif current_start is None:
            current = [(tag, value)]
            current_start = index
        else:
            current.append((tag, value))
    if current:
        entries.append(current)
        spans.append((current_start, body_start + len(body)))
    return declared, entries, spans


def _group_body(pairs):
    """Return ``(declared 268, pairs after 268 and before 10, start index)``."""
    start = None
    declared = None
    for index, (tag, value) in enumerate(pairs):
        if tag == 268:
            start = index + 1
            declared = value
            break
    if start is None:
        return None, [], 0
    body = []
    for tag, value in pairs[start:]:
        if tag == 10:
            break
        body.append((tag, value))
    return declared, body, start


def _message_unknowns(pairs, entry_spans):
    unknown = []
    for index, (tag, value) in enumerate(pairs):
        if any(start <= index < end for start, end in entry_spans):
            continue
        if tag in KNOWN_MESSAGE_TAGS:
            continue
        unknown.append({"tag": tag, "value": value})
    return unknown


def _first(pairs, wanted):
    for tag, value in pairs:
        if tag == wanted:
            return value
    return None


def _int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
