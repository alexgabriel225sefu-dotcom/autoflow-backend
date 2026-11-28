"""Evidence wording says how much the numbers can bear, never that a strategy is good.

Run: python3 tests/test_strategy_evidence.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-evid-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
from apex.platform import performance_read as P   # noqa: E402

fails = []
def check(n, c, d=""):
    print(f"  {'ok  ' if c else 'FAIL'} {n}" + (f"  {d}" if d and not c else ""))
    if not c: fails.append(n)

check("none is insufficient", P.evidence(0)["level"] == "insufficient")
check("below the minimum is insufficient", P.evidence(P.MIN_TRADES - 1)["level"] == "insufficient")
check("insufficient says the sentence", P.evidence(1)["text"] == "Not enough evidence to judge this strategy.")
check("at the minimum is early", P.evidence(P.MIN_TRADES)["level"] == "early")
check("early mentions luck", "luck" in P.evidence(10)["text"])
check("30 is readable", P.evidence(30)["level"] == "readable")
check("readable carries the caveat", "do not predict" in P.evidence(100)["text"])
for bad in (None, "5", True, 2.5):
    check(f"junk {bad!r} is insufficient", P.evidence(bad)["level"] == "insufficient")
for n in (0, 5, 50):
    t = P.evidence(n)["text"].lower()
    check(f"no praise at {n}", not any(w in t for w in ("good", "profitable", "great", "winning")))
print("\nFAILED: " + ", ".join(fails) if fails else "\nALL OK")
sys.exit(1 if fails else 0)
