# -*- coding: utf-8 -*-
"""Optional market-data-only FIX client.

Install with ``pip install 'pyRofex[fix]'``. Importing :mod:`pyRofex`
does not import this package and does not require simplefix.

quickfix is not used. simplefix is pure Python and encodes FIX tags in
insertion order, which keeps repeating groups and unknown tags intact on
Windows without a C++ build.
"""

try:
    import simplefix  # noqa: F401
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The FIX market-data client needs the optional pure-Python "
        "simplefix package. Install it with: pip install 'pyRofex[fix]'"
    ) from exc

from .client import REMARKETS_FIX_HOST, REMARKETS_FIX_PORT, FixMarketDataClient
from .errors import (
    FixConnectionError,
    FixError,
    FixLogonError,
    FixMarketDataOnlyError,
    FixSessionError,
    FixTLSError,
)

__all__ = [
    "FixConnectionError",
    "FixError",
    "FixLogonError",
    "FixMarketDataClient",
    "FixMarketDataOnlyError",
    "FixSessionError",
    "FixTLSError",
    "REMARKETS_FIX_HOST",
    "REMARKETS_FIX_PORT",
]
