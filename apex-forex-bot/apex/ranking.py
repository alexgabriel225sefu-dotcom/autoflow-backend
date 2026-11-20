"""Order the candidates, and be able to say why that order.

WHY A DOCUMENTED SCORE AND NOT A MODEL

The scanner already ranked — by confidence alone, keeping only the single
highest. That is a ranking with three problems the engine has to fix:

  * confidence is the strategy's own opinion of its trigger, so ranking by it
    compares two strategies' self-assessments as if they were one scale;
  * it ignores everything that decides whether a setup can actually be TAKEN:
    spread, regime fit, and how much of the account is already committed;
  * it discards the losers, so nothing can answer "why didn't APEX trade this
    one" for the six instruments it passed over.

The alternative is not a learned ranker. §10 forbids tuning against a small
historical sample, and this account has 124 trades — fitting weights to that
would produce a number that describes the sample rather than the market.

So the score is a weighted sum of components a person can read, each bounded
to 0..1, each carrying its own reason string. Every displayed score
corresponds to this calculation and nothing else.

WHAT THE SCORE IS NOT

It is not a probability of profit, and §10 forbids showing it as one. It is a
preference order among candidates that all already passed detection. A
candidate scoring 0.8 is not "80% likely to win"; it is ahead of one scoring
0.6 in the queue for the decision engine.
"""

import time

from apex import regime as _regime

# Component weights. They sum to 1.0 so the score stays on 0..1 and a change
# to one weight is visibly a trade against the others.
WEIGHTS = {
    "trigger":   0.30,   # the strategy's own completeness/confidence
    "regime":    0.25,   # is this strategy in the market it is built for
    "structure": 0.15,   # higher-timeframe agreement
    "cost":      0.20,   # spread against the stop it has to pay for
    "exposure":  0.10,   # how much of the account this instrument already is
}

# A spread worth this fraction of the stop distance scores zero on cost. Past
# it, the setup is not ranked last — it is rejected outright by the decision
# engine, because a cost that large changes the break-even win rate more than
# any edge the strategy claims.
COST_ZERO_AT = 0.25

RANKING_VERSION = "1.0.0"


