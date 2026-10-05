"""What kind of market this is, with the measurements that say so.

WHY THIS WRAPS strategies.detect_regime RATHER THAN REPLACING IT

`strategies.detect_regime` already does the hard part, and does it well: it
classifies from RATIOS rather than absolute thresholds, so the same code works
on EURUSD, on gold and on an index without a per-symbol table. Its reference
window is 400 bars precisely because a 100-bar base converges with the present
after about ninety minutes and stops detecting the regime it is measuring.

Throwing that away to satisfy a vocabulary would be a rewrite of working
calibration. So this module keeps the measurement and adds the three things the
engine needs and the original does not have:

  1. a stable vocabulary the decision engine and the UI can both rely on;
  2. the EVIDENCE — the numbers that produced the answer, so §26's "why" screen
     shows a reading rather than an adjective;
  3. an explicit UNKNOWN, and a validity flag, so insufficient data is reported
     as insufficient instead of being rounded to "ranging".

REVERSAL IS DELIBERATELY NOT EMITTED

§8 lists it, and §8 also says not to force a classification when evidence is
insufficient. Nothing in this repository measures reversal: there is no
divergence detector, no failed-breakout detector, and no swing-failure logic.
Emitting REVERSAL from an RSI extreme would be a label the platform cannot
defend, on the screen where a client decides whether to trust it. It is left
unimplemented and documented rather than approximated.
"""

import time

# ── Vocabulary ───────────────────────────────────────────────────────────
TRENDING = "TRENDING"
RANGING = "RANGING"
BREAKOUT = "BREAKOUT"
HIGH_VOLATILITY = "HIGH_VOLATILITY"
LOW_VOLATILITY = "LOW_VOLATILITY"
UNSTABLE = "UNSTABLE"
UNKNOWN = "UNKNOWN"

REGIMES = (TRENDING, RANGING, BREAKOUT, HIGH_VOLATILITY, LOW_VOLATILITY,
           UNSTABLE, UNKNOWN)

# Which regimes each strategy family is designed for. Used by ranking (§10) to
# discount a setup that is being taken against the market it is worst in — not
# to forbid it, because a discount that can be inspected is more useful than a
# veto that cannot.
STRATEGY_FIT = {
    "trend":           {TRENDING, BREAKOUT},
    "breakout":        {BREAKOUT, HIGH_VOLATILITY},
    "mean_reversion":  {RANGING, LOW_VOLATILITY},
    "fibonacci":       {TRENDING, RANGING},
    "fvg":             {TRENDING, BREAKOUT},
    "ifvg":            {RANGING, TRENDING},
    "supply_demand":   {RANGING, TRENDING},
    "liquidity_sweep": {HIGH_VOLATILITY, BREAKOUT},
    "evc":             {TRENDING},
}

# The old vocabulary, kept so a stored reading from before this module can
# still be understood. `quiet` and `volatile` were the two the loop acted on.
_LEGACY = {
    "trending": TRENDING,
    "ranging": RANGING,
    "volatile": HIGH_VOLATILITY,
    "quiet": LOW_VOLATILITY,
    "unknown": UNKNOWN,
}


class Reading:
    """One regime classification, with the numbers behind it."""

    __slots__ = ("regime", "confidence", "evidence", "at", "valid", "label",
                 "symbol", "timeframe")

    def __init__(self, regime, *, evidence=None, valid=True, label="",
                 symbol=None, timeframe=None, confidence=None, at=None):
        self.regime = regime if regime in REGIMES else UNKNOWN
        # Not a probability, and never presented as one. It is how far the
        # measurement sat from its own decision boundary, on 0..1 — a reading
        # that only just crossed a threshold should not look as firm as one
        # that cleared it by a mile.
        self.confidence = confidence
        self.evidence = dict(evidence or {})
        self.valid = bool(valid)
        self.label = label
        self.symbol = symbol
        self.timeframe = timeframe
        self.at = at or time.time()

    def fits(self, strategy_id):
        """Whether `strategy_id` is designed for this regime.

        UNKNOWN fits nothing and blocks nothing: it returns None, so a caller
        must decide what to do about not knowing rather than being handed a
        False that reads as "this strategy is wrong here".
        """
        if self.regime == UNKNOWN or not self.valid:
            return None
        fit = STRATEGY_FIT.get(str(strategy_id or "").lower())
        if fit is None:
            return None
        return self.regime in fit

    def to_dict(self):
        return {"regime": self.regime, "confidence": self.confidence,
                "label": self.label, "valid": self.valid,
                "evidence": self.evidence, "symbol": self.symbol,
                "timeframe": self.timeframe, "at": round(self.at, 3)}

    def __repr__(self):
        return f"<Regime {self.symbol or '?'} {self.regime} valid={self.valid}>"


