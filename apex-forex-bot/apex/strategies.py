"""Legendary-trader strategy engine (port of strategies.js).

Turtle breakout, Livermore structure, Soros momentum, PTJ/Seykota defense,
Druckenmiller position sizing.
"""
import time
from datetime import date

session = {
    "consecutiveLosses": 0,
    "consecutiveWins": 0,
    "dailyTrades": 0,
    "dailyPnL": 0.0,
    "dailyPnLPct": 0.0,
    "lastResetDay": date.today().isoformat(),
    "peakBalance": None,
    "totalTrades": 0,
    "lastLossAt": 0.0,
}


def _reset_daily_if_needed():
    today = date.today().isoformat()
    if session["lastResetDay"] != today:
        session["dailyTrades"] = 0
        session["dailyPnL"] = 0.0
        session["dailyPnLPct"] = 0.0
        session["lastResetDay"] = today
        print("[STRATEGY] 🌅 New day — counters reset.")


def should_stop(balance, start_balance):
    _reset_daily_if_needed()
    reasons = []
    if session["peakBalance"] is None or balance > session["peakBalance"]:
        session["peakBalance"] = balance
    if session["consecutiveLosses"] >= 3:
        reasons.append("3 consecutive losses — unfavorable conditions (Seykota rule)")
    daily_dd_pct = (session["dailyPnL"] / start_balance) * 100 if start_balance else 0
    if daily_dd_pct < -3:
        reasons.append(f"Daily loss exceeded -3% (${abs(session['dailyPnL']):.2f}) — PTJ daily stop")
    peak_dd = ((balance - session["peakBalance"]) / session["peakBalance"]) * 100 if session["peakBalance"] else 0
    if peak_dd < -20:
        reasons.append(f"Drawdown from peak: {peak_dd:.1f}% — capital protection stop")
    if session["dailyTrades"] >= 10:
        reasons.append("10 trades/day limit reached — Turtle rule")
    if balance < 1:
        reasons.append("Balance under $1 — cannot trade")
    return {"stop": len(reasons) > 0, "reasons": reasons}


def turtle_breakout(candles):
    PERIOD = 20
    if len(candles) < PERIOD + 2:
        return {"signal": None, "high20": None, "low20": None, "nearSignal": None, "breakoutStr": "NONE"}
    lookback = candles[-(PERIOD + 1):-1]
    current = candles[-1]
    prev = candles[-2]
    high20 = max(c["high"] for c in lookback)
    low20 = min(c["low"] for c in lookback)
    rng = high20 - low20
    buy_bo = current["close"] > high20 and prev["close"] <= high20
    sell_bo = current["close"] < low20 and prev["close"] >= low20
    near_high = current["close"] > high20 * 0.995 and not buy_bo
    near_low = current["close"] < low20 * 1.005 and not sell_bo
    return {
        "signal": "BUY" if buy_bo else ("SELL" if sell_bo else None),
        "nearSignal": "BUY" if near_high else ("SELL" if near_low else None),
        "high20": round(high20, 6), "low20": round(low20, 6), "range": round(rng, 6),
        "breakoutStr": "STRONG" if (buy_bo or sell_bo) else ("NEAR" if (near_high or near_low) else "NONE"),
    }


def livermore_structure(candles):
    if len(candles) < 12:
        return {"trend": "NEUTRAL", "strength": 0}
    last12 = candles[-12:]
    h1, h2 = last12[:6], last12[6:]
    h1_high = max(c["high"] for c in h1)
    h2_high = max(c["high"] for c in h2)
    h1_low = min(c["low"] for c in h1)
    h2_low = min(c["low"] for c in h2)
    higher_highs = h2_high > h1_high
    higher_lows = h2_low > h1_low
    lower_highs = h2_high < h1_high
    lower_lows = h2_low < h1_low
    closes = [c["close"] for c in last12]
    slope = (closes[-1] - closes[0]) / closes[0] * 100
    if higher_highs and higher_lows and slope > 0:
        return {"trend": "BULLISH", "strength": 0.85, "reason": "HH+HL structure"}
    if lower_highs and lower_lows and slope < 0:
        return {"trend": "BEARISH", "strength": 0.85, "reason": "LH+LL structure"}
    if higher_highs and not higher_lows:
        return {"trend": "BULLISH", "strength": 0.55, "reason": "HH only"}
    if lower_lows and not lower_highs:
        return {"trend": "BEARISH", "strength": 0.55, "reason": "LL only"}
    return {"trend": "NEUTRAL", "strength": 0.2, "reason": "Mixed structure"}


