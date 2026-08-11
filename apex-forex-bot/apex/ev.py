"""EV / probability / risk engine — the APEX V2 decision core.

Pipeline this implements:

    calibrated probability → regime → cost → EV → risk → SL/TP

Everything here is pure arithmetic: no I/O, no network, no third-party deps.
That keeps it unit-testable in isolation and safe to import from the live
trading loop.

WHY THIS EXISTS
---------------
The signal engine reports a "confidence" that is not a probability. It is a
rescaled indicator count (`ai.py`: ``confidence = min(85, 52 + abs_score * 8)``
— four indicators voting, mapped onto a 52-85 range). Feeding that number into
an expected-value formula as if it were P(win) produces nonsense, because a
"76%" from that expression has never been checked against how often those
setups actually reached TP before SL.

So `calibrate()` measures the real hit rate per confidence bucket from the
user's own closed trades, and every downstream formula (EV, Kelly, the
no-trade gate) runs on that measured number instead of the heuristic.

The spec's `ProbabilityEngine` assumes a trained ML model with
`predict_proba`. There is no such model and no dataset to train one yet.
Empirical bucket calibration is the honest stand-in: it uses data that already
exists, and it degrades safely (few samples → shrinks toward a conservative
prior rather than inventing confidence).
"""

import math
import random

# ── Costs ────────────────────────────────────────────────────────────────
# Slippage assumption when the broker does not report a fill difference.
# Deliberately pessimistic: underestimating cost is what turns a backtest
# positive and a live account negative.
DEFAULT_SLIPPAGE_PIPS = 0.3


def cost_in_r(spread_pips, sl_pips, slippage_pips=None, commission_pips=0.0):
    """Round-trip cost expressed in R (multiples of the stop distance).

    Cost is paid on entry (half spread + slippage) and again on exit, so the
    spread is counted once in full rather than halved.
    """
    if sl_pips is None or sl_pips <= 0:
        return float("inf")
    slip = DEFAULT_SLIPPAGE_PIPS if slippage_pips is None else slippage_pips
    total_pips = max(0.0, float(spread_pips or 0.0)) + 2.0 * max(0.0, float(slip)) \
        + max(0.0, float(commission_pips))
    return total_pips / float(sl_pips)


# ── Expected value ───────────────────────────────────────────────────────
def expected_value(probability, tp_r, sl_r=1.0, cost_r=0.0):
    """EV in R:  p × TP − (1−p) × SL − cost.

    A trade is only worth taking when this is positive. Note that a high win
    rate does NOT imply positive EV — p=0.9 with TP=0.1R and SL=1R gives
    0.9×0.1 − 0.1×1.0 = −0.01R, a losing system that wins nine times in ten.
    """
    p = max(0.0, min(1.0, float(probability)))
    return p * float(tp_r) - (1.0 - p) * float(sl_r) - float(cost_r)


def build_trade_plan(probability, sl_r, tp_r, cost_r):
    ev = expected_value(probability, tp_r, sl_r, cost_r)
    return {
        "probability": round(float(probability), 4),
        "sl_r": round(float(sl_r), 4),
        "tp_r": round(float(tp_r), 4),
        "cost_r": round(float(cost_r), 4),
        "ev_r": round(ev, 4),
        "approved": ev > 0,
    }


def breakeven_probability(tp_r, sl_r=1.0, cost_r=0.0):
    """The win rate below which this R:R loses money.

    Useful for the operator: at TP=1.7R you need >38% to break even, so a
    "low" win rate can still be very profitable — and chasing a higher win
    rate by shrinking TP raises this floor against you.
    """
    denom = float(tp_r) + float(sl_r)
    if denom <= 0:
        return 1.0
    return max(0.0, min(1.0, (float(sl_r) + float(cost_r)) / denom))


