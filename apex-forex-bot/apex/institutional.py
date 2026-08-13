"""Institutional State — one composite read of a symbol, built from many sources.

The spec's own warning (section 7) is the whole design brief:

    "Institutional proxy" este o estimare compusă, nu acces la ordinele interne
    ale unei bănci. Scorul trebuie etichetat permanent cu sursele care l-au
    produs și cu nivelul de încredere. Dacă o sursă lipsește, scorul trebuie
    degradat; nu se inventează date.

So the interesting part of this module is not the weighted sum — that is four
lines. It is everything that stops the sum from lying:

  * an observation that has expired is missing, not old. It is dropped, and
    the score says so.
  * a missing source NEVER gets a default value. Imputing 0.0 for "no COT data
    this week" would silently claim neutral positioning as a fact, and a
    neutral fact is not the same as no fact.
  * every state carries `data_quality` (how much of the intended picture is
    actually present) and `sources` (which ones), so a +0.58 built from two
    feeds is never mistaken for a +0.58 built from nine.
  * sources marked critical are load-bearing. Without them the state is
    unusable and says so, rather than degrading quietly toward a number that
    still looks like an opinion.

Deliberately NOT here: TimescaleDB, Redis Streams, Prometheus, licensed
Bloomberg/Refinitiv feeds. Those are the spec's phase-1 infrastructure and
this bot runs on a single small instance. This module is pure arithmetic over
whatever observations the caller can actually obtain, which is the part that
produces the edge; the storage layer can arrive later without changing it.
"""
import time

# Every feature is normalised to [-1, +1] before it enters the composite:
# +1 maximally bullish for the base currency, -1 maximally bearish, 0 neutral.
# Without a shared scale a weighted sum of "RSI 68" and "COT net +45,000" is
# meaningless arithmetic.
FEATURES = (
    "price_momentum",
    "liquidity_quality",
    "volatility",
    "futures_positioning",
    "cot_bias",
    "rate_differential",
    "central_bank_bias",
    "macro_risk",
    "sentiment",
)

# Relative weight of each feature in the composite, and whether the state is
# usable without it. Weights are a starting point to be tuned against the
# journal, not a claim of discovered truth.
WEIGHTS = {
    "price_momentum":      1.0,
    "liquidity_quality":   0.6,
    "volatility":          0.6,
    "futures_positioning": 0.9,
    "cot_bias":            0.8,
    "rate_differential":   1.0,
    "central_bank_bias":   0.9,
    "macro_risk":          0.7,
    "sentiment":           0.4,
}

# Without price there is no read at all. Everything else is contributory: the
# score degrades when they are absent instead of becoming unusable.
CRITICAL = ("price_momentum",)

# Below this fraction of the intended picture, the composite is not an opinion
# worth acting on. Spec section 11: "Missing critical data → HOLD".
MIN_DATA_QUALITY = 0.35


def clamp(v, lo=-1.0, hi=1.0):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return None


def observe(feature, value, source, confidence=1.0, ttl_s=3600, now=None):
    """One measurement, tagged with where it came from and how long it counts.

    `value` is clamped to [-1, +1]; anything unparseable produces None, which
    the aggregator drops as missing rather than treating as neutral.
    """
    now = time.time() if now is None else float(now)
    v = clamp(value)
    c = clamp(confidence, 0.0, 1.0)
    return {
        "feature": feature,
        "value": v,
        "source": source,
        "confidence": 1.0 if c is None else c,
        "ts": now,
        "expires_at": now + max(1.0, float(ttl_s)),
    }


def _usable(obs, now):
    """Fresh, well-formed and actually carrying a value."""
    if not obs or obs.get("value") is None:
        return False
    if obs.get("feature") not in WEIGHTS:
        return False
    try:
        return now < float(obs["expires_at"])
    except (TypeError, ValueError):
        return False


