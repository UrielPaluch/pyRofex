# -*- coding: utf-8 -*-
"""Demo leaf pin and TLS error text. No network."""

import ssl
import unittest
import warnings

from pyRofex.fix.client import default_connector
from pyRofex.fix.constants import REMARKETS_FIX_HOST
from pyRofex.fix.errors import FixTLSError
from pyRofex.fix.tls import (
    allow_demo_pin,
    demo_leaf_der,
    demo_leaf_sha256,
    explain_tls_failure,
    leaf_matches_demo_pin,
)


class _RawSocket(object):
    def __init__(self):
        self.closed = False

    def settimeout(self, _timeout):
        return None

    def setsockopt(self, *_args):
        return None

    def close(self):
        self.closed = True


class _Wrapped(object):
    def __init__(self, der):
        self.der = der
        self.closed = False

    def getpeercert(self, binary_form=False):
        if not binary_form:
            raise AssertionError("pin check must read the DER leaf")
        return self.der

    def close(self):
        self.closed = True


class TlsPinTests(unittest.TestCase):
    def test_pinned_digest_matches_shipped_leaf(self):
        der = demo_leaf_der()
        self.assertEqual(
            demo_leaf_sha256(),
            "b587260ba74133b291ff344553290bffef121a122e791ec08936efd3c28759f1",
        )
        self.assertTrue(leaf_matches_demo_pin(der))
        self.assertFalse(leaf_matches_demo_pin(b"other-leaf"))
        self.assertTrue(allow_demo_pin(REMARKETS_FIX_HOST, None, True))
        self.assertFalse(allow_demo_pin(REMARKETS_FIX_HOST, "ca.pem", True))
        self.assertFalse(allow_demo_pin("fix.example.invalid", None, True))
        self.assertFalse(allow_demo_pin(REMARKETS_FIX_HOST, None, False))

    def test_pki_failure_accepts_only_the_pinned_demo_leaf(self):
        import pyRofex.fix.client as client_module
        import pyRofex.fix.tls as tls_module

        created = []

        def create_connection(_addr, timeout=None):
            sock = _RawSocket()
            created.append(sock)
            return sock

        def wrap_verified(sock, host, cafile):
            raise ssl.SSLError("unable to get local issuer certificate")

        def wrap_unverified(sock, host):
            return _Wrapped(demo_leaf_der())

        original_create = client_module.socket.create_connection
        original_verified = tls_module.wrap_verified
        original_unverified = tls_module.wrap_unverified
        client_module.socket.create_connection = create_connection
        tls_module.wrap_verified = wrap_verified
        tls_module.wrap_unverified = wrap_unverified
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                wrapped = default_connector(REMARKETS_FIX_HOST, 9876, True, True, 5)
            self.assertIsInstance(wrapped, _Wrapped)
            self.assertFalse(wrapped.closed)
            self.assertEqual(len(created), 2)
            self.assertTrue(any("pinned demo certificate" in str(item.message) for item in caught))
        finally:
            client_module.socket.create_connection = original_create
            tls_module.wrap_verified = original_verified
            tls_module.wrap_unverified = original_unverified

    def test_pin_mismatch_is_a_tls_error(self):
        import pyRofex.fix.client as client_module
        import pyRofex.fix.tls as tls_module

        def create_connection(_addr, timeout=None):
            return _RawSocket()

        def wrap_verified(sock, host, cafile):
            raise ssl.SSLError("unable to get local issuer certificate")

        def wrap_unverified(sock, host):
            return _Wrapped(b"not-the-demo-leaf")

        original_create = client_module.socket.create_connection
        original_verified = tls_module.wrap_verified
        original_unverified = tls_module.wrap_unverified
        client_module.socket.create_connection = create_connection
        tls_module.wrap_verified = wrap_verified
        tls_module.wrap_unverified = wrap_unverified
        try:
            with self.assertRaises(FixTLSError) as caught:
                default_connector(REMARKETS_FIX_HOST, 9876, True, True, 5)
        finally:
            client_module.socket.create_connection = original_create
            tls_module.wrap_verified = original_verified
            tls_module.wrap_unverified = original_unverified
        message = str(caught.exception)
        self.assertIn("unable to get local issuer certificate", message)
        self.assertIn("did not match the pinned demo certificate", message)
        self.assertNotIsInstance(caught.exception, OSError)

    def test_custom_cafile_does_not_fall_back_to_the_pin(self):
        import pyRofex.fix.client as client_module
        import pyRofex.fix.tls as tls_module

        calls = {"tcp": 0, "unverified": 0}

        def create_connection(_addr, timeout=None):
            calls["tcp"] += 1
            return _RawSocket()

        def wrap_verified(sock, host, cafile):
            raise ssl.SSLError("unable to get local issuer certificate")

        def wrap_unverified(sock, host):
            calls["unverified"] += 1
            return _Wrapped(demo_leaf_der())

        original_create = client_module.socket.create_connection
        original_verified = tls_module.wrap_verified
        original_unverified = tls_module.wrap_unverified
        client_module.socket.create_connection = create_connection
        tls_module.wrap_verified = wrap_verified
        tls_module.wrap_unverified = wrap_unverified
        try:
            with self.assertRaises(FixTLSError):
                default_connector(
                    REMARKETS_FIX_HOST, 9876, True, True, 5, cafile="custom-ca.pem"
                )
        finally:
            client_module.socket.create_connection = original_create
            tls_module.wrap_verified = original_verified
            tls_module.wrap_unverified = original_unverified
        self.assertEqual(calls["tcp"], 1)
        self.assertEqual(calls["unverified"], 0)

    def test_missing_cafile_is_a_tls_error(self):
        import pyRofex.fix.client as client_module

        def create_connection(_addr, timeout=None):
            return _RawSocket()

        original = client_module.socket.create_connection
        client_module.socket.create_connection = create_connection
        try:
            with self.assertRaises(FixTLSError) as caught:
                default_connector(
                    "fix.example.invalid", 443, True, True, 5, cafile="/no/such/ca.pem"
                )
        finally:
            client_module.socket.create_connection = original
        self.assertIn("CA file not found", str(caught.exception))

    def test_explain_mentions_the_expired_thawte_leaf(self):
        text = explain_tls_failure(
            ssl.SSLError("unable to get local issuer certificate"),
            REMARKETS_FIX_HOST,
            None,
        )
        self.assertIn("2014-06-11", text)
        self.assertIn("www.primary.com.ar", text)
        self.assertIn("certifi", text)


if __name__ == "__main__":
    unittest.main()
