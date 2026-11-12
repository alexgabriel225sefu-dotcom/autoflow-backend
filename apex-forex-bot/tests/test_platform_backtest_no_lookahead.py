"""A rule backtest fills on the bar AFTER the signal and uses the rule's stop.

Found on a real account: "Run backtest" on a breakout rule returned 36
trades, every one a winner, drawdown 0, profit factor unknown. The trade was
booked from the signal bar's own open to its own close, so the move that
produced the signal was counted as the profit.

Run: python3 tests/test_platform_backtest_no_lookahead.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex.platform import backtest as BT                       # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name if not detail else f"{name} — {detail}")
        print(f"  FAIL {name} {detail}")


def bar(i, o, h, low, c):
    return {"time": 1_700_000_000 + i * 3600, "open": o, "high": h, "low": low,
            "close": c, "volume": 100}


RULE = {"stopLoss": {"mode": "pips", "pips": 20.0}, "takeProfit": {"mode": "pips", "pips": 40.0}}


def run(candles, signal, rule=RULE, **kw):
    """Run the rule path with a scripted signal in place of the evaluator."""
    return BT._run_rule(candles, signal, rule=rule, symbol="EURUSD",
                        starting_balance=kw.get("balance"), cost_pips=kw.get("cost", 0.0),
                        commission=0.0, spread_pips=0.0, slippage_pips=0.0, latency_bars=0)


def on(indices, side="BUY"):
    seen = {"i": -1}

    def fn(_candle):
        seen["i"] += 1
        return {"side": side} if seen["i"] in indices else None
    return fn


print("\n[1] the signal bar's own move is not the profit")
# Bar 1 breaks out hard (the signal). Bar 2 opens at the high and falls to the stop.
candles = [bar(0, 1.1000, 1.1005, 1.0995, 1.1000),
           bar(1, 1.1000, 1.1100, 1.1000, 1.1100),
           bar(2, 1.1100, 1.1105, 1.1050, 1.1060),
           bar(3, 1.1060, 1.1070, 1.1050, 1.1060)]
r = run(candles, on({1}))
t = r["trades"][0]
check("one trade", r["tradeCount"] == 1, str(r["tradeCount"]))
check("filled at the NEXT bar's open, not the signal bar's", t["entry"] == 1.1100 and t["index"] == 2
      and t["signalIndex"] == 1, str(t))
check("stopped out 20 pips lower", t["exitReason"] == "stop" and abs(t["exit"] - 1.1080) < 1e-9, str(t))
check("it is a loss, where the old booking showed +100 pips", abs(t["pnl"] + 0.0020) < 1e-9, str(t["pnl"]))
check("a losing trade produces a drawdown", r["maxDrawdown"] > 0, str(r["maxDrawdown"]))

print("\n[2] the target, the order of stop and target, and a gap")
up = [bar(0, 1.1, 1.1, 1.1, 1.1), bar(1, 1.1000, 1.1010, 1.0995, 1.1005),
      bar(2, 1.1005, 1.1050, 1.1000, 1.1045)]
t = run(up, on({0}))["trades"][0]
check("target reached on a later bar", t["exitReason"] == "target" and abs(t["exit"] - 1.1040) < 1e-9
      and t["exitIndex"] == 2, str(t))
both = [bar(0, 1.1, 1.1, 1.1, 1.1), bar(1, 1.1000, 1.1060, 1.0970, 1.1050)]
t = run(both, on({0}))["trades"][0]
check("a bar reaching both counts as the stop", t["exitReason"] == "stop" and t["pnl"] < 0, str(t))
gap = [bar(0, 1.1, 1.1, 1.1, 1.1), bar(1, 1.1000, 1.1005, 1.0995, 1.1000),
       bar(2, 1.0950, 1.0960, 1.0940, 1.0955)]
t = run(gap, on({0}))["trades"][0]
check("an open beyond the stop exits at that open", t["exitReason"] == "stop" and t["exit"] == 1.0950, str(t))
sell = [bar(0, 1.1, 1.1, 1.1, 1.1), bar(1, 1.1000, 1.1005, 1.0950, 1.0955)]
t = run(sell, on({0}, "SELL"))["trades"][0]
check("a sell is mirrored", t["side"] == "SELL" and t["exitReason"] == "target"
      and abs(t["pnl"] - 0.0040) < 1e-9, str(t))

print("\n[3] edges")
check("a signal on the last bar has no next bar to fill", run(candles[:2], on({1}))["tradeCount"] == 0)
r = run(candles, on({1, 2, 3}))
check("one position at a time", r["tradeCount"] == 1 or all(
    a["exitIndex"] <= b["index"] for a, b in zip(r["trades"], r["trades"][1:])), str(r["tradeCount"]))
flat = [bar(i, 1.1, 1.1002, 1.0998, 1.1) for i in range(4)]
t = run(flat, on({0}))["trades"][0]
check("still open at the end is closed at the last close and says so",
      t["exitReason"].startswith("still open"), str(t))
t = run(flat, on({0}), rule={"stopLoss": {"mode": "atr", "atrMultiple": 2}})["trades"][0]
check("no fixed stop or target holds the fill bar only", t["index"] == 1 and t["exitIndex"] == 1
      and "one bar held" in t["exitReason"], str(t))
r = run([bar(0, 1.1, 1.1, 1.1, 1.1), {"time": 1, "open": None}, *candles[1:]], on({0}))
check("an unreadable bar is skipped and counted", r["skippedCandles"] == 1, str(r["skippedCandles"]))
check("the result states its assumptions",
      r["assumptions"]["entry"] == "the open of the bar after the signal"
      and r["assumptions"]["stopPips"] == 20.0)
r = run(candles, on({1}), cost=2.0)
check("costs come off in pips", abs(r["trades"][0]["pnl"] + 0.0022) < 1e-9, str(r["trades"][0]["pnl"]))

print("\n[4] the public entry point uses this path for a rule")
calls = []
orig = BT._rule_signal
BT._rule_signal = lambda rule, symbol, timeframe: on({1})
try:
    r = BT.run(candles, rule=RULE, symbol="EURUSD", timeframe="1h")
finally:
    BT._rule_signal = orig
check("run(rule=...) fills on the next bar", r["trades"][0]["index"] == 2, str(r["trades"]))
old = BT.run(candles, signal=lambda c: {"side": "BUY"})
check("a caller-supplied signal keeps its own entry and exit", old["tradeCount"] == 4)

if _fails:
    print(f"\n{len(_fails)} FAILED:")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("\nall backtest look-ahead checks passed")
