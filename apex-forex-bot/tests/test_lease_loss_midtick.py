"""Losing the lease in the middle of a tick stands the loop down.

SCENARIO. A tick starts as the owner. While it is busy (a slow broker read, a
sizing step) another container takes the lease. Three things must follow:

  1. the renewer thread notices and flags the loss;
  2. an order that reaches the send point AFTER the takeover is refused and
     never touches the broker;
  3. the loop's next pass leaves the while-loop without trading, releasing
     nothing it no longer owns.

Real `ownership` (including its real renewer thread, with the period shortened)
and the real `force_trade`; only the shared store and the broker are fakes.
The stand-down branch itself lives inside the 3,000-line `_loop` closure,
which cannot be called without a live tick, so it is pinned the way the
neighbouring tests pin it: by reading the shipped source for the branch and
its position relative to the first trading step.

KNOWN GAP (asserted at current behaviour): between the takeover and the
renewer's next heartbeat, `ownership.holds()` trusts its local record and
`may_trade` answers OWNER. The window is RENEW_EVERY_S. See section [5].

Run: python3 tests/test_lease_loss_midtick.py
"""
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-leaseloss-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex import gates as GATES                             # noqa: E402
from apex import ownership, user_loop as UL, user_store     # noqa: E402

USER = "dddddddd-8888-4888-8888-dddddddddddd"
OTHER = "container-B-0001"


class Fake:
    def __init__(self):
        self.lock = threading.Lock()
        self.kv = {}
        self.users = {USER: {"id": USER, "paper": True}}

    def claim_value(self, k, v, ttl_s=120):
        with self.lock:
            if k in self.kv:
                return False
            self.kv[k] = str(v)
            return True

    def renew_claim(self, k, v, ttl_s=120):
        with self.lock:
            return self.kv.get(k) == str(v)

    def release_claim(self, k, v):
        with self.lock:
            if self.kv.get(k) != str(v):
                return False
            del self.kv[k]
            return True


FAKE = Fake()
_names = ("claim_value", "renew_claim", "release_claim", "get_blob", "load",
          "update", "claim", "_USE_REDIS")
_orig = {n: getattr(user_store, n) for n in _names}
user_store._USE_REDIS = True
user_store.claim_value = FAKE.claim_value
user_store.renew_claim = FAKE.renew_claim
user_store.release_claim = FAKE.release_claim
user_store.get_blob = lambda k: FAKE.kv.get(k)
user_store.load = lambda uid: dict(FAKE.users.get(str(uid), {}))
user_store.update = lambda uid, patch, **k: FAKE.users.setdefault(str(uid), {}).update(patch) or True
user_store.claim = lambda k, ttl_s=120, **kw: FAKE.claim_value(k, "1", ttl_s)

KEY = f"own:user:{USER}"
_real_renew_every = ownership.RENEW_EVERY_S


def reset():
    FAKE.kv.clear()
    ownership._held.clear()
    ownership._renewers.clear()
    ownership._lost.clear()
    ownership._shutdown.clear()


_CANDLES = [{"open": 1.0920, "high": 1.0940, "low": 1.0910, "close": 1.0930,
             "time": 1_700_000_000 + i * 300} for i in range(60)]
_REAL_CFG = UL._make_broker({"paper": True})[1]


class Broker:
    def __init__(self):
        self.orders = []

    def get_candles(self, sym, tf, n):
        return _CANDLES[-int(n):]

    def get_bid_ask(self, sym):
        return 1.0929, 1.0931

    def get_balance(self):
        return 10_000.0

    def get_open_position(self, sym=None):
        return None

    def place_order(self, side, units, sym, sl=None, tp=None):
        self.orders.append((side, units, sym))
        return {"orderId": "o1", "status": "FILLED", "fillPrice": 1.0930}


def order(broker):
    saved = {n: getattr(UL, n) for n in
             ("_make_broker", "_persist_open_position", "get_dash", "_alert_fn_for")}
    _ent = GATES.live_entitlement
    try:
        UL._make_broker = lambda user, user_id=None: (broker, _REAL_CFG)
        UL._persist_open_position = lambda *a: None
        UL.get_dash = lambda uid: {}
        UL._alert_fn_for = lambda uid, fn: None
        GATES.live_entitlement = lambda uid, u=None: ("allowed", "stubbed")
        return UL.force_trade(USER, "BUY", symbol="EURUSD", lots=0.01,
                              sl_override=1.0900, tp_override=1.0960,
                              origin="approval")
    finally:
        for n, f in saved.items():
            setattr(UL, n, f)
        GATES.live_entitlement = _ent


