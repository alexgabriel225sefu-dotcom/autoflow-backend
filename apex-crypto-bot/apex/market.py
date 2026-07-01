"""Market Pulse — a plain-language read of how the market is moving right now.

The core reads (volatility, volume, momentum, trend) come from indicators the
bot already computes every tick, so they ALWAYS work with no extra network.
Funding rate + long/short ratio are best-effort Binance-futures extras that
fail soft (a squeeze warning when the crowd is lopsided), never blocking.
"""
import requests

_FAPI = "https://fapi.binance.com"


def pulse(ind, strat=None, symbol=""):
    """Plain-language market state from the tick's indicators. {} on bad input."""
    try:
        atr_pct = float(ind.get("atrPct") or 0)
        vol_ratio = float(ind.get("volumeRatio") or 0)
        rsi = float(ind.get("rsi") or 50)
    except (TypeError, ValueError):
        return {}

    volatility = ("calm 🟢" if atr_pct < 0.8 else "normal" if atr_pct < 2.0
                  else "elevated ⚠️" if atr_pct < 4.0 else "extreme 🚨")
    volume = ("quiet" if vol_ratio < 0.7 else "normal" if vol_ratio < 1.5
              else "high 📈" if vol_ratio < 3.0 else "spike 🔥")
    momentum = "overbought" if rsi >= 70 else "oversold" if rsi <= 30 else "neutral"
    trend = ((strat or {}).get("livermore") or {}).get("trend") or ind.get("emaTrend") or "NEUTRAL"

    return {
        "symbol": symbol,
        "volatility": volatility, "volume": volume, "momentum": momentum, "trend": trend,
        "atrPct": round(atr_pct, 2), "volRatio": round(vol_ratio, 2), "rsi": round(rsi, 1),
        # a notable condition worth a proactive heads-up (spike or big volatility)
        "notable": atr_pct >= 4.0 or vol_ratio >= 3.0,
    }


def futures(symbol):
    """Best-effort funding rate (%) + long/short account ratio from Binance
    futures. Returns {} if unreachable (fail-soft). A very high/low funding rate
    or a lopsided ratio flags squeeze risk."""
    out = {}
    sym = (symbol or "BTCUSDT").upper()
    try:
        r = requests.get(f"{_FAPI}/fapi/v1/premiumIndex", params={"symbol": sym}, timeout=6)
        if r.ok:
            out["funding"] = round(float(r.json().get("lastFundingRate") or 0) * 100, 4)
    except Exception:
        pass
    try:
        r = requests.get(f"{_FAPI}/futures/data/globalLongShortAccountRatio",
                         params={"symbol": sym, "period": "5m", "limit": 1}, timeout=6)
        if r.ok and r.json():
            out["longShort"] = round(float(r.json()[0].get("longShortRatio") or 0), 2)
    except Exception:
        pass
    return out


def squeeze_note(fut):
    """One-line squeeze/imbalance read from the futures extras, or ''."""
    if not fut:
        return ""
    notes = []
    fr = fut.get("funding")
    if fr is not None:
        if fr >= 0.05:
            notes.append("funding high — crowd over-long, pullback/squeeze risk")
        elif fr <= -0.05:
            notes.append("funding negative — crowd over-short, bounce/squeeze risk")
    ls = fut.get("longShort")
    if ls is not None:
        if ls >= 2.0:
            notes.append(f"{ls}:1 long/short — heavily long")
        elif ls <= 0.5:
            notes.append(f"{ls}:1 long/short — heavily short")
    return " · ".join(notes)
