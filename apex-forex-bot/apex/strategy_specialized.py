"""Grid and martingale — quarantined, capped, and honest about the caps.

Blueprint §2 lists these "separat, cu avertismente și limite stricte de risc".
Separate file, so nobody adds one of these by accident while editing the
ordinary strategies.

READ THIS BEFORE ENABLING EITHER.

Both families work by adding exposure to a position that is already losing.
That converts a string of small losses into one large one, and it is the
single most common way a retail account is emptied. They are included because
they were asked for; they are capped because the caps are the only reason
including them is defensible.

What the architecture already prevents, regardless of what these ask for:

  * advise_risk() is ADVISORY. Strategy.risk() clamps it into [0.4, 1.2] and
    advisory_multiplier() clamps it again at the Risk Engine's read. Neither
    of these can double a position. A classic martingale needs 2x, 4x, 8x —
    the ceiling here is 1.2x, so the progression is a lean, not a doubling.
    That is deliberate and it is not negotiable from inside a strategy.
  * The loop runs ONE position at a time (maxpos). A textbook grid holds many
    open orders at once; this cannot. It re-enters at grid distances instead,
    one at a time.
  * The daily-loss and drawdown circuit breakers in apex/strategies.py sit
    outside the strategy interface and cannot be reached from here.

So what is shipped is a CAPPED progression, not the unbounded thing the names
usually mean. Anyone reading "martingale" and expecting doubling should read
MAX_STEPS and the clamp above instead.
"""
from apex import strategies as _st
from apex.strategy_api import Strategy, register
from apex.strategy_extra import BaseExtra, _f, _hold, _verdict


class _Specialized(BaseExtra):
    """Shared guard rail: stop the progression entirely after N losses."""

    # Beyond this many consecutive losses the strategy refuses to trade at
    # all. Not a suggestion to the Risk Engine — a refusal to emit a signal.
    MAX_STEPS = 3

    def _loss_streak(self, user_id=""):
        try:
            sess = _st.get_session(user_id) if user_id else {}
            return int((sess or {}).get("consecutiveLosses", 0) or 0)
        except Exception:
            return 0

    def _streak_block(self, streak):
        if streak >= self.MAX_STEPS:
            return _hold(
                f"{self.label}: {streak} losses in a row — this strategy stops "
                f"at {self.MAX_STEPS}. Adding size to a losing run is how "
                f"accounts are emptied; it will resume after a win.",
                [f"{streak} consecutive losses", "progression halted"])
        return None


@register
class GridStrategy(_Specialized):
    """Re-enter at fixed distances from a reference price.

    A real grid holds a ladder of open orders. This bot holds one position at
    a time, so what is implemented is the honest single-position form: wait
    until price has travelled a whole grid step from the recent mean, then
    take that step in the direction of reversion.

    Only in a RANGING market. A grid in a trend is a machine for averaging
    into a loss all the way down, which is its entire historical reputation.
    """
    strategy_id = "grid"
    strategy_version = "1.0.0"
    label = "Grid (capped, ranging only)"

    STEP_ATR = 0.8          # one grid step, in ATR
    ADX_MAX = 22.0          # above this it is a trend, not a range

    def decide(self, market, ind):
        blocked = self._streak_block(self._loss_streak(getattr(market, "user_id", "")))
        if blocked:
            return blocked
        adx = _f(ind, "adx")
        if adx > self.ADX_MAX:
            return _hold(f"Grid: ADX {adx:.0f} — this is a trend. A grid in a "
                         f"trend averages into a loss the whole way down.",
                         ["trending", f"ADX {adx:.0f}"])
        price, atr = _f(ind, "price"), _f(ind, "atr")
        mid = _f(ind, "bb_mid")
        if not (price and atr and mid):
            return _hold("Grid: missing price/ATR/mid", ["no data"])
        step = atr * self.STEP_ATR
        dist = price - mid
        steps = abs(dist) / step if step else 0
        if steps < 1:
            return _hold(f"Grid: {steps:.2f} steps from the mean — waiting for a "
                         f"full step ({step:.5f})", [f"{steps:.2f} steps"])
        conf = min(72, 52 + int(steps * 8))
        side = "BUY" if dist < 0 else "SELL"
        return _verdict(side, conf, 2,
                        f"Grid {side}: {steps:.1f} step(s) {'below' if dist < 0 else 'above'} "
                        f"the mean {mid:.5f} (step {step:.5f}, ADX {adx:.0f} ranging)",
                        [f"{steps:.1f} steps", f"ADX {adx:.0f}"], "HIGH")

    def advise_risk(self, market):
        # Grid takes MORE entries, so each one is smaller. The clamp floor is
        # 0.4, which is where this deliberately sits.
        return {"multiplier": 0.5, "basis": "grid: many small entries"}


@register
class MartingaleStrategy(_Specialized):
    """Increase size after a loss — within a ceiling that makes it survivable.

    The honest description: a doubling martingale needs 2x, 4x, 8x. The
    advisory band tops out at 1.2x, so what this does is lean slightly harder
    after a loss and stop entirely after MAX_STEPS. It will not recover a
    losing streak in one trade, because nothing that could do that is safe on
    a real account.

    Direction comes from mean reversion — martingale is a SIZING scheme, not
    an entry signal, and pairing it with a random entry is what turns it from
    dangerous into ruinous.
    """
    strategy_id = "martingale"
    strategy_version = "1.0.0"
    label = "Martingale (capped 1.2x, stops at 3 losses)"

    ADX_MAX = 25.0

    def decide(self, market, ind):
        streak = self._loss_streak(getattr(market, "user_id", ""))
        blocked = self._streak_block(streak)
        if blocked:
            return blocked
        adx = _f(ind, "adx")
        if adx > self.ADX_MAX:
            return _hold(f"Martingale: ADX {adx:.0f} — adding size against a "
                         f"trend is the ruinous version of this strategy.",
                         ["trending", f"ADX {adx:.0f}"])
        rsi, bbpos = _f(ind, "rsi", 50), _f(ind, "bb_position", 50)
        step_note = (f" (recovery step {streak + 1}/{self.MAX_STEPS})"
                     if streak else "")
        if rsi <= 32 and bbpos <= 20:
            return _verdict("BUY", 66, 2, f"Martingale BUY: oversold (RSI {rsi:.0f}, "
                            f"band {bbpos:.0f}%) in a ranging market{step_note}",
                            [f"RSI {rsi:.0f}", f"streak {streak}"], "HIGH")
        if rsi >= 68 and bbpos >= 80:
            return _verdict("SELL", 66, 2, f"Martingale SELL: overbought (RSI {rsi:.0f}, "
                            f"band {bbpos:.0f}%) in a ranging market{step_note}",
                            [f"RSI {rsi:.0f}", f"streak {streak}"], "HIGH")
        return _hold(f"Martingale: no reversion setup (RSI {rsi:.0f}, "
                     f"band {bbpos:.0f}%)", ["no setup"])

    def advise_risk(self, market):
        """Lean harder after a loss — and hit the ceiling almost immediately.

        Spelled out so the number is not mistaken for a doubling: step 1 is
        1.0x, step 2 asks 1.15x, step 3 asks 1.3x and RECEIVES 1.2x because
        the base class clamps it. The clamp is the point.
        """
        streak = self._loss_streak(getattr(market, "user_id", ""))
        asked = 1.0 + 0.15 * min(streak, self.MAX_STEPS)
        return {"multiplier": asked, "basis": "martingale progression",
                "consecutive_losses": streak,
                "note": "clamped to the advisory band by Strategy.risk()"}
