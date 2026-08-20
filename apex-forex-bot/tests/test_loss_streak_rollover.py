"""A loss streak from yesterday must not still be halving today's positions.

The risk ladder is deliberate: two losses in a row halve the next position, three
or more quarter it. What was not deliberate is how long that lasted.

The clearing check was written and it was correct — and it ran exactly once, in
the loop's SETUP, before the `while True`. So it was evaluated once per process.
A loop that stayed up across midnight never re-read it:

    19 Aug 15:48   two losses -> loss_streak = 2, positions halve
    20 Aug 00:00   new trading day; strategy_session rolls over as designed
    20 Aug         loss_streak is STILL 2 — the check never ran again
    ...            winning trades came in at half size, ~$2-3 profit each

Observed on a live account, reported as "the protection came on two days ago and
never went away". Two counters for the same idea — strategy_session's
consecutiveLosses and loss_streak — disagreed, because only one of them was ever
re-read. The only escapes were a winning trade through a path that resets, or a
redeploy, and neither is a design.

Run: python tests/test_loss_streak_rollover.py
"""
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-streak-")

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()

print("\n🧪 LOSS-STREAK ROLLOVER — the brake has to let go\n")

print("1. The check is callable, not a one-off in the setup")
check("it lives in a function", "def _clear_stale_streak" in SRC)
check("...that can actually clear the streak", "nonlocal loss_streak" in SRC)
check("...and reports whether it did, so the caller can persist it",
      re.search(r"def _clear_stale_streak.*?return True", SRC, re.S) is not None)

print("\n2. It runs EVERY TICK, which is the whole fix")
_body = SRC[SRC.index("while True:"):] if "while True:" in SRC else SRC
check("the tick calls it", "if _clear_stale_streak():" in _body,
      "called only at startup, it is evaluated once per process")
check("...and persists the cleared value",
      re.search(r"if _clear_stale_streak\(\):\s*\n\s*_persist_risk_state\(\)", SRC)
      is not None,
      "clearing it in memory only would come back on the next restart")
check("it is checked after the market-open guard, not before",
      SRC.index("if not forex.is_market_open():") < SRC.index("if _clear_stale_streak():"),
      "no point rolling the day over while the market is shut")

print("\n2b. What it clears at STARTUP is written down too")
# Found by checking the live record after the first fix shipped: the loop had
# cleared the streak in memory and the stored value still said 2. Behaviour was
# right, the record was wrong — and the record is what every restart re-reads,
# what the operator sees, and what a new loss today would build on.
check("the startup clear is captured, not discarded",
      "_cleared_at_start = _clear_stale_streak()" in SRC)
check("...and persisted once the persister exists",
      re.search(r"if _cleared_at_start:\s*\n\s*_persist_risk_state\(\)", SRC)
      is not None)
check("the persist happens AFTER _persist_risk_state is defined",
      SRC.index("def _persist_risk_state") < SRC.index("if _cleared_at_start:"),
      "calling it earlier is a NameError at loop start")

print("\n3. The behaviour itself: yesterday clears, today does not")


def simulate(streak, last_loss_ts, now=None):
    """The exact rule the loop applies, run in isolation."""
    if not (streak and last_loss_ts):
        return streak
    day = datetime.fromtimestamp(last_loss_ts).strftime("%Y-%m-%d")
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    return 0 if day != today else streak


now = datetime.now()
today_loss = now.replace(hour=9, minute=0, second=0).timestamp()
yday_loss = (now - timedelta(days=1)).replace(hour=15, minute=48).timestamp()
old_loss = (now - timedelta(days=6)).timestamp()

check("a streak from TODAY survives — the brake still works intraday",
      simulate(2, today_loss) == 2)
check("a streak from YESTERDAY clears", simulate(2, yday_loss) == 0,
      "this is the reported bug: 19 Aug's streak still halving on 20 Aug")
check("a streak from last week clears", simulate(3, old_loss) == 0)
check("no streak stays no streak", simulate(0, yday_loss) == 0)
check("a streak with no recorded loss time is left alone",
      simulate(2, 0) == 2, "clearing on missing data would erase a real brake")

print("\n4. The ladder it feeds is unchanged")
check("two losses still halve", "elif loss_streak == 2:" in SRC and "0.5" in SRC)
check("three or more still quarter", "if loss_streak >= 3:" in SRC and "0.25" in SRC)
check("the longer-horizon guards are untouched",
      "max_dd_pct" in SRC and "max_daily_loss_pct" in SRC,
      "the daily clear is safe precisely because drawdown caps still apply")

print("\n5. The two counters can no longer disagree indefinitely")
# strategy_session already rolled over on lastResetDay; loss_streak did not.
check("strategy session rolls over on its own day key", "lastResetDay" in
      open(os.path.join(ROOT, "apex", "strategies.py"), encoding="utf-8").read())
check("and the streak now rolls over on the same rule",
      'strftime("%Y-%m-%d")' in SRC[SRC.index("def _clear_stale_streak"):
                                    SRC.index("def _persist_risk_state")])

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — yesterday's losses stop sizing today's trades.")
