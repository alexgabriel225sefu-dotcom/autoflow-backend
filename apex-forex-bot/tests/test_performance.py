"""The journal, sliced the ways a client asks.

ev.metrics() has computed win rate, profit factor, expectancy and max drawdown
since the walk-forward work, but only ever over backtest R-multiples — never
over the live journal. So a client with seventeen methods available had no
report saying which one worked on their own account, and expectancy, the one
figure that says "is this edge real", appeared nowhere in the product.

What this pins:
  * the numbers are right, including the awkward cases (no losses, no trades,
    rows missing fields);
  * dollars and R are counted separately, because far fewer rows carry the
    stop distance R needs and a shared count would overstate the evidence;
  * ev.metrics stays the single definition — a second expectancy formula that
    drifts from the first is worse than none.

Run: python tests/test_performance.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import ev, performance  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def row(sym, net, *, entry=None, exit=None, sl=None, side="BUY",
        strat=None, mode=None, time="2026-08-14 10:00:00"):
    return {"symbol": sym, "netPnl": net, "entry": entry, "exit": exit,
            "slPips": sl, "side": side, "strategyId": strat, "mode": mode,
            "time": time}


print("\n── R comes from the stop the trade was opened with ──")
# 35-pip stop, 70 pips made → exactly 2R. The pip size cancels, so this holds
# for any instrument.
check("a 2R win reads as 2.0",
      abs(performance.r_multiple(
          row("EURUSD", 70, entry=1.15000, exit=1.15700, sl=35)) - 2.0) < 0.01)
check("a full stop-out reads as -1.0",
      abs(performance.r_multiple(
          row("EURUSD", -35, entry=1.15000, exit=1.14650, sl=35)) + 1.0) < 0.01)
check("a SELL is measured in its own direction",
      abs(performance.r_multiple(
          row("EURUSD", 70, entry=1.15700, exit=1.15000, sl=35, side="SELL")) - 2.0) < 0.01)
for _bad, _why in (({}, "empty row"),
                   (row("EURUSD", 5, entry=1.15, exit=1.16), "no stop"),
                   (row("EURUSD", 5, entry=1.15, exit=1.16, sl=0), "zero stop"),
                   (row("EURUSD", 5, exit=1.16, sl=35), "no entry"),
                   (row("EURUSD", 5, entry=1.15, exit=1.16, sl=35, side="?"), "no side")):
    check(f"{_why} → no R, not a wrong R", performance.r_multiple(_bad) is None)

print("\n── the money figures ──")
J = [row("EURUSD", 100), row("EURUSD", -50), row("GBPUSD", 200), row("GBPUSD", -50)]
s = performance.summarize(J)
check("trades counted", s["trades"] == 4, str(s["trades"]))
check("wins and losses split", (s["wins"], s["losses"]) == (2, 2))
check("win rate as a percentage", s["win_rate"] == 50.0, str(s["win_rate"]))
check("net is the sum", s["net"] == 200.0, str(s["net"]))
check("profit factor = won / lost", s["profit_factor"] == 3.0, str(s["profit_factor"]))
check("expectancy is per-trade, not total", s["expectancy"] == 50.0, str(s["expectancy"]))
check("best and worst", (s["best"], s["worst"]) == (200.0, -50.0))
check("average win / loss", (s["avg_win"], s["avg_loss"]) == (150.0, -50.0))
# +100, -50, +200, -50 → peak 100 then 50: the dip is 50, not the final total.
check("max drawdown is the deepest dip, not the last loss",
      s["max_drawdown"] == 50.0, str(s["max_drawdown"]))

print("\n── the awkward cases ──")
check("no trades at all → zeros, no crash", performance.summarize([])["trades"] == 0)
check("no trades → expectancy 0, not a divide by zero",
      performance.summarize([])["expectancy"] == 0.0)
_allwin = performance.summarize([row("EURUSD", 10), row("EURUSD", 20)])
check("no losses → profit factor is infinite, not zero",
      _allwin["profit_factor"] == float("inf"), str(_allwin["profit_factor"]))
_allloss = performance.summarize([row("EURUSD", -10)])
check("no wins → profit factor 0", _allloss["profit_factor"] == 0.0)
check("rows with no netPnl are skipped, not counted as zero",
      performance.summarize([row("EURUSD", None), row("EURUSD", 10)])["trades"] == 1)

print("\n── R is counted separately from dollars ──")
MIX = [row("EURUSD", 70, entry=1.15, exit=1.157, sl=35),      # has R
       row("EURUSD", -35, entry=1.15, exit=1.1465, sl=35),    # has R
       row("EURUSD", 40)]                                     # no stop → no R
s = performance.summarize(MIX)
check("dollars count every row", s["trades"] == 3, str(s["trades"]))
check("R counts only the rows that can support it",
      s["r"]["trades"] == 2, str(s["r"]["trades"]))
check("so the R sample is never overstated", s["r"]["trades"] < s["trades"])
check("expectancy_R is present", "expectancy_R" in s["r"])
check("no row carries R → the R block is None, not a fake zero",
      performance.summarize([row("EURUSD", 40)])["r"] is None)

print("\n── ev.metrics stays the only definition ──")
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "performance.py"), encoding="utf-8").read()
check("performance.py calls it", "ev.metrics(" in SRC)
check("and does not reimplement expectancy_R",
      "expectancy_R\":" not in SRC.replace('"expectancy_R": m["expectancy_R"]', ""))
_rs = [2.0, -1.0, 2.0, -1.0]
check("the R block matches ev.metrics exactly",
      performance.summarize(
          [row("E", 70, entry=1.15, exit=1.157, sl=35),
           row("E", -35, entry=1.15, exit=1.1465, sl=35)]
      )["r"]["expectancy_R"] == ev.metrics([2.0, -1.0])["expectancy_R"])

print("\n── sliced by method, symbol and account mode ──")
J2 = [row("EURUSD", 100, strat="momentum", mode="live"),
      row("EURUSD", -50, strat="momentum", mode="live"),
      row("GBPUSD", 300, strat="zscore", mode="demo"),
      row("GBPUSD", -20, strat=None, mode=None)]
bs = performance.by_strategy(J2)
check("each method gets its own row", set(bs) == {"momentum", "zscore", "unlabelled"},
      str(set(bs)))
check("unlabelled trades are kept, not dropped",
      bs["unlabelled"]["trades"] == 1)
check("per-method net is right", bs["momentum"]["net"] == 50.0)
check("by symbol splits too", set(performance.by_symbol(J2)) == {"EURUSD", "GBPUSD"})
bm = performance.by_mode(J2)
check("demo and live are kept apart", bm["live"]["net"] == 50.0 and bm["demo"]["net"] == 300.0)
check("rows written before mode existed are 'unknown', not guessed",
      bm["unknown"]["trades"] == 1)

print("\n── ranking refuses to crown a lucky method ──")
G = {"good": performance.summarize([row("E", 100)] * 5),
     "lucky": performance.summarize([row("E", 900)]),
     "bad": performance.summarize([row("E", -100)] * 5)}
order = [n for n, _ in performance.ranked(G, min_trades=3)]
check("a one-trade method does not top the list", order[0] == "good", str(order))
check("thin samples are pushed last", order[-1] == "lucky", str(order))
check("and flagged as thin", dict(performance.ranked(G, min_trades=3))["lucky"]["thin"])
check("losers rank below winners", order.index("good") < order.index("bad"))

print("\n── date filter ──")
JD = [row("E", 10, time="2026-08-13 23:59:59"), row("E", 20, time="2026-08-14 00:00:01")]
check("only today's rows survive",
      performance.since(JD, "2026-08-14")[0]["netPnl"] == 20)
check("and an empty journal is fine", performance.since([], "2026-08-14") == [])

print("\n── the loop records the mode going forward ──")
LOOP = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "apex", "user_loop.py"), encoding="utf-8").read()
check("mode is journalled per trade", '"mode":            _mode_of(user_id),' in LOOP)
check("it comes from THIS user's record, not the process-global config",
      'user_store.load(user_id).get("paper"' in LOOP)
check("an unreadable mode is None, never a guess",
      "return None" in LOOP[LOOP.index("def _mode_of"):LOOP.index("def _already_journaled")])

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the journal can finally answer 'which method works'.")
