"""Pins three integrity bugs found in review of backtest.py — the file that
backtests the REAL strategy (apex.indicators / apex.strategies / apex.position,
the same code that trades live).

Why each check exists:

  · ENTRY LOOK-AHEAD — backtest.py used to read a signal off bar i's CLOSE
    and then fill the trade AT THAT SAME CLOSE (`mid = bar["close"]`, then
    `entry = mid + ...`). A live bot cannot do that: the close is only known
    the instant the bar finishes, so the earliest a real order can reach the
    market is the NEXT bar's open. The fix extracts the fill decision into
    next_bar_fill() and these tests pin it directly with a candle series that
    has a deliberate gap between one bar's close and the next bar's open —
    mirroring how test_userloop_mirror.py tests position.py's pure functions
    by calling them directly rather than re-running the whole simulation
    loop. (On the synthetic engine's own candles the gap happens to be zero
    by construction — see the note in section 1 — so this is the only way to
    prove the fix deterministically.)

  · CANDLE VALIDATION — the context for this fix: a malformed journal row
    containing the literal string "x" once crashed a live feature that
    trusted its input unchecked. backtest.py feeds candles straight into the
    REAL indicators/strategy/position code, so the same class of bad row
    here (a NaN, a non-positive price, a wick that doesn't contain the
    open/close, negative volume, an out-of-order or duplicate timestamp)
    would corrupt every indicator computed on a window containing it —
    silently, with nothing to notice. validate_candles() rejects at the door
    and reports a count instead of failing silently; these tests exercise
    every rejection rule individually plus the "x"-shaped scenario from the
    original incident, then confirm run() actually calls it.

  · SHARPE ANNUALISATION — sqrt(365) is only correct for daily bars; on 5m/1h
    bars it overstates a risk-adjusted return by roughly 5x, because it
    assumes one bar = one day. backtest.py has no Sharpe or other
    risk-adjusted metric today (grep confirms it), so item 3 does not apply
    — this file documents that with a check that fails loudly the day
    someone adds one with a hard-coded sqrt(365)/sqrt(252) instead of
    deriving the annualisation factor from the candle timestamps.

Run: python tests/test_backtest_integrity.py
"""
import contextlib
import io
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

import backtest  # noqa: E402


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0


def mk(t, o, h, l, c, v=100):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v}


print("\n🧪 BACKTEST INTEGRITY TESTS\n")

print("1. next_bar_fill() — no look-ahead at entry")
half_spread, slip = 0.00005, 0.00003
# Deliberate gap: bar 0 closes at 1.1010 but bar 1 opens at 1.1050 — the kind
# of overnight/weekend gap real feeds have and backtest's own synthetic
# generator does not (there, open[i+1] == close[i] exactly by construction,
# so a close-fill and a next-open-fill are numerically indistinguishable —
# this handcrafted gap is what actually separates the old bug from the fix).
gapped = [
    mk(0, 1.1000, 1.1015, 1.0995, 1.1010),
    mk(1, 1.1050, 1.1060, 1.1040, 1.1055),
    mk(2, 1.1060, 1.1070, 1.1050, 1.1065),
]

fill_buy = backtest.next_bar_fill(gapped, 0, "BUY", half_spread, slip)
expected_buy = gapped[1]["open"] + half_spread + slip
old_buggy_fill = gapped[0]["close"] + half_spread + slip
check("BUY fills on the NEXT bar's open",
      abs(fill_buy - expected_buy) < 1e-12, fill_buy)
check("...and that is NOT the same price the signal was read from (real gap)",
      abs(fill_buy - old_buggy_fill) > 1e-6, (fill_buy, old_buggy_fill))

fill_sell = backtest.next_bar_fill(gapped, 0, "SELL", half_spread, slip)
expected_sell = gapped[1]["open"] - (half_spread + slip)
check("SELL fills on the NEXT bar's open, spread/slippage the other way",
      abs(fill_sell - expected_sell) < 1e-12, fill_sell)

check("mid-series bar (index 1) still resolves to bar 2's open",
      abs(backtest.next_bar_fill(gapped, 1, "BUY", half_spread, slip)
          - (gapped[2]["open"] + half_spread + slip)) < 1e-12)

check("the LAST bar in the series produces no entry (no next bar to fill on)",
      backtest.next_bar_fill(gapped, len(gapped) - 1, "BUY", half_spread, slip)
      is None)
check("...same for SELL on the last bar",
      backtest.next_bar_fill(gapped, len(gapped) - 1, "SELL", half_spread, slip)
      is None)


print("\n2. validate_candles() — malformed rows never reach the strategy layer")
clean_series = [
    mk(0, 1.1000, 1.1010, 1.0990, 1.1005),
    mk(1, 1.1005, 1.1020, 1.0995, 1.1010),
    mk(2, 1.1010, 1.1030, 1.1000, 1.1025),
]
clean, rejected = backtest.validate_candles(clean_series)
check("a clean series passes through untouched",
      rejected == 0 and clean == clean_series, (rejected, clean))


