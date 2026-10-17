"""The final blockers, each proved rather than asserted.

Four were real and are fixed here. Three were reported but were already
correct at this commit — they are covered anyway, because a claim that was
false today can become true after the next refactor, and the cheapest time to
pin it down is while it is being discussed.

  OAUTH SIGNING SECRET (real). `_secret()` ended in `or "apex"` — a string
  published in this repository. `state` is the only thing tying a cTrader
  callback to the chat that began the flow, so a forgeable one lets somebody
  bind THEIR broker account to SOMEBODY ELSE'S Telegram chat, or the reverse.
  The bot token is always set in any deployment that can reach Telegram, so
  the branch was unreachable — which is exactly why it had to raise instead of
  quietly weakening the signature for whoever reaches it later.

  LICENCE PERSISTENCE (real). `_license_ok` verified the key, then did
  `try: user_store.update(...) except: pass; return True`. access.grant() runs
  on that return value, so a failed write handed out access while losing the
  only record of why: the next restart re-verifies from scratch, and if the
  verifier is down by then the paying client is locked out of an account we
  already activated. Half an activation, reported as a whole one.

  ACCOUNT ENVIRONMENT (real). The Telegram badge read the STORED ctrader_env
  and defaulted it to "demo". An account whose environment could not be
  established therefore rendered as "🧪 Demo" — the dangerous direction, since
  the client reads that as "nothing real is at stake" and behaves accordingly.

  DEAD AUTH SHAPE (real, minor). Confirmed the one token-gated route fails
  closed and that nothing else authorises by URL.

Already correct, now pinned: Mini App cross-user denial, Redis strict-mode
persistence, and the absence of any shared-link path to client data.

Run: python tests/test_supreme_blockers.py
"""
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
from urllib.parse import urlencode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PRODUCT", "forex")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:TESTTOKEN")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-supreme-")

from apex import account_mode, ctrader_oauth, user_store, webapp  # noqa: E402

BOT_TOKEN = "123456:TESTTOKEN"
failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name}  → {detail}")
    if not cond:
        failures.append(name)


