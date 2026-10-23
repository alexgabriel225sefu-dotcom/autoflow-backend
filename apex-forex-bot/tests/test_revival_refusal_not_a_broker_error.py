"""A restart's lease handover must not be filed as a "Broker error".

SEEN ON THE OWNER'S PHONE, 22 Oct 2026, right after a deploy: the journal
showed four "Broker error — the engine refused to start this loop" entries,
three minutes apart. Nothing was wrong with the broker. The previous instance
still held the loop's lease (it lasts ten minutes), the supervisor retried
every three, and each refused retry was journalled as a broker error.

An interactive Start the client pressed is different and must still be
journalled: they asked, so the refusal is theirs to see.

Run: python3 tests/test_revival_refusal_not_a_broker_error.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-revive-")
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

filed = []
_real = AU._jstore.record_error
AU._jstore.record_error = lambda msg, **kw: filed.append((msg, kw))
try:
    print("\n[1] the supervisor's retry is not a journal error")
    AU._note_engine_refused("u1", "c1", 501, revive=True)
    check("nothing is filed for a revival", filed == [], str(filed))

    print("\n[2] a Start the client pressed still is")
    AU._note_engine_refused("u1", "c2", 501, revive=False)
    check("one entry is filed", len(filed) == 1, str(filed))
    check("with the user and account",
          filed and filed[0][1]["user_id"] == "u1"
          and filed[0][1]["account_id"] == "501", str(filed))
finally:
    AU._jstore.record_error = _real

print("\n[3] start() really routes through it, and passes `revive`")
src = open(os.path.join(ROOT, "apex", "platform", "automation.py")).read()
body = src.split("def start(", 1)[1].split("\ndef ", 1)[0]
check("start calls the helper with revive=revive",
      "_note_engine_refused(user_id, corr, conn.get(\"ctid\"), revive=revive)" in body)
check("and no longer writes the error inline",
      "_jstore.record_error(" not in body)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All revival-journal checks passed.")
