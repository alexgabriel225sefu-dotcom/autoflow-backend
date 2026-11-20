"""Walking through the app must not answer 429.

WHY THIS EXISTS

Observed in production on a brand-new account with NO broker connected,
opening one page about every four seconds: `/trades` answered
`429 GET /api/v1/trades?days=30&mode=demo`, and a direct
`GET /api/v1/admin/users` answered 429 with `"bucket": "candles"`.

Two faults produced that, and each is pinned here:

  1. THE SHARED COUNTER HAD NO BUCKET IN ITS KEY. `ratelimit.check` handed
     `_shared_check` the caller's key and nothing else, so with a shared
     backend (production) every per-minute bucket incremented ONE counter per
     session. The 31st request of any kind in a minute made every route in the
     30-a-minute `candles` bucket refuse; the 11th did the same to `oauth`.
     The in-memory limiter keeps one window per bucket, which is why no test
     in memory mode ever saw it.

  2. ROUTES WERE CHARGED TO A BUCKET THAT DID NOT DESCRIBE THEM. `trades`,
     `symbols` and `trade/min-lot` spent the broker-data budget before the
     session was even verified, so they spent it for a client with no broker
     to read. `admin/*` spent it too, which is how an operator route came to
     report `candles`.

WHAT THESE TESTS WILL NOT ACCEPT

* one bucket's requests counting against another's, in either store mode;
* a read that never reaches the broker spending the broker-data budget;
* the fix being a looser limit: every configured limit is pinned, and a linked
  client's broker reads are still refused at the same thirty a minute;
* any route that moves money, starts a flow or erases an account landing in a
  looser bucket than before.

Run: python3 tests/test_rate_limit_browsing.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-rl-browse-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "test"
os.environ.setdefault("PRODUCT", "forex")
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
for _name in [k for k in os.environ if k.startswith("RL_A4T_")]:
    os.environ.pop(_name)

import requests  # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body

    def json(self):
        return self._b


USERS = {"new-client-token": "11111111-1111-4111-8111-111111111111",
         "linked-client-token": "22222222-2222-4222-8222-222222222222"}


def _fake_get(url, **kw):
    if "supabase" not in str(url):
        raise AssertionError(f"unexpected GET {url}")
    auth = (kw.get("headers") or {}).get("Authorization", "")
    for token, uid in USERS.items():
        if auth.endswith(token):
            return _Resp(200, {"id": uid, "email": f"{token}@example.com",
                               "email_confirmed_at": "2026-01-01T00:00:00Z"})
    return _Resp(401, {})


requests.get = _fake_get

from apex import user_store                  # noqa: E402
from apex.platform import api as A           # noqa: E402
from apex.platform import ctrader_link as L  # noqa: E402
from apex.platform import ratelimit as RL    # noqa: E402

# ── 1. the limits themselves have not moved ────────────────────────────────
print("\n[1] no limit was loosened")
LIMITS = {
    "oauth": (10, 60), "candles": (30, 60), "preview": (20, 60),
    "control": (120, 60), "emergency": (30, 60), "emergency_user": (30, 60),
    "activate": (10, 60), "webhook": (120, 60), "waitlist": (5, 60),
    "default": (240, 60), "addr": (600, 60), "addr_control": (120, 60),
    "addr_verify": (120, 60), "account_delete": (5, 3600),
    "account_export": (10, 3600),
}
for name, (limit, window) in LIMITS.items():
    lim = RL.LIMITERS[name]
    check(f"{name} is still {limit} per {window}s",
          (lim.limit, lim.window_s) == (limit, window),
          f"{lim.limit}/{lim.window_s}")
check("the operator audit has a bucket of its own, no looser than before",
      "admin" in RL.LIMITERS and RL.LIMITERS["admin"].limit <= 30
      and RL.LIMITERS["admin"].window_s == 60)
check("and nothing else was added",
      set(RL.LIMITERS) == set(LIMITS) | {"admin"}, str(sorted(RL.LIMITERS)))

# ── 2. each route is charged to the bucket that describes it ───────────────
print("\n[2] routes map to the bucket that matches what they do")
MAPPING = [
    # Reads that reach the broker only for a client who has linked one. Before
    # the session is known they are ordinary reads; the broker budget is spent
    # in the handler, and only when there is a broker to ask.
    ("GET", "trades", "default"),
    ("GET", "trades?days=30&mode=demo", "default"),
    ("GET", "symbols", "default"),
    ("GET", "trade/min-lot", "default"),
    # Always a broker read: the path names the linked account it reads.
    ("GET", "accounts/501/candles", "candles"),
    # The operator audit is not a candles request.
    ("GET", "admin", "admin"),
    ("GET", "admin/users", "admin"),
    ("GET", "admin/audit/accounts", "admin"),
    ("GET", "admin/audit/accounts/501/deals", "admin"),
    # Ordinary reads a page makes.
    ("GET", "me", "default"), ("GET", "accounts", "default"),
    ("GET", "ctrader/status", "default"), ("GET", "automation", "default"),
    ("GET", "rules", "default"), ("GET", "conditions", "default"),
    ("GET", "positions", "default"), ("GET", "orders", "default"),
    ("GET", "journal", "default"), ("GET", "notifications", "default"),
    # Unchanged, and must stay that way: order placement, automation control,
    # auth, billing and the live gate.
    ("POST", "approvals/approve", "control"),
    ("POST", "accounts/501/positions/7/close", "control"),
    ("POST", "automation/start", "control"),
    ("POST", "automation/stop", "control"),
    ("POST", "automation/setup", "control"),
    ("POST", "ctrader/select", "control"),
    ("POST", "ctrader/disconnect", "control"),
    ("POST", "ctrader/connect", "oauth"),
    ("POST", "ctrader/complete", "oauth"),
    ("POST", "rules/abc/activate", "activate"),
    ("POST", "rules/abc/preview", "preview"),
    ("POST", "emergency/stop", "emergency"),
    ("POST", "billing/webhook", "webhook"),
    ("POST", "billing/checkout", "default"),
    ("POST", "waitlist", "waitlist"),
    ("GET", "live/status", "default"),
    ("POST", "live/request", "default"),
    ("DELETE", "account", "account_delete"),
    ("GET", "account/export", "account_export"),
]
for method, route, expected in MAPPING:
    got = RL.classify(method, route)
    check(f"{method} {route} -> {expected}", got == expected, got)
check("an admin look-alike is not the admin bucket",
      RL.classify("GET", "administrator") == "default")

# ── 3. with a shared backend, buckets do not share a counter ───────────────
print("\n[3] one bucket's requests do not count against another's")
_shared = {}


def _fake_incr(key, ttl_s=60):
    _shared[key] = _shared.get(key, 0) + 1
    return _shared[key]


_real_incr = user_store.incr


def _fresh(shared):
    """A clean window in the store mode under test."""
    user_store.incr = _fake_incr if shared else _real_incr
    RL.reset_all()
    _shared.clear()


AUTH = "Bearer some-session"
_fresh(shared=True)
check("the store mode under test is the production one",
      RL.store_mode() == "shared", RL.store_mode())
_shared.clear()
for _ in range(60):
    RL.check("GET", "journal", client_key="198.51.100.1", auth_header=AUTH)
ok, bucket, _wait = RL.check("GET", "accounts/501/candles",
                             client_key="198.51.100.1", auth_header=AUTH)
check("sixty ordinary reads leave the broker-data budget untouched",
      ok is True, f"refused by {bucket}")
ok, bucket, _wait = RL.check("POST", "ctrader/connect",
                             client_key="198.51.100.1", auth_header=AUTH)
check("and the oauth budget", ok is True, f"refused by {bucket}")
ok, bucket, _wait = RL.check("POST", "rules/abc/activate",
                             client_key="198.51.100.1", auth_header=AUTH)
check("and the activate budget", ok is True, f"refused by {bucket}")
session_keys = [k for k in _shared if ":rl:" in k and ":ip:" not in k]
check("every session counter names its bucket",
      session_keys and all(":b:" in k for k in session_keys), str(session_keys))
check("and no key carries the bearer token",
      not any("some-session" in k for k in _shared))

for name in ("candles", "oauth", "activate", "preview", "control", "admin"):
    route = {"candles": ("GET", "accounts/501/candles"),
             "oauth": ("POST", "ctrader/connect"),
             "activate": ("POST", "rules/abc/activate"),
             "preview": ("POST", "rules/abc/preview"),
             "control": ("POST", "automation/stop"),
             "admin": ("GET", "admin/audit/accounts")}[name]
    _fresh(shared=True)
    limit = RL.LIMITERS[name].limit
    # No address: this measures the session bucket, not the address floor.
    outs = [RL.check(route[0], route[1], auth_header=AUTH)
            for _ in range(limit + 1)]
    check(f"{name} still allows exactly {limit} and refuses the next",
          all(o[0] for o in outs[:limit]) and outs[limit][0] is False
          and outs[limit][1] == name, str(outs[limit]))

# ── 4. the walk, for a client with no broker linked ────────────────────────
print("\n[4] opening every page in one minute is never refused")
SHELL = ["me", "ctrader/status", "automation", "notifications?limit=1"]
PAGES = [
    ("dashboard", ["me", "ctrader/status", "automation", "positions", "orders",
                   "journal?limit=8", "rules", "accounts/reads", "approvals",
                   "automation/why"]),
    ("connect", ["ctrader/status"]),
    ("accounts", ["ctrader/status", "account-kinds"]),
    ("rules", ["rules", "automation"]),
    ("rules/new", ["conditions"]),
    ("rules/new/strategy", ["strategies"]),
    ("trade", ["automation/setup", "ctrader/status", "me", "automation",
               "symbols", "rules",
               "trade/min-lot?symbol=EURUSD&timeframe=1h&riskPercent=1"]),
    ("positions", ["ctrader/status", "positions"]),
    ("orders", ["ctrader/status", "orders"]),
    ("trades", ["trades?days=30&mode=demo"]),
    ("performance", ["performance?period=all&mode=demo", "ctrader/status"]),
    ("journal", ["journal?limit=20", "ctrader/status"]),
    ("notifications", ["notifications?limit=20"]),
    ("health", ["health-score"]),
    ("incidents", ["incidents"]),
    ("risk", ["risk"]),
    ("risk/guard", ["accounts"]),
    ("backtest", ["rules", "accounts"]),
    ("forward", ["rules"]),
    ("overfit", ["rules"]),
    ("replay", ["rules", "accounts"]),
    ("rule-layer", ["rules"]),
    ("settings", ["me", "ctrader/status"]),
    ("license", ["me", "billing/offer"]),
    ("live", ["live/status"]),
    ("help", []),
    ("admin/audit", ["admin/audit/accounts"]),
]


def _walk(token, address):
    """Every page once, each with the shell's own reads, in one window."""
    refused, sent = [], 0
    for page, reads in PAGES:
        for path in dict.fromkeys(SHELL + reads):
            status, body = A.handle(
                "GET", A.PREFIX + path,
                headers={"Authorization": f"Bearer {token}"},
                client_key=address)
            sent += 1
            if status == 429:
                refused.append((page, path, (body.get("error") or {}).get("bucket")))
    return sent, refused


