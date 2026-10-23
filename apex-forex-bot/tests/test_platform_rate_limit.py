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
    # NOT oauth. Both change which account is in use; neither goes through
    # cTrader's OAuth. Metering them against the tight oauth bucket meant a
    # client who had just connected could not then select the account they
    # had connected — seen in production on 2026-10-04 as a 429 on select
    # with retryAfterSec=42, while the phone showed "No account selected".
    ("POST", "ctrader/select", "control"),
    ("POST", "ctrader/disconnect", "control"),
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

# The bug the owner hit: connecting spends the oauth budget, and selecting the
# account you just connected was metered against the same budget. The whole
# point of the flow is that one follows the other.
print("\n[1c] spending the oauth budget does not lock you out of your own account")
RL.reset_all()
for _ in range(RL.LIMITERS["oauth"].limit + 5):
    RL.check("POST", "ctrader/connect", client_key="9.9.9.9", auth_header="Bearer u1")
blocked, bucket, _ = RL.check("POST", "ctrader/connect",
                              client_key="9.9.9.9", auth_header="Bearer u1")
check("connect itself is still limited", blocked is False, bucket)
allowed, bucket, _ = RL.check("POST", "ctrader/select",
                              client_key="9.9.9.9", auth_header="Bearer u1")
check("select still goes through", allowed is True, bucket)
check("and it is not metered as oauth", bucket == "control", bucket)

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

# ── 3b. the wait it reports is the wait there actually is ───────────────────
# WHY THIS SECTION EXISTS
#
# The check above passes for any positive number, and the number was the
# WINDOW LENGTH — a flat 60 — whichever second of the minute you were in. The
# window is a floor of the clock (`int(time.time() // window_s)`), so it rolls
# at the top of the next minute: 59 seconds in, the true wait is one second
# and the API said sixty.
#
# The owner hit RATE_LIMITED twice while connecting a broker account, and both
# times the only thing the page could tell him was "wait a moment". A number
# that is wrong by up to a minute is worse than no number, because a countdown
# is exactly what a person acts on.
#
# check() is exercised DIRECTLY rather than through A.handle(). The reported
# wait is computed there, and driving the whole API to reach it meant a few
# hundred authenticated requests against a stubbed Supabase — which made this
# file the slowest in the suite for no extra coverage. One end-to-end case at
# the bottom keeps the wiring honest.
print("\n[3b] the reported wait tracks the clock, not the window length")
import time as _time                                              # noqa: E402
_real_time = _time.time


def _at(second_of_minute):
    """A clock parked at a known offset into the window."""
    base = 1_700_000_000
    return float(base - (base % 60)) + float(second_of_minute)


def _wait_at(offset, key):
    """The seconds check() reports once `key` has spent its budget."""
    RL.time.time = lambda: _at(offset)
    try:
        limit = RL.LIMITERS["candles"].limit
        hdr = f"Bearer {key}"
        for _ in range(limit + 2):
            RL.check("GET", "accounts/501/candles",
                     client_key="9.9.9.9", auth_header=hdr)
        allowed, _bucket, retry = RL.check(
            "GET", "accounts/501/candles", client_key="9.9.9.9",
            auth_header=hdr)
        return allowed, retry
    finally:
        RL.time.time = _real_time


# The fractional offsets are the ones that matter: at a whole second, rounding
# up and rounding down agree, so integer cases alone cannot tell a correct
# implementation from one that under-reports and sends the client back a beat
# early — to be refused again. (A surviving mutant proved exactly that.)
for _offset, _expected in ((0, 60), (5, 55), (30, 30), (59, 1),
                           (30.4, 30), (0.1, 60), (58.6, 2), (59.5, 1)):
    RL.reset_all()
    _allowed, _got = _wait_at(_offset, f"clock-{_offset}")
    check(f"{_offset}s into the window it reports {_expected}s, not 60",
          _allowed is False and _got == _expected,
          f"allowed={_allowed} reported={_got}")

# Never zero: a wait of zero invites an instant retry that fails again, which
# is how a client ends up hammering a limiter it is already behind.
RL.reset_all()
_allowed, _edge = _wait_at(59.99, "edge")
check("at the very end of the window it still asks for at least a second",
      _edge >= 1, str(_edge))
check("and never more than the window itself", _edge <= 60, str(_edge))

# And the number reaches the client, in the message a person actually reads.
RL.reset_all()
RL.time.time = lambda: _at(30)
try:
    _hdr3d = {"Authorization": "Bearer message-client"}
    for _ in range(RL.LIMITERS["candles"].limit + 2):
        A.handle("GET", "/api/v1/accounts/501/candles?symbol=EURUSD",
                 _hdr3d, None, client_key="9.9.9.7")
    _st, _o = A.handle("GET", "/api/v1/accounts/501/candles",
                       _hdr3d, None, client_key="9.9.9.7")
    check("the refusal really does travel through the API",
          _o["error"]["code"] == "RATE_LIMITED", json.dumps(_o))
    check("the human-readable message names the seconds",
          "30" in _o["error"]["message"], _o["error"]["message"])
    check("and so does the field a client can branch on",
          _o["error"]["retryAfterSec"] == 30, str(_o["error"]))