def unknown(symbol=None, reason="insufficient data", timeframe=None):
    """The honest answer when the market could not be read."""
    return Reading(UNKNOWN, valid=False, label=reason, symbol=symbol,
                   timeframe=timeframe, evidence={"reason": reason})


def _clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else round(x, 3))


def classify(candles, *, symbol=None, timeframe=None, breakout=None):
    """Read the market from candles. Never raises; UNKNOWN on any failure.

    `breakout` is an optional turtle-breakout reading from
    `strategies.turtle_breakout`. It is what separates BREAKOUT from
    HIGH_VOLATILITY: violent tape with no structural break is just violent
    tape, and calling it a breakout would invite trading a range at its worst
    possible moment.
    """
    from apex import strategies

    if not candles or len(candles) < 130:
        return unknown(symbol, f"only {len(candles or [])} candles, need 130",
                       timeframe)
    try:
        raw = strategies.detect_regime(candles, symbol)
    except Exception as e:
        return unknown(symbol, f"regime read failed: {str(e)[:80]}", timeframe)

    base = _LEGACY.get(str(raw.get("regime") or "").lower(), UNKNOWN)
    vol = raw.get("vol_ratio")
    ev = {"volRatio": vol, "source": "strategies.detect_regime",
          "rawRegime": raw.get("regime")}

    if base == UNKNOWN:
        return unknown(symbol, raw.get("label") or "not classified", timeframe)

    # Structure, when the caller measured it. Used twice below.
    liv = None
    try:
        liv = strategies.livermore_structure(candles)
        ev["structureTrend"] = liv.get("trend")
        ev["structureStrength"] = liv.get("strength")
    except Exception:
        pass

    regime, conf = base, None

    # A structural break during elevated volatility is a BREAKOUT. Without the
    # break it stays HIGH_VOLATILITY — the distinction is the whole reason this
    # function takes the `breakout` argument.
    if base == HIGH_VOLATILITY:
        sig = (breakout or {}).get("signal")
        strength = str((breakout or {}).get("breakoutStr") or "NONE").upper()
        ev["breakoutSignal"] = sig
        ev["breakoutStrength"] = strength
        if sig in ("BUY", "SELL") and strength not in ("NONE", ""):
            regime = BREAKOUT
        elif liv and str(liv.get("trend") or "") not in ("BULLISH", "BEARISH"):
            # Violent AND directionless. Trading either edge of that is how a
            # stop gets taken twice in one bar.
            regime = UNSTABLE
        if vol:
            conf = _clamp01((float(vol) - 1.8) / 1.2)

    elif base == LOW_VOLATILITY and vol:
        conf = _clamp01((0.42 - float(vol)) / 0.42)

    elif base == TRENDING and liv:
        conf = _clamp01((float(liv.get("strength") or 0) - 0.55) / 0.45)

    elif base == RANGING and vol:
        # Firmest in the middle of the band, weakest near either edge.
        try:
            v = float(vol)
            conf = _clamp01(1.0 - abs(v - 1.0) / 0.8)
        except (TypeError, ValueError):
            conf = None

    return Reading(regime, evidence=ev, valid=True,
                   label=raw.get("label") or "", symbol=symbol,
                   timeframe=timeframe, confidence=conf)


def from_legacy(raw, *, symbol=None, timeframe=None):
    """Adapt a stored `strategies.detect_regime` dict to a Reading.

    For journal rows and dash state written before this module existed. Carries
    no confidence: it was never measured, and inventing one here would put a
    number on an old record that nobody computed.
    """
    if not isinstance(raw, dict):
        return unknown(symbol, "no regime recorded", timeframe)
    name = _LEGACY.get(str(raw.get("regime") or "").lower(), UNKNOWN)
    if name == UNKNOWN:
        return unknown(symbol, raw.get("label") or "not classified", timeframe)
    return Reading(name, evidence={"volRatio": raw.get("vol_ratio"),
                                   "rawRegime": raw.get("regime"),
                                   "source": "stored"},
                   valid=True, label=raw.get("label") or "", symbol=symbol,
                   timeframe=timeframe)
