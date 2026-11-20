#!/usr/bin/env python3
"""A drill of the live gates: stop, licence, approval, mode, pilot, watched step by step.

WHAT THIS IS

`docs/LIVE_EXECUTION_SPECIFICATION.md` section 12 asks for "entitlement, consent
and the global stop exercised in a drill, not only in tests". The tests prove
each gate refuses. A drill is somebody WATCHING the sequence: everything open and
an order allowed, then one lever pulled at a time, the refusal named, the lever
put back and the order allowed again. This script plays that sequence against
the REAL gate code and narrates it, so the person who signs the milestone off
has read it once with their own eyes.

WHAT IT IS NOT

It is not a live test. The broker is a function that returns "live" and the
store is an in-memory fake. Nothing here talks to cTrader, Redis, Supabase or
Stripe, and it opens the release switch ONLY inside its own throwaway process.
It refuses to start if it can see production credentials, so it cannot be
pointed at the real deployment by mistake. The owner's half of the drill, on
the real deployment, is in docs/LIVE_DRILL.md.

RUN:
    cd apex-forex-bot && python3 scripts/live_gate_drill.py

Exit 0 means every step behaved as written. Anything else means a gate did not
do what its spec says: do not open live until it is understood.
"""
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Refuse to run anywhere near production ─────────────────────────────────
_DANGER = ("REDIS_URL", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN",
           "SUPABASE_SERVICE_ROLE_KEY", "STRIPE_SECRET_KEY",
           "A4T_LIVE_EXECUTION", "APEX_ALLOW_LIVE_ACCOUNTS")
_found = [n for n in _DANGER if os.environ.get(n)]
if _found or os.environ.get("APP_ENV", "").lower() == "production":
    print("\n⛔ This drill only runs on a machine with NO production settings.")
    print("   Found: " + (", ".join(_found) or "APP_ENV=production"))
    print("   It uses a fake store and a fake broker. Run it on a laptop or in a")
    print("   fresh shell, never on the deployment.")
    sys.exit(2)

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-drill-")
os.environ["ALLOW_PLAINTEXT_DEV_STORAGE"] = "true"
os.environ["ALLOW_LOCAL_BACKEND_DEV"] = "true"
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("A4T_EMERGENCY_HALT", None)

from apex import user_store                                    # noqa: E402

USER = "dddd0000-1111-4222-8333-dddd44445555"
OTHER = "eeee0000-1111-4222-8333-eeee44445555"
ACCOUNT = "9001"
os.environ["A4T_LIVE_PILOT_PAIRS"] = f"{USER}:{ACCOUNT}"
os.environ["A4T_LIVE_PILOT_SYMBOLS"] = "EURUSD"
os.environ["A4T_LIVE_PILOT_MAX_UNITS"] = "2000"


class FakeStore:
    """An in-memory shared store: the gates refuse to work without one."""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}

    def install(self):
        user_store._USE_REDIS = True
        user_store._BACKEND = "redis"
        for n in ("set_blob_nx", "set_blob", "get_blob", "get_blob_strict",
                  "del_blob", "claim", "claim_value", "release_claim", "incr"):
            setattr(user_store, n, getattr(self, n))

    def set_blob_nx(self, k, v):
        with self.lock:
            if k in self.data:
                return False
            self.data[k] = v
            return True

    def set_blob(self, k, v, ttl_s=None):
        with self.lock:
            self.data[k] = v
        return True

    def get_blob(self, k):
        with self.lock:
            return self.data.get(k)

    get_blob_strict = get_blob

    def del_blob(self, k):
        # Like the real store: a number (0 = nothing was there), never None.
        with self.lock:
            return 1 if self.data.pop(k, None) is not None else 0

    def claim(self, k, ttl_s=120):
        return self.claim_value(k, "1", ttl_s=ttl_s)

    def claim_value(self, k, v, ttl_s=120):
        with self.lock:
            if k in self.data:
                return False
            self.data[k] = str(v)
            return True

    def release_claim(self, k, v):
        with self.lock:
            if self.data.get(k) != str(v):
                return False
            del self.data[k]
        return True

    def incr(self, k, ttl_s=60):
        with self.lock:
            self.data[k] = int(self.data.get(k, 0)) + 1
            return self.data[k]


STORE = FakeStore()
STORE.install()

from apex.platform import emergency as EM                       # noqa: E402
from apex.platform import entitlement as ENT                    # noqa: E402
from apex.platform import licence as LIC                        # noqa: E402
from apex.platform import live_execution as LX                  # noqa: E402
from apex.platform import live_gate as LG                       # noqa: E402
from apex.platform import plans as PLANS                        # noqa: E402

FAIL = []
NOW = 1_760_000_000.0


def step(title, expect, got, note=""):
    ok = got == expect
    print(f"  {'✅' if ok else '❌'} {title}")
    print(f"       expected {expect!r}, got {got!r}" + (f"  — {note}" if note else ""))
    if not ok:
        FAIL.append(title)
    return ok


_tick = [0]


