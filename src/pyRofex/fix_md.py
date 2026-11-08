# -*- coding: utf-8 -*-
"""Command line for the market-data-only FIX client.

::

    set REMARKETS_FIX_USER=...
    set REMARKETS_FIX_PASSWORD=...
    python -m pyRofex.fix_md --symbol DLR/NOV26 --entries BI,OF,LA --depth 5 --seconds 120 --out file.jsonl

The default host is the reMarkets demo. Pass ``--host`` for any other
endpoint. Each output line is a JSON object with ``received_at`` (local
time), ``raw`` (the FIX frame; SOH is U+0001), and ``parsed``.
"""

import argparse
import json
import os
import ssl
import sys

from .fix.client import FixMarketDataClient
from .fix.constants import REMARKETS_FIX_HOST, REMARKETS_FIX_PORT
from .fix.errors import FixError, FixTLSError


class _OutputWriteError(Exception):
    """The JSONL file could not be written. Not a TLS or socket error."""

    def __init__(self, path, original):
        super().__init__(path)
        self.path = path
        self.original = original


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m pyRofex.fix_md",
        description=(
            "Read Primary market-data snapshots over FIX. "
            "Market data only: this command cannot send orders. "
            "Credentials come from REMARKETS_FIX_USER and REMARKETS_FIX_PASSWORD, "
            "or from --user and --password."
        ),
    )
    parser.add_argument("--symbol", action="append", required=True,
                        help="Instrument symbol, for example DLR/NOV26. Repeat for more than one.")
    parser.add_argument(
        "--entries",
        default="BI,OF,LA",
        help=(
            "Comma-separated entry codes. Default: BI,OF,LA. "
            "Also OP (269=4), CL (5), SE (6), HI (7), LO (8), TV (B), OI (C)."
        ),
    )
    parser.add_argument("--depth", type=int, default=5,
                        help="Book depth 0 (full) through 5. Default: 5")
    parser.add_argument("--seconds", type=float, default=120,
                        help="How long to listen after logon. Default: 120")
    parser.add_argument("--out", required=True,
                        help="JSONL file for raw FIX frames and parsed messages")
    parser.add_argument("--host", default=None,
                        help="FIX host. Omit for the reMarkets demo ({}).".format(REMARKETS_FIX_HOST))
    parser.add_argument("--port", type=int, default=None,
                        help="TCP port. Default: {}.".format(REMARKETS_FIX_PORT))
    parser.add_argument("--user", default=None, help="Overrides REMARKETS_FIX_USER")
    parser.add_argument("--password", default=None, help="Overrides REMARKETS_FIX_PASSWORD")
    parser.add_argument("--heartbeat", type=int, default=30,
                        help="HeartBtInt in seconds, minimum 10. Default: 30")
    parser.add_argument("--snapshot-only", action="store_true",
                        help="Request one snapshot (263=0) instead of snapshot plus updates")
    parser.add_argument("--no-aggregated", action="store_true",
                        help="Ask for a non-aggregated book (266=N)")
    parser.add_argument("--no-tls", action="store_true",
                        help="Plain TCP, for a local stunnel listener")
    verify = parser.add_mutually_exclusive_group()
    verify.add_argument("--insecure", action="store_true",
                        help="TLS without certificate verification or the demo leaf pin")
    verify.add_argument("--cafile", default=None,
                        help="PEM CA bundle. Disables the reMarkets demo leaf pin. "
                             "Default trust store is certifi.")
    parser.add_argument("--reset-seq-num", action="store_true",
                        help="Send Logon tag 141=Y. Not in the Primary ROE; off by default")
    parser.add_argument("--reconnect", action="store_true",
                        help="Reconnect after a drop. Off by default")
    return parser


def main(argv=None, connector=None, clock=None, sleeper=None):
    """Run the listener. Returns a process exit code.

    ``connector`` and ``clock`` exist so tests can supply a fake socket.
    The real command line does not pass them and does not open a connection
    until credentials and arguments are valid.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    username = args.user or os.environ.get("REMARKETS_FIX_USER")
    password = args.password or os.environ.get("REMARKETS_FIX_PASSWORD")
    if not username or not password:
        parser.error(
            "set REMARKETS_FIX_USER and REMARKETS_FIX_PASSWORD, or pass --user and --password"
        )
    entries = [part.strip() for part in args.entries.split(",") if part.strip()]
    if args.host is None:
        print(
            "FIX host: {}:{} (reMarkets demo). Pass --host for any other endpoint.".format(
                REMARKETS_FIX_HOST, args.port or REMARKETS_FIX_PORT
            ),
            file=sys.stderr,
        )
    else:
        print("FIX host: {}:{}".format(args.host, args.port or REMARKETS_FIX_PORT), file=sys.stderr)
    client = FixMarketDataClient(
        username,
        password,
        host=args.host,
        port=args.port,
        heartbeat_interval=args.heartbeat,
        use_tls=not args.no_tls,
        tls_verify=not args.insecure,
        cafile=args.cafile,
        reconnect=args.reconnect,
        reset_seq_num=args.reset_seq_num,
        connector=connector,
        clock=clock,
        sleeper=sleeper,
    )
    counts = {"messages": 0, "W": 0, "X": 0, "Y": 0, "h": 0}
    endpoint = "{}:{}".format(client.host, client.port)
    exit_code = 0
    try:
        handle = open(args.out, "w", encoding="utf-8", newline="\n")
    except OSError as exc:
        print("could not write {}: {}".format(args.out, exc), file=sys.stderr)
        return 1
    try:
        def on_message(record, _handle=handle, _counts=counts):
            _counts["messages"] += 1
            msg_type = record.get("parsed", {}).get("msg_type")
            if msg_type in _counts:
                _counts[msg_type] += 1
            try:
                _handle.write(json.dumps(record, ensure_ascii=True))
                _handle.write("\n")
                _handle.flush()
            except OSError as exc:
                raise _OutputWriteError(args.out, exc) from exc

        client.on_message = on_message
        try:
            client.connect()
            client.subscribe(
                args.symbol,
                entries,
                depth=args.depth,
                updates=not args.snapshot_only,
                aggregated=not args.no_aggregated,
            )
            client.run(args.seconds)
        except _OutputWriteError as exc:
            print("could not write {}: {}".format(exc.path, exc.original), file=sys.stderr)
            exit_code = 1
        except FixTLSError as exc:
            print("TLS error connecting to {}: {}".format(endpoint, exc), file=sys.stderr)
            exit_code = 1
        except ssl.SSLError as exc:
            # SSLError is an OSError. Keep it out of the file-write message.
            print("TLS error connecting to {}: {}".format(endpoint, exc), file=sys.stderr)
            exit_code = 1
        except FixError as exc:
            print("FIX market data failed: {}".format(exc), file=sys.stderr)
            exit_code = 1
        except OSError as exc:
            print("could not connect to {}: {}".format(endpoint, exc), file=sys.stderr)
            exit_code = 1
        except KeyboardInterrupt:
            print("interrupted", file=sys.stderr)
            exit_code = 130
        finally:
            # Logout while the file is still open so the peer Logout is recorded.
            try:
                client.logout()
            except Exception as exc:
                print("logout: {}".format(exc), file=sys.stderr)
    finally:
        handle.close()
    if exit_code == 0:
        print(
            "wrote {messages} messages to {path} (W={W} X={X} Y={Y} h={h})".format(
                path=args.out, **counts
            ),
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
