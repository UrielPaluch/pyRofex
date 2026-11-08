# -*- coding: utf-8 -*-
"""Market-data-only FIX client for Primary / reMarkets.

The default host is the reMarkets demo endpoint published on the account
page (``fix.remarkets.primary.com.ar:9876``). Any other host, including
production, has to be passed in. Credentials come from the caller. This
module does not embed them.

Transport is a TLS socket (the usual stunnel ``client = yes`` setup talks
TLS to that port). ``use_tls=False`` is for a local stunnel listener.
"""

import socket
import ssl
import sys
import warnings
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from .constants import (
    BUENOS_AIRES_TZ,
    REMARKETS_FIX_HOST,
    REMARKETS_FIX_PORT,
    SESSION_CLOSE_HOUR,
    SESSION_OPEN_HOUR,
)
from .errors import FixConnectionError, FixLogonError, FixSessionError, FixTLSError
from .messages import check_depth, check_heartbeat, normalize_entries
from .session import FixMdSession
from . import tls as tlsmod


class RealClock(object):
    """Wall and monotonic clock used by a live session."""

    def monotonic(self):
        import time
        return time.monotonic()

    def on_idle(self):
        return None

    def sending_time(self):
        from .messages import format_sending_time
        return format_sending_time(datetime.now(timezone.utc))

    def received_at(self):
        return datetime.now().astimezone().isoformat(timespec="microseconds")

    def wall(self):
        return datetime.now(timezone.utc)


def in_fix_session_hours(moment):
    """True when ``moment`` is inside 09:00-19:00 in Buenos Aires.

    The ROE says "FIX Session Hours: 9.00am-7pm" and gives a Buenos Aires
    address. It does not name a timezone or say whether weekends are closed,
    so this is a warning hint only and does not block the connection.
    """
    if ZoneInfo is None:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        zone = ZoneInfo(BUENOS_AIRES_TZ)
    except Exception:
        # Windows does not ship the IANA database unless tzdata is installed.
        return True
    local = moment.astimezone(zone)
    minutes = local.hour * 60 + local.minute
    return SESSION_OPEN_HOUR * 60 <= minutes < SESSION_CLOSE_HOUR * 60


def _tcp_socket(host, port, timeout):
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(1.0)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass
    return sock


def _close_quietly(sock):
    if sock is None:
        return
    try:
        sock.close()
    except Exception:
        pass


def default_connector(host, port, use_tls, tls_verify, timeout, cafile=None):
    """Open a TCP connection, optionally wrapped in TLS.

    ``timeout`` is the connect timeout. The socket is then put on a short
    read timeout so heartbeat timers can run. This function is the only
    place that touches the network.

    With verification on, the trust store is ``cafile`` or certifi. If that
    rejects the reMarkets demo and ``cafile`` was not set, the peer leaf
    must match the pinned demo certificate. A mismatch raises
    :class:`FixTLSError` (not a bare ``ssl.SSLError``).
    """
    sock = _tcp_socket(host, port, timeout)
    if not use_tls:
        return sock
    if not tls_verify:
        try:
            return tlsmod.wrap_unverified(sock, host)
        except Exception:
            _close_quietly(sock)
            raise
    try:
        return tlsmod.wrap_verified(sock, host, cafile)
    except ssl.SSLError as exc:
        _close_quietly(sock)
        sock = None
        if not tlsmod.allow_demo_pin(host, cafile, tls_verify):
            raise FixTLSError(tlsmod.explain_tls_failure(exc, host, cafile)) from exc
        pinned_sock = None
        try:
            pinned_sock = _tcp_socket(host, port, timeout)
            wrapped = tlsmod.wrap_unverified(pinned_sock, host)
            pinned_sock = None
            if tlsmod.accept_pinned_demo(wrapped) is None:
                raise FixTLSError(
                    tlsmod.explain_tls_failure(exc, host, cafile)
                    + " The peer leaf did not match the pinned demo certificate."
                ) from exc
        except ssl.SSLError as pin_exc:
            _close_quietly(pinned_sock)
            raise FixTLSError(tlsmod.explain_tls_failure(pin_exc, host, cafile)) from pin_exc
        except FixTLSError:
            _close_quietly(pinned_sock)
            raise
        except Exception:
            _close_quietly(pinned_sock)
            raise
        warnings.warn(tlsmod._PIN_WARNING, stacklevel=2)
        print(
            "TLS: public PKI rejected the reMarkets demo certificate "
            "(expired Thawte leaf CN=www.primary.com.ar). "
            "Accepted the pinned demo leaf.",
            file=sys.stderr,
        )
        return wrapped
    except Exception:
        _close_quietly(sock)
        raise


