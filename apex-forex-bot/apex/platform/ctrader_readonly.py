"""Read-only cTrader session for the operator audit.

What this module will put on a socket is the whole security boundary. A
message is forwarded only when both its class and its payload type are on
the allowlist: application auth, account auth, the account list, trader,
reconcile, deal list, order list, the symbol list and order details. A write
payload is refused before the connection sees it.

The socket and framing belong to the existing Open API client. The audit
does not join the trading connection pool, and it closes its socket when
the read finishes. A live host is opened only when this deployment already
allows live accounts.

The account-list response echoes the access token. Nothing in this module
copies that field into a result.
"""

import socket
import ssl

from apex.brokers import ctrader as _ct
from apex.ctrader_proto.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAApplicationAuthRes,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetAccountListByAccessTokenRes,
    ProtoOAReconcileReq,
    ProtoOAReconcileRes,
    ProtoOATraderReq,
    ProtoOATraderRes,
)
from apex.ctrader_proto.OpenApiModelMessages_pb2 import ProtoOAPayloadType
from apex.platform import ctrader_link as _link

ALLOWED_REQUESTS = frozenset({
    "ProtoOAApplicationAuthReq",
    "ProtoOAAccountAuthReq",
    "ProtoOAGetAccountListByAccessTokenReq",
    "ProtoOATraderReq",
    "ProtoOAReconcileReq",
    "ProtoOADealListReq",
    "ProtoOAOrderListReq",
    "ProtoOASymbolsListReq",
    "ProtoOAOrderDetailsReq",
})
ALLOWED_PAYLOADS = frozenset({
    int(ProtoOAPayloadType.Value("PROTO_OA_APPLICATION_AUTH_REQ")),
    int(ProtoOAPayloadType.Value("PROTO_OA_ACCOUNT_AUTH_REQ")),
    int(ProtoOAPayloadType.Value("PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ")),
    int(ProtoOAPayloadType.Value("PROTO_OA_TRADER_REQ")),
    int(ProtoOAPayloadType.Value("PROTO_OA_RECONCILE_REQ")),
    int(ProtoOAPayloadType.Value("PROTO_OA_DEAL_LIST_REQ")),
    int(ProtoOAPayloadType.Value("PROTO_OA_ORDER_LIST_REQ")),
    int(ProtoOAPayloadType.Value("PROTO_OA_SYMBOLS_LIST_REQ")),
    int(ProtoOAPayloadType.Value("PROTO_OA_ORDER_DETAILS_REQ")),
})


class ReadOnlyViolation(Exception):
    """Raised before a disallowed payload is sent.

    The text is the class name and nothing else. Auth requests carry a
    token and a write request can carry a label; an exception string is
    logged, so neither may be in it.
    """

    def __init__(self, kind):
        self.kind = str(kind or "unknown")
        super().__init__(f"refused read-only: {self.kind}")


def assert_read_only(req):
    """Refuse unless this message is one of the nine reads, unchanged."""
    kind = type(req).__name__
    try:
        payload = int(getattr(req, "payloadType", None))
    except (TypeError, ValueError):
        payload = None
    if kind not in ALLOWED_REQUESTS or payload not in ALLOWED_PAYLOADS:
        raise ReadOnlyViolation(kind)
    return req


def _install_guard(conn):
    """Check every send, including the auth `connect` performs itself."""
    real = conn._request

    def guarded(req, res_cls, timeout=15, accept=None):
        assert_read_only(req)
        return real(req, res_cls, timeout=timeout, accept=accept)

    conn._request = guarded
    return conn


class ReadOnlySession:
    """One checked connection. It does not remember the access token."""

    def __init__(self, send, *, ctid=None, close=None):
        self._send = send
        self.ctid = ctid
        self._close = close
        self._symbols = None

    def request(self, req, res_cls, timeout=15):
        assert_read_only(req)
        return self._send(req, res_cls, timeout=timeout)

    def close(self):
        closer, self._close = self._close, None
        if closer is not None:
            try:
                closer()
            except Exception:                                # noqa: BLE001
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def open_application_session(token):
    """Demo host, application auth only. Same shape as the existing account list."""
    if not _ct._SDK_OK:
        raise RuntimeError("cTrader protobuf definitions unavailable")
    ctx = ssl.create_default_context()
    raw = socket.create_connection((_ct._HOST["demo"], _ct._PORT), timeout=15)
    sock = ctx.wrap_socket(raw, server_hostname=_ct._HOST["demo"])
    conn = _ct._Conn("demo", token, 0)
    conn._sock = sock
    _install_guard(conn)
    try:
        app = ProtoOAApplicationAuthReq()
        app.clientId = _ct.cfg.CTRADER_CLIENT_ID
        app.clientSecret = _ct.cfg.CTRADER_CLIENT_SECRET
        conn._request(app, ProtoOAApplicationAuthRes)
    except Exception:
        conn.close()
        raise
    return ReadOnlySession(conn._request, close=conn.close)


