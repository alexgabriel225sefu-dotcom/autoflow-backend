"""The operator token must never travel in a URL — proven against a live server.

`?token=DASHBOARD_TOKEN` was how the dashboard authenticated. A credential in
a URL is a credential in the browser history, in every proxy and web-server
access log between the browser and here, in the Referer header of any outbound
link, and in any screenshot of the address bar. Render logs request paths.
Rotating a token that has already been copied into all of those is not a
rotation, it is a hope.

`tests/test_dashboard_auth.py` reads the source. This one starts the real
HTTP server and attacks it, because a static check cannot tell whether a route
actually refuses.

Run: python tests/test_dashboard_session.py
"""
import json
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-dashsess-")

TOKEN = "test-dashboard-token-0123456789abcdef"
os.environ["DASHBOARD_TOKEN"] = TOKEN

_s = socket.socket()
_s.bind(("127.0.0.1", 0))
PORT = _s.getsockname()[1]
_s.close()
os.environ["PORT"] = str(PORT)

from apex import bot, http_security, http_session  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


BASE = f"http://127.0.0.1:{PORT}"


def call(path, method="GET", body=None, headers=None):
    """(status, body_text, response_headers). Never raises on an HTTP error."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    # Mark the request as arriving over TLS the way Render's proxy does, so
    # the Secure cookie attribute is exercised rather than skipped.
    req.add_header("X-Forwarded-Proto", "https")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


bot._start_dashboard_server()
for _ in range(100):
    try:
        urllib.request.urlopen(BASE + "/health", timeout=1).read()
        break
    except Exception:
        time.sleep(0.05)

print("\nDASHBOARD SESSIONS - no credential in any URL\n")

print("1. A token in the query string is REFUSED, not merely ignored")
for path in ("/api/status", "/api/candles", "/"):
    st, body, _ = call(f"{path}?token={TOKEN}")
    check(f"{path}?token=<correct token> -> 401", st == 401, f"got {st}")
st, body, _ = call(f"/api/status?token={TOKEN}")
check("the refusal explains why a URL token cannot work",
      "history" in body.lower() or "url" in body.lower(), body[:160])
check("the refusal does not echo the token back", TOKEN not in body, body[:160])

print("\n2. Missing and malformed authentication are refused")
for name, hdrs in (
    ("no credential at all",      {}),
    ("empty bearer",              {"Authorization": "Bearer "}),
    ("wrong scheme",              {"Authorization": "Basic " + TOKEN}),
    ("bearer with wrong token",   {"Authorization": "Bearer not-the-token"}),
    ("bearer with token prefix",  {"Authorization": "Bearer " + TOKEN[:20]}),
    ("garbage cookie",            {"Cookie": "apex_session=nonsense"}),
    ("empty cookie",              {"Cookie": "apex_session="}),
    ("someone else's cookie name", {"Cookie": "session=" + TOKEN}),
):
    st, _, _ = call("/api/status", headers=hdrs)
    check(f"{name} -> 401", st == 401, f"got {st}")

print("\n3. The Authorization header still works, for scripts and ops")
st, body, _ = call("/api/status", headers={"Authorization": "Bearer " + TOKEN})
check("Bearer <token> -> 200", st == 200, f"got {st}")
check("and returns the account payload", '"balance"' in body, body[:120])

print("\n4. Login exchanges the token for a session cookie")
st, body, hdrs = call("/api/session", method="POST", body={"token": TOKEN})
check("POST /api/session with the right token -> 200", st == 200, f"got {st} {body[:120]}")
cookie = hdrs.get("Set-Cookie", "")
check("a session cookie is set", "apex_session=" in cookie, cookie)
check("it is HttpOnly - page script cannot read it", "HttpOnly" in cookie, cookie)
check("it is SameSite=Strict - another origin cannot ride it",
      "SameSite=Strict" in cookie, cookie)
check("it is Secure - it never crosses plain HTTP", "Secure" in cookie, cookie)
check("it expires", "Max-Age=" in cookie, cookie)
check("the response body does not contain the session id",
      "apex_session" not in body, body[:120])

sid = cookie.split("apex_session=")[1].split(";")[0]
st, body, _ = call("/api/status", headers={"Cookie": f"apex_session={sid}"})
check("the session cookie authenticates", st == 200, f"got {st}")

print("\n5. Wrong and malformed logins are refused, and say nothing useful")
for name, payload in (("wrong token", {"token": "wrong"}),
                      ("empty token", {"token": ""}),
                      ("null token", {"token": None}),
                      ("no token field", {"nope": 1}),
                      ("token as a number", {"token": 12345})):
    st, body, hdrs = call("/api/session", method="POST", body=payload)
    check(f"{name} -> 401", st == 401, f"got {st}")
    check(f"{name}: no cookie issued", "apex_session=" not in hdrs.get("Set-Cookie", ""))
st, body, _ = call("/api/session", method="POST", body={"token": "wrong"})
check("the failure message is generic", "failed" in body.lower(), body[:120])
check("it does not reveal whether the token was close",
      "length" not in body.lower() and "prefix" not in body.lower(), body[:120])

print("\n6. Sessions expire, and revocation works")
sid2 = http_session.create()
check("a fresh session is valid", http_session.valid(sid2))
http_session.revoke(sid2)
check("a revoked session is not", not http_session.valid(sid2))
st, _, _ = call("/api/status", headers={"Cookie": f"apex_session={sid2}"})
check("and the server refuses it -> 401", st == 401, f"got {st}")

import apex.http_session as hs  # noqa: E402
sid3 = hs.create()
with hs._lock:
    hs._sessions[sid3] = time.time() - 1        # expire it
check("an expired session is not valid", not hs.valid(sid3))
st, _, _ = call("/api/status", headers={"Cookie": f"apex_session={sid3}"})
check("and the server refuses it -> 401", st == 401, f"got {st}")

print("\n7. Logout revokes")
st, _, hdrs = call("/api/session", method="POST", body={"token": TOKEN})
sid4 = hdrs.get("Set-Cookie", "").split("apex_session=")[1].split(";")[0]
st, _, _ = call("/api/status", headers={"Cookie": f"apex_session={sid4}"})
check("session works before logout", st == 200, f"got {st}")
st, _, hdrs = call("/api/session/logout", method="POST", body={},
                   headers={"Cookie": f"apex_session={sid4}"})
check("logout -> 200", st == 200, f"got {st}")
check("and clears the cookie", "Max-Age=0" in hdrs.get("Set-Cookie", ""))
st, _, _ = call("/api/status", headers={"Cookie": f"apex_session={sid4}"})
check("the session no longer authenticates -> 401", st == 401, f"got {st}")

print("\n8. Session ids are unguessable")
ids = {http_session.create() for _ in range(200)}
check("200 sessions produced 200 distinct ids", len(ids) == 200, str(len(ids)))
check("each carries at least 128 bits of entropy",
      all(len(i) >= 22 for i in ids), str(min(len(i) for i in ids)))
http_session.revoke_all()

print("\n9. Login is rate limited")
http_security.LOGIN.reset()
codes = [call("/api/session", method="POST", body={"token": "wrong"})[0]
         for _ in range(http_security.LOGIN.limit + 6)]
check("guessing eventually gets 429", 429 in codes, str(codes[-4:]))
check("...and not before the limit", codes[0] == 401, str(codes[:2]))
http_security.LOGIN.reset()
st, _, _ = call("/api/session", method="POST", body={"token": TOKEN})
check("a legitimate login still works after a reset", st == 200, f"got {st}")

print("\n10. Security headers are on the responses")
st, _, hdrs = call("/api/status", headers={"Authorization": "Bearer " + TOKEN})
for h, want in (("X-Content-Type-Options", "nosniff"),
                ("Referrer-Policy", "no-referrer"),
                ("Cache-Control", "no-store"),
                ("Content-Security-Policy", "default-src"),
                ("Strict-Transport-Security", "max-age="),
                ("Permissions-Policy", "camera=()")):
    check(f"{h}: {want}", want in (hdrs.get(h) or ""), f"got {hdrs.get(h)!r}")
check("no wildcard CORS on an authenticated endpoint",
      hdrs.get("Access-Control-Allow-Origin") != "*",
      repr(hdrs.get("Access-Control-Allow-Origin")))

print("\n11. An unauthenticated browser gets a login form, not a dead end")
st, body, _ = call("/")
check("GET / -> 200", st == 200, f"got {st}")
check("it is a sign-in page", "current-password" in body, body[:160])
check("it posts to /api/session", "/api/session" in body)
check("it contains no account data", "balance" not in body.lower())
check("and no token", TOKEN not in body)

print("\n12. /health stays open and leaks nothing")
st, body, _ = call("/health")
check("/health -> 200 without credentials", st == 200, f"got {st}")
check("it carries no token", TOKEN not in body, body[:120])

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL DASHBOARD-SESSION CHECKS PASSED - no credential travels in a URL.")
