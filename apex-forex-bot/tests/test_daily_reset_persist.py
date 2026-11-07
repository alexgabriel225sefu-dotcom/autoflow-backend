"""The daily trade counter must reset before anything reads or persists it —
not just eventually, and not only when should_stop() happens to run first.

Reported symptom: strategy_session showed lastResetDay: "2026-09-04" while the
bot was already on 09-07 and had opened positions on 09-06, with dailyTrades: 5
already past max_trades_day: 4 — yet entries kept going through.

Root cause: `_reset_daily_if_needed()` (called inside `should_stop()`) rolls
the in-memory session over correctly every tick, but never persists that
roll-over. Only `record_trade()` persists the session, and only as a side
effect of recording a trade. Several `record_trade()` call sites in the tick
loop (apex/user_loop.py:1880, 2249, 2761, 2825, 3043, 3272) run BEFORE
`should_stop()` (apex/user_loop.py:3493) in the same tick — closes are
processed early, the risk check runs later. On the first tick after a
restart, if a stale position closes before `should_stop()` gets a chance to
roll the day over, `record_trade()` increments and persists *yesterday's*
count instead of starting the new day at 1 — exactly the "dailyTrades: 5,
lastResetDay: three days ago" snapshot that was observed.

The entry gate in `user_loop.py` (apex/user_loop.py:3788) reads `dailyTrades`
straight off the shared session with no reset of its own, so whichever count
is on disk when a restart reloads it is the one the cap trusts.

Run: python tests/test_daily_reset_persist.py
"""
import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-dailyreset-")

from apex import strategies  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


STALE_DAY = (date.today() - timedelta(days=3)).isoformat()
TODAY = date.today().isoformat()


def seed_stale_session(user_id, daily_trades):
    """Persist a session stuck on an old day — how a real account looks after
    restarts with no trade closing in between to carry the reset along."""
    strategies._sessions.pop(user_id, None)
    s = strategies.get_session(user_id)
    s["lastResetDay"] = STALE_DAY
    s["dailyTrades"] = daily_trades
    s["dailyPnL"] = -12.0
    strategies._persist_session(user_id)
    strategies._sessions.pop(user_id, None)  # next get_session() must reload from disk


print("\n🧪 DAILY COUNTER RESET — must not survive as a stale, unpersisted artefact\n")

print("1. A trade closing before should_stop() runs this tick must not stack onto a stale count")
seed_stale_session("u_early_close", daily_trades=4)  # already at the cap, from 3 days ago
# The buggy order: record_trade() fires first in the tick (closes at
# user_loop.py:1880/2249/2761/2825/3043/3272 all run before should_stop() at 3493).
strategies.record_trade(True, 10, 1000, user_id="u_early_close")
s = strategies.get_session("u_early_close")
check("the new day starts the count at 1, not 5",
      s["dailyTrades"] == 1, s["dailyTrades"])
check("lastResetDay rolled to today",
      s["lastResetDay"] == TODAY, s["lastResetDay"])

print("\n2. should_stop()'s reset is not just in memory — it survives a restart")
seed_stale_session("u_restart", daily_trades=4)
strategies.should_stop(1000, 1000, user_id="u_restart")  # only the risk check runs, no trade closes
s = strategies.get_session("u_restart")
check("in-memory reset happens immediately",
      s["dailyTrades"] == 0 and s["lastResetDay"] == TODAY, s)
# Simulate the process restarting: the in-memory cache is gone, only what was
# actually written to disk survives.
strategies._sessions.pop("u_restart", None)
reloaded = strategies.get_session("u_restart")
check("...and the reset was written to disk, not lost on restart",
      reloaded["dailyTrades"] == 0, reloaded["dailyTrades"])
check("...same for lastResetDay",
      reloaded["lastResetDay"] == TODAY, reloaded["lastResetDay"])

print("\n3. A dashboard/report reading the session right after a restart must not see a stale count")
# apex/bot.py:1681 reads dailyTrades straight off the session for /report and
# the dashboard, with no reset of its own — same trust the entry gate places.
seed_stale_session("u_cap_check", daily_trades=4)
strategies._sessions.pop("u_cap_check", None)
fresh = strategies.get_session("u_cap_check")   # first read after a restart, before any tick runs
check("a freshly-loaded session already reads the new day's count",
      fresh["dailyTrades"] == 0,
      "if this is 4, the client's dashboard shows yesterday's trade count as today's")

print("\n4. Order no longer matters — should_stop() first still works as before")
seed_stale_session("u_normal_order", daily_trades=4)
strategies.should_stop(1000, 1000, user_id="u_normal_order")
strategies.record_trade(True, 5, 1000, user_id="u_normal_order")
s = strategies.get_session("u_normal_order")
check("counts exactly the one trade of the new day",
      s["dailyTrades"] == 1, s["dailyTrades"])

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the daily counter resets once and it sticks.")
