"""Unit tests for the technical indicator library.

Run: python tests/test_indicators.py
"""
import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import indicators  # noqa: E402


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0


def make_candles(closes, volume=1000):
    """Build OHLCV candles from a list of closes (high/low ±0.5%)."""
    return [{"time": i, "open": c * 0.999, "high": c * 1.005,
             "low": c * 0.995, "close": c, "volume": volume}
            for i, c in enumerate(closes)]


# ─── SMA ──────────────────────────────────────────────────
print("\n🧪 INDICATOR UNIT TESTS\n")
print("1. SMA")
out = indicators.sma([1, 2, 3, 4, 5], 3)
check("warm-up values are None", out[0] is None and out[1] is None)
check("SMA(3) of [1,2,3] == 2", out[2] == 2, out[2])
check("SMA(3) of [3,4,5] == 4", out[4] == 4, out[4])

print("\n2. EMA")
out = indicators.ema([10] * 20, 5)
check("EMA of constant series == constant", all(v == 10 for v in out if v is not None), out[-1])
rising = indicators.ema(list(range(1, 31)), 5)
check("EMA rises with rising prices", rising[-1] > rising[10], rising[-1])
check("EMA lags below latest price in uptrend", rising[-1] < 30, rising[-1])

print("\n3. RSI")
up_only = indicators.rsi([float(i) for i in range(1, 31)])
check("RSI == 100 when only gains", up_only[-1] == 100.0, up_only[-1])
down_only = indicators.rsi([float(v) for v in range(31, 1, -1)])
check("RSI near 0 when only losses", down_only[-1] is not None and down_only[-1] < 1, down_only[-1])
flat_in_range = indicators.rsi([100 + (1 if i % 2 else -1) for i in range(30)])
check("alternating series stays within 0–100",
      all(0 <= v <= 100 for v in flat_in_range if v is not None))

print("\n4. MACD")
closes = [100 + math.sin(i / 5) * 10 + i * 0.2 for i in range(80)]
m = indicators.macd(closes)
check("macd/signal/histogram same length", len(m["macd"]) == len(m["signal"]) == len(m["histogram"]) == 80)
check("histogram = macd - signal",
      abs(m["histogram"][-1] - (m["macd"][-1] - m["signal"][-1])) < 1e-9, m["histogram"][-1])

print("\n5. Bollinger Bands")
bb = indicators.bollinger_bands(closes)
last = bb[-1]
check("upper > mid > lower", last["upper"] > last["mid"] > last["lower"],
      f"{last['upper']}/{last['mid']}/{last['lower']}")
check("bandwidth is positive", last["bandwidth"] > 0, last["bandwidth"])
flat_bb = indicators.bollinger_bands([100.0] * 30)
check("flat series → bands collapse on mid",
      abs(flat_bb[-1]["upper"] - flat_bb[-1]["lower"]) < 1e-9)

print("\n6. ATR")
candles = make_candles(closes)
a = indicators.atr(candles)
check("ATR positive for volatile series", a[-1] is not None and a[-1] > 0, a[-1])
flat_candles = [{"time": i, "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1}
                for i in range(30)]
fa = indicators.atr(flat_candles)
check("ATR == 0 for flat series", fa[-1] == 0, fa[-1])

print("\n7. Stoch RSI")
s = indicators.stoch_rsi(closes)
check("K and D within 0–100",
      (s["k"] is None or 0 <= s["k"] <= 100) and (s["d"] is None or 0 <= s["d"] <= 100),
      f"k={s['k']} d={s['d']}")

print("\n8. Divergence")
no_div = indicators.detect_divergence([1, 2, 3], [None, None, 50])
check("too little data → NONE", no_div == "NONE", no_div)

print("\n9. Market structure")
up = make_candles([100 + i for i in range(25)])
check("steady rise → UPTREND", indicators.market_structure(up) == "UPTREND",
      indicators.market_structure(up))
down = make_candles([100 - i for i in range(25)])
check("steady fall → DOWNTREND", indicators.market_structure(down) == "DOWNTREND",
      indicators.market_structure(down))

print("\n10. analyze() smoke test")
ind = indicators.analyze(make_candles(closes + closes + closes))  # 240 candles
required = ["price", "rsi", "macdHist", "ema20", "ema50", "ema200", "atr",
            "volumeRatio", "bb_position", "marketStructure", "recentCandles"]
missing = [k for k in required if k not in ind]
check("all expected fields present", not missing, str(missing))
check("returns 5 recent candles", len(ind["recentCandles"]) == 5, len(ind["recentCandles"]))
check("RSI parses as float 0–100", 0 <= float(ind["rsi"]) <= 100, ind["rsi"])

# ─── Result ───────────────────────────────────────────────
print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — indicator library works.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