class FixMarketDataClient(object):
    """Subscribe to Primary market-data snapshots over FIX.

    There is no order, cancel, or order-status method. Outbound application
    messages are Market Data Requests only.

    :param username: reMarkets / Primary user. Sent as SenderCompID and tag 553.
    :param password: Sent only as Logon tag 554. Never logged by this class.
    :param host: Omit to use the reMarkets demo host. Pass a host for anything else.
    :param port: TCP port. Defaults to 9876.
    :param use_tls: Wrap the socket with ``ssl``. Default True.
    :param tls_verify: Verify the server certificate. Default True.
    :param reconnect: When False (default), a dropped session stays dropped.
    :param reconnect_attempts: How many extra sessions to open after a drop.
    """

    def __init__(self, username, password, host=None, port=None, *,
                 sender_comp_id=None, target_comp_id="ROFX",
                 heartbeat_interval=30, use_tls=True, tls_verify=True,
                 cafile=None, reconnect=False, reconnect_attempts=3,
                 connect_timeout=10, logon_timeout=15,
                 reset_seq_num=False, connector=None, clock=None, sleeper=None,
                 warn_outside_session_hours=True):
        if username is None or password is None or username == "" or password == "":
            raise ValueError("username and password are required")
        self.username = str(username)
        self.password = str(password)
        if host is None:
            self.host = REMARKETS_FIX_HOST
            self.port = REMARKETS_FIX_PORT if port is None else int(port)
        else:
            if str(host).strip() == "":
                raise ValueError("host is empty")
            self.host = str(host)
            self.port = REMARKETS_FIX_PORT if port is None else int(port)
        self.sender = str(sender_comp_id or self.username)
        self.target = str(target_comp_id)
        self.heartbeat_interval = check_heartbeat(int(heartbeat_interval))
        self.use_tls = bool(use_tls)
        self.tls_verify = bool(tls_verify)
        if cafile is not None and str(cafile).strip() == "":
            raise ValueError("cafile is empty")
        self.cafile = None if cafile is None else str(cafile)
        self.reconnect = bool(reconnect)
        self.reconnect_attempts = int(reconnect_attempts)
        self.connect_timeout = connect_timeout
        self.logon_timeout = logon_timeout
        self.reset_seq_num = bool(reset_seq_num)
        self._connector = connector or default_connector
        self.clock = clock or RealClock()
        self._sleeper = sleeper or _sleep
        self.warn_outside_session_hours = warn_outside_session_hours
        self._session = None
        self._subscriptions = {}
        self._req_counter = 0
        self._saw_disconnect = False
        self.on_message = None

    def __repr__(self):
        return "FixMarketDataClient(user={!r}, host={!r}, port={!r})".format(
            self.username, self.host, self.port
        )

    def connect(self):
        """Open the socket and complete Logon. Does not reconnect on failure."""
        if self.warn_outside_session_hours and not in_fix_session_hours(self.clock.wall()):
            warnings.warn(
                "Primary documents FIX session hours as 09:00-19:00 Buenos Aires; "
                "the clock appears to be outside that window",
                stacklevel=2,
            )
        self._open_session()
        deadline = self.clock.monotonic() + self.logon_timeout
        while self.clock.monotonic() < deadline:
            self._session.pump()
            if self._session.state == "logged_on":
                return
            if self._session.state == "disconnected":
                text = self._session.logout_text or "logon rejected"
                raise FixLogonError(text)
        raise FixLogonError("timed out waiting for Logon")

    def subscribe(self, symbols, entries, depth=5, updates=True, aggregated=True, md_req_id=None):
        """Send Market Data Request (35=V). Returns the MDReqID.

        ``updates=True`` asks for snapshot plus full-refresh updates
        (``263=1``, ``265=0``). ``updates=False`` asks for one snapshot
        (``263=0``). ``entries`` are pyRofex codes such as ``BI``, ``OF``,
        ``LA`` or :class:`~pyRofex.components.enums.MarketDataEntry` values.
        """
        self._require_logged_on()
        if isinstance(symbols, str):
            symbols = [symbols]
        symbols = [str(symbol) for symbol in symbols]
        entry_types = normalize_entries(entries)
        depth = check_depth(depth)
        if md_req_id is None:
            self._req_counter += 1
            md_req_id = "md{}".format(self._req_counter)
        md_req_id = str(md_req_id)
        subscription = "1" if updates else "0"
        self._subscriptions[md_req_id] = {
            "symbols": symbols,
            "entry_types": entry_types,
            "depth": depth,
            "subscription": subscription,
            "aggregated": bool(aggregated),
        }
        self._session.send_market_data_request(
            md_req_id, symbols, entry_types, depth, subscription, bool(aggregated)
        )
        return md_req_id

    def unsubscribe(self, md_req_id):
        """Disable a previous snapshot+updates request (``263=2``).

        The ROE requires the MDReqID of the request being disabled. The
        symbol, depth, and entry groups are sent again because those tags
        are required on Market Data Request.
        """
        self._require_logged_on()
        stored = self._subscriptions.get(md_req_id)
        if stored is None:
            raise FixSessionError("unknown MDReqID {!r}".format(md_req_id))
        self._session.send_market_data_request(
            md_req_id,
            stored["symbols"],
            stored["entry_types"],
            stored["depth"],
            "2",
            stored["aggregated"],
        )
        stored["subscription"] = "2"

    def run(self, seconds, on_message=None):
        """Pump the session for ``seconds`` of clock time.

        With ``reconnect=False`` a dropped connection raises
        :class:`FixConnectionError`. With ``reconnect=True`` a new logon is
        attempted and the current subscriptions are sent again.
        """
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        if on_message is not None:
            self.on_message = on_message
            if self._session is not None:
                self._session.on_message = on_message
        end = self.clock.monotonic() + seconds
        retries = 0
        while self.clock.monotonic() < end:
            if self._session is None or self._session.state != "logged_on":
                if self._saw_disconnect:
                    if not self.reconnect or retries >= self.reconnect_attempts:
                        raise FixConnectionError("FIX connection closed")
                    self._sleeper(min(2 ** retries, 5))
                    retries += 1
                    self.connect()
                    self._restore_subscriptions()
                else:
                    raise FixSessionError("connect and log on before run")
            try:
                self._session.pump()
            except FixConnectionError:
                self._saw_disconnect = True
                self._drop_session()
                continue
            if self._session is None:
                continue
            if self._session.state == "logging_out":
                return
            if self._session.state != "logged_on":
                self._saw_disconnect = True
                self._drop_session()
        return

    def logout(self):
        """Send Logout, wait briefly for the answering Logout, and close.

        This is not a reconnect. A caller that has finished reading market
        data should call this so the single FIX session is released.
        """
        session = self._session
        if session is None or session.state == "disconnected":
            if session is not None:
                session.close()
            self._session = None
            return
        session.logout()
        deadline = self.clock.monotonic() + 2
        while session.state != "disconnected" and self.clock.monotonic() < deadline:
            try:
                session.pump()
            except FixConnectionError:
                break
        session.close()
        self._session = None

    def _open_session(self):
        transport = self._connector(
            self.host,
            self.port,
            self.use_tls,
            self.tls_verify,
            self.connect_timeout,
            cafile=self.cafile,
        )
        self._session = FixMdSession(
            self.username,
            self.password,
            self.sender,
            self.target,
            self.heartbeat_interval,
            transport,
            self.clock,
            reset_seq_num=self.reset_seq_num,
            on_message=self.on_message,
        )
        try:
            self._session.start()
        except Exception:
            self._session.close()
            self._session = None
            raise

    def _restore_subscriptions(self):
        for md_req_id, stored in list(self._subscriptions.items()):
            if stored["subscription"] == "2":
                continue
            self._session.send_market_data_request(
                md_req_id,
                stored["symbols"],
                stored["entry_types"],
                stored["depth"],
                stored["subscription"],
                stored["aggregated"],
            )

    def _require_logged_on(self):
        if self._session is None or self._session.state != "logged_on":
            raise FixSessionError("connect and log on before requesting market data")

    def _drop_session(self):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
        self._session = None


def _sleep(seconds):
    import time
    time.sleep(seconds)
