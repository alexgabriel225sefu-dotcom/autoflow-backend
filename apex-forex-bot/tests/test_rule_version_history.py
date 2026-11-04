"""Rule version history: compare two versions, list them, go back to one.

WHAT THESE TESTS WILL NOT ACCEPT

* A diff that reports bookkeeping (version, state, timestamps) as a change.
* A diff that misses a changed, added or removed term, or a nested one.
* Reverting that rewrites the frozen version or the running one.
* Reverting that makes the result anything but an editable DRAFT.
* Listing versions that were never stored.

Run: python3 tests/test_rule_version_history.py
"""
import copy
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-verhist-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

from apex.platform import ruledoc as RD            # noqa: E402
from apex.platform import store as S               # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


USER = "u-1111"
doc = RD.blank(user_id=USER, account_id="1", symbols=["EURUSD"], timeframe="1h")
doc["name"] = "Trend"
doc["conditions"] = [{"id": "rsi", "params": {"period": 14}}]

# ── diff ────────────────────────────────────────────────────────────────────
print("[1] diff")
b = copy.deepcopy(doc)
b["version"], b["state"], b["updatedAt"] = 2, "active", 99
check("bookkeeping alone is no change", RD.diff(doc, b) == [])
b["name"] = "Trend v2"
b["conditions"][0]["params"]["period"] = 21
b["conditions"].append({"id": "ema", "params": {}})
del b["timeframe"]
ch = {c["path"]: c for c in RD.diff(doc, b)}
check("a changed term", ch["name"]["kind"] == "changed"
      and ch["name"]["before"] == "Trend" and ch["name"]["after"] == "Trend v2")
check("a nested change", ch["conditions[0].params.period"]["after"] == 21)
check("an added list item", ch["conditions[1]"]["kind"] == "added")
check("a removed term", ch["timeframe"]["kind"] == "removed")
check("inputs untouched", doc["name"] == "Trend" and len(doc["conditions"]) == 1)

# ── versions and revert ─────────────────────────────────────────────────────
print("[2] versions and revert")
S.create(USER, doc)
rid = doc["ruleDocId"]
frozen1 = copy.deepcopy(doc)
frozen1["state"] = "active"
frozen1["activatedAt"] = 1.0
S._write(S._k_version(USER, rid, 1), frozen1)
cur = copy.deepcopy(frozen1)
cur["version"], cur["name"] = 2, "Trend v2"
cur["conditions"][0]["params"]["period"] = 21
S._write(S._k_version(USER, rid, 2), cur)
S._write(S._k_current(USER, rid), cur)

vs = S.versions(USER, rid)
check("both stored versions listed, newest first", [v["version"] for v in vs] == [2, 1], vs)
check("no invented version", all(v["version"] in (1, 2) for v in vs))

out = S.revert_to_version(USER, rid, 1, now=5.0)
check("revert makes a DRAFT", out["state"] == "draft")
check("revert starts a new version", out["version"] == 3, out["version"])
check("revert carries the old terms", out["name"] == "Trend"
      and out["conditions"][0]["params"]["period"] == 14)
check("same id and owner", out["ruleDocId"] == rid and out["userId"] == USER)
check("frozen v1 untouched", S.get_version(USER, rid, 1)["name"] == "Trend")
check("frozen v2 untouched", S.get_version(USER, rid, 2)["name"] == "Trend v2")

again = S.revert_to_version(USER, rid, 2, now=6.0)
check("reverting a draft replaces its terms, same version",
      again["version"] == 3 and again["name"] == "Trend v2")

try:
    S.revert_to_version(USER, rid, 9)
    check("an unknown version is refused", False)
except S.NotFound:
    check("an unknown version is refused", True)
try:
    S.revert_to_version("someone-else", rid, 1)
    check("another owner cannot revert", False)
except S.NotFound:
    check("another owner cannot revert", True)

print("\nFAILED: " + ", ".join(fails) if fails else "\nALL OK")
sys.exit(1 if fails else 0)
