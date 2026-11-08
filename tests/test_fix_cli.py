# -*- coding: utf-8 -*-
"""CLI tests with a fake transport. No sockets and no credentials on disk."""

import io
import json
import os
import ssl
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from pyRofex.fix.constants import REMARKETS_FIX_HOST
from pyRofex.fix_md import main

from fixutil import FakeClock, ScriptedExchange, first, frames_of


class CliTests(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.copy()
        os.environ.pop("REMARKETS_FIX_USER", None)
        os.environ.pop("REMARKETS_FIX_PASSWORD", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_missing_credentials_exits_before_any_connection(self):
        def connector(*_args, **_kwargs):
            raise AssertionError("connector should not be called")

        with tempfile.TemporaryDirectory() as directory:
            out = str(Path(directory) / "out.jsonl")
            with self.assertRaises(SystemExit) as caught:
                main(
                    ["--symbol", "DLR/NOV26", "--out", out],
                    connector=connector,
                )
        self.assertEqual(caught.exception.code, 2)

    def test_writes_raw_fix_and_parsed_trade_side(self):
        os.environ["REMARKETS_FIX_USER"] = "demo-user"
        os.environ["REMARKETS_FIX_PASSWORD"] = "from-env"
        exchange = ScriptedExchange()

        def connector(host, port, use_tls, tls_verify, timeout, cafile=None):
            self.assertEqual(host, REMARKETS_FIX_HOST)
            self.assertEqual(port, 9876)
            self.assertTrue(use_tls)
            self.assertTrue(tls_verify)
            self.assertIsNone(cafile)
            return exchange

        with tempfile.TemporaryDirectory() as directory:
            out = str(Path(directory) / "book.jsonl")
            code = main(
                [
                    "--symbol", "DLR/NOV26",
                    "--entries", "BI,OF,LA",
                    "--depth", "5",
                    "--seconds", "1",
                    "--out", out,
                ],
                connector=connector,
                clock=FakeClock(),
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 0)
            lines = Path(out).read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(lines), 2)
        records = [json.loads(line) for line in lines]
        for record in records:
            self.assertEqual(record["received_at"], "2026-11-08T13:00:00.000000-03:00")
            self.assertIn("\x01", record["raw"])
            self.assertTrue(record["raw"].startswith("8=FIXT.1.1\x01"))
            self.assertIn("parsed", record)
        snapshots = [record for record in records if record["parsed"]["msg_type"] == "W"]
        self.assertEqual(len(snapshots), 1)
        entry = snapshots[0]["parsed"]["entries"][0]
        self.assertEqual(entry["trade_side"], "BUY")
        self.assertEqual(entry["trade_condition"], "U")
        self.assertEqual(entry["trd_type"], "0")
        self.assertEqual(snapshots[0]["parsed"]["symbol"], "DLR/NOV26")
        requests = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "V"]
        self.assertEqual(values_of(requests[0], 269), ["0", "1", "2"])
        self.assertEqual(first(requests[0], 264), "5")
        self.assertEqual(first(requests[0], 55), "DLR/NOV26")
        logons = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "A"]
        self.assertEqual(first(logons[0], 553), "demo-user")
        self.assertEqual(first(logons[0], 554), "from-env")
        raw_dump = "\n".join(record["raw"] for record in records)
        self.assertNotIn("from-env", raw_dump)

    def test_explicit_host_is_passed_through(self):
        seen = {}

        def connector(host, port, use_tls, tls_verify, timeout, cafile=None):
            seen["host"] = host
            seen["port"] = port
            seen["tls"] = use_tls
            return ScriptedExchange()

        with tempfile.TemporaryDirectory() as directory:
            out = str(Path(directory) / "out.jsonl")
            code = main(
                [
                    "--symbol", "DLR/NOV26",
                    "--seconds", "1",
                    "--out", out,
                    "--host", "127.0.0.1",
                    "--port", "8080",
                    "--no-tls",
                    "--user", "demo-user",
                    "--password", "from-env",
                ],
                connector=connector,
                clock=FakeClock(),
                sleeper=lambda _seconds: None,
            )
        self.assertEqual(code, 0)
        self.assertEqual(seen, {"host": "127.0.0.1", "port": 8080, "tls": False})

    def test_entries_flag_can_request_reference_data(self):
        exchange = ScriptedExchange()

        def connector(host, port, use_tls, tls_verify, timeout, cafile=None):
            return exchange

        with tempfile.TemporaryDirectory() as directory:
            out = str(Path(directory) / "out.jsonl")
            code = main(
                [
                    "--symbol", "DLR/NOV26",
                    "--entries", "OP,CL,SE,HI,LO,TV,OI",
                    "--seconds", "1",
                    "--out", out,
                    "--user", "demo-user",
                    "--password", "from-env",
                ],
                connector=connector,
                clock=FakeClock(),
                sleeper=lambda _seconds: None,
            )
        self.assertEqual(code, 0)
        request = next(pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "V")
        self.assertEqual(values_of(request, 269), ["4", "5", "6", "7", "8", "B", "C"])

def values_of(pairs, tag):
    return [value for item_tag, value in pairs if item_tag == tag]