for shared in (True, False):
    label = "shared counter" if shared else "in-process counter"
    _fresh(shared=shared)
    sent, refused = _walk("new-client-token", "203.0.113.20")
    check(f"{label}: {sent} reads across {len(PAGES)} pages, none refused",
          refused == [], str(refused[:4]))
    check(f"{label}: the walk is well inside the ordinary read budget",
          sent < RL.LIMITERS["default"].limit, str(sent))
    # What is left of the broker-data budget, asked of the limiter itself.
    spare = [RL.check("GET", "accounts/501/candles",
                      auth_header="Bearer new-client-token")[0]
             for _ in range(RL.LIMITERS["candles"].limit)]
    check(f"{label}: with no broker linked the walk spent none of the "
          "broker-data budget", all(spare), f"{spare.count(False)} refused")

# Twice round in one minute, as a reader going back and forth would.
_fresh(shared=True)
_sent1, refused1 = _walk("new-client-token", "203.0.113.21")
_fresh_keys = dict(_shared)
status, body = A.handle("GET", A.PREFIX + "trades?days=30&mode=demo",
                        headers={"Authorization": "Bearer new-client-token"},
                        client_key="203.0.113.21")
check("/trades answers after the walk, as it did not in production",
      status == 200 and refused1 == [], f"{status} {str(body)[:120]}")
