"""Market Pulse (forex) — a plain-language read of how the market is moving.

Core reads (volatility, momentum, trend) come from the indicators the loop
already computes, so they always work. The forex-specific edge is SESSION
AWARENESS: forex is driven by the Sydney/Tokyo/London/New-York sessions, and
which pairs move — and how much — depends entirely on which are open. That is
computed purely from the UTC clock: zero data, zero cost, never blocked.
"""
from datetime import datetime, timezone


def pulse(ind, strat=None, symbol=""):
    """Plain-language market state from the tick's indicators. {} on bad input."""
    try:
        atr_pct = float(ind.get("atrPct") or 0)
        rsi = float(ind.get("rsi") or 50)
    except (TypeError, ValueError):
        return {}
    try:
        vol_ratio = float(ind.get("volumeRatio") or 0)
    except (TypeError, ValueError):
        vol_ratio = 0.0

    volatility = ("calm 🟢" if atr_pct < 0.15 else "normal" if atr_pct < 0.4
                  else "elevated ⚠️" if atr_pct < 0.8 else "extreme 🚨")
    momentum = "overbought" if rsi >= 70 else "oversold" if rsi <= 30 else "neutral"
    trend = ((strat or {}).get("livermore") or {}).get("trend") or ind.get("emaTrend") or "NEUTRAL"
    # Forex tick volume isn't always available; only report it when present.
    volume = None
    if vol_ratio > 0:
        volume = ("quiet" if vol_ratio < 0.7 else "normal" if vol_ratio < 1.5
                  else "high 📈" if vol_ratio < 3.0 else "spike 🔥")

    return {
        "symbol": symbol, "volatility": volatility, "momentum": momentum, "trend": trend,
        "volume": volume, "atrPct": round(atr_pct, 3), "rsi": round(rsi, 1),
        "notable": atr_pct >= 0.8 or (vol_ratio >= 3.0),
    }


def session(hour=None):
    """Which forex sessions are open right now (from the UTC clock) and what that
    means for volatility. Overlaps are the high-activity windows."""
    h = hour if hour is not None else datetime.now(timezone.utc).hour
    active = []
    if h >= 22 or h < 7:
        active.append("Sydney")
    if h < 9:
        active.append("Tokyo")
    if 7 <= h < 16:
        active.append("London")
    if 12 <= h < 21:
        active.append("New York")

    lo, ny = "London" in active, "New York" in active
    if lo and ny:
        return {"label": "London + New York overlap 🔥", "vol": "highest", "active": active,
                "note": "Peak liquidity — USD & EUR pairs move most. Prime trading window."}
    if lo:
        return {"label": "London", "vol": "high", "active": active,
                "note": "London session — EUR/GBP pairs are active."}
    if ny:
        return {"label": "New York", "vol": "high", "active": active,
                "note": "New York session — USD pairs are active."}
    if active:
        return {"label": " / ".join(active), "vol": "low", "active": active,
                "note": "Asian session — quiet, majors barely move. London opens 07:00 UTC."}
    return {"label": "Between sessions", "vol": "very low", "active": active,
            "note": "Market is quiet between sessions."}
