"""Fibonacci entry quality: rejection confirmation and real confirming inputs.

Two defects this covers:

  * The engine fired on TOUCH. `price <= level` in an uptrend is true while
    price is still below the level and moving down — buying into a live
    down-move. A rejection is a different event: the previous bar pierced the
    level and the current bar closed back across it.
  * RSI and the EMA trend were computed, compared, formatted into a string and
    discarded. The action came from the level alone and the confidence was a
    hardcoded 72, which is why MIN_CONFIDENCE, the size multiplier and the EV
    calibration all had nothing to work with.

Run: python tests/test_fib_entry.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

from apex import indicators, ai  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def bars(seq):
    """seq of (high, low, close) → candles the indicator accepts."""
    return [{"open": c, "high": h, "low": lo, "close": c, "time": 1700000000 + i * 60,
             "volume": 100} for i, (h, lo, c) in enumerate(seq)]


def uptrend_then(last_two):
    """A 50-bar up-swing (low first, high later) followed by two shaped bars."""
    base = []
    for i in range(48):
        p = 1.1000 + i * 0.0004          # rises → swing low early, high late
        base.append((p + 0.0002, p - 0.0002, p))
    return bars(base + list(last_two))


print("\n── a touch alone is not a signal ──")
# 61.8% retracement of the swing sits around 1.1072. Price drifting down
# through it, closing below, must NOT fire a BUY.
fib = indicators.fibonacci_levels(
    uptrend_then([(1.1080, 1.1070, 1.1072), (1.1074, 1.1060, 1.1062)]))
check("price falling through the level does not fire",
      fib["signal"] is None, str(fib["signal"]))
check("and it is reported as un-rejected", fib.get("rejected") is False)

print("\n── a rejection does fire ──")
lvl = None
f0 = indicators.fibonacci_levels(uptrend_then([(1.1090, 1.1085, 1.1088),
                                               (1.1090, 1.1085, 1.1088)]))
lvl = f0["nearestPrice"]
# Previous bar pierces below the level, current bar closes back above it.
fib2 = indicators.fibonacci_levels(uptrend_then([
    (lvl + 0.0002, lvl - 0.0006, lvl - 0.0004),
    (lvl + 0.0004, lvl - 0.0002, lvl + 0.0003)]))
check("pierce then close back across fires", fib2["signal"] == "BUY",
      f"{fib2['signal']} rejected={fib2.get('rejected')}")
check("rejection is flagged", fib2.get("rejected") is True)

print("\n── the swing is reported so a caller can size against it ──")
check("swing range exposed", fib2.get("swingRange", 0) > 0)
check("structural target exposed", fib2.get("target") is not None)
check("target is the swing extreme for an uptrend",
      abs(fib2["target"] - fib2["swingHigh"]) < 1e-9)

print("\n── extensions can never be the nearest level ──")
# They sit >= 0.272*diff away while retracements cluster within 0.084*diff, so
# including them in the search was dead code that hid the real nearest level.
check("nearest is always a retracement",
      not str(fib2.get("nearest", "")).startswith("ext_"),
      str(fib2.get("nearest")))

print("\n── RSI, EMA and MACD now change the outcome ──")


def sig(rsi, ema20, ema50, macd, signal="BUY"):
    ind = {"fibonacci": {"signal": signal, "trend": "UP" if signal == "BUY" else "DOWN",
                         "nearest": "61.8%"},
           "rsi": rsi, "ema20": ema20, "ema50": ema50, "macdHist": macd}
    return ai.fibonacci_signal(ind)


agree = sig(rsi=35, ema20=1.11, ema50=1.10, macd=0.5)
check("everything agreeing produces a BUY", agree["action"] == "BUY")
check("and a confidence above the old constant 72",
      agree["confidence"] > 72, str(agree["confidence"]))

weak = sig(rsi=50, ema20=1.10, ema50=1.11, macd=-0.1)
check("EMA against the setup lowers confidence",
      weak["confidence"] < agree["confidence"],
      f"{weak['confidence']} vs {agree['confidence']}")

against = sig(rsi=78, ema20=1.10, ema50=1.11, macd=-0.5)
check("a setup fighting itself is refused outright",
      against["action"] == "HOLD", str(against["action"]))
check("and says why", "disagrees" in against["reasoning"]
      or "against" in against["reasoning"], against["reasoning"])

print("\n── confidence is no longer a constant ──")
seen = {sig(r, 1.11, 1.10, m)["confidence"]
        for r in (35, 50) for m in (0.5, -0.5)}
check("more than one value is reachable", len(seen) > 1, str(seen))
check("no signal still returns a HOLD, not a crash",
      ai.fibonacci_signal({"fibonacci": {"signal": None,
                                         "nearest": "50.0%"}})["action"] == "HOLD")

print("\n── short setups mirror correctly ──")
short = sig(rsi=70, ema20=1.10, ema50=1.11, macd=-0.5, signal="SELL")
check("an aligned SELL fires", short["action"] == "SELL", str(short["action"]))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL FIBONACCI ENTRY CHECKS PASSED.")
