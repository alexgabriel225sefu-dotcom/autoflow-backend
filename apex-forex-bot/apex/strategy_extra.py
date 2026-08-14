"""The blueprint §2 categories the bot did not have: momentum, session
breakout, and quant/statistical.

Unlike apex/strategy_modules.py, these are NOT adapters over an existing
engine — they are new decision logic, so they get held to the same standard
the existing ones are: every verdict names the numbers it was based on, and
every strategy refuses to trade the conditions it is known to be bad in.

Shared discipline across all of them:

  * A setup is only a signal when the market REGIME allows it. A momentum
    entry in a dead tape and a breakout in chop are the two ways these
    families lose money, so each declines rather than shrugs.
  * advise_risk() is advisory and clamped by the base class to the band the
    live sizing code already enforces. None of these can enlarge a position
    beyond what the Risk Engine computed.
  * exit() answers only "has my thesis broken", never "take profit here" —
    the stop, the target and MIN_EXIT_R are the loop's job.
"""
from apex.strategy_api import Strategy, register


def _f(d, key, default=0.0):
    try:
        v = d.get(key)
        return default if v is None else float(v)
    except (TypeError, ValueError, AttributeError):
        return default


def _verdict(action, confidence, score, reason, factors, risk="MEDIUM"):
    return {"action": action, "confidence": int(confidence),
            "criteriaScore": int(score), "reasoning": reason,
            "riskLevel": risk, "keyFactors": list(factors)}


def _hold(reason, factors=()):
    return _verdict("HOLD", 40, 0, reason, factors, "LOW")


class BaseExtra(Strategy):
    """Shared read + a thesis-broken exit. Subclasses implement `decide`."""

    def analyze(self, market):
        ind = market.indicators
        return self.stamp({
            "rsi": ind.get("rsi"), "adx": ind.get("adx"),
            "macdHist": ind.get("macdHist"), "bb_position": ind.get("bb_position"),
            "bb_bandwidth": ind.get("bb_bandwidth"), "atrPct": ind.get("atrPct"),
            "regime": market.regime, "session": (market.strat or {}).get("session"),
        })

    def decide(self, market, ind):
        raise NotImplementedError

    def signal(self, market):
        ind = market.indicators or {}
        pos = market.open_position
        if pos:
            ex = self._thesis_broken(market, ind, pos)
            if ex:
                return self.stamp(ex)
            return self.stamp(_hold("thesis intact — letting the stop and "
                                    "target do their job"))
        return self.stamp(self.decide(market, ind))

    def _thesis_broken(self, market, ind, pos):
        """CLOSE only when the reason for the trade is gone. None = hold."""
        side = pos.get("side")
        hist = _f(ind, "macdHist")
        if side == "BUY" and hist < 0:
            return _verdict("CLOSE", 60, 1, f"{self.label}: momentum flipped "
                            f"negative (MACD hist {hist:.5f}) — thesis broken",
                            ["momentum flip"], "LOW")
        if side == "SELL" and hist > 0:
            return _verdict("CLOSE", 60, 1, f"{self.label}: momentum flipped "
                            f"positive (MACD hist {hist:.5f}) — thesis broken",
                            ["momentum flip"], "LOW")
        return None

    def exit(self, market):
        pos = market.open_position
        if not pos:
            return self.stamp({"exit": False, "action": "HOLD",
                               "reason": "no open position"})
        v = self._thesis_broken(market, market.indicators or {}, pos)
        return self.stamp({"exit": bool(v), "action": v["action"] if v else "HOLD",
                           "reason": v["reasoning"] if v else "thesis intact",
                           "verdict": v})


# ── Momentum ────────────────────────────────────────────────────────────
@register
class MomentumStrategy(BaseExtra):
    """Ride established momentum, but refuse an exhausted move.

    The failure mode of every momentum strategy is buying the top of the
    move it just measured, so RSI is used as a CEILING, not a trigger: above
    75 the move is late and this declines. ADX gates it to a market that is
    actually trending — momentum readings in chop are noise.
    """
    strategy_id = "momentum"
    strategy_version = "1.0.0"
    label = "Momentum (RSI + MACD + ADX)"

    RSI_FLOOR, RSI_CEILING, ADX_MIN = 52.0, 75.0, 20.0

    def decide(self, market, ind):
        rsi, adx = _f(ind, "rsi", 50), _f(ind, "adx")
        hist, price = _f(ind, "macdHist"), _f(ind, "price")
        ema20 = _f(ind, "ema20")
        if adx < self.ADX_MIN:
            return _hold(f"no trend to ride (ADX {adx:.0f} < {self.ADX_MIN:.0f}) "
                         f"— momentum in chop is noise", ["ADX too low"])
        up = rsi >= self.RSI_FLOOR and hist > 0 and price > ema20 > 0
        dn = rsi <= (100 - self.RSI_FLOOR) and hist < 0 and 0 < price < ema20
        if up and rsi > self.RSI_CEILING:
            return _hold(f"momentum is late (RSI {rsi:.0f} > {self.RSI_CEILING:.0f}) "
                         f"— not chasing the top", ["exhausted"])
        if dn and rsi < (100 - self.RSI_CEILING):
            return _hold(f"momentum is late (RSI {rsi:.0f}) — not chasing the bottom",
                         ["exhausted"])
        conf = min(88, 55 + int(adx / 2) + (5 if abs(hist) > 0 else 0))
        if up:
            return _verdict("BUY", conf, 3, f"Momentum BUY: ADX {adx:.0f} trending, "
                            f"MACD hist {hist:+.5f}, RSI {rsi:.0f}, price above EMA20",
                            [f"ADX {adx:.0f}", f"RSI {rsi:.0f}", "MACD positive"])
        if dn:
            return _verdict("SELL", conf, 3, f"Momentum SELL: ADX {adx:.0f} trending, "
                            f"MACD hist {hist:+.5f}, RSI {rsi:.0f}, price below EMA20",
                            [f"ADX {adx:.0f}", f"RSI {rsi:.0f}", "MACD negative"])
        return _hold(f"momentum not aligned (RSI {rsi:.0f}, MACD hist {hist:+.5f})",
                     ["not aligned"])

    def advise_risk(self, market):
        adx = _f(market.indicators, "adx")
        return {"multiplier": 1.1 if adx >= 30 else 1.0,
                "basis": "ADX strength", "adx": adx}


