# -*- coding: utf-8 -*-
"""TLS for the reMarkets demo and for hosts with a normal public chain.

The demo server at ``fix.remarkets.primary.com.ar:9876`` sends three
certificates:

* leaf ``CN=www.primary.com.ar``, SHA-1, notAfter 2014-06-11, no subject
  alternative name (it does not name the FIX host)
* intermediate ``Thawte SSL CA``, notAfter 2020-02-07
* ``thawte Primary Root CA``, itself signed by ``Thawte Premium Server CA``,
  notAfter 2020-12-30

None of those are in the Mozilla bundle shipped by certifi, which is why
OpenSSL and Windows both report ``unable to get local issuer certificate``.
Supplying certifi does not make public PKI succeed: the leaf is expired,
the signature is SHA-1, and the hostname does not match. The chain is not
a single missing modern intermediate.

Verification stays on. For this demo host, when the caller does not pass a
CA file, a public-PKI failure is followed by a second check: the peer leaf
must be byte-for-byte the certificate in ``remarkets_demo_leaf.pem``. Any
other certificate is rejected. ``--cafile`` uses that bundle and does not
fall back to the pin. ``--insecure`` skips both checks.
"""

import hashlib
import os
import ssl
from pathlib import Path

from .constants import REMARKETS_FIX_HOST
from .errors import FixTLSError


_LEAF_PATH = Path(__file__).with_name("remarkets_demo_leaf.pem")
_PIN_WARNING = (
    "reMarkets demo certificate failed public PKI verification "
    "(expired Thawte leaf CN=www.primary.com.ar, notAfter 2014-06-11, SHA-1); "
    "accepted because the peer leaf matches the pinned demo certificate"
)


def demo_leaf_der():
    """DER bytes of the demo leaf captured from the live server."""
    pem = _LEAF_PATH.read_text(encoding="ascii")
    return ssl.PEM_cert_to_DER_cert(pem)


def demo_leaf_sha256():
    """SHA-256 hex digest of the pinned demo leaf."""
    return hashlib.sha256(demo_leaf_der()).hexdigest()


def leaf_matches_demo_pin(der):
    """True when ``der`` is the pinned reMarkets demo leaf."""
    if not der:
        return False
    return hashlib.sha256(der).hexdigest() == demo_leaf_sha256()


def allow_demo_pin(host, cafile, tls_verify):
    """Pin only the known demo host, and only when no CA file was requested."""
    return bool(tls_verify) and not cafile and host == REMARKETS_FIX_HOST


def explain_tls_failure(exc, host, cafile):
    """Text for a certificate failure. Includes the original OpenSSL reason."""
    text = "certificate verification failed: {}".format(exc)
    if host == REMARKETS_FIX_HOST and not cafile:
        text += (
            ". The demo leaf is an expired SHA-1 Thawte certificate "
            "CN=www.primary.com.ar (notAfter 2014-06-11). The chain sent by "
            "the server is not in certifi or a current Windows trust store, "
            "so verification reports 'unable to get local issuer certificate'. "
            "certifi cannot complete that chain. With no --cafile, the demo "
            "is accepted only when the peer leaf matches the pinned certificate. "
            "Pass --cafile to trust a bundle instead, or --insecure to skip checks."
        )
    elif cafile:
        text += ". Checked only against CA file {}.".format(cafile)
    else:
        text += ". Pass --cafile to supply a CA bundle, or --insecure to skip verification."
    return text


def verified_context(cafile):
    """Context that verifies against ``cafile`` or, by default, certifi."""
    if cafile:
        if not os.path.isfile(cafile):
            raise FixTLSError("CA file not found: {}".format(cafile))
        return ssl.create_default_context(cafile=cafile)
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def wrap_verified(sock, host, cafile):
    """Handshake with hostname and certificate checks enabled."""
    context = verified_context(cafile)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context.wrap_socket(sock, server_hostname=host)


def wrap_unverified(sock, host):
    """Handshake without PKI checks. Callers must pin or be in --insecure mode."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context.wrap_socket(sock, server_hostname=host)


def accept_pinned_demo(wrapped):
    """Return the socket when its leaf matches the pin. Close it otherwise."""
    der = wrapped.getpeercert(binary_form=True)
    if leaf_matches_demo_pin(der):
        return wrapped
    try:
        wrapped.close()
    except Exception:
        pass
    return None