def soros_momentum(candles):
    if len(candles) < 8:
        return {"momentum": 0, "direction": "NEUTRAL", "velocity": 0}
    recent = candles[-8:]
    wins = sum(1 for c in recent if c["close"] > c["open"])
    bull_pct = wins / len(recent)
    closes = [c["close"] for c in recent]
    velocity = (closes[-1] - closes[0]) / closes[0] * 100
    if bull_pct >= 0.75 and velocity > 0.3:
        return {"momentum": bull_pct, "direction": "BULLISH", "velocity": velocity}
    if bull_pct <= 0.25 and velocity < -0.3:
        return {"momentum": 1 - bull_pct, "direction": "BEARISH", "velocity": velocity}
    return {"momentum": 0.5, "direction": "NEUTRAL", "velocity": velocity}


def mean_reversion(candles, period=20, threshold=2.0):
    """Z-score of price vs SMA — flags stretched moves likely to snap back."""
    if len(candles) < period + 1:
        return {"signal": None, "zscore": 0, "stretched": False}
    closes = [c["close"] for c in candles[-period:]]
    mean = sum(closes) / period
    std = (sum((c - mean) ** 2 for c in closes) / period) ** 0.5
    price = candles[-1]["close"]
    z = (price - mean) / std if std else 0
    return {
        "signal": "SELL" if z > threshold else ("BUY" if z < -threshold else None),
        "zscore": round(z, 2),
        "stretched": abs(z) > threshold,
        "mean": round(mean, 6),
    }


def druckenmiller_multiplier(confidence, criteria_score, livermore, turtle):
    mult = 1.0
    if confidence >= 85 and criteria_score >= 5:
        mult *= 1.5
    elif confidence >= 80 and criteria_score >= 4:
        mult *= 1.2
    elif confidence < 75 or criteria_score < 3:
        mult *= 0.6
    if turtle and turtle.get("breakoutStr") == "STRONG":
        mult *= 1.3
    if livermore and (livermore.get("strength") or 0) >= 0.8:
        mult *= 1.1
    return min(2.0, max(0.4, mult))


def record_trade(won, pnl_amount, start_balance):
    session["totalTrades"] += 1
    session["dailyTrades"] += 1
    session["dailyPnL"] += pnl_amount
    session["dailyPnLPct"] = (session["dailyPnL"] / start_balance) * 100 if start_balance else 0
    if won:
        session["consecutiveWins"] += 1
        session["consecutiveLosses"] = 0
    else:
        session["consecutiveLosses"] += 1
        session["consecutiveWins"] = 0
        session["lastLossAt"] = time.time()
    icon = "✅" if won else "❌"
    print(f"[STRATEGY] {icon} Streak: {session['consecutiveLosses']} losses / "
          f"{session['consecutiveWins']} wins | Today: {session['dailyTrades']} trades | "
          f"Daily PnL: {'+' if session['dailyPnL'] >= 0 else ''}${session['dailyPnL']:.4f}")


def cooldown_remaining(cooldown_min):
    """Ed Seykota: after a loss, the worst trade is the revenge trade.
    Returns minutes left until entries are allowed again (0 = clear)."""
    if not session["lastLossAt"] or cooldown_min <= 0:
        return 0
    elapsed = (time.time() - session["lastLossAt"]) / 60
    return 0 if elapsed >= cooldown_min else int(cooldown_min - elapsed) + 1


def htf_trend(candles):
    """Higher-timeframe trend via EMA50 (Livermore: trade WITH the tape).
    Price above rising EMA = BULLISH, below falling EMA = BEARISH, else NEUTRAL."""
    if not candles or len(candles) < 55:
        return "NEUTRAL"
    closes = [c["close"] for c in candles]
    k = 2 / 51
    ema = sum(closes[:50]) / 50
    ema_prev = ema
    for px in closes[50:]:
        ema_prev = ema
        ema = px * k + ema * (1 - k)
    price = closes[-1]
    if price > ema and ema >= ema_prev:
        return "BULLISH"
    if price < ema and ema <= ema_prev:
        return "BEARISH"
    return "NEUTRAL"


def analyze(candles):
    return {
        "turtle": turtle_breakout(candles),
        "livermore": livermore_structure(candles),
        "soros": soros_momentum(candles),
        "meanReversion": mean_reversion(candles),
        "session": dict(session),
    }
