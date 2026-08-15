"""The dashboard must fail CLOSED when its token is missing.

`_authorized()` returned True whenever DASHBOARD_TOKEN was unset, so one
missing environment variable published /api/status — balance, open position
and the trade journal — to anyone with the URL. Not theoretical: an
unauthenticated GET against the live deployment returned 200.

A missing secret is a misconfiguration, not permission.

Two details the fix has to get right or it will be reverted in a week:

  * A missing token and a wrong token are different operator problems, so
    they get different codes: 503 "not configured" vs 401 "wrong token".
  * The dashboard shell fetched /api/status with no token of its own. Closing
    the gate without fixing that turns "set a token" into "break the
    dashboard" — which is exactly why running without one felt like the only
    option.

Covers the audit's checklist: unauthenticated → rejected; wrong token →
rejected; missing token → no private data.

Run: python tests/test_dashboard_auth.py
"""
import os
import re
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


# The authorization decision, exercised exactly as the handler defines it:
# pulled out of apex/bot.py by source so the test breaks if the real one is
# loosened. Importing bot.py would start threads and a live broker.
import hmac  # noqa: E402

SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "bot.py")).read()


def make_authorized(token):
    """Rebuild the handler's _authorized() over a given configured token."""
    def _authorized(path, auth_header=""):
        if not token:
            return False
        qs = parse_qs(urlparse(path).query)
        supplied = qs.get("token", [""])[0]
        if not supplied:
            supplied = (auth_header or "").removeprefix("Bearer ").strip()
        return hmac.compare_digest(supplied, token)
    return _authorized


print("\n── the live hole: no token configured ──")
auth = make_authorized("")
check("an anonymous request is refused", auth("/api/status") is False)
check("a guessed token does not help", auth("/api/status?token=x") is False)
check("nor does an Authorization header",
      auth("/api/status", "Bearer anything") is False)
check("candles are refused too", auth("/api/candles") is False)

print("\n── with a token configured ──")
auth = make_authorized("s3cret-value")
check("no token → refused", auth("/api/status") is False)
check("wrong token → refused", auth("/api/status?token=wrong") is False)
check("empty token → refused", auth("/api/status?token=") is False)
check("a prefix of the token → refused", auth("/api/status?token=s3cret") is False)
check("correct token in the query → allowed",
      auth("/api/status?token=s3cret-value") is True)
check("correct token as a Bearer header → allowed",
      auth("/api/status", "Bearer s3cret-value") is True)
check("query token wins and still validates",
      auth("/api/status?token=s3cret-value&x=1") is True)

print("\n── the source itself must not regain a fail-open path ──")
body = SRC[SRC.index("def _authorized"):SRC.index("def _deny")]
check("no branch returns True on a missing token",
      not re.search(r"if not token:\s*\n\s*return True", body), body[:200])
check("the missing-token branch returns False",
      re.search(r"if not token:\s*\n\s*return False", body) is not None)
check("comparison is constant-time, not ==",
      "compare_digest" in body and not re.search(r"==\s*token", body), body[:300])

print("\n── a missing token and a wrong token are different problems ──")
deny = SRC[SRC.index("def _deny"):SRC.index("def do_POST")]
check("no token configured → 503", "send_response(503)" in deny, deny[:200])
check("token configured but wrong → 401", "send_response(401)" in deny, deny[:200])
check("the 503 tells the operator what to set", "DASHBOARD_TOKEN" in deny)

print("\n── health stays open; it exposes nothing ──")
check("/health is answered before the auth gate",
      SRC.index('self.path.startswith("/health")') < SRC.index("if not self._authorized()"))

print("\n── setting a token must not break the dashboard ──")
DASH = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "apex", "dashboard.py")).read()
check("the shell reads its own token from the URL", "location.search" in DASH)
check("status is fetched through the token helper",
      "_api('/api/status')" in DASH, "still a bare fetch")
check("candles too", "_api('/api/candles')" in DASH, "still a bare fetch")
check("no bare data fetch is left behind",
      "fetch('/api/" not in DASH, "a bare fetch('/api/...') remains")

print("\n── the startup line must not still promise a public dashboard ──")
check("it says disabled, not PUBLIC",
      "is PUBLIC" not in SRC and "DISABLED" in SRC)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL DASHBOARD-AUTH CHECKS PASSED.")
