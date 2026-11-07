"""Tags and a comment on a journal entry, kept beside it and never in it.

WHAT THESE TESTS WILL NOT ACCEPT

* A note on someone else's entry, or on one that does not exist.
* A note that changes the recorded entry.
* Unbounded tags or comment, or a tag with markup characters.
* An empty note being stored as a record.

Run: python3 tests/test_journal_notes.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-jnotes-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
from apex.platform import journal as J            # noqa: E402
from apex.platform import journal_notes as N      # noqa: E402
from apex.platform import journal_store as JS     # noqa: E402

fails = []
def check(n, c, d=""):
    print(f"  {'ok  ' if c else 'FAIL'} {n}" + (f"  {d}" if d and not c else ""))
    if not c: fails.append(n)

e = J.error_entry("boom", correlation_id="c1", user_id="u1") if hasattr(J, "error_entry") else None
if e is None:
    e = J.JournalEntry(kind="error", correlation_id="c1", user_id="u1", error="boom")
JS.append(e)
before = JS.get("u1", e.entry_id)

check("no note yet", N.get("u1", e.entry_id) is None)
n = N.put("u1", e.entry_id, ["review", " Review ", "late entry"], "  too early  ")
check("tags de-duplicated, comment trimmed", n["tags"] == ["review", "late entry"] and n["comment"] == "too early", n)
check("note read back", N.get("u1", e.entry_id)["tags"] == ["review", "late entry"])
check("entry itself unchanged", JS.get("u1", e.entry_id) == before)

for bad, why in [((["<b>"], ""), "markup tag"), (([f"t{i}" for i in range(9)], ""), "too many"),
                 (([], "y" * 2001), "long comment"), (("a", ""), "tags not a list")]:
    try:
        N.put("u1", e.entry_id, *bad); check(f"refuses {why}", False)
    except N.NoteInvalid:
        check(f"refuses {why}", True)

try:
    N.put("u2", e.entry_id, ["x"], ""); check("another owner refused", False)
except JS.JournalNotFound:
    check("another owner refused", True)
try:
    N.put("u1", "missing", ["x"], ""); check("missing entry refused", False)
except JS.JournalNotFound:
    check("missing entry refused", True)

check("empty note removes the record", N.put("u1", e.entry_id, [], "") is None and N.get("u1", e.entry_id) is None)
print("\nFAILED: " + ", ".join(fails) if fails else "\nALL OK")
sys.exit(1 if fails else 0)