def order(user=USER, account=ACCOUNT, symbol="EURUSD", units=1000, mode="live"):
    """One engine order through the real door. Returns the refusal code or ALLOWED."""
    _tick[0] += 1
    r = LX.authorize_order(user, symbol=symbol, side="BUY", units=units,
                           account_id=account, mode_reader=lambda: mode,
                           now=NOW + _tick[0] * 120)     # a new window each time
    return "ALLOWED" if r["allowed"] else r["code"]


def entitle(user=USER):
    LIC.grant(user, plan=PLANS.FOUNDER_LIVE, expires_at=None)


def satisfy_live_gate(user=USER):
    """Terms published, accepted, the licence confirmed, an operator's approval."""
    actor = "operator-drill"
    for doc in ("terms", "refund", "tax"):
        LG.publish(doc, "v1", actor=actor)
    LG.accept_current(user)
    LG.grant_operator_licence(user, actor=actor)
    LG.request_live(user)
    LG.decide(user, "approved", actor=actor, reason="drill")


print("\n🧯 LIVE GATE DRILL  (fake broker, fake store, this process only)\n")

# ── 1. The way the product ships ───────────────────────────────────────────
print("[1] As shipped: the release switch is closed")
entitle()
satisfy_live_gate()
step("an order is refused at the release switch", LX.LIVE_NOT_ENABLED, order(),
     "everything else may be in order; the switch is the owner's last step")

# ── 2. Open everything, in this process only ───────────────────────────────
print("\n[2] Everything open (the switch is opened in THIS process only)")
LX._ent.live_execution_enabled = lambda: True
from apex.platform import ctrader_link as _CTL                  # noqa: E402
_CTL.live_allowed = lambda: True
step("an order that passes every gate is allowed", "ALLOWED", order())

# ── 3. The emergency stop ──────────────────────────────────────────────────
print("\n[3] The emergency stop (the same functions scripts/emergency_stop.py calls)")
EM.halt(reason="drill: global stop", by="drill")
step("a GLOBAL halt refuses every order", LX.HALTED, order())
step("... and says who pressed it", True,
     "drill" in str(EM.state().get("by")), "recorded in the stored switch")
EM.release(by="drill")
step("released: the same order is allowed again", "ALLOWED", order())

EM.halt(scope=EM.LIVE, reason="drill: live only", by="drill")
step("a LIVE-only halt refuses a live order", LX.HALTED, order())
EM.release(by="drill")

EM.halt(EM.NONE, instruments=["XAUUSD"], reason="drill: gold only", by="drill")
step("an instrument halt refuses that instrument ... ", LX.HALTED,
     order(symbol="XAUUSD"))
step("... and leaves the others open (EURUSD allowed)", "ALLOWED", order())
EM.release(by="drill")

EM.halt(EM.NONE, users=[OTHER], reason="drill: one client", by="drill")
step("a halt on ANOTHER client leaves this one trading", "ALLOWED", order())
EM.release(by="drill")

os.environ[EM.ENV_VAR] = "all"
step("the environment switch halts it (it works even with the store down)",
     LX.HALTED, order())
EM.halt(reason="drill: stored switch too", by="drill")
EM.release(by="drill")
step("a stored release does NOT clear the environment switch", LX.HALTED, order())
os.environ.pop(EM.ENV_VAR, None)
step("only removing the variable does", "ALLOWED", order())

# ── 4. The licence (entitlement) ───────────────────────────────────────────
print("\n[4] The licence")
LIC._store._write(f"{LIC._store._ns()}:{LIC._store._P}:licence:{USER}", None)
step("a client without the paid plan is refused", LX.NOT_ENTITLED, order())
entitle()
step("licence restored: allowed again", "ALLOWED", order())

# ── 5. Terms, confirmed licence, operator approval ─────────────────────────
print("\n[5] Consent and approval")
LG.decide(USER, "rejected", actor="operator-drill", reason="drill: withdrawn")
blocked = order()
step("an approval withdrawn by the operator blocks the order", True,
     blocked not in ("ALLOWED",), f"refused with {blocked!r}")
STORE.data.clear()
entitle()
satisfy_live_gate()
step("re-approved from scratch: allowed", "ALLOWED", order())

# ── 6. The broker decides what is live ─────────────────────────────────────
print("\n[6] The mode comes from the broker")
step("a demo account on the live path is refused", LX.MODE_NOT_LIVE,
     order(mode="demo"))

# ── 7. The pilot ───────────────────────────────────────────────────────────
print("\n[7] The pilot: the operator's own account, small, listed instruments")
step("another account of the same client is refused", True,
     order(account="1234") != "ALLOWED")
step("an instrument not on the list is refused", True,
     order(symbol="GBPUSD") != "ALLOWED")
step("an order over the cap is refused", True, order(units=5000) != "ALLOWED")
step("the pilot's own account, symbol and size are allowed", "ALLOWED", order())

# ── Result ─────────────────────────────────────────────────────────────────
print()
if FAIL:
    print(f"❌ DRILL FAILED ({len(FAIL)}): " + "; ".join(FAIL))
    print("   Do not open live until each of these is understood.")
    sys.exit(1)
print("✅ Every gate behaved as written. This is a drill of the CODE with a fake")
print("   broker: it does not replace the owner's drill on the real deployment")
print("   (docs/LIVE_DRILL.md) or the first real order at minimum size.")