def check_one_bad_row(label, bad_candle):
    """Sandwich one malformed candle between two valid ones and confirm
    exactly that row — and only that row — gets rejected."""
    rows = [mk(0, 1.1000, 1.1010, 1.0990, 1.1005),
            bad_candle,
            mk(9, 1.1010, 1.1030, 1.1000, 1.1025)]
    c, r = backtest.validate_candles(rows)
    check(label, r == 1 and len(c) == 2 and bad_candle not in c, (r, len(c)))


check_one_bad_row("rejects a non-finite value (NaN close)",
                   mk(1, 1.1005, 1.1020, 1.0995, float("nan")))
check_one_bad_row("rejects a non-finite value (+inf high)",
                   mk(1, 1.1005, float("inf"), 1.0995, 1.1010))
check_one_bad_row("rejects non-positive open",
                   mk(1, 0.0, 1.1020, 1.0995, 1.1010))
check_one_bad_row("rejects non-positive close",
                   mk(1, 1.1005, 1.1020, 1.0995, -1.1010))
check_one_bad_row("rejects high < max(open, close)",
                   mk(1, 1.1005, 1.1006, 1.0995, 1.1010))  # high below the close
check_one_bad_row("rejects low > min(open, close)",
                   mk(1, 1.1005, 1.1030, 1.1007, 1.1010))  # low above the open
check_one_bad_row("rejects negative volume",
                   mk(1, 1.1005, 1.1020, 1.0995, 1.1010, v=-5))
check_one_bad_row("rejects a duplicate timestamp (t == previous kept t)",
                   mk(0, 1.1005, 1.1020, 1.0995, 1.1010))
check_one_bad_row("rejects an out-of-order timestamp (t < previous kept t)",
                   mk(-1, 1.1005, 1.1020, 1.0995, 1.1010))

# The actual incident this fix guards against: a stray non-numeric string in
# a numeric field ("a malformed journal row containing 'x' once crashed a
# live feature — the same class of bug").
poisoned = mk(1, 1.1005, 1.1020, 1.0995, 1.1010)
poisoned["close"] = "x"
check_one_bad_row("rejects the 'x'-poisoned row instead of crashing on float('x')",
                   poisoned)
poisoned_missing = mk(1, 1.1005, 1.1020, 1.0995, 1.1010)
del poisoned_missing["volume"]
check_one_bad_row("rejects a row missing a required field instead of KeyError-ing",
                   poisoned_missing)

# Aggregate count: several independently-invalid rows mixed into a longer,
# otherwise-valid run — proves the reject count is a real tally, not a
# per-call artefact, and that validation doesn't stop at the first bad row.
good = backtest.synthetic_candles(700)
bad_rows = [dict(good[350]) for _ in range(4)]
bad_rows[0]["close"] = float("nan")
bad_rows[1]["open"] = -1.0
bad_rows[2]["volume"] = -5
bad_rows[3]["high"] = bad_rows[3]["low"] - 0.01  # high below low entirely
mixed = good[:350] + bad_rows + good[350:]
c, r = backtest.validate_candles(mixed)
check("4 independently-bad rows mixed into 700 good ones → 4 rejected, 700 clean",
      r == 4 and len(c) == 700, (r, len(c)))

print("\n2b. validate_candles() is actually wired into run(), not just defined")
orig_fetch = backtest.fetch_candles
backtest.fetch_candles = lambda: mixed
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        backtest.run()
    out = buf.getvalue()
    check("run() reports the rejected-row count instead of staying silent",
          "4 lumânări respinse" in out, out[:600])
    check("run() still completes and prints a result after dropping bad rows",
          "Rezultat net" in out, out[-600:])
finally:
    backtest.fetch_candles = orig_fetch


print("\n3. Sharpe annualisation (item 3 — does not apply, guarded so it stays that way)")
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "backtest.py"), encoding="utf-8").read()
check("backtest.py currently has no Sharpe/risk-adjusted metric (item 3 N/A today)",
      "sharpe" not in src.lower(),
      "a 'sharpe' mention appeared — item 3 now applies, verify it derives its "
      "annualisation factor from the candle timestamps, not a hard-coded constant")
check("...and no hard-coded daily/annual sqrt(365)/sqrt(252) constant is lurking either",
      not re.search(r"sqrt\(\s*(365|252)\s*\)", src, re.I),
      "found a hard-coded sqrt(365)/sqrt(252) — on non-daily bars this overstates "
      "Sharpe by ~5x; derive the factor from the actual bar interval instead")


# ─── Result ───────────────────────────────────────────────
print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — backtest.py's entry timing and candle intake "
          "are honest.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
