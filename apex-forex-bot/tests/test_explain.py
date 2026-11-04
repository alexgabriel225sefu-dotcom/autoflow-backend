"""A decision's explanation names who stopped it, and never invents a reason.

WHAT THESE TESTS WILL NOT ACCEPT

* A refusal filed under a category it was never given (an unknown code is
  "unknown", with the code in the sentence).
* A risk-guard refusal that hides that the conditions had held.
* A HOLD that does not say which conditions failed.
* An unevaluated condition counted as met or as failed.
* A crash on a malformed decision.

Run: python3 tests/test_explain.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from apex.platform import explain as E  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def cond(i, passed, detail=""):
    return {"id": i, "params": {}, "passed": passed, "detail": detail}


base = {"symbol": "EURUSD", "snapshotTs": 1700000000, "ruleDocId": "r", "ruleDocVersion": 3}

print("[1] hold names the failed conditions")
x = E.explain({**base, "verdict": "HOLD", "conditions": [cond("rsi", True), cond("ema", False)]})
check("outcome no_setup", x["outcome"] == "no_setup")
check("lists the unmet one", [c["id"] for c in x["unmet"]] == ["ema"])
check("and the met one", [c["id"] for c in x["met"]] == ["rsi"])
check("headline names it", "ema" in x["headline"], x["headline"])
check("no block on a hold", x["blockedBy"] is None)
check("data used carries version and time", x["dataUsed"]["ruleDocVersion"] == 3 and x["dataUsed"]["snapshotTs"] == 1700000000)

print("[2] a risk guard says the setup was there")
x = E.explain({**base, "verdict": "REJECT", "refusalCode": "SPREAD_LIMIT_EXCEEDED",
               "conditions": [cond("rsi", True)]})
check("category risk_guard", x["blockedBy"]["category"] == "risk_guard")
check("guard named", x["blockedBy"]["guard"] == "spread limit")
check("headline says the condition held", "1 condition(s) held" in x["headline"], x["headline"])

print("[3] other owners of a refusal")
for code, cat in [("MODE_UNVERIFIED", "broker"), ("LEDGER_UNAVAILABLE", "infrastructure"),
                  ("NOT_ENTITLED", "account"), ("RULE_INVALID", "strategy"),
                  ("INSUFFICIENT_DATA", "infrastructure")]:
    r = E.explain({**base, "verdict": "REJECT", "refusalCode": code})
    check(f"{code} is {cat}", r["blockedBy"]["category"] == cat)

print("[4] honesty")
x = E.explain({**base, "verdict": "REJECT", "refusalCode": "SOMETHING_NEW"})
check("unknown code stays unknown", x["blockedBy"]["category"] == "unknown")
check("and names the code", "SOMETHING_NEW" in x["blockedBy"]["sentence"])
x = E.explain({**base, "verdict": "HOLD", "conditions": [cond("a", None), cond("b", True)]})
check("unevaluated is neither met nor failed",
      [c["id"] for c in x["unknown"]] == ["a"] and [c["id"] for c in x["met"]] == ["b"] and x["unmet"] == [])
check("headline mentions the unevaluated", "could not be evaluated" in x["headline"])
x = E.explain({**base, "verdict": "BUY", "conditions": [cond("a", True), cond("b", True)]})
check("a setup says all held", x["outcome"] == "setup" and "All 2" in x["headline"])

print("[5] malformed input")
for bad in (None, "x", 5, {}, {"verdict": "HOLD", "conditions": [None, 3]}):
    try:
        out = E.explain(bad)
        check(f"survives {bad!r}", isinstance(out["headline"], str))
    except Exception as e:  # noqa: BLE001
        check(f"survives {bad!r}", False, repr(e))

print("\nFAILED: " + ", ".join(fails) if fails else "\nALL OK")
sys.exit(1 if fails else 0)
