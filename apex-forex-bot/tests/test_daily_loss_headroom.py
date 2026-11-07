"""The minimum-lot ceiling is what is LEFT of the daily-loss limit.

Observed on 2026-10-28: a $3,817 account with a 3% daily stop ($114.52) took a
1 oz gold trade that lost $84.20, then a second that lost $103.92, because the
ceiling handed to floor_risk_ok was the whole $114.52 each time and each trade
on its own was under it. The day ended at -$188.12, 4.9% against a 3% stop.

Run: python tests/test_daily_loss_headroom.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ["PAPER_TRADING"] = "true"

from apex import forex  # noqa: E402


def check(label, condition, detail=""):
    print(f"  {'✅' if condition else '❌'} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0

BAL, LIMIT = 3817.21, 3.0
PRICE = 4040.0
PV = forex.pip_value_per_unit("XAUUSD", PRICE)
TARGET = BAL * 0.01  # the 1% the client chose

print("\n1. the headroom")
check("a fresh day has the whole limit",
      abs(forex.daily_loss_headroom_usd(BAL, LIMIT, 0.0) - BAL * 0.03) < 1e-9)
check("a loss uses it up",
      abs(forex.daily_loss_headroom_usd(BAL, LIMIT, -84.2) - (BAL * 0.03 - 84.2)) < 1e-9)
check("a gain extends it, as the stop itself counts the day net",
      forex.daily_loss_headroom_usd(BAL, LIMIT, 50.0) > BAL * 0.03)
check("it is never negative", forex.daily_loss_headroom_usd(BAL, LIMIT, -500.0) == 0.0)
check("no balance or no limit means none",
      forex.daily_loss_headroom_usd(0, LIMIT, 0) == 0.0
      and forex.daily_loss_headroom_usd(BAL, 0, 0) == 0.0)

print("\n2. the 28 October trades, replayed")
stop_pips = 84.2 / PV   # a stop that costs 1 oz $84.20, as the first trade did
first = forex.daily_loss_headroom_usd(BAL, LIMIT, 0.0)
check("trade 1 (risks about $84) is allowed on a fresh day",
      forex.floor_risk_ok(1, "XAUUSD", PRICE, stop_pips, TARGET, hard_ceiling_usd=first))
after_loss = forex.daily_loss_headroom_usd(BAL, LIMIT, -84.2)
stop_pips_2 = 103.9 / PV
check("trade 2 (risks about $104) is refused once $84 is gone",
      not forex.floor_risk_ok(1, "XAUUSD", PRICE, stop_pips_2, TARGET,
                              hard_ceiling_usd=after_loss),
      f"left=${after_loss:.2f}")
check("the same trade WAS allowed against the whole limit (the bug)",
      forex.floor_risk_ok(1, "XAUUSD", PRICE, stop_pips_2, TARGET,
                          hard_ceiling_usd=BAL * 0.03))

print("\n3. a trade inside the 10% tolerance of the target needs no headroom")
check("a normal-size trade is not blocked by an empty day budget",
      forex.floor_risk_ok(1, "XAUUSD", PRICE, (TARGET / PV) * 1.05, TARGET,
                          hard_ceiling_usd=0.0))

print()
if check.failed:
    print(f"❌ {check.failed} check(s) failed")
    sys.exit(1)
print("✅ ALL CHECKS PASSED")