# ── Session breakout ────────────────────────────────────────────────────
def _session_range(candles, bars):
    window = candles[-bars:] if len(candles) >= bars else candles
    highs = [_f(c, "high") for c in window if _f(c, "high")]
    lows = [_f(c, "low") for c in window if _f(c, "low")]
    return (max(highs) if highs else 0.0), (min(lows) if lows else 0.0)


@register
class SessionBreakoutStrategy(BaseExtra):
    """Break of the prior quiet range, taken only in a liquid session.

    The blueprint asks for Asian-range / London / New York breakouts. The
    ingredient that makes those work is not the clock, it is that a range
    built in thin liquidity gets resolved when volume arrives — so the range
    is measured over the preceding quiet window and the entry is gated on
    being in an active session. A break with no session behind it is the
    classic false breakout this family is known for.
    """
    strategy_id = "session_breakout"
    strategy_version = "1.0.0"
    label = "Session Breakout (range → liquidity)"

    RANGE_BARS = 16          # the quiet window that defines the range
    BUFFER_ATR = 0.15        # how far past the edge counts as a real break

    def decide(self, market, ind):
        sess = (market.strat or {}).get("session") or ""
        live = bool(sess) and "closed" not in str(sess).lower()
        if not live:
            return _hold(f"no active session ({sess or 'closed'}) — a break "
                         f"without liquidity behind it is the false one",
                         ["session closed"])
        candles = market.candles[:-1]           # exclude the forming bar
        hi, lo = _session_range(candles, self.RANGE_BARS)
        if not hi or not lo or hi <= lo:
            return _hold("no usable range yet", ["no range"])
        price, atr = _f(ind, "price"), _f(ind, "atr")
        buf = atr * self.BUFFER_ATR
        width_atr = (hi - lo) / atr if atr else 0
        if width_atr > 6:
            return _hold(f"the '{self.RANGE_BARS}-bar range' is {width_atr:.1f} ATR "
                         f"wide — that is a trend, not a range", ["not a range"])
        conf = min(85, 60 + int(_f(ind, "volumeRatio", 1) * 10))
        if price > hi + buf:
            return _verdict("BUY", conf, 3, f"Session breakout BUY: {price:.5f} cleared "
                            f"the {self.RANGE_BARS}-bar high {hi:.5f} by "
                            f"{buf:.5f} in {sess}",
                            [f"broke {hi:.5f}", sess])
        if price < lo - buf:
            return _verdict("SELL", conf, 3, f"Session breakout SELL: {price:.5f} broke "
                            f"the {self.RANGE_BARS}-bar low {lo:.5f} by "
                            f"{buf:.5f} in {sess}",
                            [f"broke {lo:.5f}", sess])
        return _hold(f"inside the range {lo:.5f}–{hi:.5f} — waiting for a break",
                     ["inside range"])


@register
class OpeningRangeStrategy(SessionBreakoutStrategy):
    """The same idea on a tighter, faster window — the opening range."""
    strategy_id = "opening_range"
    strategy_version = "1.0.0"
    label = "Opening Range Breakout"
    RANGE_BARS = 6
    BUFFER_ATR = 0.10