def build(symbol, observations, now=None, weights=None,
          min_quality=MIN_DATA_QUALITY):
    """Aggregate observations into one institutional read of `symbol`.

    Returns a dict carrying the composite, its data quality, the per-feature
    values that produced it and the sources behind them. `usable` is the
    single field a caller should gate on; `reason` says why when it is False.

    Later observations of the same feature win, so a caller can hand over a
    stream without deduplicating first.
    """
    now = time.time() if now is None else float(now)
    w = dict(weights or WEIGHTS)

    latest = {}
    for o in observations or []:
        if not _usable(o, now):
            continue
        prev = latest.get(o["feature"])
        if prev is None or o["ts"] >= prev["ts"]:
            latest[o["feature"]] = o

    # data_quality is coverage of the INTENDED picture, so a feature that was
    # never supplied and one whose feed died look the same to the consumer —
    # which is correct, because in both cases we do not know its value.
    total_w = sum(w.get(f, 0.0) for f in w) or 1.0
    have_w = sum(w.get(f, 0.0) for f in latest)
    quality = round(have_w / total_w, 4)

    missing_critical = [f for f in CRITICAL if f not in latest]

    # The composite is a confidence-weighted mean over PRESENT features only.
    # Dividing by the full weight of every intended feature instead would drag
    # the score toward zero purely because a feed is down, dressing missing
    # data up as a neutral market.
    num = den = 0.0
    per_feature = {}
    for f, o in latest.items():
        fw = w.get(f, 0.0) * o["confidence"]
        num += o["value"] * fw
        den += fw
        per_feature[f] = {"value": o["value"], "source": o["source"],
                          "confidence": o["confidence"],
                          "age_s": round(now - o["ts"], 1)}
    proxy = round(num / den, 4) if den > 0 else None

    if missing_critical:
        usable, reason = False, f"missing critical: {', '.join(missing_critical)}"
    elif proxy is None:
        usable, reason = False, "no usable observations"
    elif quality < min_quality:
        usable, reason = False, f"data quality {quality:.0%} < {min_quality:.0%}"
    else:
        usable, reason = True, "ok"

    return {
        "symbol": symbol,
        "ts": now,
        "institutional_proxy": proxy,
        "data_quality": quality,
        "usable": usable,
        "reason": reason,
        "features": per_feature,
        "sources": sorted({o["source"] for o in latest.values()}),
        "missing": sorted(f for f in w if f not in latest),
    }


def delta(prev, curr):
    """Change between two states — spec section 10.

    The level of a feature and its CHANGE are different signals: rates being
    high is not the same event as rates being repriced this morning, and it is
    usually the repricing that moves FX. Only features present and fresh in
    BOTH states are compared; a feature that just appeared has no delta, and
    inventing one against an assumed previous value would manufacture a move
    that never happened.
    """
    out = {"per_feature": {}, "composite": None, "compared": 0}
    if not prev or not curr:
        return out
    pf, cf = prev.get("features") or {}, curr.get("features") or {}
    num = den = 0.0
    for f, c in cf.items():
        p = pf.get(f)
        if not p:
            continue
        d = c["value"] - p["value"]
        out["per_feature"][f] = round(d, 4)
        fw = WEIGHTS.get(f, 0.0)
        num += d * fw
        den += fw
    out["compared"] = len(out["per_feature"])
    if den > 0:
        out["composite"] = round(num / den, 4)
    return out


def action_bias(state, threshold=0.25):
    """Turn a usable state into BUY / SELL / HOLD.

    HOLD is the answer whenever the state is not usable, which is the spec's
    fail-safe (section 11) rather than a fallback: an unusable state means we
    do not know, and "we do not know" is a reason to stand aside, never a
    reason to guess a direction.
    """
    if not state or not state.get("usable"):
        return "HOLD"
    p = state.get("institutional_proxy")
    if p is None:
        return "HOLD"
    if p >= threshold:
        return "BUY"
    if p <= -threshold:
        return "SELL"
    return "HOLD"


def describe(state):
    """One line for Telegram / the dashboard, honest about its own coverage."""
    if not state:
        return "no institutional state"
    p = state.get("institutional_proxy")
    bits = [state.get("symbol", "?")]
    bits.append(f"proxy {p:+.2f}" if p is not None else "proxy n/a")
    bits.append(f"quality {state.get('data_quality', 0):.0%}")
    # Name the features, don't just count them. "4/9" cannot answer the only
    # question anyone asks of this line — WHICH four — so diagnosing a missing
    # source meant reverse-engineering the count from the quality percentage
    # and the weight table, which is guesswork. The names are already here.
    feats = state.get("features") or {}
    bits.append(f"{len(feats)}/{len(WEIGHTS)}: "
                + (", ".join(f for f in FEATURES if f in feats) or "none"))
    if not state.get("usable"):
        bits.append(f"UNUSABLE ({state.get('reason')})")
    return " · ".join(bits)