def _clamp01(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _trigger_component(c):
    conf = c.features.get("confidence")
    if conf is None:
        return None, "no confidence recorded"
    v = _clamp01(float(conf) / 100.0)
    return v, f"strategy confidence {conf}%"


def _regime_component(c):
    r = c.regime
    if r is None or not getattr(r, "valid", False):
        return None, "regime not read"
    fit = r.fits(c.strategy_id)
    if fit is None:
        return None, f"no fit defined for {c.strategy_id} in {r.regime}"
    if not fit:
        return 0.0, f"{c.strategy_id} is not built for {r.regime}"
    # A firm reading of a fitting regime is worth more than a marginal one.
    conf = r.confidence
    v = 0.6 + 0.4 * _clamp01(conf) if conf is not None else 0.6
    return v, f"{c.strategy_id} fits {r.regime}"


def _structure_component(c):
    htf = c.features.get("htfTrend")
    if htf is None:
        return None, "higher timeframe not read"
    want = "BULLISH" if c.direction == "BUY" else "BEARISH"
    if htf == want:
        return 1.0, f"higher timeframe {htf} agrees"
    if htf in ("BULLISH", "BEARISH"):
        return 0.0, f"higher timeframe {htf} disagrees"
    return 0.5, f"higher timeframe {htf}"


def _cost_component(c):
    spread = c.features.get("spreadPips")
    sl = c.features.get("slPips")
    if spread is None or not sl:
        return None, "spread or stop distance not measured"
    try:
        ratio = float(spread) / float(sl)
    except (TypeError, ValueError, ZeroDivisionError):
        return None, "cost not computable"
    v = _clamp01(1.0 - ratio / COST_ZERO_AT)
    return v, f"spread is {ratio * 100:.1f}% of the stop"


def _exposure_component(c):
    """How much room is left on this instrument.

    `exposureCount` and `maxPositions` come from the caller, which reads them
    from the account. They are not derived here: a ranking module inventing an
    exposure number is exactly the kind of second implementation that made
    equity disagree with itself across three files.
    """
    used = c.features.get("exposureCount")
    cap = c.features.get("maxPositions")
    if used is None or not cap:
        return None, "exposure not read"
    if c.features.get("sameSymbolOpen"):
        return 0.0, f"{c.symbol} is already open"
    v = _clamp01(1.0 - float(used) / float(cap))
    return v, f"{used} of {cap} slots used"


_COMPONENTS = (
    ("trigger", _trigger_component),
    ("regime", _regime_component),
    ("structure", _structure_component),
    ("cost", _cost_component),
    ("exposure", _exposure_component),
)


def score(candidate):
    """(score, reasons) for one candidate. Deterministic; never raises.

    A component that could not be measured is EXCLUDED and its weight is
    redistributed, rather than scored zero. Scoring an unread spread as zero
    would rank a candidate below one whose spread is genuinely terrible, which
    inverts the meaning of the number — the whole point of the tri-state is
    that "unknown" and "bad" are different answers.

    When nothing at all could be measured the score is None. A caller must not
    turn that into 0.0: an unrankable candidate is not a bad one.
    """
    parts, reasons, weight_used = [], [], 0.0
    for name, fn in _COMPONENTS:
        try:
            v, why = fn(candidate)
        except Exception as e:                    # a ranking bug must not stop a loop
            v, why = None, f"component failed: {str(e)[:60]}"
        w = WEIGHTS[name]
        if v is None:
            reasons.append({"component": name, "value": None, "weight": 0.0,
                            "reason": why})
            continue
        parts.append(v * w)
        weight_used += w
        reasons.append({"component": name, "value": round(v, 3), "weight": w,
                        "reason": why})
    if weight_used <= 0:
        return None, reasons
    total = round(sum(parts) / weight_used, 4)
    reasons.append({"component": "_coverage", "value": round(weight_used, 3),
                    "weight": 1.0,
                    "reason": f"{weight_used * 100:.0f}% of the score was measurable"})
    return total, reasons


def rank(candidates):
    """Score every candidate and return them ordered, best first.

    Unrankable candidates are kept and sorted LAST, still carrying their
    reasons. Dropping them here would recreate the exact hole this module
    exists to close — a screen that cannot say why an instrument was passed
    over.

    The sort is stable and fully ordered: ties break on symbol then direction,
    so the same input always produces the same output. A ranking that reorders
    between identical runs cannot be tested and cannot be replayed.
    """
    out = []
    for c in candidates or []:
        s, why = score(c)
        c.rank_score = s
        c.rank_reasons = why
        out.append(c)
    out.sort(key=lambda c: (c.rank_score is None,
                            -(c.rank_score or 0.0),
                            c.symbol, c.direction))
    return out


def explain(candidate):
    """The score as lines a person reads, for §26 and §61."""
    if candidate.rank_score is None:
        head = "Not ranked — nothing measurable"
    else:
        head = f"Rank score {candidate.rank_score:.2f} (v{RANKING_VERSION})"
    lines = [head]
    for r in candidate.rank_reasons or []:
        if r["component"] == "_coverage":
            continue
        mark = "?" if r["value"] is None else f"{r['value']:.2f}"
        lines.append(f"  {r['component']:<10} {mark:>5}  {r['reason']}")
    return "\n".join(lines)


def snapshot(candidates, *, at=None):
    """A recordable view of one ranking pass — what the scanner saw, in order.

    This is what makes §61 answerable: the losers are kept with their reasons,
    so "why didn't APEX trade GBPUSD" has a stored answer instead of a shrug.
    """
    return {
        "at": round(at or time.time(), 3),
        "rankingVersion": RANKING_VERSION,
        "weights": dict(WEIGHTS),
        "candidates": [{
            "symbol": c.symbol, "direction": c.direction,
            "strategyId": c.strategy_id, "status": c.status,
            "score": c.rank_score, "reasons": c.rank_reasons,
            "regime": (c.regime.regime if c.regime is not None
                       else _regime.UNKNOWN),
        } for c in candidates or []],
    }