class CliCredentialTests(unittest.TestCase):
    def test_env_credentials_are_used_and_not_hardcoded(self):
        root = Path(__file__).resolve().parents[1].joinpath("src", "pyRofex", "fix")
        hosts = []
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            hosts.extend(host for host in text.split() if "primary.com.ar" in host)
            self.assertNotIn("REMARKETS_FIX_PASSWORD =", text)
        self.assertTrue(hosts)
        for host in hosts:
            self.assertTrue(
                "fix.remarkets.primary.com.ar" in host or "www.primary.com.ar" in host,
                host,
            )

        os.environ["REMARKETS_FIX_USER"] = "demo-user"
        os.environ["REMARKETS_FIX_PASSWORD"] = "from-env"
        exchange = ScriptedExchange()

        def connector(*_args, **_kwargs):
            return exchange

        with tempfile.TemporaryDirectory() as directory:
            out = str(Path(directory) / "out.jsonl")
            code = main(
                ["--symbol", "DLR/NOV26", "--seconds", "1", "--out", out],
                connector=connector,
                clock=FakeClock(),
                sleeper=lambda _seconds: None,
            )
            text = Path(out).read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        logon = [pairs for pairs in frames_of(exchange.sent) if first(pairs, 35) == "A"][0]
        self.assertEqual(first(logon, 554), "from-env")
        self.assertNotIn("from-env", text)


class CliErrorTests(unittest.TestCase):
    def _run(self, argv, connector):
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(
                argv,
                connector=connector,
                clock=FakeClock(),
                sleeper=lambda _seconds: None,
            )
        return code, err.getvalue()

    def test_tls_error_is_not_reported_as_a_file_error(self):
        def connector(*_args, **_kwargs):
            raise ssl.SSLError("unable to get local issuer certificate")

        with tempfile.TemporaryDirectory() as directory:
            out = str(Path(directory) / "book.jsonl")
            code, err = self._run(
                ["--symbol", "DLR/NOV26", "--seconds", "1", "--out", out,
                 "--user", "demo-user", "--password", "secret"],
                connector,
            )
        self.assertEqual(code, 1)
        self.assertIn("TLS error connecting to", err)
        self.assertIn("unable to get local issuer certificate", err)
        self.assertNotIn("could not write", err)

    def test_connection_refused_is_not_a_file_error(self):
        def connector(*_args, **_kwargs):
            raise ConnectionRefusedError(111, "Connection refused")

        with tempfile.TemporaryDirectory() as directory:
            out = str(Path(directory) / "book.jsonl")
            code, err = self._run(
                ["--symbol", "DLR/NOV26", "--seconds", "1", "--out", out,
                 "--user", "demo-user", "--password", "secret"],
                connector,
            )
        self.assertEqual(code, 1)
        self.assertIn("could not connect to", err)
        self.assertNotIn("could not write", err)
        self.assertNotIn("TLS error", err)

    def test_missing_output_directory_is_a_file_error(self):
        def connector(*_args, **_kwargs):
            raise AssertionError("connector should not be called")

        with tempfile.TemporaryDirectory() as directory:
            code, err = self._run(
                ["--symbol", "DLR/NOV26", "--seconds", "1", "--out", directory,
                 "--user", "demo-user", "--password", "secret"],
                connector,
            )
        self.assertEqual(code, 1)
        self.assertIn("could not write", err)
        self.assertNotIn("TLS error", err)
        self.assertNotIn("could not connect", err)

    def test_write_failure_after_connect_is_a_file_error(self):
        import builtins

        class Handle(object):
            def write(self, _data):
                raise OSError("disk full")

            def flush(self):
                pass

            def close(self):
                pass

        original = builtins.open

        def fake_open(path, *args, **kwargs):
            if str(path).endswith("book.jsonl"):
                return Handle()
            return original(path, *args, **kwargs)

        builtins.open = fake_open
        try:
            code, err = self._run(
                ["--symbol", "DLR/NOV26", "--seconds", "1", "--out", "book.jsonl",
                 "--user", "demo-user", "--password", "secret"],
                lambda *_args, **_kwargs: ScriptedExchange(),
            )
        finally:
            builtins.open = original
        self.assertEqual(code, 1)
        self.assertIn("could not write book.jsonl", err)
        self.assertIn("disk full", err)
        self.assertNotIn("TLS error", err)

    def test_cafile_is_passed_to_the_connector(self):
        seen = {}

        def connector(host, port, use_tls, tls_verify, timeout, cafile=None):
            seen["cafile"] = cafile
            seen["tls_verify"] = tls_verify
            return ScriptedExchange()

        with tempfile.TemporaryDirectory() as directory:
            cafile = str(Path(directory) / "ca.pem")
            Path(cafile).write_text("placeholder\n", encoding="ascii")
            out = str(Path(directory) / "out.jsonl")
            code, _err = self._run(
                ["--symbol", "DLR/NOV26", "--seconds", "1", "--out", out,
                 "--cafile", cafile, "--user", "demo-user", "--password", "secret"],
                connector,
            )
        self.assertEqual(code, 0)
        self.assertEqual(seen["cafile"], cafile)
        self.assertTrue(seen["tls_verify"])


if __name__ == "__main__":
    unittest.main()
