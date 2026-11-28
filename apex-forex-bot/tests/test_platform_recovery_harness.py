"""Application restart behaviour on a local store. Not a provider backup test.

No Postgres, no Redis, no broker, no Stripe, no production data. What this
shows is the process's own answers: a restart that did not hear the broker
does not mark a position closed, a second identical order claim in this
process is a duplicate, and a withdrawn licence is not active. It says
nothing about Render, Supabase, or Redis recovery time.

Run: python3 tests/test_platform_recovery_harness.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.update(
    APP_ENV="test",
    ALLOW_LOCAL_BACKEND_DEV="true",
    ALLOW_PLAINTEXT_DEV_STORAGE="true",
    PRODUCT="forex",
    DATA_DIR=tempfile.mkdtemp(prefix="a4t-recover-"),
    TOKEN_ENCRYPTION_KEY="cDcb_wSOjqAiI8jn9la_Vx3J1GpCVJyFlJXX6VYHHWI=",
)

from apex import user_loop                                              # noqa: E402
from apex import ledger                                                  # noqa: E402
from apex.platform import licence as LIC                                 # noqa: E402
from apex.platform import store as store                                 # noqa: E402
from apex.platform import ruledoc                                        # noqa: E402

_fails = []
USER = "cccccccc-3333-4333-8333-cccccccccccc"


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name if not detail else f"{name} — {detail}")
        print(f"  FAIL {name} {detail}")


print("\n[1] restart reconciliation")
check("broker still shows the position: adopt it",
      user_loop.recovery_verdict({"positionId": "1"}, True) == user_loop.ADOPT)
check("broker did not answer: keep it tracked",
      user_loop.recovery_verdict(None, False) == user_loop.KEEP_TRACKED)
check("broker answered flat: confirmed closed",
      user_loop.recovery_verdict(None, True) == user_loop.CONFIRMED_CLOSED)
check("a missing stop is not invented",
      user_loop._risk_from_snapshot(1.1, None) is None)

print("\n[2] a second identical claim in this process is a duplicate")
ok1, why1, _rid = ledger.claim(USER, "EURUSD", "BUY", 1000, sl=1.0, tp=1.2, now=1_700_000_000)
ok2, why2, _rid2 = ledger.claim(USER, "EURUSD", "BUY", 1000, sl=1.0, tp=1.2, now=1_700_000_000)
check("first claim wins", ok1 is True, why1)
check("second is refused", ok2 is False and "DUPLICATE" in why2, why2)

print("\n[3] a rule written before a 'restart' is still that user's")
doc = ruledoc.blank(user_id=USER, account_id="501", symbols=["EURUSD"], timeframe="1h")
stored = store.create(USER, doc)
again = store.get(USER, stored["ruleDocId"])
check("the rule is readable after the write", again["ruleDocId"] == stored["ruleDocId"])
try:
    store.get("dddddddd-4444-4444-8444-dddddddddddd", stored["ruleDocId"])
    check("another user does not receive it", False)
except store.NotFound:
    check("another user does not receive it", True)

print("\n[4] revoke is a withdrawn licence, not an active one")
LIC.grant(USER, plan="demo_trial", expires_at=None)
check("granted", LIC.status_for(USER)["state"] == LIC.ACTIVE)
LIC.revoke(USER)
check("revoked", LIC.status_for(USER)["state"] == LIC.REVOKED)

if _fails:
    print(f"\nFAILED ({len(_fails)}):")
    for item in _fails:
        print(f"  - {item}")
    sys.exit(1)
print("\nALL OK")