check("and says there is no broker rather than an empty list",
      body.get("status") == "unavailable" and "trades" not in body, str(body)[:160])

# ── 5. a linked client's broker reads are still bounded at the same limit ──
print("\n[5] with a broker linked the broker-data budget is still spent")
LINKED = USERS["linked-client-token"]
_real_linked = L.is_platform_account
_real_trades = A._tradesread.read
_real_symbols = A._read.symbols
_real_minlot = A._read.min_lot
_reached = {"n": 0}


def _stub(*_a, **_k):
    _reached["n"] += 1
    return {"connected": True, "status": "unavailable", "reason": "stubbed"}


L.is_platform_account = lambda uid: str(uid) == LINKED
A._tradesread.read = _stub
A._read.symbols = _stub
A._read.min_lot = _stub
try:
    for shared in (True, False):
        label = "shared counter" if shared else "in-process counter"
        _fresh(shared=shared)
        _reached["n"] = 0
        limit = RL.LIMITERS["candles"].limit
        paths = ["trades?days=30&mode=demo", "symbols",
                 "trade/min-lot?symbol=EURUSD&timeframe=1h&riskPercent=1"]
        outs = []
        for i in range(limit + 3):
            outs.append(A.handle(
                "GET", A.PREFIX + paths[i % 3],
                headers={"Authorization": "Bearer linked-client-token"},
                client_key="203.0.113.30"))
        check(f"{label}: the first {limit} broker reads are served",
              all(s == 200 for s, _b in outs[:limit]),
              str([s for s, _b in outs[:limit] if s != 200][:3]))
        over = outs[limit:]
        check(f"{label}: the next ones are refused, and say which budget",
              all(s == 429 and b["error"]["bucket"] == "candles"
                  and b["error"]["retryAfterSec"] >= 1 for s, b in over),
              str(over[0])[:200])
        check(f"{label}: a refused read never reached the broker",
              _reached["n"] == limit, str(_reached["n"]))
        ok, bucket, _wait = RL.check("GET", "accounts/501/candles",
                                     auth_header="Bearer linked-client-token")
        check(f"{label}: and candles share that same budget",
              ok is False and bucket == "candles", f"{ok} {bucket}")
        status, _body = A.handle(
            "GET", A.PREFIX + "me",
            headers={"Authorization": "Bearer linked-client-token"},
            client_key="203.0.113.30")
        check(f"{label}: while an ordinary read is still answered",
              status == 200, str(status))

    # The unlinked client, on the same routes, spends nothing and is never
    # refused by the broker budget however often they ask.
    _fresh(shared=True)
    _reached["n"] = 0
    outs = [A.handle("GET", A.PREFIX + "symbols",
                     headers={"Authorization": "Bearer new-client-token"},
                     client_key="203.0.113.31")[0] for _ in range(40)]
    check("forty reads with nothing linked are not a broker-budget refusal",
          set(outs) == {200}, str(set(outs)))

    # A store that cannot say whether a broker is linked is not a "no".
    def _boom(uid):
        raise user_store.StoreUnavailable("down")
    L.is_platform_account = _boom
    _fresh(shared=False)
    for _ in range(RL.LIMITERS["candles"].limit):
        A.handle("GET", A.PREFIX + "symbols",
                 headers={"Authorization": "Bearer linked-client-token"},
                 client_key="203.0.113.32")
    status, body = A.handle(
        "GET", A.PREFIX + "symbols",
        headers={"Authorization": "Bearer linked-client-token"},
        client_key="203.0.113.32")
    check("an unreadable link is charged, not waved through",
          status == 429 and body["error"]["bucket"] == "candles", f"{status}")
finally:
    L.is_platform_account = _real_linked
    A._tradesread.read = _real_trades
    A._read.symbols = _real_symbols
    A._read.min_lot = _real_minlot
    user_store.incr = _real_incr
    RL.reset_all()

print()
if _fails:
    print(f"FAILED: {len(_fails)}")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("ALL RATE-LIMIT BROWSING TESTS PASSED.")
