"""Order idempotency — one intent must never become two positions.

Guardian blueprint acceptance criterion 7, and the only item on that list that
loses money directly rather than degrading a signal.

Both failure modes under test are observed, not hypothetical:

  * TWO INSTANCES. Render's zero-downtime deploy overlaps containers. In the
    live logs instance 6n5hh ran tick 101 at 18:21:07 while vvlq4 had started
    its loop at 18:21:00 — both driving one cTrader account. The loop's
    generation token only sees threads inside its own process.
  * A TIMED-OUT SUBMIT. "positions read: timed out" already appears in these
    logs. A timeout is not a failure; the broker may have filled it, and a
    retry doubles the position.

Run: python tests/test_ledger.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-ledger-test-")
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import ledger, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


T0 = 1_786_500_000.0
ORDER = ("u1", "EURUSD", "BUY", 10000, 1.0950, 1.1050)


def reset():
    ledger._local.clear()


# ── shared backend absent: local-only protection ────────────────────────
print("\n── a retry inside one process is blocked ──")
reset()
ok1, why1, rid1 = ledger.claim(*ORDER, now=T0)
ok2, why2, rid2 = ledger.claim(*ORDER, now=T0 + 1)
check("first claim wins", ok1 is True and why1 == "CLAIMED")
check("the immediate retry is refused", ok2 is False, why2)
check("and says why", "DUPLICATE" in why2)
check("both compute the same id", rid1 == rid2)

print("\n── a genuinely different order is not blocked ──")
reset()
ledger.claim(*ORDER, now=T0)
check("different symbol",
      ledger.claim("u1", "GBPUSD", "BUY", 10000, 1.0950, 1.1050, now=T0)[0])
check("different side",
      ledger.claim("u1", "EURUSD", "SELL", 10000, 1.0950, 1.1050, now=T0)[0])
check("different size",
      ledger.claim("u1", "EURUSD", "BUY", 20000, 1.0950, 1.1050, now=T0)[0])
check("different stop",
      ledger.claim("u1", "EURUSD", "BUY", 10000, 1.0900, 1.1050, now=T0)[0])
check("different target",
      ledger.claim("u1", "EURUSD", "BUY", 10000, 1.0950, 1.1099, now=T0)[0])
check("different user — two clients may trade the same setup",
      ledger.claim("u2", "EURUSD", "BUY", 10000, 1.0950, 1.1050, now=T0)[0])

print("\n── the window expires so a later re-entry is allowed ──")
reset()
ledger.claim(*ORDER, now=T0)
check("still blocked inside the window",
      ledger.claim(*ORDER, now=T0 + 60)[0] is False)
check("allowed well after it",
      ledger.claim(*ORDER, now=T0 + 500)[0] is True)

print("\n── THE BUCKET SEAM: two instances either side of a boundary ──")
# Without checking the previous bucket, an intent at 119s and one at 121s land
# in different buckets, compute different ids, and BOTH trade — which is
# exactly the deploy-overlap case this exists to stop.
reset()
edge = (int(T0 // 120) + 1) * 120.0     # exact bucket boundary
a_ok, _, a_id = ledger.claim(*ORDER, now=edge - 1)
b_ok, b_why, b_id = ledger.claim(*ORDER, now=edge + 1)
check("the two sides of the boundary DO compute different raw ids",
      a_id != b_id)
check("but the second is still blocked", b_ok is False, b_why)

print("\n── symbol spelling cannot be used to slip a duplicate through ──")
reset()
ledger.claim("u1", "EURUSD", "BUY", 10000, 1.0950, 1.1050, now=T0)
for spelling in ("EUR_USD", "eur/usd", "eurusd"):
    check(f"{spelling} is the same instrument",
          ledger.claim("u1", spelling, "BUY", 10000, 1.0950, 1.1050,
                       now=T0)[0] is False)

print("\n── the original result is retrievable for a duplicate ──")
reset()
ok, _, rid = ledger.claim(*ORDER, now=T0)
ledger.record(rid, {"orderId": "CT_123", "status": "FILLED"})
check("recorded", ledger.result_for(rid)["orderId"] == "CT_123")
check("unknown id → None", ledger.result_for("nope") is None)

print("\n── release() frees a claim that never became an order ──")
reset()
ok, _, rid = ledger.claim(*ORDER, now=T0)
ledger.release(rid)
check("the intent can be retried after an explicit release",
      ledger.claim(*ORDER, now=T0 + 1)[0] is True)

# ── shared backend present: cross-process protection ────────────────────
print("\n── with a shared backend, another INSTANCE is blocked ──")
reset()
_shared = {}


def fake_claim(key, ttl_s=120):
    if key in _shared:
        return False
    _shared[key] = 1
    return True


_orig = user_store.claim
user_store.claim = fake_claim
check("instance A claims", ledger.claim(*ORDER, now=T0)[0] is True)
reset()   # instance B has a COMPLETELY separate process memory
check("instance B, with no local memory of it, is still blocked",
      ledger.claim(*ORDER, now=T0 + 3)[0] is False,
      "this is the deploy-overlap case")

print("\n── a shared backend that ERRORS must not halt trading ──")
_shared.clear()
reset()
user_store.claim = lambda key, ttl_s=120: None      # backend unreachable
ok, why, _ = ledger.claim(*ORDER, now=T0)
check("the order is allowed, not refused", ok is True, why)
check("and the local ledger still catches the retry",
      ledger.claim(*ORDER, now=T0 + 1)[0] is False)
check("the reason names it as local-only",
      "LOCAL" in ledger.claim(*ORDER, now=T0 + 2)[1])

print("\n── shared_backed() is honest about which mode is active ──")
user_store.claim = _orig
check("no Redis configured in this test → False",
      ledger.shared_backed() is False)

print("\n── malformed input never crashes the order path ──")
reset()
check("None units", ledger.claim("u1", "EURUSD", "BUY", None, None, None,
                                 now=T0)[0] is True)
check("junk prices", ledger.claim("u1", "EURUSD", "BUY", 1000, "x", "y",
                                  now=T0)[0] is True)
check("no symbol", ledger.claim("u1", None, "BUY", 1000, now=T0)[0] is True)

print("\n── the local ledger does not grow without bound ──")
reset()
for i in range(700):
    ledger.claim("u1", "EURUSD", "BUY", i, now=T0)
check("pruned below the cap", len(ledger._local) <= ledger._LOCAL_KEEP,
      str(len(ledger._local)))

print("\n── live claims require a shared backend and a decision setup key ──")
reset()
decision = {
    "symbol": "EUR_USD", "side": "BUY", "verdict": "BUY",
    "ruleDocId": "rule-7", "ruleDocVersion": 3,
    "snapshotTs": 1_758_542_400.0,
}
setup = ledger.setup_key_from_decision(decision)
check("the setup key has the legacy four-part shape",
      setup == "EURUSD:BUY:rule-7-v3:1758542400", setup)
check("the setup key is stable and does not read wall time",
      ledger.setup_key_from_decision(dict(decision)) == setup)

_saved_live = (user_store._USE_REDIS, user_store.claim,
               user_store.redis_health, user_store.release_claim)
try:
    user_store._USE_REDIS = False
    refused = ledger.claim_live_order("u1", "acc1", decision)
    check("live refuses when no shared backend is configured",
          refused["ok"] is False
          and refused["code"] == "SHARED_BACKEND_REQUIRED", str(refused))
    check("but the legacy/demo claim still stays local-only and allowed",
          ledger.claim("u1", "EURUSD", "BUY", 1234, now=T0)[0] is True)

    user_store._USE_REDIS = True
    user_store.redis_health = lambda: {
        "configured": True, "reachable": False, "status": "DOWN"}
    called = []
    user_store.claim = lambda key, ttl_s=120: called.append(key) or True
    down = ledger.claim_live_order("u1", "acc1", decision)
    check("live refuses when the shared backend cannot answer",
          down["ok"] is False
          and down["code"] == "COORDINATION_UNAVAILABLE", str(down))
    check("and it does not take a claim after a failed health check",
          called == [], str(called))

    user_store.redis_health = lambda: {
        "configured": True, "reachable": True, "status": "HEALTHY"}
    shared = {}

    def live_claim(key, ttl_s=120):
        if key in shared:
            return False
        shared[key] = ttl_s
        return True

    user_store.claim = live_claim
    reset()
    a = ledger.claim_live_order("u1", "acc1", decision)
    reset()  # another process: no local memory of the first claim
    b = ledger.claim_live_order("u1", "acc1", decision)
    check("exactly one live process claims a setup",
          [a["ok"], b["ok"]].count(True) == 1
          and [a["ok"], b["ok"]].count(False) == 1, f"{a} / {b}")
    check("the loser is refused as a duplicate live order",
          b["code"] == "DUPLICATE_LIVE_ORDER", str(b))

    release_calls = []
    user_store.release_claim = lambda key, value: release_calls.append((key, value))
    claim = ledger.claim_live_order(
        "u1", "acc1", dict(decision, snapshotTs=1_758_542_460.0))
    unknown = ledger.record_live_order_outcome(
        claim, {"error": "broker timeout after submit"}, confirmed=False)
    check("an unknown broker outcome keeps the live claim held",
          unknown["code"] == "OUTCOME_UNKNOWN_CLAIM_HELD", str(unknown))
    check("and no release is attempted on that unknown outcome",
          release_calls == [], str(release_calls))
finally:
    (user_store._USE_REDIS, user_store.claim,
     user_store.redis_health, user_store.release_claim) = _saved_live

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL ORDER-IDEMPOTENCY CHECKS PASSED.")
