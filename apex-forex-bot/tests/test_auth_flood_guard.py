"""A flood of bearer tokens cannot exhaust the platform's Supabase budget.

FOUND BY THE SECURITY AUDIT. Two gaps, together:

* The rate limiter keys authenticated requests on a hash of the bearer string
  before anyone has checked it, so invented tokens each got a fresh bucket.
  The per-address floor bounded REQUESTS, but at 600 a minute every one of
  them was still a Supabase lookup.
* A token Supabase had REJECTED was never remembered, so repeating one bad
  token paid a round trip per request.

WHAT THESE TESTS WILL NOT ACCEPT

* One address causing more Supabase lookups than its verify budget, however
  many tokens it invents.
* A rejected token causing a second Supabase lookup inside the negative TTL,
  even on a fresh-session route.
* An OUTAGE (AuthUnavailable) being remembered as a rejection.
* A cached, valid session spending the verify budget.
* A second address being throttled by the first.

Run: python3 tests/test_auth_flood_guard.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-authflood-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["RATE_LIMIT_STORE"] = "memory"
os.environ["RL_A4T_ADDR_VERIFY_PER_MIN"] = "5"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"

import requests                                              # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


calls = {"n": 0}
MODE = {"status": 401}
GOOD = {"id": "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
        "email": "alice@example.com",
        "email_confirmed_at": "2026-01-01T00:00:00Z"}


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


def _fake_get(url, **kw):
    calls["n"] += 1
    if MODE["status"] == "boom":
        raise OSError("unreachable")
    return _Resp(MODE["status"], GOOD if MODE["status"] == 200 else {})


requests.get = _fake_get

from apex.platform import api as A                           # noqa: E402
from apex.platform import identity as I                      # noqa: E402
from apex.platform import ratelimit as RL                    # noqa: E402


def get(token, ip):
    return A.handle("GET", "/api/v1/me",
                    headers={"Authorization": f"Bearer {token}"},
                    client_key=ip)


print("\n[1] invented tokens from one address are bounded by the verify budget")
RL.reset_all()
I.forget_all()
calls["n"] = 0
statuses = [get(f"junk-{i}", "198.51.100.7")[0] for i in range(30)]
check("only the verify budget's worth of Supabase lookups happened",
      calls["n"] == 5, f"{calls['n']} lookups")
check("the first five are 401, the rest 429",
      statuses[:5] == [401] * 5 and set(statuses[5:]) == {429},
      str(statuses))
st, body = get("junk-x", "198.51.100.7")
check("the refusal names the verify bucket",
      st == 429 and body["error"]["bucket"] == "addr_verify", str(body))

print("\n[2] another address is unaffected")
calls["n"] = 0
st, _ = get("junk-other", "203.0.113.9")
check("401 from Supabase, not 429", st == 401, str(st))
check("one lookup", calls["n"] == 1, str(calls["n"]))

print("\n[3] a rejected token is remembered, even on fresh routes")
RL.reset_all()
I.forget_all()
calls["n"] = 0
for _ in range(10):
    get("same-bad-token", "192.0.2.1")
check("one Supabase lookup for ten requests", calls["n"] == 1, str(calls["n"]))
try:
    I.verify_token("same-bad-token", fresh=True)
    check("fresh=True still refuses", False)
except I.AuthFailed:
    check("fresh=True still refuses, without a lookup", calls["n"] == 1,
          str(calls["n"]))
# After the TTL the token is asked about again.
_real_time = I.time.time
I.time.time = lambda: _real_time() + I.NEG_CACHE_TTL_S + 1
try:
    try:
        I.verify_token("same-bad-token")
    except I.AuthFailed:
        pass
    check("asked again after the negative TTL", calls["n"] == 2, str(calls["n"]))
finally:
    I.time.time = _real_time

print("\n[4] an outage is not remembered as a rejection")
RL.reset_all()
I.forget_all()
calls["n"] = 0
MODE["status"] = "boom"
st, _ = get("good-token", "192.0.2.2")
check("503 during the outage", st == 503, str(st))
MODE["status"] = 200
st, _ = get("good-token", "192.0.2.2")
check("the same token works once Supabase is back", st == 200, str(st))

print("\n[5] a cached valid session does not spend the verify budget")
RL.reset_all()
I.forget_all()
calls["n"] = 0
MODE["status"] = 200
ok = [get("good-token", "192.0.2.3")[0] for _ in range(20)]
check("twenty reads, all 200", set(ok) == {200}, str(ok))
check("one Supabase lookup", calls["n"] == 1, str(calls["n"]))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All auth flood checks passed.")
