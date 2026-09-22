"""The platform API over real HTTP, mounted in the real server.

Every other platform test calls handle() directly, which is the right way to
test decisions. This one exists for the things only a socket can show: that
the mount actually happened, that the Authorization header survives the trip,
that a request body is read from the wire, and — the part that would be easy
to break silently — that the routes which were already in this server still
answer exactly as they did.

That last one is why /health is checked here. Reading the request body before
knowing whether the path is ours would starve whichever existing handler the
request was really for, and nothing in the platform's own tests would notice.

Run: python tests/test_platform_http.py
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-http-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
# A real key: the OAuth state is signed with material derived from it, and
# without one the connect endpoint correctly answers 503 rather than signing
# with something weaker.
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("ALLOW_PLAINTEXT_DEV_STORAGE", None)
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ["DASHBOARD_TOKEN"] = "operator-token-for-the-old-routes"
os.environ["CTRADER_REDIRECT_URI"] = "https://apex4traders.test/api/v1/ctrader/callback"
os.environ.pop("RENDER_EXTERNAL_URL", None)     # no keepalive thread
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

with socket.socket() as _s:
    _s.bind(("127.0.0.1", 0))
    PORT = _s.getsockname()[1]
os.environ["PORT"] = str(PORT)

import requests  # noqa: E402

ALICE = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
BOB = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
_USERS = {
    ALICE: {"id": ALICE, "email": "alice@example.com",
            "email_confirmed_at": "2026-01-01T00:00:00Z"},
    BOB: {"id": BOB, "email": "bob@example.com",
          "email_confirmed_at": "2026-01-01T00:00:00Z"},
}
_WHO = {"id": ALICE}


class _Resp:
    status_code = 200

    def json(self):
        return _USERS[_WHO["id"]]


_real_get = requests.get


def _fake_get(url, **kw):
    if "supabase" in str(url):
        return _Resp()
    return _real_get(url, **kw)


requests.get = _fake_get

from apex import bot  # noqa: E402
from apex.platform import identity as I  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def as_user(uid):
    from apex.platform import identity as _I
    _WHO["id"] = uid
    _I.forget_all()


def call(method, path, body=None, auth="Bearer alice-token"):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    headers = {}
    if auth:
        headers["Authorization"] = auth
    payload = None
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    c.request(method, path, body=payload, headers=headers)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        return r.status, json.loads(raw or b"{}")
    except Exception:
        return r.status, raw.decode("utf-8", "replace")


try:
    bot._start_dashboard_server()
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)

    print("\n1. the routes that were here before still answer")
    st, body = call("GET", "/health", auth=None)
    check("/health still returns 200 without a token", st == 200, str(st))
    check("and still says ok, not JSON from the new API", body == "ok",
          str(body)[:40])
    st, _ = call("GET", "/api/app/data", auth=None)
    check("an existing protected route still refuses anonymously",
          st in (401, 403, 503), str(st))

    print("\n2. the platform API is mounted and authenticates over the wire")
    st, b = call("GET", "/api/v1/me", auth=None)
    check("no Authorization header is 401", st == 401, str(st))
    st, b = call("GET", "/api/v1/me")
    check("a bearer token is carried through the transport",
          st == 200 and b["user"]["userId"] == ALICE, f"{st} {b}")
    check("the reply is JSON with the licence state",
          b["licence"]["state"] == "none", str(b.get("licence")))
    st, b = call("GET", "/api/v1/conditions")
    check("the condition library is served over HTTP",
          st == 200 and len(b["conditions"]) == 12,
          f"{st} {len(b.get('conditions', {}))}")

    print("\n3. a request body is read from the wire")
    st, b = call("POST", "/api/v1/rules", body={
        "name": "http rule", "symbols": ["EUR_USD"], "timeframe": "1h",
        "accountId": "ct-demo-1", "sides": "BUY",
        "entry": {"combine": "AND", "conditions": [
            {"id": "rsi", "params": {"op": "below", "value": 30}}]},
        "exit": {"combine": "OR", "conditions": [
            {"id": "rsi", "params": {"op": "above", "value": 70}}]}})
    check("a POST body arrives intact", st == 200 and
          b["rule"]["name"] == "http rule", f"{st} {str(b)[:80]}")
    rid = b["rule"]["ruleDocId"]
    check("the rule is owned by the token's user",
          b["rule"]["userId"] == ALICE)
    st, b = call("GET", "/api/v1/rules")
    check("and comes back in the list",
          st == 200 and [r["ruleDocId"] for r in b["rules"]] == [rid])
    st, b = call("POST", "/api/v1/rules", body="not-json-at-all")
    check("a malformed body is 400, not a 500", st == 400, str(st))

    print("\n4. the OAuth callback answers unauthenticated, and only it does")
    st, b = call("GET", "/api/v1/ctrader/callback", auth=None)
    check("the callback is reachable with no session", st == 400, str(st))
    check("and refuses for the right reason, not for the missing token",
          b["error"]["code"] == "STATE_MISSING", str(b.get("error")))
    st, b = call("POST", "/api/v1/ctrader/connect", auth=None)
    check("but connecting still needs a session", st == 401, str(st))

    st, b = call("POST", "/api/v1/ctrader/connect")
    check("a signed-in client gets an authorize URL",
          st == 200 and b["authorizeUrl"].startswith("https://id.ctrader.com/"),
          f"{st} {str(b)[:70]}")
    nonce = b["nonce"]
    state = b["authorizeUrl"].split("state=")[1].split("&")[0]
    st, b = call("GET", f"/api/v1/ctrader/callback?code=abc123&state={state}",
                 auth=None)
    check("a real callback is accepted over HTTP", st == 200, f"{st} {b}")
    check("it returns only the nonce", b.get("nonce") == nonce, str(b))
    check("and never echoes the authorization code",
          "abc123" not in json.dumps(b), json.dumps(b)[:80])
    st, b = call("GET", "/api/v1/ctrader/status")
    check("the account is not connected until it is completed",
          b["ctrader"]["connected"] is False, str(b))

    print("\n5. reads answer with a stated status, never a bare empty list")
    # Nothing is 501 any more. What replaced it is a stronger claim: each of
    # these says the store WAS read. Sections 8 and 9 then put real entries
    # behind them.
    for cap, key in (("journal", "entries"), ("notifications",
                                              "notifications")):
        st, b = call("GET", f"/api/v1/{cap}")
        check(f"{cap} reads ok and empty", st == 200
              and b["status"] == "ok" and b[key] == [], f"{st} {b}")
    st, b = call("GET", "/api/v1/accounts")
    check("accounts is no longer 501 — it reports the real link state",
          st == 200 and b["connected"] is False, f"{st} {b}")
    print("\n6. reading a cTrader account, read-only")
    from apex import user_store
    from apex.platform import ctrader_link as CL

    # Paper mode, so the connector answers from the paper path and no socket
    # is opened to cTrader. The [] it returns is a FACT about paper mode, not
    # a placeholder — which is exactly the distinction under test.
    user_store.save(ALICE, {"paper": True, "paper_balance": 5000})
    started = call("POST", "/api/v1/ctrader/connect")[1]
    state = started["authorizeUrl"].split("state=")[1].split("&")[0]
    call("GET", f"/api/v1/ctrader/callback?code=c&state={state}", auth=None)
    CL.complete(ALICE, started["nonce"],
                exchanger=lambda c, u: {"accessToken": "ALICE-TOKEN-SECRET",
                                        "refreshToken": "ALICE-REFRESH",
                                        "expiresIn": 2592000},
                lister=lambda a: [{"ctid": 501, "live": False, "label": "D"},
                                  {"ctid": 502, "live": True, "label": "L"}])
    st, b = call("POST", "/api/v1/ctrader/select", body={"ctid": 501})
    check("a demo account can be selected over HTTP",
          st == 200 and b["ctrader"]["selected"]["mode"] == "demo", str(st))

    st, b = call("GET", "/api/v1/positions")
    check("an authorised client reads positions", st == 200 and
          b["status"] == "ok", f"{st} {b}")
    check("the answer names the account and says demo, not just 'connected'",
          b["accountId"] == 501 and b["mode"] == "demo", str(b))
    check("and the empty list came with an ok status, not on its own",
          b["positions"] == [] and b["connected"] is True, str(b))
    st, b = call("GET", "/api/v1/orders")
    check("orders reads the same way", st == 200 and b["status"] == "ok"
          and b["orders"] == [], f"{st} {b}")
    st, b = call("GET", "/api/v1/accounts/501/positions")
    check("the per-account route works for a connected account",
          st == 200 and b["accountId"] == 501, f"{st} {b}")
    st, b = call("GET", "/api/v1/accounts/501")
    check("and the account itself reports its balance and mode",
          st == 200 and b["mode"] == "demo" and "balance" in b, str(b)[:90])
    check("no token appears anywhere in a read response",
          "ALICE-TOKEN-SECRET" not in json.dumps(b))

    st, b = call("GET", "/api/v1/accounts/999/positions")
    check("an account that is not connected is refused",
          st == 400 and b["error"]["code"] == "NO_SUCH_ACCOUNT", f"{st} {b}")
    st, b = call("GET", "/api/v1/accounts/502/positions")
    check("a live account is refused in this environment",
          st == 400 and b["error"]["code"] == "LIVE_BLOCKED", f"{st} {b}")

    as_user(BOB)
    st, b = call("GET", "/api/v1/positions")
    check("a client with nothing linked reads as not connected",
          st == 200 and b["connected"] is False
          and "positions" not in b, str(b))
    # Give Bob his OWN connection, so the next check tests ownership rather
    # than simply hitting "you have no connection at all" — which would pass
    # even if the ownership check were deleted.
    user_store.save(BOB, {"paper": True, "paper_balance": 100})
    b_started = call("POST", "/api/v1/ctrader/connect")[1]
    b_state = b_started["authorizeUrl"].split("state=")[1].split("&")[0]
    call("GET", f"/api/v1/ctrader/callback?code=c&state={b_state}", auth=None)
    CL.complete(BOB, b_started["nonce"],
                exchanger=lambda c, u: {"accessToken": "BOB-TOKEN-SECRET",
                                        "refreshToken": "BOB-REFRESH",
                                        "expiresIn": 2592000},
                lister=lambda a: [{"ctid": 777, "live": False, "label": "B"}])
    call("POST", "/api/v1/ctrader/select", body={"ctid": 777})
    st_own, b_own = call("GET", "/api/v1/accounts/777/positions")
    check("Bob can read his own account", st_own == 200 and
          b_own["accountId"] == 777, f"{st_own} {b_own}")
    st, b = call("GET", "/api/v1/accounts/501/positions")
    check("but not Alice's, even though it exists",
          st == 400 and b["error"]["code"] == "NO_SUCH_ACCOUNT", f"{st} {b}")
    st2, b2 = call("GET", "/api/v1/accounts/999/positions")
    check("and Alice's account is indistinguishable from one that does not "
          "exist at all",
          (st, b["error"]["code"]) == (st2, b2["error"]["code"]),
          f"{st}/{st2}")
    check("Bob's read never carries Alice's token",
          "ALICE-TOKEN-SECRET" not in json.dumps(b_own))
    as_user(ALICE)

    # An expired token whose refresh cannot work must not read as "no
    # positions". The remedy is to reconnect, and the status has to say so.
    conn = CL._read_conn(ALICE)
    conn["expiresAt"] = 1.0
    conn["refreshToken"] = ""
    CL._store._write(CL._k_conn(ALICE), conn)
    st, b = call("GET", "/api/v1/positions")
    check("an unrefreshable token reports reauth_required",
          st == 200 and b["status"] == "reauth_required", f"{st} {b}")
    check("and returns no positions key at all", "positions" not in b, str(b))
    check("while still reporting the account as connected",
          b["connected"] is True, str(b))
    conn["expiresAt"] = None
    conn["refreshToken"] = user_store.encrypt_value("ALICE-REFRESH")
    CL._store._write(CL._k_conn(ALICE), conn)

    # A broker that fails is not an account with nothing in it.
    from apex import user_loop as _ul
    _real_mb = _ul._make_broker
    try:
        def _boom(user, user_id=None):
            raise RuntimeError("cTrader socket closed while token "
                               "ALICE-TOKEN-SECRET was in use")
        _ul._make_broker = _boom
        st, b = call("GET", "/api/v1/positions")
        check("a broker failure reports unavailable, not an empty account",
              st == 200 and b["status"] == "unavailable", f"{st} {b}")
        check("no positions are claimed", "positions" not in b, str(b))
        check("and the token is scrubbed out of the error",
              "ALICE-TOKEN-SECRET" not in json.dumps(b)
              and "[redacted]" in json.dumps(b), str(b)[:140])
        # The check above breaks broker CONSTRUCTION. This one breaks the
        # CALL, which is the likelier failure in production — a socket that
        # constructs fine and then times out mid-request — and it travels a
        # different code path.
        class _TimingOutBroker:
            def get_all_positions(self):
                raise TimeoutError("cTrader did not answer within 12s")

            def get_pending_orders(self):
                raise TimeoutError("cTrader did not answer within 12s")

        _ul._make_broker = lambda user, user_id=None: (_TimingOutBroker(), {})
        st, b = call("GET", "/api/v1/positions")
        check("a broker that times out mid-call reports unavailable",
              st == 200 and b["status"] == "unavailable", f"{st} {b}")
        check("and claims no positions", "positions" not in b, str(b))
        check("the account it failed on is still named",
              b.get("accountId") == 501, str(b))
        st, b = call("GET", "/api/v1/orders")
        check("orders behaves the same way on a timeout",
              st == 200 and b["status"] == "unavailable"
              and "orders" not in b, f"{st} {b}")
    finally:
        _ul._make_broker = _real_mb

    st, b = call("POST", "/api/v1/ctrader/disconnect")
    check("disconnecting is accepted", st == 200, str(st))
    st, b = call("GET", "/api/v1/positions")
    check("a disconnected account reads as connected: false",
          st == 200 and b["connected"] is False, f"{st} {b}")
    check("and claims no positions", "positions" not in b, str(b))

    print("\n8. the journal: real entries, filtered and paged")
    from apex.platform import decision as _D
    from apex.platform import journal_store as JS
    from apex.platform import notifications as NF

    st, b = call("GET", "/api/v1/journal")
    check("a client who has done nothing gets an ok read, not a placeholder",
          st == 200 and b["status"] == "ok" and b["entries"] == []
          and b["total"] == 0, f"{st} {b}")

    def _dec(verdict, symbol, code=None):
        return _D.RuleDecision(verdict=verdict, rule_doc_id="rule-a",
                               rule_doc_version=1, symbol=symbol,
                               snapshot_ts=1000.0, reason="t",
                               refusal_code=code,
                               side=verdict if verdict in ("BUY", "SELL")
                               else None)

    JS.record_evaluation(_dec("HOLD", "EUR_USD"), None, correlation_id="c1",
                         user_id=ALICE, account_id="501", ts=1000.0)
    JS.record_evaluation(_dec("REJECT", "EUR_USD", "INSUFFICIENT_DATA"), None,
                         correlation_id="c2", user_id=ALICE,
                         account_id="501", ts=2000.0)
    JS.record_evaluation(_dec("BUY", "GBP_USD"), None, correlation_id="c3",
                         user_id=ALICE, account_id="502", ts=3000.0)
    JS.record_error("cTrader socket closed", correlation_id="c4",
                    user_id=ALICE, account_id="501", symbol="EUR_USD",
                    ts=4000.0)
    JS.record_position_closed({"symbol": "EUR_USD", "pnl": 12.5},
                              correlation_id="c5", user_id=ALICE,
                              account_id="501", ts=5000.0)
    JS.record_evaluation(_dec("HOLD", "EUR_USD"), None, correlation_id="c9",
                         user_id=BOB, account_id="777", ts=9000.0)

    st, b = call("GET", "/api/v1/journal")
    check("every entry comes back, newest first",
          st == 200 and b["total"] == 5
          and b["entries"][0]["correlationId"] == "c5", f"{st} {b['total']}")
    check("each entry names which of the nine things it is",
          [e["status"] for e in b["entries"]] ==
          ["position_closed", "broker_error", "evaluated", "reject", "hold"],
          str([e["status"] for e in b["entries"]]))
    st, b = call("GET", "/api/v1/journal?status=hold")
    check("filtering by status works",
          b["total"] == 1 and b["entries"][0]["status"] == "hold", str(b))
    st, b = call("GET", "/api/v1/journal?status=reject")
    check("a REJECT is distinguishable from a HOLD",
          b["total"] == 1 and b["entries"][0]["status"] == "reject", str(b))
    st, b = call("GET", "/api/v1/journal?symbol=GBP_USD")
    check("filtering by symbol works", b["total"] == 1, str(b["total"]))
    st, b = call("GET", "/api/v1/journal?accountId=501")
    check("filtering by account works", b["total"] == 4, str(b["total"]))
    st, b = call("GET", "/api/v1/journal?ruleDocId=rule-a")
    check("filtering by RuleDoc works", b["total"] == 3, str(b["total"]))
    st, b = call("GET", "/api/v1/journal?since=2500&until=4500")
    check("filtering by period works", b["total"] == 2, str(b["total"]))
    st, b = call("GET", "/api/v1/journal?limit=2")
    check("paging returns a page and says there is more",
          len(b["entries"]) == 2 and b["hasMore"] is True and b["total"] == 5,
          str(b["total"]))
    st, b2 = call("GET", "/api/v1/journal?limit=2&offset=4")
    check("the last page says there is no more",
          len(b2["entries"]) == 1 and b2["hasMore"] is False, str(b2))
    check("pages do not overlap",
          b["entries"][0]["entryId"] != b2["entries"][0]["entryId"])
    st, b = call("GET", "/api/v1/journal?status=not-a-status")
    check("an unknown status is refused, not silently ignored",
          st == 400, f"{st} {b}")
    st, b = call("GET", "/api/v1/journal?limit=abc")
    check("a non-numeric limit is refused rather than defaulted",
          st == 400, f"{st} {b}")

    one = call("GET", "/api/v1/journal?limit=1")[1]["entries"][0]
    st, b = call("GET", f"/api/v1/journal/{one['entryId']}")
    check("a single entry can be fetched", st == 200 and
          b["entry"]["entryId"] == one["entryId"], f"{st} {b}")
    as_user(BOB)
    st, b = call("GET", f"/api/v1/journal/{one['entryId']}")
    check("another client cannot read it", st == 404, f"{st} {b}")
    st, b = call("GET", "/api/v1/journal")
    check("and sees only their own", b["total"] == 1
          and b["entries"][0]["correlationId"] == "c9", str(b["total"]))
    as_user(ALICE)
    check("no token appears anywhere in a journal page",
          "ALICE-TOKEN-SECRET" not in json.dumps(
              call("GET", "/api/v1/journal")[1]))

    print("\n9. notifications, in the platform and not in Telegram")
    st, b = call("GET", "/api/v1/notifications")
    check("an empty centre is an ok read", st == 200
          and b["notifications"] == [] and b["unread"] == 0, f"{st} {b}")
    NF.notify(ALICE, type=NF.ACCOUNT, title="cTrader connected", ts=1000.0)
    NF.notify(ALICE, type=NF.ORDER, title="Order refused",
              level=NF.WARNING, ts=2000.0)
    NF.notify(BOB, type=NF.SYSTEM, title="Bob only", ts=3000.0)
    st, b = call("GET", "/api/v1/notifications")
    check("both of Alice's arrive, newest first",
          b["total"] == 2 and b["unread"] == 2
          and b["notifications"][0]["title"] == "Order refused", str(b))
    check("Bob's is not among them",
          "Bob only" not in json.dumps(b))
    st, b = call("GET", "/api/v1/notifications?type=order")
    check("filtering by type works", b["total"] == 1, str(b["total"]))
    check("but the unread badge still counts everything",
          b["unread"] == 2, str(b["unread"]))
    nid = b["notifications"][0]["id"]
    st, b = call("POST", f"/api/v1/notifications/{nid}/read")
    check("one can be marked read", st == 200 and b["unread"] == 1,
          f"{st} {b}")
    as_user(BOB)
    st, b = call("POST", f"/api/v1/notifications/{nid}/read")
    check("another client cannot mark it", st == 404, f"{st} {b}")
    as_user(ALICE)
    st, b = call("POST", "/api/v1/notifications/read-all")
    check("all can be marked read", st == 200 and b["marked"] == 1
          and b["unread"] == 0, f"{st} {b}")
    st, b = call("POST", "/api/v1/notifications/read-all")
    check("marking again marks nothing and is not an error",
          st == 200 and b["marked"] == 0, f"{st} {b}")
    st, b = call("GET", "/api/v1/notifications?unread=true")
    check("nothing is unread afterwards", b["total"] == 0, str(b))

    print("\n10. preview: a verdict, on the caller's bars, changing nothing")
    import math as _math
    bars = []
    for i in range(120):
        c = 1.1000 + 0.0050 * _math.sin(2 * _math.pi * i / 41)
        bars.append({"open": c, "high": c + 0.0006, "low": c - 0.0006,
                     "close": c})
    rule = call("POST", "/api/v1/rules", body={
        "name": "preview rule", "symbols": ["EUR_USD"], "timeframe": "1h",
        "accountId": "501", "sides": "BUY",
        "entry": {"combine": "AND", "conditions": [
            {"id": "rsi", "params": {"op": "below", "value": 100}}]},
        "exit": {"combine": "OR", "conditions": [
            {"id": "rsi", "params": {"op": "above", "value": 70}}]}})[1]["rule"]
    prid = rule["ruleDocId"]
    before = call("GET", "/api/v1/journal")[1]["total"]

    st, b = call("POST", f"/api/v1/rules/{prid}/preview",
                 body={"snapshot": {"candles": bars, "ts": 1758542400.0}})
    check("a preview on supplied bars returns a decision",
          st == 200 and b["decision"]["verdict"] == "BUY", f"{st} {b}")
    check("and states plainly that it is not executable",
          b["executable"] is False and b["wouldTrade"] is True, str(b))
    check("the decision names every condition it evaluated",
          len(b["decision"]["conditions"]) == 1, str(b["decision"]))
    check("previewing wrote nothing to the journal",
          call("GET", "/api/v1/journal")[1]["total"] == before,
          str(call("GET", "/api/v1/journal")[1]["total"]))
    check("a draft can be previewed before it is ever activated",
          rule["state"] == "draft")

    st, b = call("POST", f"/api/v1/rules/{prid}/preview", body={"snapshot": {}})
    check("no candles is INSUFFICIENT_DATA, not a verdict",
          st == 422 and b["error"]["code"] == "INSUFFICIENT_DATA", f"{st} {b}")
    st, b = call("POST", f"/api/v1/rules/{prid}/preview",
                 body={"snapshot": {"candles": bars}})
    check("no timestamp is refused — the evaluator must not pick one",
          st == 422 and "ts" in b["error"]["message"], f"{st} {b}")
    st, b = call("POST", f"/api/v1/rules/{prid}/preview", body={
        "snapshot": {"candles": [{"open": 1, "high": 1, "low": 1}],
                     "ts": 1758542400.0}})
    check("a malformed candle is refused, not guessed at",
          st == 422, f"{st} {b}")
    as_user(BOB)
    st, b = call("POST", f"/api/v1/rules/{prid}/preview",
                 body={"snapshot": {"candles": bars, "ts": 1758542400.0}})
    check("another client cannot preview somebody else's rule",
          st == 404, f"{st} {b}")
    as_user(ALICE)

    print("\n11. demo automation: an explicit act, never a side effect")
    from apex import user_loop as _UL
    from apex.platform import automation as AU
    from apex.platform import licence as LC

    started_for, stopped_for = [], []
    _real_start, _real_stop = _UL.start, _UL.stop
    try:
        _UL.start = lambda uid, alert_fn=None: (started_for.append(uid), True)[1]
        _UL.stop = lambda uid: stopped_for.append(uid)

        st, b = call("GET", "/api/v1/automation")
        check("automation starts out stopped", st == 200
              and b["state"] == "stopped", f"{st} {b}")
        check("connecting cTrader did NOT start anything",
              started_for == [], str(started_for))

        active = call("POST", "/api/v1/rules", body={
            "name": "demo rule", "symbols": ["EUR_USD"], "timeframe": "1h",
            "accountId": "501", "sides": "BUY",
            "entry": {"combine": "AND", "conditions": [
                {"id": "rsi", "params": {"op": "below", "value": 30}}]},
            "exit": {"combine": "OR", "conditions": [
                {"id": "rsi", "params": {"op": "above", "value": 70}}]}
        })[1]["rule"]
        arid = active["ruleDocId"]

        st, b = call("POST", "/api/v1/automation/start",
                     body={"ruleDocId": arid})
        check("without a licence, nothing starts", st == 402, f"{st} {b}")
        LC.grant(ALICE, plan="pro")
        st, b = call("POST", "/api/v1/automation/start",
                     body={"ruleDocId": arid})
        check("a DRAFT rule cannot be automated",
              st == 409 and b["error"]["code"] == "RULE_NOT_ACTIVE",
              f"{st} {b}")
        call("POST", f"/api/v1/rules/{arid}/activate")
        check("nothing started merely by activating the rule",
              started_for == [], str(started_for))

        # Alice is still connected to the DEMO account 501 from section 6?
        # No — section 6 disconnected her. Reconnect, demo.
        s2 = call("POST", "/api/v1/ctrader/connect")[1]
        st2 = s2["authorizeUrl"].split("state=")[1].split("&")[0]
        call("GET", f"/api/v1/ctrader/callback?code=c&state={st2}", auth=None)
        CL.complete(ALICE, s2["nonce"],
                    exchanger=lambda c, u: {"accessToken": "ALICE-TOKEN-SECRET",
                                            "refreshToken": "R",
                                            "expiresIn": 2592000},
                    lister=lambda a: [{"ctid": 501, "live": False},
                                      {"ctid": 502, "live": True}])
        st, b = call("POST", "/api/v1/automation/start",
                     body={"ruleDocId": arid})
        check("a connected-but-unselected account does not start it",
              st == 409 and b["error"]["code"] == "NO_ACCOUNT", f"{st} {b}")
        call("POST", "/api/v1/ctrader/select", body={"ctid": 501})
        check("selecting an account still did not start anything",
              started_for == [], str(started_for))

        before_j = call("GET", "/api/v1/journal")[1]["total"]
        paper_before = user_store.load(ALICE).get("paper")
        # Section 8 wrote a deliberate broker_error, so the assertion below
        # has to be "no NEW one", not "none at all".
        errs_before = call("GET",
                           "/api/v1/journal?status=broker_error")[1]["total"]
        st, b = call("POST", "/api/v1/automation/start",
                     body={"ruleDocId": arid})
        check("with licence, active rule and a demo account it starts",
              st == 200 and b["state"] == "running" and b["started"] is True,
              f"{st} {b}")
        check("and the engine was actually asked to run",
              started_for == [ALICE], str(started_for))
        check("the mode is recorded as demo", b["mode"] == "demo", str(b))
        st, b = call("GET", "/api/v1/journal?status=automation_started")
        check("the start is journalled as a start, not as an error",
              b["total"] == 1, str(b["total"]))
        st, b = call("GET", "/api/v1/journal?status=broker_error")
        check("and no fake broker error was written alongside it",
              b["total"] == errs_before, f"{b['total']} vs {errs_before}")
        st, b = call("GET", "/api/v1/notifications?unread=true")
        check("the client is notified in the platform",
              b["total"] == 1 and "started" in
              b["notifications"][0]["title"].lower(), str(b))

        # Automation deliberately does NOT write the live/demo flag — one
        # writer only, and it is the gated one. So the demo guarantee has to
        # come from somewhere else, and this is it: the broker config is
        # derived from the connected account's own mode.
        _u = user_store.load(ALICE)
        check("starting did not touch the live/demo flag — it is what "
              "section 6 set and nothing since",
              _u.get("paper") is True and paper_before == _u.get("paper"),
              f"{paper_before!r} -> {_u.get('paper')!r}")
        _brk, _cfg = _UL._make_broker(_u, ALICE)
        check("yet the broker built for this client is in paper mode",
              _cfg.PAPER_TRADING is True, str(_cfg.PAPER_TRADING))
        check("and points at the selected demo account",
              str(_cfg.CTRADER_ACCOUNT_ID) == "501"
              and _cfg.CTRADER_ENV == "demo",
              f"{_cfg.CTRADER_ACCOUNT_ID}/{_cfg.CTRADER_ENV}")

        st, b = call("POST", "/api/v1/automation/start",
                     body={"ruleDocId": arid})
        check("starting again is idempotent, not a second loop",
              st == 200 and b["alreadyRunning"] is True
              and b["started"] is False, f"{st} {b}")
        check("and the engine was not asked twice",
              started_for == [ALICE], str(started_for))

        other = call("POST", "/api/v1/rules", body={
            "name": "other", "symbols": ["GBP_USD"], "timeframe": "1h",
            "accountId": "501", "sides": "BUY",
            "entry": {"combine": "AND", "conditions": [
                {"id": "rsi", "params": {"op": "below", "value": 30}}]},
            "exit": {"combine": "OR", "conditions": [
                {"id": "rsi", "params": {"op": "above", "value": 70}}]}
        })[1]["rule"]["ruleDocId"]
        call("POST", f"/api/v1/rules/{other}/activate")
        st, b = call("POST", "/api/v1/automation/start",
                     body={"ruleDocId": other})
        check("a second rule cannot run alongside the first",
              st == 409 and b["error"]["code"] == "ALREADY_RUNNING",
              f"{st} {b}")

        st, b = call("POST", "/api/v1/automation/pause")
        check("pausing reports paused", st == 200 and b["state"] == "paused",
              f"{st} {b}")
        check("and the engine was actually stopped, not just flagged",
              stopped_for == [ALICE], str(stopped_for))
        st, b = call("POST", "/api/v1/automation/resume")
        check("resuming runs again", st == 200 and b["state"] == "running",
              f"{st} {b}")
        check("and re-checked everything by starting afresh",
              started_for == [ALICE, ALICE], str(started_for))
        st, b = call("POST", "/api/v1/automation/stop")
        check("stopping reports stopped", st == 200 and b["state"] == "stopped"
              and b["stopped"] is True, f"{st} {b}")
        st, b = call("POST", "/api/v1/automation/stop")
        check("stopping again is not an error",
              st == 200 and b["alreadyStopped"] is True, f"{st} {b}")
        st, b = call("POST", "/api/v1/automation/pause")
        check("pausing something stopped is refused clearly",
              st == 409 and b["error"]["code"] == "NOT_RUNNING", f"{st} {b}")

        st, b = call("POST", "/api/v1/ctrader/select", body={"ctid": 502})
        check("a live account cannot even be selected here",
              st == 400 and b["error"]["code"] == "LIVE_BLOCKED", f"{st} {b}")
        # That is the first lock. Force the record past it to prove the
        # SECOND one — _preflight's own mode check — is really there and not
        # just shadowed by the selection guard.
        _conn = CL._read_conn(ALICE)
        CL._store._write(CL._k_conn(ALICE),
                         dict(_conn, selectedCtid=502, selectedMode="live"))
        asked = len(started_for)
        st, b = call("POST", "/api/v1/automation/start",
                     body={"ruleDocId": arid})
        check("and a live selection forced past that still cannot automate",
              st in (400, 409), f"{st} {b}")
        check("the engine was never asked for the live account",
              len(started_for) == asked, str(started_for))
        CL._store._write(CL._k_conn(ALICE),
                         dict(_conn, selectedCtid=501, selectedMode="demo"))

        as_user(BOB)
        st, b = call("POST", "/api/v1/automation/start",
                     body={"ruleDocId": arid})
        check("another client cannot automate somebody else's rule",
              st in (402, 404), f"{st} {b}")
        st, b = call("GET", "/api/v1/automation")
        check("and their own automation is untouched",
              b["state"] == "stopped", str(b))
        as_user(ALICE)
    finally:
        _UL.start, _UL.stop = _real_start, _real_stop

    print("\n7. the read path cannot trade")
    import ast as _ast
    called = set()
    for node in _ast.walk(_ast.parse(open(os.path.join(
            ROOT, "apex", "platform", "broker_read.py")).read())):
        if isinstance(node, _ast.Attribute):
            called.add(node.attr)
    for forbidden in ("place_order", "close_position", "amend_sltp",
                      "force_trade", "authorize_order"):
        check(f"broker_read.py never calls {forbidden}()",
              forbidden not in called)
    check("it calls only the three read methods",
          {"get_all_positions", "get_pending_orders", "get_balance"} <= called)

    # Preview must be just as incapable. It is checked the same way, and for
    # imports too: a module that cannot reach a broker, a gate, the ledger or
    # the execution controller has no expression that could place an order,
    # whatever anyone later writes inside it.
    _ptree = _ast.parse(open(os.path.join(
        ROOT, "apex", "platform", "preview.py")).read())
    p_called, p_imported = set(), set()
    for node in _ast.walk(_ptree):
        if isinstance(node, _ast.Attribute):
            p_called.add(node.attr)
        elif isinstance(node, _ast.Import):
            p_imported.update(a.name for a in node.names)
        elif isinstance(node, _ast.ImportFrom):
            p_imported.add(node.module or "")
    for forbidden in ("place_order", "close_position", "force_trade",
                      "authorize_order", "authorize_close", "claim",
                      "record", "submit", "build"):
        check(f"preview.py never calls {forbidden}()",
              forbidden not in p_called)
    for module in ("broker", "gates", "ledger", "user_loop", "bridge",
                   "journal", "execution"):
        check(f"preview.py imports nothing from {module}",
              not any(module in m for m in p_imported), str(p_imported))
    # Demo automation may start and stop the engine — that is its job — but
    # it must never place, close or authorise an order itself. It delegates,
    # and delegation is the only thing it is allowed to do.
    _atree = _ast.parse(open(os.path.join(
        ROOT, "apex", "platform", "automation.py")).read())
    a_called = {n.attr for n in _ast.walk(_atree)
                if isinstance(n, _ast.Attribute)}
    for forbidden in ("place_order", "close_position", "amend_sltp",
                      "force_trade", "authorize_order", "authorize_close"):
        check(f"automation.py never calls {forbidden}()",
              forbidden not in a_called)
    check("it drives the engine through start and stop only",
          {"start", "stop"} <= a_called)
    check("and no telegram anywhere in demo automation",
          not any("telegram" in (n.module or "").lower()
                  for n in _ast.walk(_atree)
                  if isinstance(n, _ast.ImportFrom)))

    check("and no telegram anywhere in the notification centre",
          not any("telegram" in m.lower() for m in {
              n.module or "" for n in _ast.walk(_ast.parse(open(os.path.join(
                  ROOT, "apex", "platform", "notifications.py")).read()))
              if isinstance(n, _ast.ImportFrom)}))
finally:
    requests.get = _real_get
    shutil.rmtree(_TMP, ignore_errors=True)

print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
