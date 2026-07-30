"""Pins apex/position.py's user_loop mirror against the real live loop.

apex/user_loop.py (the loop that trades every client) carries its own inline
exit maths and never imports apex/position.py. The backtest has to reproduce
that maths to be worth anything, so position.py holds a mirror — and a mirror
silently rots the moment either side is edited.

These tests fail when the two drift apart:
  · trail_stop()      is compared by EXECUTION against user_loop._manage_trailing()
  · calc_entry_sltp() is compared against the ATR multipliers/floor found in
    user_loop.py's source (that block is inline in _loop(), so it cannot be
    called directly — a source check is the honest fallback)

Run: python tests/test_userloop_mirror.py
"""
import os
import re
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import position, user_loop  # noqa: E402


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0


class _StubBroker:
    """Accepts every amend and records it — _manage_trailing only moves the
    stop when the broker confirms, so it must return True."""

    def __init__(self):
        self.amended = []

    def amend_sltp(self, pid, sl=None, instrument=None):
        self.amended.append((pid, sl, instrument))
        return True


def _live_trail(side, entry, cur_sl, price, trailing, breakeven_r):
    """Whatever the REAL user_loop._manage_trailing() decides."""
    cfg = types.SimpleNamespace(TRAILING_STOP=trailing, BREAKEVEN_AT_R=breakeven_r)
    pos = {"positionId": 1, "entryPrice": entry, "stopLoss": cur_sl, "side": side}
    return user_loop._manage_trailing(_StubBroker(), cfg, pos, "EUR_USD", price)


print("\n1. trail_stop() matches user_loop._manage_trailing()")
# Grid spans: losing / flat / winning, stop below+above entry (the ratchet
# crossing entry is where the live risk= abs(entry-cur_sl) quirk shows up),
# trailing on/off, breakeven on/off, both directions.
cases = []
for side, entry in (("BUY", 1.1000), ("SELL", 1.1000)):
    for sl_off in (0.0020, 0.0010, -0.0010):       # stop below / at / past entry
        cur_sl = entry - sl_off if side == "BUY" else entry + sl_off
        for move in (-0.0030, 0.0, 0.0005, 0.0020, 0.0050, 0.0200):
            price = entry + move if side == "BUY" else entry - move
            for trailing in (True, False):
                for be_r in (0.0, 1.0):
                    cases.append((side, entry, cur_sl, price, trailing, be_r))

mismatches = []
for side, entry, cur_sl, price, trailing, be_r in cases:
    live = _live_trail(side, entry, cur_sl, price, trailing, be_r)
    mirror = position.trail_stop(side, entry, cur_sl, price,
                                 trailing=trailing, breakeven_r=be_r)
    both_none = live is None and mirror is None
    if not (both_none or (live is not None and mirror is not None
                          and abs(live - mirror) < 1e-9)):
        mismatches.append(
            f"side={side} sl={cur_sl:.5f} px={price:.5f} trail={trailing} "
            f"be={be_r} → live={live} mirror={mirror}")

check(f"all {len(cases)} trailing scenarios agree",
      not mismatches, "; ".join(mismatches[:4]))

print("\n2. trail_stop() honours the documented contract")
check("no move while the trade is under water",
      position.trail_stop("BUY", 1.10, 1.098, 1.099) is None)
check("no move when both trailing and breakeven are off",
      position.trail_stop("BUY", 1.10, 1.098, 1.11,
                          trailing=False, breakeven_r=0) is None)
check("tighten-only: never returns a looser stop",
      all((position.trail_stop("BUY", 1.10, 1.098, px) or 1.098) >= 1.098
          for px in (1.101, 1.105, 1.12)))
_be = position.trail_stop("BUY", 1.10, 1.098, 1.1021, trailing=False, breakeven_r=1.0)
check("breakeven at +1R lifts the stop to entry", _be == 1.10, _be)