try:
    # ── 1. the renewer notices a genuine takeover ──────────────────────────
    print("\n[1] a takeover mid-tick is noticed by the renewer thread")
    reset()
    ownership.RENEW_EVERY_S = 0.05          # real thread, test-sized period
    check("the lease is ours at the start of the tick",
          ownership.acquire(USER) is True and FAKE.kv[KEY] == ownership.INSTANCE_ID)
    ownership.start_renewer(USER, on_lost=ownership.mark_lost)
    time.sleep(0.2)
    check("(control) while we own it, nothing is flagged", ownership.was_lost(USER) is False)
    FAKE.kv[KEY] = OTHER                    # container B takes over, mid-tick
    for _ in range(100):
        if ownership.was_lost(USER):
            break
        time.sleep(0.05)
    check("the loss is flagged for the loop", ownership.was_lost(USER) is True)
    check("the lease is NOT stolen back", FAKE.kv[KEY] == OTHER, str(FAKE.kv))
    check("we no longer claim to hold it", USER not in ownership._held)
    ownership.RENEW_EVERY_S = _real_renew_every

    # ── 2. an order after the takeover never reaches the broker ────────────
    print("\n[2] an order that reaches the send point after the takeover is refused")
    check("may_trade says NOT_OWNER (demo and live alike)",
          ownership.may_trade(USER, live=False) == (False, "NOT_OWNER")
          and ownership.may_trade(USER, live=True) == (False, "NOT_OWNER"),
          str(ownership.may_trade(USER, live=True)))
    broker = Broker()
    out = order(broker)
    check("force_trade refuses", out.get("ok") is False, str(out))
    check("and says why: not the owning instance", "owning instance" in str(out.get("error")),
          str(out.get("error")))
    check("the broker was never asked", broker.orders == [], str(broker.orders))

    # ── 3. the loop leaves its while-loop, before it trades ────────────────
    print("\n[3] the loop's stand-down branch (shipped source)")
    src = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
    loop = src.split("def _loop(", 1)[1].split("\ndef ", 1)[0]
    i_lost = loop.index("if ownership.was_lost(user_id):")
    i_market = loop.index("forex.is_market_open()")
    block = loop[i_lost:loop.index("_stop_requested(user_id)", i_lost)]
    check("the loss is checked before the market check and any order", i_lost < i_market)
    check("the client is told (OWNERSHIP_LOST)", '"OWNERSHIP_LOST"' in block)
    check("the renewer is stopped, so the next restart does not re-alert",
          "ownership.stop_renewer(user_id)" in block)
    check("the loop breaks", "\n            break" in block)
    check("it does NOT release a lease it no longer owns",
          "ownership.release(" not in block,
          "the lease is container B's now; standing down must only stop the renewer")

    # ── 4. and a later restart is not poisoned by the old loss ─────────────
    print("\n[4] once the other container's lease is gone, we may take it again")
    ownership.stop_renewer(USER)            # what the stand-down branch does
    check("the loss flag is cleared by stopping the renewer",
          ownership.was_lost(USER) is False)
    del FAKE.kv[KEY]                        # B released / its lease lapsed
    check("a fresh acquire succeeds", ownership.acquire(USER) is True)
    check("and trading is permitted again", ownership.may_trade(USER, live=True)[0] is True)

    # ── 5. KNOWN GAP ───────────────────────────────────────────────────────
    print("\n[5] KNOWN GAP: the takeover is invisible to may_trade until the renewer runs")
    # `holds()` answers from the local `_held` timestamp while it is fresher
    # than RENEW_EVERY_S, to keep a network hop off the money path. The
    # renewer thread is what corrects it. So for up to RENEW_EVERY_S after
    # another container takes the lease, an order from THIS container still
    # passes the ownership gate - two owners for that interval, on the very
    # path (live orders) where the docstring says unknown ownership fails
    # closed. BETTER BEHAVIOUR: a live order re-reads the key (one GET) when
    # it is about to send, instead of trusting the cached timestamp.
    reset()
    ownership.RENEW_EVERY_S = 3600          # no renewer will run in this test
    check("we hold the lease", ownership.acquire(USER) is True)
    FAKE.kv[KEY] = OTHER                    # B takes over; no heartbeat has run
    verdict = ownership.may_trade(USER, live=True)
    check("(current) a LIVE order is still allowed: OWNER from the stale local record",
          verdict == (True, "OWNER"), str(verdict))
    check("(current) the store itself already says someone else holds it",
          FAKE.kv[KEY] == OTHER)
    ownership._held.pop(USER, None)         # what the next heartbeat does
    check("(corrected by the renewer) the same call then refuses",
          ownership.may_trade(USER, live=True) == (False, "NOT_OWNER"))
finally:
    ownership.RENEW_EVERY_S = _real_renew_every
    reset()
    for n, f in _orig.items():
        setattr(user_store, n, f)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All lease-loss checks passed.")