# ── Dynamic SL / TP ──────────────────────────────────────────────────────
def dynamic_sl_tp(atr_pips, structure_distance_pips=0.0, spread_pips=0.0,
                  atr_multiplier=1.25, min_sl_pips=4.0, max_sl_pips=25.0,
                  rr=1.7):
    """Stop distance from volatility, structure and cost — never a fixed pip
    count.

    The stop must clear all three or it gets taken out by noise:
      • ATR × multiplier — ordinary volatility
      • structure distance — the swing the trade is actually invalidated by
      • spread × 2 — a stop inside the spread is hit on entry
    """
    sl = max(
        float(atr_pips or 0.0) * float(atr_multiplier),
        float(structure_distance_pips or 0.0),
        float(spread_pips or 0.0) * 2.0,
        float(min_sl_pips),
    )
    sl = min(sl, float(max_sl_pips))
    return sl, sl * float(rr)


# ── Position sizing ──────────────────────────────────────────────────────
def fractional_kelly(p, win_loss_ratio):
    """Full Kelly fraction. Returns 0 when the edge is non-positive."""
    b = max(float(win_loss_ratio), 1e-9)
    q = 1.0 - float(p)
    return max(0.0, (b * float(p) - q) / b)


def position_risk(equity, probability, tp_r, sl_r=1.0,
                  kelly_fraction=0.10, max_risk_pct=0.50):
    """Risk for this trade, as (cash, percent-of-equity).

    Full Kelly is far too aggressive for a real account — it is optimal only
    with a perfectly known probability, and ours is estimated. `kelly_fraction`
    (default 1/10 Kelly) plus a hard `max_risk_pct` ceiling keeps a
    miscalibrated probability from sizing up into a blow-up.
    """
    b = float(tp_r) / max(float(sl_r), 1e-9)
    k = fractional_kelly(probability, b)
    risk_pct = min(k * float(kelly_fraction) * 100.0, float(max_risk_pct))
    risk_pct = max(0.0, risk_pct)
    return max(0.0, float(equity)) * risk_pct / 100.0, risk_pct


def drawdown_risk_multiplier(drawdown_pct):
    """Cut risk as the account bleeds; stop entirely past −8%.

    `drawdown_pct` is negative when down (e.g. −4.2).
    """
    dd = float(drawdown_pct)
    if dd >= 0:
        return 1.0
    if dd > -3:
        return 0.85
    if dd > -5:
        return 0.65
    if dd > -8:
        return 0.40
    return 0.0


def final_risk_pct(base_risk_pct, drawdown_pct):
    return float(base_risk_pct) * drawdown_risk_multiplier(drawdown_pct)


# ── No-trade engine ──────────────────────────────────────────────────────
# Regimes in which a directional entry is allowed at all. Matches
# strategies.detect_regime() vocabulary, which this bot already computes.
TRADEABLE_REGIMES = {"trending", "ranging", "TREND", "RANGE"}


def approve_trade(probability, ev_r, regime=None, spread_pips=None,
                  atr_pips=None, risk_ok=True, min_probability=0.55,
                  max_spread_to_atr=0.25, require_regime=True):
    """Every reason to refuse a trade, in one place.

    Returns (approved: bool, reason: str).

    `min_probability` is the operator's win-rate dial. Raising it takes fewer
    trades and wins a higher fraction of them; it does not by itself raise
    profit, and set high enough it will stop trading altogether.
    """
    if probability is None:
        return False, "NO_PROBABILITY"
    if float(probability) < float(min_probability):
        return False, "LOW_PROBABILITY"
    if ev_r is None or float(ev_r) <= 0:
        return False, "NEGATIVE_EV"
    # Spread relative to volatility — an absolute pip limit means nothing when
    # ATR swings between 4 and 40 pips across sessions and symbols.
    if spread_pips is not None and atr_pips:
        try:
            if float(spread_pips) / float(atr_pips) > float(max_spread_to_atr):
                return False, "SPREAD_TOO_HIGH"
        except ZeroDivisionError:
            return False, "SPREAD_TOO_HIGH"
    if require_regime and regime is not None and regime not in TRADEABLE_REGIMES:
        return False, "REGIME_NOT_ALLOWED"
    if not risk_ok:
        return False, "RISK_BLOCK"
    return True, "APPROVED"


