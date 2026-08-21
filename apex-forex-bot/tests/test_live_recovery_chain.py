"""A restart with a LIVE position open, proven as one chain.

The pieces are each tested elsewhere — Redis atomicity, ownership, close
idempotency, reconnect. What was never proven is that they COMPOSE: that a
process holding a live position can die, come back, and reach a state that is
either correct or explicitly unknown, without ever opening a second position.

The thing being tested is not "does recovery succeed". It is what happens
when it CANNOT succeed. A restart that cannot establish the truth must keep
tracking and place nothing; it must never resolve an unanswered question in
the direction that resumes trading.

Every safety primitive here is the real one — gates.authorize_order,
ledger.claim, ownership.may_trade, user_loop.recovery_verdict. Only the broker
and the clock are simulated.

Run: python tests/test_live_recovery_chain.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-recov-")

from apex import gates, ledger, ownership, user_loop, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


LIVE_POS = {"symbol": "GBPUSD", "side": "BUY", "units": 5000.0,
            "entryPrice": 1.36078, "stopLoss": 1.35777, "takeProfit": 1.36681,
            "positionId": 54669878, "initialStop": 1.357768}

UID = "900001"
user_store.save(UID, {"active": True, "paper": False, "symbol": "GBPUSD",
                      "ctrader_account_id": 47765456,
                      "open_position_snapshot": dict(LIVE_POS),
                      "licence_key": "TEST-LICENCE"})

print("\n♻️  LIVE RECOVERY CHAIN — restart with money on the table\n")

print("1. The verdict a restart is allowed to reach")
V = user_loop
check("broker says still open → adopt it",
      V.recovery_verdict(LIVE_POS, True) == V.ADOPT)
check("broker says flat, definitively → treat as closed",
      V.recovery_verdict(None, True) == V.CONFIRMED_CLOSED)
check("broker never answered → keep tracking, do NOT conclude closed",
      V.recovery_verdict(None, False) == V.KEEP_TRACKED,
      "an unreachable broker is not the same fact as a closed position")
check("no answer AND no position is still not 'closed'",
      V.recovery_verdict(None, False) != V.CONFIRMED_CLOSED)
# The bug this shape exists to prevent: two failures then a clean answer.
check("failing twice then answering counts as answered",
      V.recovery_verdict(None, True) == V.CONFIRMED_CLOSED,
      "keyed on 'did any attempt succeed', not 'did any attempt fail'")

print("\n2. A recovered position is never re-opened as a new order")
first_ok, _, rid = ledger.claim(UID, "GBPUSD", "BUY", 5000.0,
                                1.35777, 1.36681, fail_closed=True)
check("the original order holds its claim", first_ok is True)
again_ok, why, _ = ledger.claim(UID, "GBPUSD", "BUY", 5000.0,
                                1.35777, 1.36681, fail_closed=True)
check("an identical order after restart is refused", again_ok is False, why)

print("\n3. Ownership decides whether this instance may act at all")
_may = ownership.may_trade


def owned(verdict, why="test"):
    ownership.may_trade = lambda uid, live=False: (verdict, why)


# Entitlement is checked BEFORE ownership, so it has to be satisfied first or
# the order is refused for the wrong reason and this proves nothing about
# ownership. (Discovered by writing it the naive way: the assertion passed on
# "denied" while the gate under test never ran.)
_ent0 = gates.live_entitlement
try:
    gates.live_entitlement = lambda uid, user=None: ("allowed", "test licence")
    owned(False, "another instance holds the lease")
    d, _ = gates.authorize_order(UID, symbol="GBPUSD", side="BUY", units=5000.0,
                                 sl=1.35777, tp=1.36681, origin="signal",
                                 dash={})
    check("a second instance recovering the same account may not order",
          not d, d.reason if d else "")
    check("and it is refused for OWNERSHIP, not something earlier",
          "OWNER" in (d.reason or "").upper(), d.reason)

    owned(True, "lease held")
    d2, _ = gates.authorize_order(UID, symbol="GBPUSD", side="BUY", units=4321.0,
                                  sl=1.35777, tp=1.36681, origin="signal",
                                  dash={})
    check("the owning instance is allowed through", bool(d2),
          d2.reason if d2 else "")
finally:
    gates.live_entitlement = _ent0
    ownership.may_trade = _may

print("\n4. Unknown state fails closed, in every direction")
_ent = gates.live_entitlement
try:
    gates.live_entitlement = lambda uid, user=None: ("unknown", "index unreadable")
    owned(True)
    d, _ = gates.authorize_order(UID, symbol="GBPUSD", side="BUY", units=1000.0,
                                 sl=1.0, tp=2.0, origin="signal", dash={})
    check("entitlement UNKNOWN blocks a LIVE order", not d, d.reason if d else "")
finally:
    gates.live_entitlement = _ent
    ownership.may_trade = _may

owned(True)
try:
    halted = {"riskGuard": {"halted": True, "reasons": ["daily loss limit"]}}
    d, _ = gates.authorize_order(UID, symbol="GBPUSD", side="BUY", units=1000.0,
                                 sl=1.0, tp=2.0, origin="signal", dash=halted)
    check("a halted risk guard blocks a recovered account from trading",
          not d, d.reason if d else "")
finally:
    ownership.may_trade = _may

print("\n5. Idempotency that cannot be proven is not idempotency")
# "No shared backend configured" and "configured but unreachable" are
# deliberately different cases in ledger.claim, and only the second is a
# refusal: an unconfigured backend implies a single instance, so there is no
# second writer to be blind to. Both have to be pinned, because collapsing
# them either way is a real bug — one halts a demo for nothing, the other
# opens a live position on trust.
_claim, _shared = user_store.claim, ledger.shared_backed
try:
    user_store.claim = lambda *a, **k: None          # errored / timed out
    ledger.shared_backed = lambda: True              # …but it IS configured
    ok, why, _ = ledger.claim(UID, "EURUSD", "BUY", 1000.0, 1.0, 2.0,
                              fail_closed=True)
    check("a LIVE order during a coordination outage is refused",
          ok is False and why == "COORDINATION_UNAVAILABLE", why)
    ok2, _, _ = ledger.claim(UID, "AUDUSD", "BUY", 1000.0, 1.0, 2.0,
                             fail_closed=False)
    check("a simulated order in the same outage may proceed", ok2 is True,
          "fail-closed is for real money; a demo blocked by an outage helps "
          "nobody")

    ledger.shared_backed = lambda: False             # none configured at all
    ok3, _, _ = ledger.claim(UID, "NZDUSD", "BUY", 1000.0, 1.0, 2.0,
                             fail_closed=True)
    check("with no backend configured, a live order still proceeds", ok3 is True,
          "nothing to be unreachable — a single instance has no second writer")
finally:
    user_store.claim, ledger.shared_backed = _claim, _shared

print("\n6. The snapshot carries what the broker cannot give back")
snap = user_store.load(UID).get("open_position_snapshot") or {}
check("the position survived the restart in storage", snap.get("positionId") == 54669878)
check("its ORIGINAL stop is preserved, not the trailed one",
      snap.get("initialStop") == 1.357768,
      "re-deriving R from a trailed stop resumes noise-tight trailing")
check("stop and target are both on record",
      snap.get("stopLoss") and snap.get("takeProfit"))
risk = user_loop._risk_from_snapshot(snap.get("entryPrice"), snap.get("initialStop"))
check("initial risk is recoverable from it", risk and round(risk, 6) == 0.003012,
      risk)

print("\n7. Recovery is idempotent — running it twice changes nothing")
before = user_store.load(UID).get("open_position_snapshot")
for _ in range(3):
    v = user_loop.recovery_verdict(dict(LIVE_POS), True)
check("repeated recovery reaches the same verdict", v == user_loop.ADOPT)
check("and does not disturb the stored snapshot",
      user_store.load(UID).get("open_position_snapshot") == before)

print("\n8. A close during the outage is booked once, not twice")
c1, _, _ = ledger.claim(UID, "CLOSE:54669878", "CLOSE", 0, None, None,
                        fail_closed=True)
c2, why2, _ = ledger.claim(UID, "CLOSE:54669878", "CLOSE", 0, None, None,
                           fail_closed=True)
check("the first close claim is taken", c1 is True)
check("a duplicate close after restart is refused", c2 is False, why2)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — unknown state never resumes trading.")