# ── Quant / statistical ─────────────────────────────────────────────────
@register
class ZScoreStrategy(BaseExtra):
    """Fade a statistically extreme deviation from the mean.

    Bollinger position answers "far from the mean" on a fixed band; a z-score
    answers "far relative to how far this instrument usually goes", which is
    the same question asked in units that survive a change of volatility.
    Only taken when the market is NOT trending — fading a trend is how mean
    reversion produced the losing week this bot already lived through.
    """
    strategy_id = "zscore"
    strategy_version = "1.0.0"
    label = "Z-Score Reversion (statistical)"

    LOOKBACK, ENTRY_Z, ADX_MAX = 40, 2.0, 25.0

    def _z(self, market, price):
        closes = [_f(c, "close") for c in market.candles[-self.LOOKBACK:]]
        closes = [c for c in closes if c]
        if len(closes) < 10:
            return None, 0.0, 0.0
        mean = sum(closes) / len(closes)
        var = sum((c - mean) ** 2 for c in closes) / len(closes)
        sd = var ** 0.5
        if sd <= 0:
            return None, mean, 0.0
        return (price - mean) / sd, mean, sd

    def decide(self, market, ind):
        adx, price = _f(ind, "adx"), _f(ind, "price")
        if adx > self.ADX_MAX:
            return _hold(f"trending market (ADX {adx:.0f} > {self.ADX_MAX:.0f}) "
                         f"— not fading a trend", ["ADX too high"])
        z, mean, sd = self._z(market, price)
        if z is None:
            return _hold("not enough history for a z-score", ["no history"])
        conf = min(85, 55 + int(abs(z) * 12))
        if z <= -self.ENTRY_Z:
            return _verdict("BUY", conf, 3, f"Z-score BUY: {z:.2f}σ below the "
                            f"{self.LOOKBACK}-bar mean {mean:.5f} (σ {sd:.5f}), "
                            f"ADX {adx:.0f} — statistically stretched, not trending",
                            [f"z {z:.2f}", f"ADX {adx:.0f}"])
        if z >= self.ENTRY_Z:
            return _verdict("SELL", conf, 3, f"Z-score SELL: {z:.2f}σ above the "
                            f"{self.LOOKBACK}-bar mean {mean:.5f} (σ {sd:.5f}), "
                            f"ADX {adx:.0f}",
                            [f"z {z:.2f}", f"ADX {adx:.0f}"])
        return _hold(f"z-score {z:.2f} inside ±{self.ENTRY_Z} — no edge",
                     [f"z {z:.2f}"])

    def _thesis_broken(self, market, ind, pos):
        """Reverting means going BACK to the mean — momentum is not the test."""
        z, _m, _s = self._z(market, _f(ind, "price"))
        if z is None:
            return None
        side = pos.get("side")
        if (side == "BUY" and z >= 0) or (side == "SELL" and z <= 0):
            return _verdict("CLOSE", 62, 1, f"Z-Score: back at the mean "
                            f"(z {z:.2f}) — thesis complete", ["reverted"], "LOW")
        if abs(z) > self.ENTRY_Z * 2:
            return _verdict("CLOSE", 55, 1, f"Z-Score: deviation widened to "
                            f"{z:.2f}σ — the mean is not holding",
                            ["thesis broken"], "LOW")
        return None


@register
class VolRegimeStrategy(BaseExtra):
    """Trade the expansion out of a volatility squeeze, in its direction.

    Volatility clusters: a compressed range resolves into a directional move
    far more often than a compressed range continues. This waits for the
    squeeze to actually BREAK rather than predicting which way it will go.
    """
    strategy_id = "vol_regime"
    strategy_version = "1.0.0"
    label = "Volatility Regime (squeeze → expansion)"

    SQUEEZE_BW, EXPANSION = 0.12, 1.4

    def decide(self, market, ind):
        bw = _f(ind, "bb_bandwidth")
        bbpos, hist = _f(ind, "bb_position", 50), _f(ind, "macdHist")
        closes = [_f(c, "close") for c in market.candles[-60:-10]]
        prior = None
        if len(closes) > 20:
            mid = sum(closes) / len(closes)
            sd = (sum((c - mid) ** 2 for c in closes) / len(closes)) ** 0.5
            prior = (sd / mid * 100) if mid else None
        if bw <= self.SQUEEZE_BW:
            return _hold(f"still squeezed (bandwidth {bw:.3f}) — waiting for the "
                         f"expansion, not guessing its direction", ["in squeeze"])
        if prior is not None and bw < prior * self.EXPANSION:
            return _hold(f"bandwidth {bw:.3f} has not expanded enough over the "
                         f"prior {prior:.3f} — no regime change yet",
                         ["no expansion"])
        conf = min(84, 58 + int(bw * 20))
        if bbpos >= 70 and hist > 0:
            return _verdict("BUY", conf, 3, f"Volatility expansion BUY: bandwidth "
                            f"{bw:.3f}, price at {bbpos:.0f}% of the band with "
                            f"positive momentum", [f"bw {bw:.3f}", "upper band"])
        if bbpos <= 30 and hist < 0:
            return _verdict("SELL", conf, 3, f"Volatility expansion SELL: bandwidth "
                            f"{bw:.3f}, price at {bbpos:.0f}% of the band with "
                            f"negative momentum", [f"bw {bw:.3f}", "lower band"])
        return _hold(f"expanding (bandwidth {bw:.3f}) but no direction yet "
                     f"(band {bbpos:.0f}%)", ["no direction"])