# ── Probability calibration from the trade journal ───────────────────────
# Confidence buckets. The signal engine emits 52-88, so the interesting range
# is narrow and the buckets are correspondingly tight.
_BUCKETS = [(0, 60), (60, 70), (70, 76), (76, 82), (82, 101)]

# Shrinkage strength: how many "prior" observations a bucket must outweigh
# before its own hit rate dominates. Without this, a bucket holding 3 wins
# reports p=1.0, Kelly maxes out and the bot bets the account on noise.
_PRIOR_STRENGTH = 20.0


def _bucket_of(confidence):
    c = float(confidence)
    for lo, hi in _BUCKETS:
        if lo <= c < hi:
            return (lo, hi)
    return _BUCKETS[-1]


def labelled_count(journal):
    """How many closed trades carry both a confidence and a P&L.

    This is the progress counter toward `calibrate()` returning anything: rows
    written before decision-logging existed, or by broker-side reconciliation
    paths that never saw the position, are accounting-only and don't count.
    """
    n = 0
    for t in journal or []:
        pnl = t.get("netPnl")
        if pnl is None:
            pnl = t.get("grossPnl")
        if t.get("confidence") is None or pnl is None:
            continue
        try:
            float(t["confidence"]), float(pnl)
        except (TypeError, ValueError):
            continue
        n += 1
    return n


def calibrate(journal, prior=0.45, min_total=30):
    """Build a confidence → P(win) table from closed trades.

    `journal` is the list from `user_store.load_trades()`. Records need a
    `confidence` and a signed P&L (`netPnl`, falling back to `grossPnl`);
    older records predating confidence logging are skipped.

    Returns None when there is not enough labelled history to say anything —
    the caller must then fall back rather than pretend to know.
    """
    rows = []
    for t in journal or []:
        conf = t.get("confidence")
        pnl = t.get("netPnl")
        if pnl is None:
            pnl = t.get("grossPnl")
        if conf is None or pnl is None:
            continue
        try:
            rows.append((float(conf), 1 if float(pnl) > 0 else 0))
        except (TypeError, ValueError):
            continue

    if len(rows) < int(min_total):
        return None

    overall = sum(w for _, w in rows) / len(rows)
    table = {}
    for lo, hi in _BUCKETS:
        sel = [w for c, w in rows if lo <= c < hi]
        n = len(sel)
        # Shrink each bucket toward the account's own overall hit rate, and
        # the overall rate itself toward a conservative prior.
        base = (sum(sel) + _PRIOR_STRENGTH * overall) / (n + _PRIOR_STRENGTH) \
            if n else overall
        table[(lo, hi)] = {
            "p": round(max(0.01, min(0.99, base)), 4),
            "n": n,
        }
    return {
        "table": table,
        "overall": round(overall, 4),
        "samples": len(rows),
        "prior": float(prior),
    }


def calibrated_probability(confidence, calibration, fallback=None):
    """Map a raw confidence onto a measured probability.

    With no calibration available, returns `fallback` (None by default) —
    NOT confidence/100. Treating the heuristic as a probability is exactly
    the error this module exists to remove.
    """
    if not calibration:
        return fallback
    entry = calibration.get("table", {}).get(_bucket_of(confidence))
    if not entry:
        return calibration.get("overall", fallback)
    return entry["p"]


