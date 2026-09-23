"""Rate limits on the platform API.

Every route under /api/v1/ used to be unmetered. Two of them are the reason
this exists: `candles` spends cTrader's historical budget, which is five
requests per second PER CONNECTION and shared across every client on that
connection, and `preview` runs the evaluator over up to three hundred bars.
One client in a loop degraded the platform for everybody else.

Run: python3 tests/test_platform_rate_limit.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-rl-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"

from apex.platform import api as A          # noqa: E402
from apex.platform import ratelimit as RL   # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


# ── 1. every route lands in a bucket, and the costly ones in their own ──────
print("\n[1] routes are classified")
cases = [
    ("GET", "accounts/501/candles", "candles"),
    ("POST", "rules/abc/preview", "preview"),
    ("POST", "rules/abc/activate", "activate"),
    ("POST", "ctrader/connect", "oauth"),
    ("POST", "ctrader/complete", "oauth"),
    ("GET", "ctrader/status", "default"),      # a poll, not a sensitive action
    ("POST", "ctrader/disconnect", "oauth"),
    ("POST", "billing/webhook", "webhook"),
    ("POST", "automation/start", "control"),
    ("POST", "automation/stop", "control"),
    ("GET", "automation", "default"),          # a poll, not a control action
    ("GET", "positions", "default"),
    ("GET", "journal", "default"),
]
for method, route, expected in cases:
    got = RL.classify(method, route)
    check(f"{method} {route} -> {expected}", got == expected, got)

check("a query string does not change the bucket",
      RL.classify("GET", "accounts/501/candles?symbol=EURUSD&limit=300") == "candles")
check("a leading slash does not change the bucket",
      RL.classify("GET", "/accounts/501/candles") == "candles")
check("an unknown route is still metered",
      RL.classify("GET", "something/new") == "default")

# The bug this caught: polling ctrader/status drained the same bucket as
# disconnect, so a client with a tab open could not disconnect their account.
print("\n[1b] polling does not drain the budget a control action needs")
RL.reset_all()
for _ in range(RL.LIMITERS["oauth"].limit * 3):
    RL.check("GET", "ctrader/status", client_key="1.2.3.4", auth_header="Bearer poller")
allowed, bucket, _ = RL.check("POST", "ctrader/disconnect",
                              client_key="1.2.3.4", auth_header="Bearer poller")
check("disconnect still goes through after heavy polling", allowed is True, bucket)

# ── 2. the key is the user when there is one ────────────────────────────────
print("\n[2] authenticated callers are limited per user, not per address")
k_a = RL.key_for("1.2.3.4", "Bearer token-alice")
k_b = RL.key_for("1.2.3.4", "Bearer token-bob")
check("same address, different tokens -> different keys", k_a != k_b)
check("same token, different addresses -> same key",
      RL.key_for("1.2.3.4", "Bearer token-alice")
      == RL.key_for("9.9.9.9", "Bearer token-alice"))
check("no token falls back to the address",
      RL.key_for("1.2.3.4", None) != RL.key_for("5.6.7.8", None))
check("the token itself is never the key", "token-alice" not in k_a, k_a)
check("nor is any prefix of it long enough to matter",
      "token-al" not in k_a and "oken-alice" not in k_a, k_a)

# ── 3. a bucket actually refuses ────────────────────────────────────────────
print("\n[3] the candles bucket refuses a loop")
RL.reset_all()
limit = RL.LIMITERS["candles"].limit
hdr = {"Authorization": "Bearer looping-client"}
statuses = []
for _ in range(limit + 5):
    st, _out = A.handle("GET", "/api/v1/accounts/501/candles?symbol=EURUSD",
                        hdr, None, client_key="1.2.3.4")
    statuses.append(st)
check("the first request is not refused", statuses[0] != 429, str(statuses[0]))
check("the loop is eventually refused", 429 in statuses, str(set(statuses)))
check("it is refused within the configured limit",
      statuses.index(429) <= limit, f"first 429 at {statuses.index(429)}, limit {limit}")

st, out = A.handle("GET", "/api/v1/accounts/501/candles", hdr, None, client_key="1.2.3.4")
check("the refusal carries a code the UI can branch on",
      out["error"]["code"] == "RATE_LIMITED", json.dumps(out))
check("and says which bucket", out["error"]["bucket"] == "candles", json.dumps(out))
check("and how long to wait", out["error"]["retryAfterSec"] > 0, json.dumps(out))

# ── 4. one client's loop does not lock out another ──────────────────────────
print("\n[4] a limited client does not take anybody else down")
st_other, out_other = A.handle(
    "GET", "/api/v1/accounts/501/candles",
    {"Authorization": "Bearer a-different-client"}, None, client_key="1.2.3.4")
check("a different user on the SAME address is served", st_other != 429, str(st_other))

# ── 5. buckets are independent ──────────────────────────────────────────────
print("\n[5] exhausting one bucket does not exhaust the others")
st_j, _ = A.handle("GET", "/api/v1/journal", hdr, None, client_key="1.2.3.4")
check("the same user can still read the journal", st_j != 429, str(st_j))

# ── 6. the limiter runs BEFORE authentication ───────────────────────────────
print("\n[6] the limit is applied before the session is verified")
RL.reset_all()
# No Authorization at all: without a limiter this would be an auth failure
# every time, and each one costs a Supabase round trip in production.
sts = [A.handle("POST", "/api/v1/ctrader/connect", {}, b"{}", client_key="7.7.7.7")[0]
       for _ in range(RL.LIMITERS["oauth"].limit + 3)]
check("unauthenticated flooding is refused", 429 in sts, str(set(sts)))
check("and the refusal is the limiter's, not the authenticator's",
      sts[-1] == 429, str(sts[-1]))

# ── 7. a route that is not ours is still not ours ───────────────────────────
print("\n[7] the limiter does not capture routes this API does not own")
check("a non-platform path still returns None",
      A.handle("GET", "/dashboard", {}, None, client_key="1.1.1.1") is None)

# ── 8. limits are configurable, and the defaults are sane ───────────────────
print("\n[8] every bucket has a limit and an env override")
for name, (env, default, window) in RL._BUCKETS.items():
    check(f"{name} has a positive limit", RL.LIMITERS[name].limit > 0, name)
    check(f"{name} is overridable via {env}", env.startswith("RL_A4T_"), env)
check("the webhook bucket is the most generous",
      RL.LIMITERS["webhook"].limit >= max(
          RL.LIMITERS[n].limit for n in ("oauth", "candles", "preview", "activate")),
      "a throttled retry leaves a paying client unprovisioned")
check("the costly buckets are tighter than the polling default",
      all(RL.LIMITERS[n].limit < RL.LIMITERS["default"].limit
          for n in ("candles", "preview", "oauth", "activate", "control")))

# ── 9. a broken limiter must not take the platform down ─────────────────────
print("\n[9] a failure inside the limiter fails open, not closed")
_real = RL.LIMITERS["default"].check


def _boom(_key):
    raise RuntimeError("limiter exploded")


RL.LIMITERS["default"].check = _boom
try:
    allowed, bucket, _ = RL.check("GET", "journal", client_key="1.1.1.1")
    check("a limiter that raises allows the request", allowed is True)
finally:
    RL.LIMITERS["default"].check = _real

# ── 10. the counter is shared when a shared backend exists ─────────────────
# A fixed window held in one process is not a limit when there are two. This
# is the positive case: when the backend can count, the limiter must use it
# and must NOT fall back to the per-process window.
print("\n[10] a shared backend is used, and the in-process window is not")
from apex import user_store                      # noqa: E402

_shared = {}


def _fake_incr(key, ttl_s=60):
    _shared[key] = _shared.get(key, 0) + 1
    return _shared[key]


_memory_hits = {"n": 0}
_real_incr = user_store.incr
_real_check = RL.LIMITERS["default"].check


def _count_memory(key):
    _memory_hits["n"] += 1
    return _real_check(key)


user_store.incr = _fake_incr
RL.LIMITERS["default"].check = _count_memory
try:
    RL.reset_all()
    _shared.clear()
    check("store_mode reports shared", RL.store_mode() == "shared", RL.store_mode())
    for _ in range(5):
        RL.check("GET", "journal", client_key="4.4.4.4", auth_header="Bearer s")
    check("the shared counter was written", any(":rl:" in k for k in _shared),
          str(list(_shared)[:3]))
    check("and the in-process window was never consulted",
          _memory_hits["n"] == 0, str(_memory_hits["n"]))
    check("the key is namespaced by product",
          all(k.startswith("forex:a4t:rl:") for k in _shared), str(list(_shared)[:2]))
    check("and carries no bearer token",
          not any("Bearer" in k or "s" == k.split(":")[-2] for k in _shared),
          str(list(_shared)[:2]))

    # The shared counter refuses once the window is full, across what would
    # be different processes — there is only one counter now.
    RL.reset_all()
    _shared.clear()
    limit = RL.LIMITERS["default"].limit
    outs = [RL.check("GET", "journal", client_key="4.4.4.4",
                     auth_header="Bearer s")[0] for _ in range(limit + 2)]
    check("the shared window eventually refuses", False in outs, str(set(outs)))
    check("and it refuses within the configured limit",
          outs.index(False) <= limit, f"{outs.index(False)} vs {limit}")

    # A backend that cannot answer must not disable limiting altogether.
    _memory_hits["n"] = 0
    user_store.incr = lambda key, ttl_s=60: None
    RL.reset_all()
    allowed, bucket, _ = RL.check("GET", "journal", client_key="5.5.5.5")
    check("a backend that cannot answer falls back to counting in process",
          allowed is True and _memory_hits["n"] == 1,
          f"{allowed} {_memory_hits['n']}")
    check("and store_mode says so rather than claiming shared",
          RL.store_mode() == "memory", RL.store_mode())
finally:
    user_store.incr = _real_incr
    RL.LIMITERS["default"].check = _real_check
    RL.reset_all()

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All rate limit checks passed.")
