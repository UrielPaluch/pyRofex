# -*- coding: utf-8 -*-
"""
    Sample Module.

    Market-data-only FIX subscription against reMarkets.

    Credentials come from the environment, never from this file:

        REMARKETS_FIX_USER
        REMARKETS_FIX_PASSWORD

    The default host is the reMarkets demo. Pass a host to
    FixMarketDataClient only when you intend to leave that demo.

    Requires the optional extra: pip install "pyRofex[fix]"
    Primary FIX session hours are 09:00-19:00 Buenos Aires, and only one
    session may be logged on for these CompIDs.
"""
import os
import sys

from pyRofex.fix import FixMarketDataClient


def main():
    username = os.environ.get("REMARKETS_FIX_USER")
    password = os.environ.get("REMARKETS_FIX_PASSWORD")
    if not username or not password:
        print(
            "Set REMARKETS_FIX_USER and REMARKETS_FIX_PASSWORD. "
            "This sample does not connect without them.",
            file=sys.stderr,
        )
        return 1
    symbol = os.environ.get("REMARKETS_FIX_SYMBOL", "DLR/NOV26")
    client = FixMarketDataClient(username, password)
    client.connect()
    try:
        client.subscribe(symbol, ["BI", "OF", "LA"], depth=5, updates=True)

        def on_message(record):
            parsed = record["parsed"]
            if parsed.get("msg_type") != "W":
                return
            for entry in parsed.get("entries") or []:
                print(
                    parsed.get("symbol"),
                    entry.get("md_entry_type_name"),
                    entry.get("md_entry_px"),
                    entry.get("md_entry_size"),
                    entry.get("trade_condition"),
                    entry.get("trd_type"),
                    entry.get("trade_side"),
                )

        client.run(30, on_message=on_message)
    finally:
        client.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
