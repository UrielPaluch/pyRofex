# -*- coding: utf-8 -*-
"""Builders for the session and market-data messages this client sends."""

from datetime import datetime, timezone

from .codec import encode_pairs, parse_frame, require_safe_value
from .constants import (
    ALLOWED_OUTBOUND_MSG_TYPES,
    BEGIN_STRING,
    DEFAULT_APPL_VER_ID,
    ENCRYPT_METHOD_NONE,
    MAX_MARKET_DEPTH,
    MIN_HEARTBEAT_INTERVAL,
    PYROFEX_ENTRY_TO_FIX,
    TARGET_COMP_ID,
)
from .errors import FixMarketDataOnlyError


def format_sending_time(moment=None):
    """UTC timestamp ``YYYYMMDD-HH:MM:SS.sss`` as required for tag 52."""
    if moment is None:
        moment = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("sending time must be timezone-aware")
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y%m%d-%H:%M:%S.") + "{:03d}".format(moment.microsecond // 1000)


def normalize_entries(entries):
    """Map pyRofex entry codes (``BI``, ``OF``, ``LA``, ...) to tag 269 values."""
    if entries is None:
        raise ValueError("at least one market-data entry is required")
    # Local import keeps the FIX constants usable even if a caller passes
    # the existing MarketDataEntry enum.
    from ..components.enums import MarketDataEntry

    codes = []
    seen = set()
    for entry in entries:
        if isinstance(entry, MarketDataEntry):
            key = entry.value
        else:
            key = str(entry).strip().upper()
        if key not in PYROFEX_ENTRY_TO_FIX:
            known = ", ".join(sorted(PYROFEX_ENTRY_TO_FIX))
            raise ValueError(
                "unsupported market-data entry {!r}. Supported codes: {}".format(entry, known)
            )
        fix_code = PYROFEX_ENTRY_TO_FIX[key]
        if fix_code not in seen:
            seen.add(fix_code)
            codes.append(fix_code)
    if not codes:
        raise ValueError("at least one market-data entry is required")
    return codes


def check_depth(depth):
    """ROE tag 264: 0 full book, 1 top of book, 2..5 best N. Maximum 5."""
    if type(depth) is bool or not isinstance(depth, int):
        raise ValueError("depth must be an integer from 0 to {}".format(MAX_MARKET_DEPTH))
    if depth < 0 or depth > MAX_MARKET_DEPTH:
        raise ValueError(
            "depth must be 0 (full book) through {} (ROE maximum)".format(MAX_MARKET_DEPTH)
        )
    return depth


def check_heartbeat(interval):
    if type(interval) is bool or not isinstance(interval, int):
        raise ValueError("heartbeat interval must be an integer >= {}".format(MIN_HEARTBEAT_INTERVAL))
    if interval < MIN_HEARTBEAT_INTERVAL:
        raise ValueError(
            "HeartBtInt must be >= {} seconds (Primary ROE Logon)".format(MIN_HEARTBEAT_INTERVAL)
        )
    return interval


def build_frame(msg_type, body, *, seq, sender, target, sending_time,
                poss_dup=False, orig_sending_time=None):
    """Build one outbound frame.

    ``msg_type`` must be a session message or Market Data Request (``V``).
    """
    msg_type = str(msg_type)
    if msg_type not in ALLOWED_OUTBOUND_MSG_TYPES:
        raise FixMarketDataOnlyError(
            "message type {!r} cannot be sent: this client is market-data only".format(msg_type)
        )
    sender = require_safe_value(sender)
    target = require_safe_value(target)
    sending_time = require_safe_value(sending_time)
    pairs = [
        (8, BEGIN_STRING),
        (35, msg_type),
        (34, str(int(seq))),
        (49, sender),
        (52, sending_time),
        (56, target),
    ]
    if poss_dup:
        pairs.append((43, "Y"))
    pairs.append((1128, DEFAULT_APPL_VER_ID))
    if orig_sending_time:
        pairs.append((122, require_safe_value(orig_sending_time)))
    for tag, value in body:
        pairs.append((int(tag), require_safe_value(value)))
    encoded = encode_pairs(pairs)
    return encoded, parse_frame(encoded)


def logon_body(username, password, heartbeat_interval, reset_seq_num=False):
    """Logon (35=A) body.

    Tags 553 and 554 are marked not required in the ROE table, and an old
    changelog line says they stopped being required. reMarkets still
    authenticates with them, so they are always sent. Tag 1137
    ``DefaultApplVerID=9`` (FIX.5.0 SP2) is required on the FIXT logon.
    Tag 141 is not in the ROE; it is included only when requested.
    """
    check_heartbeat(heartbeat_interval)
    username = require_safe_value(username)
    password = require_safe_value(password)
    if username == "" or password == "":
        raise ValueError("username and password are required")
    body = [
        (98, ENCRYPT_METHOD_NONE),
        (108, str(heartbeat_interval)),
        (553, username),
        (554, password),
        (1137, DEFAULT_APPL_VER_ID),
    ]
    if reset_seq_num:
        body.append((141, "Y"))
    return body


def market_data_request_body(md_req_id, symbols, entry_types, depth,
                             subscription, aggregated=True):
    """Market Data Request (35=V) body, field order as in the ROE (pp.60-61).

    ``subscription`` is ``"0"`` (snapshot), ``"1"`` (snapshot + updates) or
    ``"2"`` (disable the previous snapshot + updates). Updates are full
    refreshes: tag 265 is ``0`` and is sent only when subscription is ``1``.
    """
    if subscription not in ("0", "1", "2"):
        raise ValueError("subscription must be 0, 1 or 2")
    md_req_id = require_safe_value(md_req_id)
    if md_req_id == "" or len(md_req_id) > 32:
        raise ValueError("MDReqID must be 1 to 32 characters")
    depth = check_depth(depth)
    if not symbols:
        raise ValueError("at least one symbol is required")
    if not entry_types:
        raise ValueError("at least one MDEntryType is required")
    body = [
        (262, md_req_id),
        (263, subscription),
        (264, str(depth)),
    ]
    if subscription == "1":
        body.append((265, "0"))
    body.append((266, "Y" if aggregated else "N"))
    body.append((267, str(len(entry_types))))
    for entry_type in entry_types:
        body.append((269, require_safe_value(entry_type)))
    body.append((146, str(len(symbols))))
    for symbol in symbols:
        text = require_safe_value(symbol)
        if text == "":
            raise ValueError("symbol must not be empty")
        body.append((55, text))
        body.append((207, TARGET_COMP_ID))
    return body


def heartbeat_body(test_req_id=None):
    if test_req_id is None:
        return []
    return [(112, require_safe_value(test_req_id))]


def test_request_body(test_req_id):
    return [(112, require_safe_value(test_req_id))]


def resend_request_body(begin_seq, end_seq):
    return [(7, str(int(begin_seq))), (16, str(int(end_seq)))]


def sequence_reset_body(new_seq, gap_fill=True):
    body = []
    if gap_fill:
        body.append((123, "Y"))
    body.append((36, str(int(new_seq))))
    return body


def logout_body(text=None):
    if text is None or text == "":
        return []
    return [(58, require_safe_value(text))]


def reject_body(ref_seq, ref_msg_type, reason, text):
    return [
        (45, str(int(ref_seq))),
        (372, require_safe_value(ref_msg_type) if ref_msg_type else "0"),
        (373, str(int(reason))),
        (58, require_safe_value(text)),
    ]
