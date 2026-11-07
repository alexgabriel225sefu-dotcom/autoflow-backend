"""Stop must be true wherever the loop runs — not only in the process that heard it.

FOUND BY AN INDEPENDENT REVIEW (HIGH). During a deploy both containers serve
HTTP. A client presses Stop; the request lands on container B while the trading
loop runs in container A. `user_loop.stop` on B finds no loop, returns False,
and the platform still recorded STOPPED and answered "Automation is stopped."
A never looked at the record, so it kept opening positions until it was killed
— and a second press answered "already stopped".

WHAT THESE TESTS WILL NOT ACCEPT

* A loop that keeps ticking after the shared record says `active: False`.
* A loop standing itself down because the store was unreadable, or because the
  flag was merely absent.
* "stopped" with no word of caution when no loop was stopped in this process.
* A lease that stays held by a loop that has just stood down.
* A trade permitted once the process has begun shutting down.

Run: python3 tests/test_stop_reaches_other_containers.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-stopx-")
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


from apex import ownership, user_loop, user_store            # noqa: E402
from apex.platform import automation as AU                  # noqa: E402

# ── 1. the loop honours a stop recorded elsewhere ───────────────────────────
print("\n[1] the loop reads the shared stop")
_real_load = user_store.load
try:
    user_store.load = lambda uid: {"active": False}
    check("an explicit active:False is a stop request", user_loop._stop_requested("u") is True)
    user_store.load = lambda uid: {"active": True}
    check("active:True is not", user_loop._stop_requested("u") is False)
    user_store.load = lambda uid: {}
    check("an ABSENT flag is not (a record that never recorded one)", user_loop._stop_requested("u") is False)
    user_store.load = lambda uid: None
    check("a missing record is not", user_loop._stop_requested("u") is False)

    def _boom(uid):
        raise RuntimeError("redis down")
    user_store.load = _boom
    check("an unreadable store is not — a hiccup must not stop a trading loop",
          user_loop._stop_requested("u") is False)
finally:
    user_store.load = _real_load

# ── 2. it is wired into the loop, before any trading, and cleans up ─────────
print("\n[2] the check is in the tick, ahead of the work, and hands the lease back")
src = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
loop = src.split("def _loop(", 1)[1].split("\ndef ", 1)[0]
i_stop = loop.index("_stop_requested(user_id)")
i_work = loop.index("forex.is_market_open()")
check("it is an unconditional `if _stop_requested(user_id):` (not disabled by a prefix)",
      "\n        if _stop_requested(user_id):\n" in loop)
check("it runs before the market check and any order", i_stop < i_work)
block = loop[i_stop:i_work]
check("the loop marks itself not running", '_loops[user_id]["running"] = False' in block)
check("it stops its renewer and releases the lease", "ownership.stop_renewer" in block and "ownership.release" in block)
check("and leaves the while loop", "break" in block)

# ── 3. Stop says so when it stopped nothing here ────────────────────────────
print("\n[3] a stop that stopped nothing in this process says so")
writes = []
_real = (AU._read, AU._write, AU._jstore.record_automation, AU._notify.notify, user_store.update)
try:
    AU._read = lambda uid: {"state": AU.RUNNING, "ruleDocId": "r1", "accountId": 1}
    AU._write = lambda uid, rec: writes.append(rec)
    AU._jstore.record_automation = lambda *a, **k: None
    AU._notify.notify = lambda *a, **k: None
    user_store.update = lambda uid, patch, *a, **k: writes.append(("update", patch))

    out = AU.stop("u", stopper=lambda uid: False)
    check("loopStoppedHere is False", out.get("loopStoppedHere") is False, str(out.get("loopStoppedHere")))
    check("it carries a note about another instance",
          "another instance" in (out.get("stopNote") or ""), str(out.get("stopNote")))
    check("the shared record still says active:False (that is what the other container reads)",
          ("update", {"active": False}) in writes, str(writes))

    out = AU.stop("u", stopper=lambda uid: True)
    check("when a loop here WAS stopped there is no caution", out.get("loopStoppedHere") is True and "stopNote" not in out)
finally:
    AU._read, AU._write, AU._jstore.record_automation, AU._notify.notify, user_store.update = _real

# ── 4. no trade once shutdown began ─────────────────────────────────────────
print("\n[4] may_trade refuses while the process is shutting down")
_orig_redis = user_store._USE_REDIS
try:
    user_store._USE_REDIS = True
    ownership._shutdown.clear()
    ownership._shutdown.set()
    check("demo too: SHUTTING_DOWN, not OWNERSHIP_UNKNOWN_DEMO",
          ownership.may_trade("u", live=False) == (False, "SHUTTING_DOWN"), str(ownership.may_trade("u", live=False)))
    check("live too", ownership.may_trade("u", live=True) == (False, "SHUTTING_DOWN"))
finally:
    ownership._shutdown.clear()
    user_store._USE_REDIS = _orig_redis

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All stop-propagation checks passed.")
