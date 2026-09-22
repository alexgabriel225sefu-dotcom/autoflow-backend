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
_USER = {"id": ALICE, "email": "alice@example.com",
         "email_confirmed_at": "2026-01-01T00:00:00Z"}


class _Resp:
    status_code = 200

    def json(self):
        return _USER


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
    for cap in ("positions", "orders", "journal", "notifications"):
        st, b = call("GET", f"/api/v1/{cap}")
        check(f"{cap} is 501 UNSUPPORTED", st == 501 and
              b["error"]["code"] == "UNSUPPORTED", str(st))
    st, b = call("GET", "/api/v1/accounts")
    check("accounts is no longer 501 — it reports the real link state",
          st == 200 and b["connected"] is False, f"{st} {b}")
finally:
    requests.get = _real_get
    shutil.rmtree(_TMP, ignore_errors=True)

print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