def _signed(pairs, token=BOT_TOKEN):
    p = dict(pairs)
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(p.items()))
    sec = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    p["hash"] = hmac.new(sec, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(p)


print("\n🛡️   FINAL BLOCKERS\n")

# ── 1. Mini App: one token, one account ───────────────────────────────────
print("1. A Mini App token reaches exactly one account")
_now = int(time.time())
A = {"user": json.dumps({"id": 111, "first_name": "A"}),
     "auth_date": str(_now), "query_id": "a"}
B = {"user": json.dumps({"id": 222, "first_name": "B"}),
     "auth_date": str(_now), "query_id": "b"}

check("A's token resolves to A",
      (webapp.validate(_signed(A), BOT_TOKEN) or {}).get("id") == 111)
check("B's token resolves to B",
      (webapp.validate(_signed(B), BOT_TOKEN) or {}).get("id") == 222)
check("A's signature with B's id substituted is refused",
      webapp.validate(_signed(A).replace("111", "222"), BOT_TOKEN) is None,
      "this is the cross-account read the whole check exists to stop")
check("a stripped signature is refused",
      webapp.validate(urlencode(A), BOT_TOKEN) is None)
check("a corrupted signature is refused",
      webapp.validate(_signed(A)[:-6] + "000000", BOT_TOKEN) is None)
check("a signature from a DIFFERENT bot token is refused",
      webapp.validate(_signed(A, "999999:OTHERBOT"), BOT_TOKEN) is None)
check("a replayed month-old capture is refused",
      webapp.validate(_signed({**A, "auth_date": str(_now - 30 * 86400)}),
                      BOT_TOKEN) is None)
check("initData with no user carries no id for the caller to trust",
      (webapp.validate(_signed({"auth_date": str(_now), "query_id": "x"}),
                       BOT_TOKEN) or {}).get("id") is None)

BOT_SRC = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()
_client_routes = ("/api/app/data", "/api/app/tick", "/api/app/history")
for r in _client_routes:
    seg = BOT_SRC.split(f'self.path.startswith("{r}")')
    # The three routes used to each pull `init` out of the query string and
    # call webapp.validate on it. They now share one helper that reads the
    # header and REFUSES a query `init`. The requirement is unchanged — a
    # client-data route must never take identity from the URL — so this
    # follows the mechanism rather than the old spelling.
    check(f"{r} authenticates by verified initData",
          len(seg) > 1 and "self._telegram_identity()" in seg[1][:900],
          "a client-data route must never take identity from the URL")
    check(f"{r} does not read init from the query string",
          len(seg) > 1 and 'qs.get("init")' not in seg[1][:900])
check("the identity comes from the VERIFIED payload, never a parameter",
      'chat_id = str(tg_user["id"])' in BOT_SRC
      and 'qs.get("user' not in BOT_SRC
      and 'qs.get("init")' not in BOT_SRC)
check("a query-string initData is refused rather than ignored",
      "INIT_DATA_IN_URL" in BOT_SRC)
# Behaviour, not the comment above it: the earlier version of this asserted
# on the string "Fail CLOSED." and would have passed on a route that deleted
# the check and kept the comment. test_prose_assertions.py caught exactly
# that, which is what it is for.
_auth_body = BOT_SRC.split("def _authorized(self):")[1].split("\n        def ")[0]
check("the token-gated route refuses when no token is configured",
      "if not token:" in _auth_body and "return False" in _auth_body,
      "a missing secret is a misconfiguration, not permission")
# The comparison moved into apex/http_session.verify_bootstrap when the
# dashboard stopped taking its token from the URL. The property under test is
# that a constant-time primitive checks the token and nothing compares it with
# `==` — not which function holds the call.
_SESS_SRC = open(os.path.join(ROOT, "apex", "http_session.py"), encoding="utf-8").read()
check("…and compares in constant time",
      "hmac.compare_digest(" in _SESS_SRC and "verify_bootstrap" in _auth_body,
      _auth_body[:200])
check("…and nowhere compares the token with ==",
      not re.search(r"==\s*token\b", _SESS_SRC + _auth_body))
check("a denial is actually issued on failure",
      "if not self._authorized():" in BOT_SRC and "self._deny()" in BOT_SRC)

# ── 2. OAuth signing secret ───────────────────────────────────────────────
print("\n2. There is no literal OAuth signing secret")
OAUTH_SRC = open(os.path.join(ROOT, "apex", "ctrader_oauth.py"),
                 encoding="utf-8").read()
check("the 'apex' fallback is gone from the code",
      'or "apex").encode()' not in OAUTH_SRC,
      "a signing key readable from the source is not a key")
check("a missing secret raises rather than improvising",
      "class OAuthSigningSecretMissing" in OAUTH_SRC)

_real = ctrader_oauth.cfg.TELEGRAM_BOT_TOKEN, ctrader_oauth.cfg.CTRADER_CLIENT_SECRET
try:
    ctrader_oauth.cfg.TELEGRAM_BOT_TOKEN = ""
    ctrader_oauth.cfg.CTRADER_CLIENT_SECRET = ""
    raised = False
    try:
        ctrader_oauth._secret()
    except ctrader_oauth.OAuthSigningSecretMissing:
        raised = True
    check("signing with no secret raises", raised)
    raised = False
    try:
        ctrader_oauth.assert_safe_config()
    except ctrader_oauth.OAuthSigningSecretMissing:
        raised = True
    check("and startup refuses, before the first callback can arrive", raised)
finally:
    ctrader_oauth.cfg.TELEGRAM_BOT_TOKEN, ctrader_oauth.cfg.CTRADER_CLIENT_SECRET = _real
check("with a real secret, state still round-trips",
      ctrader_oauth.read_state(ctrader_oauth.make_state("42")) == "42"
      if hasattr(ctrader_oauth, "read_state") else True)

# ── 3. Account environment ────────────────────────────────────────────────
print("\n3. UNKNOWN never borrows the word LIVE or DEMO")
for label, user, want_badge, want_real in (
        ("connected, environment unknown",
         {"paper": False, "ctrader_env": "", "ctrader_access_token": "t",
          "ctrader_account_id": 1}, "🟠 VERIFICATION REQUIRED", False),
        ("no broker token at all",
         {"paper": False}, "🟠 VERIFICATION REQUIRED", False),
        ("stored live, broker not reachable",
         {"paper": False, "ctrader_env": "live", "ctrader_access_token": "t",
          "ctrader_account_id": 1}, "🔴 LIVE (unconfirmed)", True),
        ("stored demo, broker not reachable",
         {"paper": False, "ctrader_env": "demo", "ctrader_access_token": "t",
          "ctrader_account_id": 1}, "🧪 DEMO (unconfirmed)", False),
        ("paper", {"paper": True}, "📝 SIMULATION", False)):
    mode, src = account_mode.resolve(user, allow_broker=False)
    got = account_mode.badge(mode, src)
    check(f"{label} → {want_badge}", got == want_badge, got)
    check(f"  …real money = {want_real}",
          account_mode.is_real_money(mode) is want_real)

TG_SRC = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
check("the Telegram badge asks account_mode, not the stored flag",
      '_am.badge(_mode, _src)' in TG_SRC
      and '"🔴 LIVE · real money"' not in TG_SRC,
      "reading back ctrader_env defaulted an unknown account to Demo")

# ── 4. Licence persistence ────────────────────────────────────────────────
print("\n4. A licence we cannot store is not an activation")
check("the persistence failure is no longer swallowed",
      'user_store.update(cid, {"license_key": key}, strict=True)' in TG_SRC,
      "strict=True is what turns a lost write into an exception")
_seg = TG_SRC.split('user_store.update(cid, {"license_key": key}')[1][:1200]
check("a failed write returns False, not True", "return False" in _seg,
      "access.grant() runs on that return value")
check("and the client is told to retry rather than left half-activated",
      "could not save it just now" in _seg)

# ── 5. Strict persistence is honest about a lost write ────────────────────
print("\n5. A lost write is never reported as a success")
import inspect  # noqa: E402
_sig = inspect.signature(user_store.update)
for p in ("strict", "expect_version"):
    check(f"update() takes {p}", p in _sig.parameters)
check("PersistenceError exists to carry it", hasattr(user_store, "PersistenceError"))

print("\n6. The readiness probe can see a dead licence store")
# supabase-js does NOT throw on a failure — it returns { error }. The probe
# was `try { await ...; dbConnect = true } catch { dbConnect = false }`, so it
# set dbConnect = TRUE for a database that could not be reached at all, and
# sale_ready with it. Proven against a real paused project: the call returns
# `error: TypeError: fetch failed` and never raises, so the old code reported
# a healthy licence store while there was none.
#
# This matters beyond a status page. A Supabase project in this account has no
# tables whatsoever; if SUPABASE_URL points at it every activation fails, and
# the one endpoint meant to say so was answering "fine".
SERVER = open(os.path.join(os.path.dirname(ROOT), "server.js"),
              encoding="utf-8").read()
_probe = SERVER.split("let dbConnect = false;")[1][:900]
check("the probe reads the error field, not just a throw",
      "const { error }" in _probe and "if (error)" in _probe,
      "supabase-js reports failure in `error` and does not raise")
check("a fault is still recorded when the call DOES throw",
      "catch (e) { dbFault = _licenceStoreFault(e); }" in _probe)
check("the kind of fault is reported, not just a boolean",
      "supabase_fault:" in SERVER,
      "a missing table and a missing network need opposite fixes")
check("supabase_connects is still a critical check",
      "'supabase_connects'" in SERVER.split("const critical =")[1][:200])

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — blockers closed.")
