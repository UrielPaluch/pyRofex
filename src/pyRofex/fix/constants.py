# -*- coding: utf-8 -*-
"""Constants from Primary FIX 5.0 SP2 Rules of Engagement V2.0.20.

Market-data message types published in the ROE summary (p.24):

* ``V`` Market Data Request
* ``W`` Market Data Snapshot / Full Refresh
* ``Y`` Market Data Request Reject

``X`` (Market Data Incremental Refresh) is not in that list. ``MDUpdateType``
(265) is documented only as ``0 = Full Refresh``, and the snapshot-plus-updates
flow (p.67) shows further ``W`` messages rather than ``X``. Unsubscribe is a
new ``V`` with ``SubscriptionRequestType = 2`` and the previous ``MDReqID``.
"""

# reMarkets demo only. Production DNS is assigned by Primary and must be
# passed explicitly; this module does not embed a production host.
REMARKETS_FIX_HOST = "fix.remarkets.primary.com.ar"
REMARKETS_FIX_PORT = 9876

BEGIN_STRING = "FIXT.1.1"
DEFAULT_APPL_VER_ID = "9"  # tag 1137 / 1128: FIX.5.0 SP2
TARGET_COMP_ID = "ROFX"
ENCRYPT_METHOD_NONE = "0"
MIN_HEARTBEAT_INTERVAL = 10
MAX_MARKET_DEPTH = 5

# Session and market-data requests this client is allowed to send.
# Order entry, cancel, status, and allocation types are absent on purpose.
ALLOWED_OUTBOUND_MSG_TYPES = frozenset({
    "0",  # Heartbeat
    "1",  # Test Request
    "2",  # Resend Request
    "3",  # Reject (session)
    "4",  # Sequence Reset
    "5",  # Logout
    "A",  # Logon
    "V",  # Market Data Request
})

# pyRofex MarketDataEntry values -> FIX tag 269 (MDEntryType) per the ROE.
# EV (effective volume) is mapped to ``w`` (Cash Volume) by the ROE names.
# That correspondence has not been checked against a live capture.
# IV, ACP and TC are not MDEntryType values in the ROE and are rejected.
PYROFEX_ENTRY_TO_FIX = {
    "BI": "0",   # Bid
    "OF": "1",   # Offer
    "LA": "2",   # Trade
    "OP": "4",   # Opening Price
    "CL": "5",   # Closing Price
    "SE": "6",   # Settlement Price
    "HI": "7",   # Trading Session High Price
    "LO": "8",   # Trading Session Low Price
    "TV": "B",   # Trade Volume
    "OI": "C",   # Open Interest
    "NV": "x",   # Nominal Volume
    "EV": "w",   # Cash Volume
}

FIX_ENTRY_NAMES = {
    "0": "BID",
    "1": "OFFER",
    "2": "TRADE",
    "4": "OPENING_PRICE",
    "5": "CLOSING_PRICE",
    "6": "SETTLEMENT_PRICE",
    "7": "TRADING_SESSION_HIGH_PRICE",
    "8": "TRADING_SESSION_LOW_PRICE",
    "B": "TRADE_VOLUME",
    "C": "OPEN_INTEREST",
    "x": "NOMINAL_VOLUME",
    "w": "CASH_VOLUME",
}

# Tag 7201 is "Side of the trade" (ROE snapshot table): 1=Buy, 2=Sell.
# It is not an aggressor flag. On 2026-11-08 the reMarkets demo matched the
# passive order's side in 6 of 6 trades, under both role configurations.
# Do not invert the value and do not derive it from tag 54 or from 35=8.
TRADE_SIDE_BY_VALUE = {
    "1": "BUY",
    "2": "SELL",
}

# Tag 281, Market Data Request Reject (ROE pp.64-65).
MD_REQ_REJ_REASONS = {
    "0": "UNKNOWN_SYMBOL",
    "1": "DUPLICATE_MD_REQ_ID",
    "2": "INSUFFICIENT_BANDWIDTH",
    "3": "INSUFFICIENT_PERMISSIONS",
    "4": "UNSUPPORTED_SUBSCRIPTION_REQUEST_TYPE",
    "5": "UNSUPPORTED_MARKET_DEPTH",
    "6": "UNSUPPORTED_MD_UPDATE_TYPE",
    "7": "UNSUPPORTED_AGGREGATED_BOOK",
    "8": "UNSUPPORTED_MD_ENTRY_TYPE",
}

# Tag 340 TradSesStatus, Trading Session Status (ROE p.31).
TRAD_SES_STATUS = {
    "0": "UNKNOWN",
    "1": "HALTED",
    "2": "OPEN",
    "3": "CLOSED",
}

# Tag 625 TradingSessionSubID, same message (ROE p.31).
TRADING_SESSION_SUB_ID = {
    "0": "PRE_TRADING",
    "1": "TRADING",
    "2": "POST_TRADING",
    "3": "AFTER_HOUR",
    "4": "CLOSED",
}

# Tags we name on a market-data entry. Anything else stays in unknown_tags.
KNOWN_ENTRY_TAGS = frozenset({
    55,    # Symbol (incremental entries may repeat it)
    207,   # SecurityExchange
    269,   # MDEntryType
    270,   # MDEntryPx
    271,   # MDEntrySize
    272,   # MDEntryDate
    273,   # MDEntryTime
    277,   # TradeCondition
    279,   # MDUpdateAction (standard X; not in the Primary ROE)
    288,   # MDEntryBuyer (not in the current ROE table; sent by the demo)
    289,   # MDEntrySeller (not in the current ROE table; sent by the demo)
    290,   # MDEntryPositionNo
    828,   # TrdType
    7201,  # Trade Side
})

KNOWN_MESSAGE_TAGS = frozenset({
    8, 9, 10, 34, 35, 43, 49, 52, 56, 1128, 122,
    55, 207, 262, 264, 268,
    98, 108, 112, 1137, 553, 554, 141,
    7, 16, 36, 123, 45, 58, 371, 372, 373,
    37, 39, 54,  # Execution Report identity; 54 is not trade_side
    281,
    325, 335, 336, 340, 625, 1300, 1301,  # Trading Session Status (35=h)
})

SOH = "\x01"
SOH_BYTES = b"\x01"

BUENOS_AIRES_TZ = "America/Argentina/Buenos_Aires"
SESSION_OPEN_HOUR = 9
SESSION_CLOSE_HOUR = 19
