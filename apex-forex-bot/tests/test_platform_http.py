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

    print("\n5. what is still unbuilt says so over HTTP too")
    for cap in ("journal", "notifications"):
        st, b = call("GET", f"/api/v1/{cap}")
        check(f"{cap} is 501 UNSUPPORTED", st == 501 and
              b["error"]["code"] == "UNSUPPORTED", str(st))
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
finally:
    requests.get = _real_get
    shutil.rmtree(_TMP, ignore_errors=True)

print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
