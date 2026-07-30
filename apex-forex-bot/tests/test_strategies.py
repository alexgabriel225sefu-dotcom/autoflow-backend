"""Unit tests for the strategy engine and risk-management rules.

Run: python tests/test_strategies.py
"""
import os
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import strategies  # noqa: E402


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0


def make_candles(closes):
    return [{"time": i, "open": c * 0.999, "high": c * 1.005,
             "low": c * 0.995, "close": c, "volume": 1000}
            for i, c in enumerate(closes)]


def fresh_session():
    strategies.session.update({
        "consecutiveLosses": 0, "consecutiveWins": 0, "dailyTrades": 0,
        "dailyPnL": 0.0, "dailyPnLPct": 0.0,
        "lastResetDay": date.today().isoformat(),
        "peakBalance": None, "totalTrades": 0,
    })


# ─── Turtle breakout ──────────────────────────────────────
print("\n🧪 STRATEGY ENGINE TESTS\n")
print("1. Turtle breakout")
flat = [100.0] * 21
t = strategies.turtle_breakout(make_candles(flat + [108.0]))
check("close above 20-high → BUY", t["signal"] == "BUY", t)
t = strategies.turtle_breakout(make_candles(flat + [92.0]))
check("close below 20-low → SELL", t["signal"] == "SELL", t)
t = strategies.turtle_breakout(make_candles(flat + [100.0]))
check("inside range → no signal", t["signal"] is None, t)
t = strategies.turtle_breakout(make_candles([100.0] * 5))
check("too little data → no signal", t["signal"] is None and t["breakoutStr"] == "NONE", t)

print("\n2. Livermore structure")
lv = strategies.livermore_structure(make_candles([100 + i * 2 for i in range(12)]))
check("HH+HL → BULLISH 0.85", lv["trend"] == "BULLISH" and lv["strength"] == 0.85, lv)
lv = strategies.livermore_structure(make_candles([124 - i * 2 for i in range(12)]))
check("LH+LL → BEARISH 0.85", lv["trend"] == "BEARISH" and lv["strength"] == 0.85, lv)
lv = strategies.livermore_structure(make_candles([100, 101] * 6))
check("mixed → NEUTRAL", lv["trend"] == "NEUTRAL", lv)
lv = strategies.livermore_structure(make_candles([100] * 5))
check("too little data → NEUTRAL", lv["trend"] == "NEUTRAL" and lv["strength"] == 0, lv)

print("\n3. Soros momentum")
candles = [{"time": i, "open": 100 + i, "high": 102 + i, "low": 99 + i,
            "close": 101.5 + i, "volume": 1000} for i in range(10)]
so = strategies.soros_momentum(candles)
check("8 green candles rising → BULLISH", so["direction"] == "BULLISH", so)
candles = [{"time": i, "open": 110 - i, "high": 111 - i, "low": 107 - i,
            "close": 108.5 - i, "volume": 1000} for i in range(10)]
so = strategies.soros_momentum(candles)
check("8 red candles falling → BEARISH", so["direction"] == "BEARISH", so)

print("\n4. Mean reversion")
mr = strategies.mean_reversion(make_candles([100.0] * 19 + [100.0, 130.0]))
check("price stretched far above SMA → SELL", mr["signal"] == "SELL" and mr["stretched"], mr)
mr = strategies.mean_reversion(make_candles([100.0] * 19 + [100.0, 70.0]))
check("price stretched far below SMA → BUY", mr["signal"] == "BUY" and mr["stretched"], mr)
mr = strategies.mean_reversion(make_candles([100.0] * 21))
check("price at mean → no signal", mr["signal"] is None and not mr["stretched"], mr)
mr = strategies.mean_reversion(make_candles([100.0] * 5))
check("too little data → no signal", mr["signal"] is None, mr)

