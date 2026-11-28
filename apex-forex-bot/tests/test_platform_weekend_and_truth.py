"""The automation chip tells the truth, and the weekend does not trade.

A stored RUNNING is not a running loop. A licence that is not active
(operators still read as active) is blocked, and the supervisor corrects
the record without starting a loop. Forex is shut from Friday 22:00 UTC
until Sunday 22:00 UTC; that window is idle, not an error.

Run: python3 tests/test_platform_weekend_and_truth.py
"""
import os
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-truth-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "test"
os.environ["PRODUCT"] = "forex"
os.environ.pop("A4T_OPERATOR_USER_IDS", None)

from apex.platform import automation as A          # noqa: E402
from apex.platform import licence as L             # noqa: E402
from apex.platform import live_gate as LG          # noqa: E402
from apex.platform import plans as P               # noqa: E402
from apex.platform import weekend as W             # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name} {detail}")


def at(y, m, d, h):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


print("\n[1] the weekend window is Friday 22:00 UTC to Sunday 22:00 UTC")
# 2026-08-14 is a Friday, 15 Saturday, 16 Sunday.
check("Friday 21:59 is still open", not W.weekend_closed(at(2026, 8, 14, 21)))
check("Friday 22:00 is closed", W.weekend_closed(at(2026, 8, 14, 22)))
check("Saturday is closed", W.weekend_closed(at(2026, 8, 15, 12)))
check("Sunday 21:59 is closed", W.weekend_closed(at(2026, 8, 16, 21)))
check("Sunday 22:00 has reopened", not W.weekend_closed(at(2026, 8, 16, 22)))
check("Monday is open", not W.weekend_closed(at(2026, 8, 17, 9)))
banner = W.weekend_status(at(2026, 8, 15, 12))
check("the sentence is the one the dashboard shows",
      banner["closed"] is True and banner["message"] == W.CLOSED_MESSAGE
      and banner["message"] == "Market closed (weekend), reopens Sun 22:00 UTC",
      str(banner))
check("an open hour has no sentence",
      W.weekend_status(at(2026, 8, 17, 9))["message"] is None)

print("\n[2] a stale RUNNING is not what the chip says")
USER = "truth-client"
OP = "truth-operator"
NOW = 1_700_000_000.0
L.grant(USER, plan=P.DEMO_TRIAL, expires_at=NOW - 10, now=NOW - 100)
L.grant(OP, plan=P.DEMO_TRIAL, expires_at=NOW - 10, now=NOW - 100)
os.environ[LG.OPERATOR_ENV] = OP
A._write(USER, {"state": A.RUNNING, "ruleDocId": "rule-1", "userId": USER})
A._write(OP, {"state": A.RUNNING, "ruleDocId": "rule-1", "userId": OP})

_alive = A._loop_alive
try:
    A._loop_alive = lambda uid: True
    shown = A.status(USER, weekend_reader=lambda: False)
    check("an expired licence is blocked, not running",
          shown["state"] == A.BLOCKED and shown["blockReason"]
          and "licence" in shown["blockReason"], str(shown.get("state")))
    op = A.status(OP, weekend_reader=lambda: False)
    check("an operator with the same record is running",
          op["state"] == A.RUNNING, str(op.get("state")))
    A._loop_alive = lambda uid: False
    down = A.status(OP, weekend_reader=lambda: False)
    check("a dead loop is stopped even for an operator",
          down["state"] == A.STOPPED and down["blockReason"] == A.LOOP_DOWN_REASON,
          str(down))
finally:
    A._loop_alive = _alive

print("\n[3] the supervisor corrects the record and does not start a loop")
from apex import user_loop, user_store                 # noqa: E402
from apex.platform import ctrader_link as CL           # noqa: E402

started = []
stopped = []
_all = user_store.all_active
_plat = CL.is_platform_account
_run = user_loop.is_running
_stop = user_loop.stop
_start = A.start
try:
    user_store.all_active = lambda: [USER]
    CL.is_platform_account = lambda uid: True
    user_loop.is_running = lambda uid: True
    user_loop.stop = lambda uid: stopped.append(uid) or True
    A.start = lambda *a, **k: started.append(a) or None
    alive, revived = A.supervise()
finally:
    user_store.all_active = _all
    CL.is_platform_account = _plat
    user_loop.is_running = _run
    user_loop.stop = _stop
    A.start = _start

check("nothing was started", started == [] and revived == 0, str(started))
check("the live loop was stopped", stopped == [USER], str(stopped))
stored = A._read(USER)
check("the record is blocked", stored.get("state") == A.BLOCKED, str(stored.get("state")))
check("and the supervisor did not count it as alive", alive == 0)

print("\n[4] the order loop waits through the weekend and a lapsed licence")
src = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
check("a closed weekend skips the tick",
      "_weekend_orders_paused()" in src and "time.sleep(60)" in src)
check("an unlicensed platform account skips the tick",
      "_platform_unlicensed(user_id)" in src)
# The helpers themselves do not raise and do not place.
check("the weekend helper pauses orders inside the window",
      W.weekend_closed(at(2026, 8, 15, 3)) is True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}): {_fails}")
    sys.exit(1)
print("All weekend and truth checks passed.")