def open_account_session(env, token, ctid):
    """Application auth plus account auth. Live stays behind the existing gate."""
    env = "live" if str(env).lower() == "live" else "demo"
    if env == "live" and not _link.live_allowed():
        raise _link.LinkError(
            "LIVE_BLOCKED",
            "live accounts are blocked in this environment")
    conn = _ct._Conn(env, token, int(ctid))
    _install_guard(conn)
    try:
        conn.connect()
    except Exception:
        conn.close()
        raise
    return ReadOnlySession(conn._request, ctid=int(ctid), close=conn.close)


def _opt(msg, name):
    if msg is None:
        return None
    has = getattr(msg, "HasField", None)
    if callable(has):
        try:
            if not has(name):
                return None
        except ValueError:
            return None
    value = getattr(msg, name, None)
    if isinstance(value, str) and value == "":
        return None
    return value


def _money(minor, digits):
    try:
        places = int(digits)
    except (TypeError, ValueError):
        places = 2
    if places < 0 or places > 8:
        places = 2
    try:
        major = int(minor) / (10 ** places)
    except (TypeError, ValueError):
        return None
    return round(major, places if places else 2)


def account_list_from(res):
    """Id, login and demo/live. Does not read the echoed access token."""
    rows = []
    for acc in getattr(res, "ctidTraderAccount", ()) or ():
        login = _opt(acc, "traderLogin")
        rows.append({
            "ctidTraderAccountId": int(acc.ctidTraderAccountId),
            "login": int(login) if login is not None else None,
            "environment": "live" if bool(acc.isLive) else "demo",
        })
    return rows


def trader_view(trader):
    digits = _opt(trader, "moneyDigits")
    try:
        digits = int(digits) if digits is not None else 2
    except (TypeError, ValueError):
        digits = 2
    if not 0 <= digits <= 8:
        digits = 2
    digits = digits or 2
    leverage = _opt(trader, "leverageInCents")
    if leverage is None:
        leverage_out = None
    else:
        leverage = int(leverage)
        leverage_out = leverage // 100 if leverage % 100 == 0 else leverage / 100.0
    login = _opt(trader, "traderLogin")
    return {
        "ctidTraderAccountId": int(trader.ctidTraderAccountId),
        "login": int(login) if login is not None else None,
        "broker": _opt(trader, "brokerName"),
        "balance": _money(trader.balance, digits),
        "leverage": leverage_out,
    }


def summary_view(trader, open_positions):
    """Equity is balance plus unrealized P/L, and only when that sum is exact.

    No allowlisted message carries the broker's unrealized figure. Flat means
    that figure is zero, so equity is the balance. An open position with no
    figure is reported as unknown: substituting the balance would disagree
    with the cTrader app and look like a fact.
    """
    base = trader_view(trader)
    try:
        n = int(open_positions)
    except (TypeError, ValueError):
        n = None
    if n == 0 and base.get("balance") is not None:
        base.update(openPositions=0, unrealizedPnl=0.0,
                    equity=base["balance"], equityKnown=True)
        return base
    base.update(openPositions=n, unrealizedPnl=None, equity=None,
                equityKnown=False)
    return base


def read_account_list(session, token):
    req = ProtoOAGetAccountListByAccessTokenReq()
    req.accessToken = token
    res = session.request(req, ProtoOAGetAccountListByAccessTokenRes, timeout=20)
    return account_list_from(res)


def _trader_message(session, ctid):
    req = ProtoOATraderReq()
    req.ctidTraderAccountId = int(ctid)
    return session.request(req, ProtoOATraderRes, timeout=15).trader


def read_summary(session, ctid):
    trader = _trader_message(session, ctid)
    req = ProtoOAReconcileReq()
    req.ctidTraderAccountId = int(ctid)
    reconcile = session.request(req, ProtoOAReconcileRes, timeout=15)
    return summary_view(trader, len(reconcile.position))


def describe_token(token):
    """Accounts on this token. Broker comes from a trader read when the host
    is one this deployment is allowed to open."""
    with open_application_session(token) as session:
        rows = read_account_list(session, token)
    for row in rows:
        row["broker"] = None
        if row["environment"] == "live" and not _link.live_allowed():
            continue
        try:
            with open_account_session(
                    row["environment"], token, row["ctidTraderAccountId"]) as session:
                trader = trader_view(_trader_message(
                    session, row["ctidTraderAccountId"]))
            row["broker"] = trader.get("broker")
            if row.get("login") is None:
                row["login"] = trader.get("login")
        except _link.LinkError:
            raise
        except Exception:                                    # noqa: BLE001
            # The name is one field. The exception is dropped on purpose:
            # its text can echo the token that was just sent.
            row["broker"] = None
    return rows


def describe_summary(env, token, ctid):
    with open_account_session(env, token, ctid) as session:
        return read_summary(session, ctid)
