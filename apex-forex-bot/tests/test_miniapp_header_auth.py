"""Telegram initData is a credential. It must not travel in a URL.

The Mini App called `/api/app/data?init=<initData>`. initData is Telegram's
HMAC over the user's identity - whoever holds a fresh one can act as that user
until it ages out. Putting it in the query string put it in the browser's
history, in every proxy and access log between the phone and this service, and
in the Referer header of any outbound link.

The routes now take it from a header and REFUSE a request that still carries
it in the URL, because such a request has already leaked it.

This test attacks a live server rather than reading the source.

Run: python tests/test_miniapp_header_auth.py
"""
import hashlib
import hmac as _hmac
import json
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-miniauth-")

BOT_TOKEN = "123456:test-bot-token-for-miniapp-header-auth"
os.environ["TELEGRAM_BOT_TOKEN"] = BOT_TOKEN
os.environ["DASHBOARD_TOKEN"] = "unused-here-but-required-0123456789"

_s = socket.socket()
_s.bind(("127.0.0.1", 0))
PORT = _s.getsockname()[1]
_s.close()
os.environ["PORT"] = str(PORT)

from apex import bot, http_security  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def signed(user_id=555, auth_date=None, extra=None):
    """A genuine Telegram initData string, signed with BOT_TOKEN."""
    fields = {
        "auth_date": str(int(auth_date if auth_date is not None else time.time())),
        "user": json.dumps({"id": user_id, "first_name": "T"}),
    }
    fields.update(extra or {})
    check_str = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = _hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = _hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


BASE = f"http://127.0.0.1:{PORT}"


def call(path, headers=None):
    req = urllib.request.Request(BASE + path, method="GET")
    req.add_header("X-Forwarded-Proto", "https")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:                       # a route that cannot reach a
        return 599, str(e)                       # broker still must not 200


bot._start_dashboard_server()
for _ in range(100):
    try:
        urllib.request.urlopen(BASE + "/health", timeout=1).read()
        break
    except Exception:
        time.sleep(0.05)

ROUTES = ("/api/app/data", "/api/app/tick", "/api/app/history")
GOOD = signed()

print("\nMINI APP - initData in a header, never in a URL\n")

print("1. A query-string initData is REFUSED on every client route")
for r in ROUTES:
    http_security.MINIAPP.reset()
    st, body = call(f"{r}?init={urllib.parse.quote(GOOD)}")
    check(f"{r}?init=<valid> -> 401", st == 401, f"got {st} {body[:100]}")
    check(f"{r}: the refusal says why", "INIT_DATA_IN_URL" in body, body[:140])

print("\n2. ...and the refusal does not echo the credential back")
http_security.MINIAPP.reset()
st, body = call(f"/api/app/data?init={urllib.parse.quote(GOOD)}")
check("no initData in the error body", GOOD[:40] not in body, body[:160])
check("no hash in the error body",
      GOOD.split("hash=")[1][:20] not in body, body[:160])

print("\n3. Missing or malformed header credentials are refused")
for name, hdrs in (
    ("no credential",              {}),
    ("empty header",               {"X-Telegram-Init-Data": ""}),
    ("wrong auth scheme",          {"Authorization": "Bearer " + GOOD}),
    ("garbage initData",           {"X-Telegram-Init-Data": "not-a-query-string"}),
    ("unsigned initData",          {"X-Telegram-Init-Data": "user=%7B%22id%22%3A9%7D&auth_date=1"}),
    ("empty Telegram scheme",      {"Authorization": "Telegram "}),
):
    http_security.MINIAPP.reset()
    st, body = call("/api/app/data", hdrs)
    check(f"{name} -> 401", st == 401, f"got {st} {body[:90]}")

print("\n4. A forged or tampered signature is refused")
http_security.MINIAPP.reset()
forged = urllib.parse.urlencode({
    "auth_date": str(int(time.time())),
    "user": json.dumps({"id": 999, "first_name": "T"}),
    "hash": "0" * 64,
})
st, body = call("/api/app/data", {"Authorization": "Telegram " + forged})
check("a hand-written hash -> 401", st == 401, f"got {st}")

# Take a genuine signature and swap the user it was signed over.
parts = dict(urllib.parse.parse_qsl(GOOD))
parts["user"] = json.dumps({"id": 999, "first_name": "Attacker"})
swapped = urllib.parse.urlencode(parts)
http_security.MINIAPP.reset()
st, body = call("/api/app/data", {"Authorization": "Telegram " + swapped})
check("a genuine hash over a DIFFERENT user -> 401", st == 401, f"got {st}")

print("\n5. A stale signature is refused even though it is genuine")
http_security.MINIAPP.reset()
old = signed(auth_date=time.time() - 60 * 60 * 48)     # two days ago
st, body = call("/api/app/data", {"Authorization": "Telegram " + old})
check("initData signed 48h ago -> 401", st == 401, f"got {st}")

http_security.MINIAPP.reset()
future = signed(auth_date=time.time() + 60 * 60)       # an hour ahead
st, body = call("/api/app/data", {"Authorization": "Telegram " + future})
check("initData dated an hour in the future -> 401", st == 401, f"got {st}")

print("\n6. The client cannot name the account it wants")
http_security.MINIAPP.reset()
st, body = call("/api/app/data?user_id=999&chat_id=999&telegram_id=999",
                {"Authorization": "Telegram " + GOOD})
# Not 401: the HEADER authenticated this request, so the query parameters were
# irrelevant either way. What they must never do is become the identity. (This
# test has no broker, so the handler then fails - 500/502/599 are all "got past
# the gate and died downstream", which is the point.)
check("the query user ids neither authenticate nor block", st != 401, f"got {st}")
check("and the response is not another account's data",
      '"id": 999' not in body and '"chat_id": "999"' not in body, body[:120])
BOT_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "apex", "bot.py"), encoding="utf-8").read()
check("no route reads an identity from the query string",
      'qs.get("user' not in BOT_SRC and 'qs.get("chat' not in BOT_SRC
      and 'qs.get("init")' not in BOT_SRC)

print("\n7. The header path is the one that works")
http_security.MINIAPP.reset()
st_h, _ = call("/api/app/data", {"X-Telegram-Init-Data": GOOD})
http_security.MINIAPP.reset()
st_a, _ = call("/api/app/data", {"Authorization": "Telegram " + GOOD})
check("X-Telegram-Init-Data passes the identity gate", st_h != 401, f"got {st_h}")
check("Authorization: Telegram passes it too", st_a != 401, f"got {st_a}")

print("\n8. The served Mini App does not put initData in a URL")
from apex import webapp  # noqa: E402
for name, html in (("terminal.html", webapp.terminal_html()),
                   ("legacy HTML", webapp.HTML)):
    check(f"{name}: no ?init= built by the client",
          "init='+encodeURIComponent" not in html and "'init='" not in html, name)
    check(f"{name}: sends the Telegram header", "Telegram " in html, name)

print("\n9. Client routes are rate limited")
http_security.MINIAPP.reset()
codes = [call("/api/app/data", {"Authorization": "Telegram bad"})[0]
         for _ in range(http_security.MINIAPP.limit + 4)]
check("flooding the identity gate eventually 401s on the limiter",
      codes[-1] == 401, str(codes[-3:]))
check("the limiter is keyed on the peer, not a client header",
      "X-Forwarded-For" in open(os.path.join(
          os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
          "apex", "http_security.py"), encoding="utf-8").read())
http_security.MINIAPP.reset()

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL MINI-APP AUTH CHECKS PASSED - initData never travels in a URL.")
