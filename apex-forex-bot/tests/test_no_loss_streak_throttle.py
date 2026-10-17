"""A run of losses no longer shrinks positions or halts entries.

Two separate mechanisms were removed at the owner's instruction, after both
fired on his demo account and left it opening quarter-size positions that
returned two or three dollars on winning trades:

  RISK LADDER   — 2 losses in a row halved position size, 3 or more quartered
                  it (user_loop, at sizing time).
  STAND-ASIDE   — 3 losses in a row stopped entries on that instrument for an
                  hour (strategies.should_stop).

Both had a real argument behind them. After a run of losses you are either in
a market the strategy does not suit or you are about to revenge-trade, and
both are cheaper at quarter size. The stand-aside also had history: an earlier
version cleared only on a WIN, which deadlocked an account for 37 hours,
because the bot cannot win a trade it is forbidden from entering.

The argument against is the owner's to weigh, and he weighed it: they cut
hardest exactly when the account is already down, so recovery is slowest at
the worst moment — and a streak counted off a mis-journaled close shrinks
real trades for a reason that never happened.

WHAT MUST NOT HAVE GONE WITH THEM is the point of this file. The daily loss
limit and the drawdown-from-peak limit are about how much money is gone,
which is the question that matters; the streak was a proxy for it. Removing
the proxy must not have loosened the real ones.

Run: python tests/test_no_loss_streak_throttle.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-nostreak-")

from apex import strategies  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


def fresh(user="u1"):
    strategies.SESSIONS.pop(user, None) if hasattr(strategies, "SESSIONS") else None
    s = strategies.get_session(user)
    s.update({"consecutiveLosses": 0, "consecutiveWins": 0, "dailyTrades": 0,
              "dailyPnL": 0.0, "peakBalance": None, "lastLossAt": None})
    return s


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOP = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
STRAT = open(os.path.join(ROOT, "apex", "strategies.py"), encoding="utf-8").read()

print("\n📉 LOSS STREAKS NO LONGER THROTTLE\n")

print("1. The risk ladder is gone from sizing")
check("no 3-loss quarter-size cut", "loss_streak >= 3" not in LOOP)
check("no 2-loss half-size cut", "loss_streak == 2" not in LOOP)
check("and no multiplier is applied from it",
      "risk_mult *= 0.25" not in LOOP, "0.25 was the quarter-size cut")

print("\n2. …but the cut that reads the MARKET stays")
check("a volatile regime still halves size", "risk_mult *= 0.5" in LOOP,
      "this one looks at the market in front of it, not the last three results")

print("\n3. A streak no longer halts entries")
for streak in (3, 5, 12):
    s = fresh()
    s["consecutiveLosses"] = streak
    s["lastLossAt"] = time.time()
    r = strategies.should_stop(1000, 1000, user_id="u1")
    check(f"{streak} losses in a row → no stop", r["stop"] is False, r)

s = fresh()
s["consecutiveLosses"] = 4
r = strategies.should_stop(1000, 1000, user_id="u1")
check("and no Seykota wording survives anywhere in the reasons",
      not any("Seykota" in x or "consecutive" in x for x in r["reasons"]), r)
# Scoped to the MACHINERY, not to the words. "standing aside" also appears in
# the quiet-regime label, which is a different feature — matching on prose is
# how a check like this quietly starts passing or failing on the wrong thing.
check("the cooldown constant is gone", "_SEYKOTA_COOLDOWN_MIN" not in STRAT)
check("and its parameter with it", "seykota_cooldown_min" not in STRAT)
check("should_stop no longer takes a cooldown",
      "seykota" not in strategies.should_stop.__code__.co_varnames)

print("\n4. The streak is still COUNTED — the bot must know what happened")
s = fresh()
s["consecutiveLosses"] = 7
strategies.should_stop(1000, 1000, user_id="u1")
check("the counter is untouched by the check",
      strategies.get_session("u1")["consecutiveLosses"] == 7,
      "the journal and dashboard read this")

print("\n5. What actually protects the account still bites")
s = fresh()
s["consecutiveLosses"] = 9          # a long streak must not excuse anything
s["dailyPnL"] = -50.0
r = strategies.should_stop(950, 1000, user_id="u1", max_daily_loss_pct=3.0)
check("the daily loss limit still stops", r["stop"], r)
check("and says so in money, not in results",
      any("Daily loss" in x for x in r["reasons"]), r)

s = fresh()
strategies.should_stop(1000, 1000, user_id="u1")     # sets the peak
r = strategies.should_stop(750, 1000, user_id="u1", max_dd_pct=20.0)
check("drawdown from peak still stops", r["stop"], r)
check("named as capital protection",
      any("Drawdown" in x for x in r["reasons"]), r)

s = fresh()
r = strategies.should_stop(0.5, 1000, user_id="u1")
check("an empty account still cannot trade", r["stop"], r)

print("\n6. A clean account is not stopped by any of this")
fresh()
r = strategies.should_stop(1000, 1000, user_id="u1")
check("no reasons at all", r["stop"] is False and not r["reasons"], r)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — streaks inform, money decides.")
