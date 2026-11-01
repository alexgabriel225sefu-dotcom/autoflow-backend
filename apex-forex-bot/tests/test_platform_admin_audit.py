"""Operator audit of connected cTrader accounts. Read-only, and proved so.

The guard refuses a write payload before any send. The HTTP routes accept
only an operator session — the same A4T_OPERATOR_USER_IDS check the live
approval routes use — and the documents they return do not contain the
token that was used to ask.

Run: python tests/test_platform_admin_audit.py
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-audit-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "test"
os.environ.setdefault("PRODUCT", "forex")
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ.pop("APEX_ALLOW_LIVE_ACCOUNTS", None)

import requests  # noqa: E402

from apex.ctrader_proto.OpenApiMessages_pb2 import (  # noqa: E402
    ProtoOAAmendPositionSLTPReq,
    ProtoOACancelOrderReq,
    ProtoOAClosePositionReq,
    ProtoOADealListRes,
    ProtoOAGetAccountListByAccessTokenRes,
    ProtoOANewOrderReq,
    ProtoOAReconcileRes,
    ProtoOATraderReq,
)
from apex.ctrader_proto.OpenApiModelMessages_pb2 import (  # noqa: E402
    ProtoOADeal,
    ProtoOAOrder,
    ProtoOATrader,
)

SECRET = "access-token-value-do-not-leak-aaaa"
REFRESH = "refresh-token-value-do-not-leak-bbbb"
OP = "cccccccc-3333-4333-8333-cccccccccccc"
CLIENT = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
CTID = 424242

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name} {detail}")


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body

    def json(self):
        return self._b


def _fake_get(url, **kw):
    if "supabase" not in str(url):
        raise AssertionError(f"unexpected GET {url}")
    auth = (kw.get("headers") or {}).get("Authorization", "")
    if auth.endswith("operator-token"):
        return _Resp(200, {"id": OP, "email": "op@example.com",
                           "email_confirmed_at": "2026-01-01T00:00:00Z"})
    if auth.endswith("client-token"):
        return _Resp(200, {"id": CLIENT, "email": "c@example.com",
                           "email_confirmed_at": "2026-01-01T00:00:00Z"})
    return _Resp(401, {})


requests.get = _fake_get

from apex import user_store  # noqa: E402
from apex.platform import admin_audit as AA  # noqa: E402
from apex.platform import api as A  # noqa: E402
from apex.platform import ctrader_audit_view as V  # noqa: E402
from apex.platform import ctrader_link as L  # noqa: E402
from apex.platform import ctrader_readonly as RO  # noqa: E402
from apex.platform import live_gate as LG  # noqa: E402
from apex.platform import ratelimit as RL  # noqa: E402
from apex.platform import store as ST  # noqa: E402

os.environ[LG.OPERATOR_ENV] = OP
RL.reset_all()


# ── 1. the allowlist refuses writes before a send ──────────────────────────
print("\n[1] write payloads never reach the socket")
WRITES = (
    ProtoOANewOrderReq, ProtoOAClosePositionReq,
    ProtoOAAmendPositionSLTPReq, ProtoOACancelOrderReq,
)


class _Recorder:
    def __init__(self):
        self.n = 0

    def _request(self, req, res_cls, timeout=15, accept=None):
        self.n += 1
        return "sent"


rec = _Recorder()
RO._install_guard(rec)
for cls in WRITES:
    req = cls()
    if hasattr(req, "label"):
        req.label = SECRET
    try:
        rec._request(req, object)
        check(f"{cls.__name__} is refused", False, "it was sent")
    except RO.ReadOnlyViolation as e:
        check(f"{cls.__name__} is refused", rec.n == 0, f"sends={rec.n}")
        check(f"{cls.__name__} names no token",
              SECRET not in str(e) and REFRESH not in str(e), str(e))

allowed = ProtoOATraderReq()
check("a trader read is on the allowlist",
      RO.assert_read_only(allowed) is allowed)
swapped = ProtoOATraderReq()
swapped.payloadType = 2106
try:
    RO.assert_read_only(swapped)
    check("a swapped payload type is refused", False)
except RO.ReadOnlyViolation:
    check("a swapped payload type is refused", True)

check("the allowlist is exactly the nine reads",
      RO.ALLOWED_REQUESTS == {
          "ProtoOAApplicationAuthReq", "ProtoOAAccountAuthReq",
          "ProtoOAGetAccountListByAccessTokenReq", "ProtoOATraderReq",
          "ProtoOAReconcileReq", "ProtoOADealListReq",
          "ProtoOAOrderListReq", "ProtoOASymbolsListReq",
          "ProtoOAOrderDetailsReq"}
      and not any(cls.__name__ in RO.ALLOWED_REQUESTS for cls in WRITES))

session = RO.ReadOnlySession(rec._request)
try:
    session.request(ProtoOANewOrderReq(), object)
    check("the session itself refuses a write", False)
except RO.ReadOnlyViolation:
    check("the session itself refuses a write", rec.n == 0)


# ── 2. shaping: lots, Amsterdam, platform vs manual, stops, no token ───────
print("\n[2] the document says what the broker said")
check("one FX lot is 10_000_000 volume units",
      V.lots_from_volume(10_000_000, "EURUSD") == 1.0)
check("gold uses the engine's unit-sized lot",
      V.lots_from_volume(100, "XAUUSD") == 1.0)
winter = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc).timestamp()
summer = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc).timestamp()
check("winter is CET",
      V.iso_amsterdam(winter) == "2026-01-15T13:00:00+01:00",
      V.iso_amsterdam(winter))
check("summer is CEST",
      V.iso_amsterdam(summer) == "2026-07-15T14:00:00+02:00",
      V.iso_amsterdam(summer))

start, end = AA.time_window({}, now=1_700_000_000)
check("an absent range is the last seven days",
      end - start == 7 * 86400, f"{end - start}")
try:
    AA.time_window({"from": "2026-01-01T00:00:00+01:00"})
    check("half a range is refused", False)
except ValueError:
    check("half a range is refused", True)

listed = ProtoOAGetAccountListByAccessTokenRes()
listed.accessToken = SECRET
row = listed.ctidTraderAccount.add()
row.ctidTraderAccountId = CTID
row.isLive = False
row.traderLogin = 9001
public = RO.account_list_from(listed)
check("the account list drops the echoed token",
      SECRET not in json.dumps(public) and "accessToken" not in json.dumps(public),
      json.dumps(public))
check("login and demo come from the account list",
      public[0]["login"] == 9001 and public[0]["environment"] == "demo")

trader = ProtoOATrader()
trader.ctidTraderAccountId = CTID
trader.balance = 100_000
trader.moneyDigits = 2
trader.leverageInCents = 50_000
trader.brokerName = "Pepperstone"
flat = RO.summary_view(trader, 0)
check("a flat account's equity is its balance",
      flat["balance"] == 1000.0 and flat["equity"] == 1000.0
      and flat["unrealizedPnl"] == 0.0 and flat["leverage"] == 500
      and flat["broker"] == "Pepperstone" and flat["equityKnown"] is True,
      str(flat))
open_sum = RO.summary_view(trader, 2)
check("an open position does not invent equity",
      open_sum["equity"] is None and open_sum["equityKnown"] is False
      and open_sum["balance"] == 1000.0, str(open_sum))

opening = ProtoOADeal()
opening.dealId, opening.orderId, opening.positionId = 1, 10, 77
opening.volume = opening.filledVolume = 10_000_000
opening.symbolId = 1
opening.executionTimestamp = int(winter * 1000)
opening.executionPrice = 1.1
opening.tradeSide = 1
opening.dealStatus = 2
closing = ProtoOADeal()
closing.dealId, closing.orderId, closing.positionId = 2, 11, 77
closing.volume = closing.filledVolume = 10_000_000
closing.symbolId = 1
closing.executionTimestamp = int(winter * 1000) + 60_000
closing.executionPrice = 1.12
closing.tradeSide = 2
closing.dealStatus = 2
detail = closing.closePositionDetail
detail.entryPrice = 1.1
detail.grossProfit = 2500
detail.swap = -100
detail.commission = -200
detail.moneyDigits = 2
detail.closedVolume = 10_000_000

engine = ProtoOAOrder()
engine.orderId = 10
engine.tradeData.symbolId = 1
engine.tradeData.volume = 10_000_000
engine.tradeData.tradeSide = 1
engine.tradeData.label = "apex-engine"
engine.relativeStopLoss = 50_000
manual = ProtoOAOrder()
manual.orderId = 11
manual.tradeData.symbolId = 1
manual.tradeData.volume = 10_000_000
manual.tradeData.tradeSide = 2
manual.tradeData.comment = "by hand"
manual.clientOrderId = "desk-1"

deals = V.deals_view([opening, closing], {10: engine, 11: manual}, {1: "EURUSD"})
by_id = {row["dealId"]: row for row in deals}
check("the opening deal is the platform's, with a stop and no target",
      by_id[1]["placedByPlatform"] is True and by_id[1]["entry_sl_set"] is True
      and by_id[1]["entry_tp_set"] is False and by_id[1]["lots"] == 1.0
      and by_id[1]["time"] == "2026-01-15T13:00:00+01:00"
      and by_id[1]["close"] is None, str(by_id[1]))
check("the closing deal is manual and carries the close",
      by_id[2]["placedByPlatform"] is False and by_id[2]["side"] == "BUY"
      and by_id[2]["close"]["grossProfit"] == 25.0
      and by_id[2]["close"]["commission"] == -2.0
      and by_id[2]["close"]["swap"] == -1.0
      and by_id[2]["close"]["net"] == 22.0, str(by_id[2]))
unknown = V.deals_view([closing], {}, {1: "EURUSD"})[0]
check("an unread opening order is unknown, not 'no stop'",
      unknown["placedByPlatform"] is None and unknown["entry_sl_set"] is None
      and unknown["entry_tp_set"] is None, str(unknown))

book = ProtoOAReconcileRes()
pos = book.position.add()
pos.positionId = 5
pos.tradeData.symbolId = 1
pos.tradeData.volume = 10_000_000
pos.tradeData.tradeSide = 1
pos.tradeData.label = "apex-engine"
pos.tradeData.comment = ""
pos.tradeData.openTimestamp = int(winter * 1000)
pos.price = 1.1
pos.stopLoss = 1.09
pos.takeProfit = 1.2
pending = book.order.add()
pending.orderId = 8
pending.tradeData.symbolId = 1
pending.tradeData.volume = 5_000_000
pending.tradeData.tradeSide = 2
pending.tradeData.openTimestamp = int(winter * 1000)
pending.limitPrice = 1.05
pending.stopLoss = 1.0
pending.takeProfit = 1.02
opened = V.open_view(book, {1: "EUR/USD"})
check("an open position is in lots, with its label",
      opened["positions"][0]["symbol"] == "EURUSD"
      and opened["positions"][0]["lots"] == 1.0
      and opened["positions"][0]["placedByPlatform"] is True
      and opened["positions"][0]["stopLoss"] == 1.09
      and opened["positions"][0]["openTime"].endswith("+01:00"),
      str(opened["positions"][0]))
check("a pending order without the marker is manual",
      opened["pendingOrders"][0]["lots"] == 0.5
      and opened["pendingOrders"][0]["placedByPlatform"] is False
      and opened["pendingOrders"][0]["entryPrice"] == 1.05,
      str(opened["pendingOrders"][0]))


def _fill(res, ts):
    deal = res.deal.add()
    deal.dealId, deal.orderId, deal.positionId = ts, ts, 1
    deal.volume = deal.filledVolume = 1
    deal.symbolId = 1
    deal.executionTimestamp = ts
    deal.tradeSide = 1
    deal.dealStatus = 2


class _Pages:
    def __init__(self):
        self.seen = []

    def __call__(self, req, res_cls, timeout=15, accept=None):
        RO.assert_read_only(req)
        self.seen.append(req.fromTimestamp)
        res = ProtoOADealListRes()
        if len(self.seen) == 1:
            _fill(res, 1_500)
            res.hasMore = True
        else:
            _fill(res, 2_000)
            res.hasMore = False
        return res


_pages = _Pages()


def _make(cur, end):
    from apex.ctrader_proto.OpenApiMessages_pb2 import ProtoOADealListReq
    req = ProtoOADealListReq()
    req.ctidTraderAccountId = 1
    req.fromTimestamp = int(cur)
    req.toTimestamp = int(end)
    return req


_paged, _cut = V._page(RO.ReadOnlySession(_pages), _make, ProtoOADealListRes,
                       "deal", 1_000, 5_000)
check("a deal page moves the window forward",
      _pages.seen == [1000, 1501] and len(_paged) == 2 and _cut is False,
      str(_pages.seen))


# ── 3. a live host is not opened while live accounts are blocked ───────────
print("\n[3] live reads stay behind the existing gate")


def _no_socket(*_a, **_k):
    raise AssertionError("a socket was opened")


_real_socket = __import__("socket").create_connection
__import__("socket").create_connection = _no_socket
try:
    RO.open_account_session("live", SECRET, CTID)
    check("live is refused before a socket", False)
except L.LinkError as e:
    check("live is refused before a socket", e.code == "LIVE_BLOCKED", e.code)
finally:
    __import__("socket").create_connection = _real_socket


class _ListSession:
    def __init__(self):
        self.sent = []

    def request(self, req, res_cls, timeout=15):
        RO.assert_read_only(req)
        self.sent.append(type(req).__name__)
        res = ProtoOAGetAccountListByAccessTokenRes()
        res.accessToken = SECRET
        acc = res.ctidTraderAccount.add()
        acc.ctidTraderAccountId = 9
        acc.isLive = True
        acc.traderLogin = 42
        return res

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _app(token):
    check("the list uses the stored token", token == SECRET, token)
    return _ListSession()


def _no_account(*_a, **_k):
    raise AssertionError("live account session opened")


_real_app, _real_acc = RO.open_application_session, RO.open_account_session
RO.open_application_session = _app
RO.open_account_session = _no_account
try:
    described = RO.describe_token(SECRET)
finally:
    RO.open_application_session, RO.open_account_session = _real_app, _real_acc
check("a blocked live account is listed without a live session",
      described and described[0]["environment"] == "live"
      and described[0]["login"] == 42 and described[0]["broker"] is None
      and SECRET not in json.dumps(described), str(described))


# ── 4. the HTTP routes ──────────────────────────────────────────────────────
print("\n[4] only an operator, and only GET")


def _plant(mode="demo"):
    ST._write(L._k_conn(CLIENT), {
        "userId": CLIENT,
        "accessToken": user_store.encrypt_value(SECRET),
        "refreshToken": user_store.encrypt_value(REFRESH),
        "expiresAt": 9_999_999_999,
        "accounts": [{"ctid": CTID, "mode": mode, "label": ""}],
        "selectedCtid": CTID,
        "selectedMode": mode,
    })


def _call(method, path, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    buf = io.StringIO()
    with redirect_stdout(buf):
        status, body = A.handle(method, path, headers)
    return status, body, buf.getvalue()


_plant()
status, body, _log = _call("GET", "/api/v1/admin/audit/accounts")
check("anonymous is refused",
      status == 401 and (body.get("error") or {}).get("code") == "AUTH_REQUIRED",
      str(body)[:200])
status, body, _log = _call(
    "GET", "/api/v1/admin/audit/accounts", "client-token")
check("a client is not an operator",
      status == 403 and body["error"]["code"] == "NOT_OPERATOR", str(body)[:200])
status, body, _log = _call(
    "POST", "/api/v1/admin/audit/accounts", "operator-token")
check("POST is refused",
      status == 405 and body["error"]["code"] == "METHOD_NOT_ALLOWED", str(body)[:200])

seen = {}


def _describe(token):
    seen["token"] = token
    return [{"ctidTraderAccountId": CTID, "login": 9001,
             "environment": "demo", "broker": "Pepperstone",
             "accessToken": token}]


_real_describe = RO.describe_token
RO.describe_token = _describe
try:
    status, body, log = _call(
        "GET", "/api/v1/admin/audit/accounts", "operator-token")
finally:
    RO.describe_token = _real_describe
text = json.dumps(body)
check("the operator gets the account",
      status == 200 and body["accounts"][0]["ctidTraderAccountId"] == CTID
      and body["accounts"][0]["login"] == 9001
      and body["accounts"][0]["broker"] == "Pepperstone"
      and body["accounts"][0]["environment"] == "demo"
      and body["accounts"][0]["platformUserId"] == CLIENT
      and body["accounts"][0]["status"] == "ok", text[:400])
check("the token was used and not returned",
      seen.get("token") == SECRET and SECRET not in text and REFRESH not in text
      and "accessToken" not in text and SECRET not in log and REFRESH not in log,
      text[:300])

status, body, log = _call(
    "GET", f"/api/v1/admin/audit/accounts/{CTID}?token={SECRET}",
    "operator-token")
check("a token in the query is refused",
      status == 400 and SECRET not in json.dumps(body) and SECRET not in log,
      str(body)[:240])


def _boom(env, token, ctid):
    raise RuntimeError(f"broker said {token} and {REFRESH}")


_real_summary = RO.describe_summary
RO.describe_summary = _boom
try:
    status, body, log = _call(
        "GET", f"/api/v1/admin/audit/accounts/{CTID}", "operator-token")
finally:
    RO.describe_summary = _real_summary
check("a broker error is scrubbed",
      status == 503 and SECRET not in json.dumps(body) and REFRESH not in json.dumps(body)
      and SECRET not in log and REFRESH not in log, str(body)[:300] + " " + log[:200])

calls = {}


def _summary(env, token, ctid):
    calls["summary"] = (env, token, ctid)
    return {"ctidTraderAccountId": ctid, "login": 9001, "broker": "Pepperstone",
            "balance": 1000.0, "leverage": 500, "unrealizedPnl": 0.0,
            "equity": 1000.0, "equityKnown": True, "openPositions": 0}


def _open(env, token, ctid):
    calls["open"] = (env, ctid)
    return {"positions": [], "pendingOrders": []}


def _deals(env, token, ctid, start, end):
    calls["deals"] = (end - start, token)
    return {"deals": [], "truncated": False, "timezone": "Europe/Amsterdam"}


def _orders(env, token, ctid, start, end):
    calls["orders"] = (env, ctid, end > start)
    return {"orders": [], "truncated": False, "timezone": "Europe/Amsterdam"}


RO.describe_summary = _summary
V.describe_open, V.describe_deals, V.describe_orders = _open, _deals, _orders
try:
    status, body, _log = _call(
        "GET", f"/api/v1/admin/audit/accounts/{CTID}", "operator-token")
    check("summary is the stored demo account",
          status == 200 and body["account"]["equity"] == 1000.0
          and body["account"]["environment"] == "demo"
          and calls["summary"][0] == "demo" and calls["summary"][2] == CTID
          and SECRET not in json.dumps(body), str(body)[:300])
    status, body, _log = _call(
        "GET", f"/api/v1/admin/audit/accounts/{CTID}/open", "operator-token")
    check("open positions are a GET",
          status == 200 and body["positions"] == [] and body["pendingOrders"] == [],
          str(body)[:200])
    status, body, _log = _call(
        "GET", f"/api/v1/admin/audit/accounts/{CTID}/deals", "operator-token")
    check("deals default to seven days",
          status == 200 and abs(calls["deals"][0] - 7 * 86400) < 5
          and body["timezone"] == "Europe/Amsterdam"
          and body["from"] and body["to"], str(body)[:300])
    status, body, _log = _call(
        "GET",
        f"/api/v1/admin/audit/accounts/{CTID}/orders"
        "?from=2026-01-01T00:00:00%2B01:00&to=2026-01-08T00:00:00%2B01:00",
        "operator-token")
    check("orders take a time range",
          status == 200 and calls["orders"][2] is True and body["orders"] == [],
          str(body)[:240])
finally:
    RO.describe_summary = _real_summary

_plant("live")
RO.describe_summary = _summary
try:
    calls.pop("summary", None)
    status, body, _log = _call(
        "GET", f"/api/v1/admin/audit/accounts/{CTID}", "operator-token")
finally:
    RO.describe_summary = _real_summary
check("a stored live account is not read while live is blocked",
      status == 400 and body["error"]["code"] == "LIVE_BLOCKED"
      and "summary" not in calls, str(body)[:240])

status, body, _log = _call(
    "GET", "/api/v1/admin/audit/accounts/999", "operator-token")
check("an unknown account is not an empty summary",
      status == 404 and body["error"]["code"] == "NOT_FOUND", str(body)[:200])

check("the audit is metered with the other broker reads",
      RL.classify("GET", "admin/audit/accounts") == "candles"
      and RL.classify("GET", f"admin/audit/accounts/{CTID}/deals") == "candles")

print()
if _fails:
    print(f"FAILED ({len(_fails)})")
    sys.exit(1)
print("All admin-audit checks passed.")