print("\n3. calc_entry_sltp() mirrors user_loop's ATR block")
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "user_loop.py")).read()
sl_m, tp_m = position.USERLOOP_SL_ATR_MULT, position.USERLOOP_TP_ATR_MULT
check(f"user_loop still uses {sl_m:g}×ATR / {tp_m:g}×ATR",
      re.search(rf"sl_dist,\s*tp_dist\s*=\s*{sl_m}\s*\*\s*atr_v,\s*{tp_m}\s*\*\s*atr_v", src)
      is not None,
      "user_loop.py changed its ATR multipliers — update position.py's mirror")
check("user_loop still floors the stop at 20 pips (forex)",
      re.search(r"floor_abs\s*=.*20\.0\s*\*\s*pip", src) is not None)
check("user_loop still widens the floor to 4x spread",
      re.search(r"min_stop\s*=\s*max\(\s*4\.0\s*\*\s*spread\s*\*\s*pip", src) is not None)

# ATR wide enough that the 20-pip floor does not bite: 2.5x/5x applies as-is.
sl, tp = position.calc_entry_sltp("BUY", 1.1000, 0.0010, "EUR_USD", spread_pips=1.0)
check("BUY ATR path: SL = 2.5xATR", abs(sl - (1.1000 - 0.0025)) < 1e-9, sl)
check("BUY ATR path: TP = 5xATR", abs(tp - (1.1000 + 0.0050)) < 1e-9, tp)
sl_s, tp_s = position.calc_entry_sltp("SELL", 1.1000, 0.0010, "EUR_USD", spread_pips=1.0)
check("SELL mirrors the BUY distances",
      abs(sl_s - (1.1000 + 0.0025)) < 1e-9 and abs(tp_s - (1.1000 - 0.0050)) < 1e-9,
      (sl_s, tp_s))

# Tiny ATR → the 20-pip floor takes over and TP is re-derived as 2xSL (RR 1:2).
sl_f, tp_f = position.calc_entry_sltp("BUY", 1.1000, 0.00001, "EUR_USD", spread_pips=1.0)
check("floor bites on tiny ATR: SL = 20 pips",
      abs(sl_f - (1.1000 - 0.0020)) < 1e-9, sl_f)
check("floor keeps RR >= 1:2 (TP = 2xSL)",
      abs(tp_f - (1.1000 + 0.0040)) < 1e-9, tp_f)

_sl_w, _ = position.calc_entry_sltp("BUY", 1.1000, 0.00001, "EUR_USD", spread_pips=10.0)
check("wide spread widens the floor beyond 20 pips", _sl_w < 1.0980, _sl_w)

print("\n4. exit_trigger() uses the bar range, not the close")
check("wick through the stop fills it (the close-only bug)",
      position.exit_trigger("BUY", 1.0980, 1.1050, bar_high=1.1000,
                            bar_low=1.0975) == "STOP_LOSS")
check("wick through the target fills it",
      position.exit_trigger("BUY", 1.0980, 1.1050, bar_high=1.1060,
                            bar_low=1.0995) == "TAKE_PROFIT")
check("bar spanning both resolves to the stop (pessimistic tie-break)",
      position.exit_trigger("BUY", 1.0980, 1.1050, bar_high=1.1060,
                            bar_low=1.0975) == "STOP_LOSS")
check("untouched bar returns None",
      position.exit_trigger("BUY", 1.0980, 1.1050, bar_high=1.1000,
                            bar_low=1.0990) is None)
check("SELL: stop is above, target below",
      position.exit_trigger("SELL", 1.1050, 1.0980, bar_high=1.1060,
                            bar_low=1.1000) == "STOP_LOSS"
      and position.exit_trigger("SELL", 1.1050, 1.0980, bar_high=1.1010,
                                bar_low=1.0975) == "TAKE_PROFIT")

# ─── Result ───────────────────────────────────────────────
print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — backtest exits mirror the live user_loop.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
