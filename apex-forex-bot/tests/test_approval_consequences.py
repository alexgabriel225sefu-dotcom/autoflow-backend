"""A pending approval says what approving and ignoring each do.

WHAT THESE TESTS WILL NOT ACCEPT

* Wording that promises an open position (approving asks the engine to try).
* Wording that omits the expiry window from the "do nothing" answer.
* Consequences that name a different symbol or side than the proposal.

Run: python3 tests/test_approval_consequences.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-appc-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
from apex.platform import approvals as A   # noqa: E402

fails = []
def check(n, c, d=""):
    print(f"  {'ok  ' if c else 'FAIL'} {n}" + (f"  {d}" if d and not c else ""))
    if not c: fails.append(n)

A._record = lambda uid: {"active": True, "pending_suggestion": "sig"}
A._parse = lambda p: ("GBPUSD", "SELL", 1000.0)
A._detail_for = lambda uid, ts: {}
out = A.pending("u1", now=1030.0)["approval"]
check("approve text names the proposal", "SELL" in out["ifApprove"] and "GBPUSD" in out["ifApprove"], out["ifApprove"])
check("approve text does not guarantee a position", "can still refuse" in out["ifApprove"])
check("ignore text states the expiry", "5 minutes" in out["ifIgnore"] and "Nothing opens" in out["ifIgnore"])
print("\nFAILED: " + ", ".join(fails) if fails else "\nALL OK")
sys.exit(1 if fails else 0)
