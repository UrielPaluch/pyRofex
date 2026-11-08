# -*- coding: utf-8 -*-
"""Exceptions for the market-data-only FIX client."""


class FixError(Exception):
    """Base error for the FIX market-data client."""


class FixMarketDataOnlyError(FixError):
    """Raised when code tries to send a message this client does not allow."""


class FixLogonError(FixError):
    """Logon was rejected, timed out, or the session died before it completed."""


class FixSessionError(FixError):
    """The FIX session cannot perform the requested operation."""


class FixConnectionError(FixError):
    """The TCP/TLS connection closed or could not be used."""


class FixTLSError(FixConnectionError):
    """The TLS handshake or certificate check failed.

    This is not an output-file error. ``ssl.SSLError`` is an ``OSError``,
    so callers must not report it as a failure to write the JSONL file.
    """