# ── Analytics ────────────────────────────────────────────────────────────
def metrics(r_multiples):
    """Win rate, profit factor, expectancy and max drawdown over a list of R
    outcomes. Pure Python — this runs on a box without numpy."""
    r = [float(x) for x in (r_multiples or [])]
    if not r:
        return {"win_rate": 0.0, "profit_factor": 0.0, "expectancy_R": 0.0,
                "max_drawdown_R": 0.0, "trades": 0}
    wins = [x for x in r if x > 0]
    losses = [x for x in r if x < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for x in r:
        equity += x
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "win_rate": round(len(wins) / len(r), 4),
        "profit_factor": (round(gross_profit / gross_loss, 4)
                          if gross_loss > 0 else float("inf")),
        "expectancy_R": round(sum(r) / len(r), 4),
        "max_drawdown_R": round(max_dd, 4),
        "trades": len(r),
    }


def _percentile(sorted_vals, pct):
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


def monte_carlo_r_paths(r_multiples, simulations=2000, seed=None):
    """Reshuffle the trade sequence to see what luck contributed.

    A strategy whose profit depends on one specific ordering is not an edge.
    Reports the 5th-percentile outcome, the 95th-percentile drawdown, and how
    often the resampled path ends negative.
    """
    r = [float(x) for x in (r_multiples or [])]
    if len(r) < 2:
        return {"final_return_p05": 0.0, "max_dd_p95": 0.0,
                "prob_negative": 0.0, "simulations": 0}
    rng = random.Random(seed)
    finals, dds = [], []
    for _ in range(int(simulations)):
        equity, peak, max_dd = 0.0, 0.0, 0.0
        for _ in range(len(r)):
            equity += rng.choice(r)
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        finals.append(equity)
        dds.append(max_dd)
    finals.sort()
    dds.sort()
    return {
        "final_return_p05": round(_percentile(finals, 5), 4),
        "max_dd_p95": round(_percentile(dds, 95), 4),
        "prob_negative": round(sum(1 for f in finals if f < 0) / len(finals), 4),
        "simulations": int(simulations),
    }


# ── Top-level evaluation ─────────────────────────────────────────────────
def evaluate(confidence, calibration, atr_pips, spread_pips,
             structure_distance_pips=0.0, regime=None, equity=0.0,
             drawdown_pct=0.0, risk_ok=True, min_probability=0.55,
             rr=1.7, max_risk_pct=0.5, require_regime=True):
    """Run the whole decision chain for one candidate entry.

    Returns a dict that is safe to log verbatim — it records not just the
    verdict but every number behind it, which is what makes a later
    post-mortem possible.
    """
    p = calibrated_probability(confidence, calibration)
    sl_pips, tp_pips = dynamic_sl_tp(
        atr_pips, structure_distance_pips, spread_pips, rr=rr)
    c_r = cost_in_r(spread_pips, sl_pips)
    tp_r = tp_pips / sl_pips if sl_pips else 0.0
    ev = expected_value(p, tp_r, 1.0, c_r) if p is not None else None

    ok, reason = approve_trade(
        p, ev, regime=regime, spread_pips=spread_pips, atr_pips=atr_pips,
        risk_ok=risk_ok, min_probability=min_probability,
        require_regime=require_regime)

    risk_cash, risk_pct = (0.0, 0.0)
    if ok:
        risk_cash, risk_pct = position_risk(
            equity, p, tp_r, 1.0, max_risk_pct=max_risk_pct)
        risk_pct = final_risk_pct(risk_pct, drawdown_pct)
        risk_cash = max(0.0, float(equity)) * risk_pct / 100.0
        if risk_pct <= 0:
            ok, reason = False, "DRAWDOWN_BLOCK"

    return {
        "approved": ok,
        "reason": reason,
        "probability": p,
        "confidence": confidence,
        "regime": regime,
        "sl_pips": round(sl_pips, 2),
        "tp_pips": round(tp_pips, 2),
        "tp_r": round(tp_r, 3),
        "cost_r": round(c_r, 4),
        "ev_r": round(ev, 4) if ev is not None else None,
        "breakeven_p": round(breakeven_probability(tp_r, 1.0, c_r), 4),
        "risk_pct": round(risk_pct, 4),
        "risk_cash": round(risk_cash, 2),
        "calibrated": bool(calibration),
    }
