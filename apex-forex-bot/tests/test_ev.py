"""Tests for the EV / probability / risk engine (apex/ev.py).

Run: python tests/test_ev.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import ev  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


print("\n── expected value ──")
# Spec §17: p=0.70, TP=1.7R, SL=1R, cost=0.05R → +0.84R
check("spec worked example = +0.84R",
      close(ev.expected_value(0.70, 1.7, 1.0, 0.05), 0.84, 1e-9),
      f"got {ev.expected_value(0.70, 1.7, 1.0, 0.05)}")
check("probability clamped at 1", close(ev.expected_value(5.0, 1.0, 1.0, 0.0), 1.0))
check("probability clamped at 0", close(ev.expected_value(-3.0, 1.0, 1.0, 0.0), -1.0))

# The trap this whole module exists to catch: high win rate, negative EV.
ev_high_wr = ev.expected_value(0.90, 0.1, 1.0, 0.0)
check("90% win rate with TP=0.1R is NEGATIVE EV", ev_high_wr < 0, f"got {ev_high_wr}")

print("\n── breakeven probability ──")
be = ev.breakeven_probability(1.7, 1.0, 0.0)
check("TP=1.7R breaks even near 37%", close(be, 1.0 / 2.7, 1e-6), f"got {be}")
check("shrinking TP raises the breakeven floor",
      ev.breakeven_probability(0.5, 1.0) > ev.breakeven_probability(3.0, 1.0))

print("\n── cost in R ──")
# spread 1.0p, slippage 0.3p each way, SL 10p → (1.0 + 0.6) / 10 = 0.16R
check("round-trip cost", close(ev.cost_in_r(1.0, 10.0), 0.16, 1e-9),
      f"got {ev.cost_in_r(1.0, 10.0)}")
check("zero stop is infinite cost", ev.cost_in_r(1.0, 0) == float("inf"))
check("tight stop makes cost dominate", ev.cost_in_r(2.0, 4.0) > 0.5)

print("\n── dynamic SL/TP ──")
sl, tp = ev.dynamic_sl_tp(atr_pips=8.0, structure_distance_pips=0.0,
                          spread_pips=0.5, atr_multiplier=1.25, rr=1.7)
check("ATR drives the stop", close(sl, 10.0), f"got {sl}")
check("TP is rr × SL", close(tp, 17.0), f"got {tp}")

sl2, _ = ev.dynamic_sl_tp(atr_pips=2.0, structure_distance_pips=14.0, spread_pips=0.5)
check("structure widens the stop", close(sl2, 14.0), f"got {sl2}")

sl3, _ = ev.dynamic_sl_tp(atr_pips=1.0, structure_distance_pips=0.0, spread_pips=6.0)
check("stop always clears 2× spread", sl3 >= 12.0, f"got {sl3}")

sl4, _ = ev.dynamic_sl_tp(atr_pips=100.0, max_sl_pips=25.0)
check("max stop respected", close(sl4, 25.0), f"got {sl4}")

print("\n── Kelly sizing ──")
check("no edge → no size", close(ev.fractional_kelly(0.4, 1.0), 0.0))
check("edge → positive fraction", ev.fractional_kelly(0.7, 1.7) > 0)
_, pct = ev.position_risk(10000, 0.99, 5.0, 1.0, kelly_fraction=0.10, max_risk_pct=0.5)
check("risk hard-capped at max_risk_pct", close(pct, 0.5), f"got {pct}")
cash, pct2 = ev.position_risk(10000, 0.30, 1.0, 1.0)
check("negative edge → zero risk", close(pct2, 0.0) and close(cash, 0.0))

print("\n── drawdown throttle ──")
check("flat → full risk", close(ev.drawdown_risk_multiplier(0.0), 1.0))
check("-4% → 0.65", close(ev.drawdown_risk_multiplier(-4.0), 0.65))
check("-9% → trading halted", close(ev.drawdown_risk_multiplier(-9.0), 0.0))
check("final_risk_pct scales", close(ev.final_risk_pct(1.0, -4.0), 0.65))

print("\n── no-trade engine ──")
ok, reason = ev.approve_trade(0.70, 0.5, regime="trending", spread_pips=1.0,
                              atr_pips=10.0)
check("clean setup approved", ok and reason == "APPROVED", reason)

ok, reason = ev.approve_trade(0.40, 0.5, regime="trending")
check("low probability rejected", not ok and reason == "LOW_PROBABILITY", reason)

ok, reason = ev.approve_trade(0.70, -0.1, regime="trending")
check("negative EV rejected", not ok and reason == "NEGATIVE_EV", reason)

ok, reason = ev.approve_trade(0.70, 0.5, regime="trending", spread_pips=5.0,
                              atr_pips=10.0)
check("spread/ATR too high rejected", not ok and reason == "SPREAD_TOO_HIGH", reason)

ok, reason = ev.approve_trade(0.70, 0.5, regime="quiet")
check("untradeable regime rejected", not ok and reason == "REGIME_NOT_ALLOWED", reason)

ok, reason = ev.approve_trade(0.70, 0.5, regime="trending", risk_ok=False)
check("risk block respected", not ok and reason == "RISK_BLOCK", reason)

ok, reason = ev.approve_trade(None, 0.5, regime="trending")
check("missing probability rejected", not ok and reason == "NO_PROBABILITY", reason)

print("\n── calibration ──")
check("empty journal → None", ev.calibrate([]) is None)
check("too few samples → None", ev.calibrate(
    [{"confidence": 76, "netPnl": 1.0}] * 5) is None)

# 100 trades: high-confidence bucket wins often, low bucket rarely.
journal = []
for _ in range(50):
    journal.append({"confidence": 84, "netPnl": 1.0})   # win
for _ in range(10):
    journal.append({"confidence": 84, "netPnl": -1.0})  # loss
for _ in range(10):
    journal.append({"confidence": 55, "netPnl": 1.0})
for _ in range(30):
    journal.append({"confidence": 55, "netPnl": -1.0})

cal = ev.calibrate(journal)
check("calibration built", cal is not None and cal["samples"] == 100)
p_hi = ev.calibrated_probability(84, cal)
p_lo = ev.calibrated_probability(55, cal)
check("high bucket > low bucket", p_hi > p_lo, f"{p_hi} vs {p_lo}")
check("high bucket below its raw rate (shrunk)", p_hi < 50 / 60,
      f"got {p_hi} vs raw {50/60:.3f}")
check("probabilities stay in (0,1)", 0.0 < p_lo < 1.0 and 0.0 < p_hi < 1.0)

# The safety property that matters: a tiny all-winning bucket must not report ~1.0
tiny = [{"confidence": 84, "netPnl": 1.0}] * 3 + \
       [{"confidence": 55, "netPnl": -1.0}] * 40
cal_tiny = ev.calibrate(tiny)
p_tiny = ev.calibrated_probability(84, cal_tiny)
check("3 wins do NOT produce p≈1.0", p_tiny < 0.6, f"got {p_tiny}")

check("no calibration → fallback, never confidence/100",
      ev.calibrated_probability(76, None) is None)

check("records without confidence are skipped",
      ev.calibrate([{"netPnl": 1.0}] * 100) is None)

print("\n── metrics ──")
m = ev.metrics([1.0, -1.0, 1.0, 1.0, -1.0])
check("win rate", close(m["win_rate"], 0.6), f"got {m['win_rate']}")
check("profit factor", close(m["profit_factor"], 1.5), f"got {m['profit_factor']}")
check("expectancy", close(m["expectancy_R"], 0.2), f"got {m['expectancy_R']}")
check("trade count", m["trades"] == 5)
check("empty input safe", ev.metrics([])["trades"] == 0)
check("all-wins profit factor is inf",
      ev.metrics([1.0, 2.0])["profit_factor"] == float("inf"))
m_dd = ev.metrics([1.0, -1.0, -1.0, -1.0, 1.0])
check("max drawdown in R", close(m_dd["max_drawdown_R"], 3.0),
      f"got {m_dd['max_drawdown_R']}")

print("\n── monte carlo ──")
mc = ev.monte_carlo_r_paths([1.7, -1.0] * 30, simulations=300, seed=42)
check("runs and reports", mc["simulations"] == 300)
check("prob_negative is a probability", 0.0 <= mc["prob_negative"] <= 1.0)
check("drawdown non-negative", mc["max_dd_p95"] >= 0)
mc2 = ev.monte_carlo_r_paths([1.7, -1.0] * 30, simulations=300, seed=42)
check("seeded run is reproducible", mc == mc2)
check("too-short input safe", ev.monte_carlo_r_paths([1.0])["simulations"] == 0)

print("\n── end-to-end evaluate() ──")
res = ev.evaluate(confidence=84, calibration=cal, atr_pips=10.0, spread_pips=1.0,
                  regime="trending", equity=5000.0, min_probability=0.55)
check("approved on a good setup", res["approved"], res["reason"])
check("reports probability, not confidence",
      res["probability"] is not None and res["probability"] != 0.84)
check("sizing produced", res["risk_pct"] > 0 and res["risk_cash"] > 0)
check("logs the full basis",
      all(k in res for k in ("ev_r", "cost_r", "tp_r", "breakeven_p", "sl_pips")))

res_nocal = ev.evaluate(confidence=84, calibration=None, atr_pips=10.0,
                        spread_pips=1.0, regime="trending", equity=5000.0)
check("uncalibrated → refuses rather than guessing",
      not res_nocal["approved"] and res_nocal["reason"] == "NO_PROBABILITY",
      res_nocal["reason"])

res_dd = ev.evaluate(confidence=84, calibration=cal, atr_pips=10.0, spread_pips=1.0,
                     regime="trending", equity=5000.0, drawdown_pct=-9.0)
check("deep drawdown blocks the entry",
      not res_dd["approved"] and res_dd["reason"] == "DRAWDOWN_BLOCK",
      res_dd["reason"])

res_wide = ev.evaluate(confidence=84, calibration=cal, atr_pips=4.0, spread_pips=3.0,
                       regime="trending", equity=5000.0)
check("wide spread relative to ATR blocks the entry",
      not res_wide["approved"], res_wide["reason"])

# Win-rate dial: raising min_probability must reject what a lower one accepts.
res_strict = ev.evaluate(confidence=55, calibration=cal, atr_pips=10.0,
                         spread_pips=1.0, regime="trending", equity=5000.0,
                         min_probability=0.75)
check("min_probability dial filters harder",
      not res_strict["approved"] and res_strict["reason"] == "LOW_PROBABILITY",
      res_strict["reason"])

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL EV ENGINE CHECKS PASSED.")