finally:
    RL.time.time = _real_time
RL.reset_all()

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

# ── 11. live-order limits are separate and fail closed ─────────────────────
print("\n[11] future live-order limits are not API limits")
_saved_order = (user_store._USE_REDIS, user_store.incr,
                user_store.redis_health, RL._MODE,
                os.environ.get("RL_A4T_ORDER_CLIENT_PER_MIN"),
                os.environ.get("RL_A4T_ORDER_BROKER_PER_SEC"))
try:
    user_store._USE_REDIS = False
    RL._MODE = "auto"
    no_store = RL.check_live_order_rate(
        "u1", "acc1", provider="ctrader", connection_id="conn1", now=120.0)
    check("a live order is refused without a shared counter",
          no_store["ok"] is False
          and no_store["error"]["code"] == "ORDER_RATE_LIMIT_UNAVAILABLE"
          and no_store["error"]["gate"] == "order_rate_store",
          json.dumps(no_store))

    RL.reset_all()
    demo_read = RL.check("GET", "accounts/501/candles",
                         client_key="1.2.3.4", auth_header="Bearer demo")
    check("but demo reads still use the normal API limiter",
          demo_read[0] is True and demo_read[1] == "candles", str(demo_read))

    user_store._USE_REDIS = True
    user_store.redis_health = lambda *a, **k: {
        "configured": True, "reachable": True, "status": "HEALTHY"}
    _order_counts = {}

    def _order_incr(key, ttl_s=60):
        _order_counts[key] = _order_counts.get(key, 0) + 1
        return _order_counts[key]

    user_store.incr = _order_incr
    os.environ["RL_A4T_ORDER_CLIENT_PER_MIN"] = "2"
    os.environ["RL_A4T_ORDER_BROKER_PER_SEC"] = "99"
    _order_counts.clear()
    client_out = [RL.check_live_order_rate(
        "u1", "acc1", provider="ctrader", connection_id="conn1", now=180.0)
        for _ in range(3)]
    check("the per-client order cap is separate from the API cap",
          client_out[0]["ok"] is True
          and client_out[1]["ok"] is True
          and client_out[2]["ok"] is False
          and client_out[2]["error"]["gate"] == "client_order_rate",
          json.dumps(client_out[2]))

    os.environ["RL_A4T_ORDER_CLIENT_PER_MIN"] = "99"
    os.environ["RL_A4T_ORDER_BROKER_PER_SEC"] = "2"
    _order_counts.clear()
    broker_out = [RL.check_live_order_rate(
        f"u{i}", f"acc{i}", provider="ctrader",
        connection_id="one-shared-connection", now=240.0)
        for i in range(3)]
    check("the broker-connection order cap is shared across clients",
          broker_out[0]["ok"] is True
          and broker_out[1]["ok"] is True
          and broker_out[2]["ok"] is False
          and broker_out[2]["error"]["gate"] == "broker_order_rate",
          json.dumps(broker_out[2]))
    check("order counters are in their own namespace",
          all(":order_rl:" in k for k in _order_counts),
          str(list(_order_counts)[:4]))
    check("order counters do not carry user ids or account ids",
          not any("u1" in k or "acc1" in k or "Bearer" in k
                  for k in _order_counts),
          str(list(_order_counts)[:4]))

    user_store.incr = lambda key, ttl_s=60: None
    unavailable = RL.check_live_order_rate(
        "u1", "acc1", provider="ctrader", connection_id="conn1", now=300.0)
    check("a counter failure refuses instead of using process memory",
          unavailable["ok"] is False
          and unavailable["error"]["code"] == "ORDER_RATE_LIMIT_UNAVAILABLE"
          and unavailable["error"]["gate"] == "client_order_rate",
          json.dumps(unavailable))
finally:
    (user_store._USE_REDIS, user_store.incr, user_store.redis_health,
     RL._MODE, _env_client, _env_broker) = _saved_order
    if _env_client is None:
        os.environ.pop("RL_A4T_ORDER_CLIENT_PER_MIN", None)
    else:
        os.environ["RL_A4T_ORDER_CLIENT_PER_MIN"] = _env_client
    if _env_broker is None:
        os.environ.pop("RL_A4T_ORDER_BROKER_PER_SEC", None)
    else:
        os.environ["RL_A4T_ORDER_BROKER_PER_SEC"] = _env_broker
    RL.reset_all()

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All rate limit checks passed.")