print("\n5. Druckenmiller multiplier")
strong = {"breakoutStr": "STRONG"}
weak = {"breakoutStr": "NONE"}
bull = {"strength": 0.85}
flat_lv = {"strength": 0.2}
m = strategies.druckenmiller_multiplier(90, 5, bull, strong)
# Cap was walked down 2.0 → 1.5 → 1.2 (a1c08bfd, "ATR stops widened + caps
# tightened"). This is a sizing multiplier: conviction may add 20% to a
# position, never double it. Raising it again is a real risk decision.
check("high conviction → capped at 1.2", m == 1.2, m)
m = strategies.druckenmiller_multiplier(60, 1, flat_lv, weak)
check("low conviction → floored at 0.4+", 0.4 <= m <= 0.6, m)
m = strategies.druckenmiller_multiplier(78, 3, flat_lv, weak)
check("average setup → 1.0 baseline", m == 1.0, m)

print("\n6. Risk management — should_stop")
fresh_session()
r = strategies.should_stop(1000, 1000)
check("clean session → no stop", r["stop"] is False, r)

fresh_session()
strategies.session["consecutiveLosses"] = 3
strategies.session["lastLossAt"] = time.time()  # just lost — still inside cooldown
r = strategies.should_stop(1000, 1000)
check("3 consecutive losses → stop (Seykota)", r["stop"] and any("consecutive" in x for x in r["reasons"]), r)

fresh_session()
strategies.session["consecutiveLosses"] = 3
strategies.session["lastLossAt"] = time.time() - 61 * 60  # cooldown elapsed
r = strategies.should_stop(1000, 1000)
check("Seykota cooldown expires → streak clears, no stop",
      r["stop"] is False and strategies.session["consecutiveLosses"] == 0, r)

fresh_session()
strategies.session["dailyPnL"] = -50.0
r = strategies.should_stop(950, 1000)
check("daily loss > 3% → stop (PTJ)", r["stop"] and any("-3%" in x for x in r["reasons"]), r)

fresh_session()
strategies.should_stop(1000, 1000)        # sets peak = 1000
r = strategies.should_stop(750, 1000)     # -25% from peak
check("drawdown > 20% from peak → stop", r["stop"] and any("Drawdown" in x for x in r["reasons"]), r)

fresh_session()
strategies.session["dailyTrades"] = 10
r = strategies.should_stop(1000, 1000)
# The trades/day cap was removed on purpose (6a0bc7af) — a good setup is a
# good setup regardless of how many came before it. Asserted as a REQUIREMENT,
# not an omission: re-adding a silent cap here would stop a live account
# mid-session with no other circuit breaker having fired.
check("trade count alone never stops trading (cap removed by design)",
      r["stop"] is False and not r["reasons"], r)
strategies.session["dailyTrades"] = 999
check("still no stop at an absurd trade count",
      strategies.should_stop(1000, 1000)["stop"] is False)

fresh_session()
r = strategies.should_stop(0.5, 1000)
check("balance < $1 → stop", r["stop"] and any("under $1" in x for x in r["reasons"]), r)

print("\n7. Risk management — record_trade streaks")
fresh_session()
strategies.record_trade(False, -5, 1000)
strategies.record_trade(False, -5, 1000)
check("2 losses tracked", strategies.session["consecutiveLosses"] == 2,
      strategies.session["consecutiveLosses"])
strategies.record_trade(True, 12, 1000)
check("win resets loss streak", strategies.session["consecutiveLosses"] == 0
      and strategies.session["consecutiveWins"] == 1, dict(strategies.session))
check("daily PnL accumulates", abs(strategies.session["dailyPnL"] - 2.0) < 1e-9,
      strategies.session["dailyPnL"])
check("daily trade count == 3", strategies.session["dailyTrades"] == 3,
      strategies.session["dailyTrades"])

print("\n8. Daily reset")
fresh_session()
strategies.session["dailyTrades"] = 7
strategies.session["lastResetDay"] = "2000-01-01"
strategies.should_stop(1000, 1000)
check("new day resets counters", strategies.session["dailyTrades"] == 0,
      strategies.session["dailyTrades"])

print("\n9. analyze() bundle")
fresh_session()
out = strategies.analyze(make_candles([100 + i for i in range(30)]))
keys = {"turtle", "livermore", "soros", "meanReversion", "session"}
check("contains all strategy blocks", keys.issubset(out.keys()), sorted(out.keys()))

# ─── Result ───────────────────────────────────────────────
print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — strategy engine + risk rules work.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
