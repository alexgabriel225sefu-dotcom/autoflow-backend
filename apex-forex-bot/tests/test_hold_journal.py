"""A rule that finds nothing on a closed bar says so, in the journal.

A preset strategy decides inside the engine, so the journal used to hold only
start/stop events for it, and "why didn't it trade" had no answer on screen.
These checks pin the new HOLD entry and the "last check" line in /why.

Run: python3 tests/test_hold_journal.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-hold-")
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


from apex.platform import automation as AU                  # noqa: E402
from apex.platform import journal as J                      # noqa: E402
from apex.platform import journal_store as JS               # noqa: E402
from apex.platform import signals as SIG                    # noqa: E402

USER = "hold-user"
AU._licence_active = lambda uid: True
AU._write(USER, {"state": AU.RUNNING, "ruleDocId": "r1", "mode": "demo",
                 "accountId": "123", "correlationId": "corr1",
                 "appliedTerms": {"automation": "full"}})

e = J.for_hold(user_id=USER, symbol="XAUUSD", reason="Regime reads quiet",
               correlation_id="c1", price=3550.5, bar_time=1700000000)
check("a hold entry is an evaluation with status hold",
      e.kind == J.EVALUATION and e.status == J.HOLD)
check("it says plainly that nothing is executable",
      e.decision["verdict"] == "HOLD" and e.decision["executable"] is False)

ok = SIG.record_hold(USER, symbol="XAUUSD", reason="Regime reads quiet",
                     price=3550.5, bar_time=1700000000, regime="ranging")
check("record_hold writes and reports success", ok is True)
page = JS.query(USER, status="hold")
check("the journal now lists it under Hold",
      page["total"] == 1 and page["entries"][0]["symbol"] == "XAUUSD")
check("it is filed against the running rule and account",
      page["entries"][0].get("ruleDocId") == "r1"
      or page["entries"][0].get("rule_doc_id") == "r1")


def ask():
    return AU.why(USER, loop_reader=lambda u: (True, {"skips": []}),
                  declines_reader=lambda u: [], market_open=lambda: True,
                  risk_reader=lambda u: {"state": "ok", "reasons": []})


w = ask()
check("/why names the last check", (w.get("latestCheck") or {}).get("reason") == "Regime reads quiet")
check("/why puts that check in the sentence a client reads",
      "Last check: Regime reads quiet" in w["summary"], w["summary"])
check("the reason code is still 'watching'", w["reason"] == "watching")

check("record_hold never raises on bad input",
      SIG.record_hold(USER, symbol=None, reason=None, price=float("nan")) in (True, False))

if _fails:
    print("\nFAILED (%d):" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("\nAll hold-journal checks passed.")
