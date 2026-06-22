"""Legendary-trader strategy engine — crypto, per-user session.

Turtle breakout, Livermore structure, Soros momentum, PTJ/Seykota defense,
Druckenmiller position sizing.

Unlike the forex port, the session dict is passed in per-user (no module-level
global), so every client's risk counters are fully isolated.
"""
import time
from datetime import date
from apex import config as cfg


def new_session(start_balance):
    return {
        "consecutiveLosses": 0,
        "consecutiveWins": 0,
        "dailyTrades": 0,
        "dailyPnL": 0.0,
        "lastResetDay": date.today().isoformat(),
        "peakBalance": start_balance,
        "totalTrades": 0,
        "lastLossAt": 0.0,
        "stopStartedAt": 0.0,   # self-healing risk pause timestamp
    }


def _reset_daily_if_needed(session):
    today = date.today().isoformat()
    if session.get("lastResetDay") != today:
        session["dailyTrades"] = 0
        session["dailyPnL"] = 0.0
        session["lastResetDay"] = today


def should_stop(session, balance, start_balance):
    _reset_daily_if_needed(session)
    reasons = []
    if session.get("peakBalance") is None or balance > session["peakBalance"]:
        session["peakBalance"] = balance
    if session["consecutiveLosses"] >= cfg.MAX_CONSECUTIVE_LOSSES:
        reasons.append(f"{cfg.MAX_CONSECUTIVE_LOSSES} consecutive losses (Seykota rule)")
    daily_dd = (session["dailyPnL"] / start_balance) * 100 if start_balance else 0
    if daily_dd < -cfg.MAX_DAILY_LOSS_PCT:
        reasons.append(f"Daily loss over {cfg.MAX_DAILY_LOSS_PCT:g}% (PTJ stop)")
    peak = session.get("peakBalance") or start_balance
    peak_dd = ((balance - peak) / peak) * 100 if peak else 0
    if peak_dd < -cfg.MAX_DRAWDOWN_PCT:
        reasons.append(f"Drawdown {peak_dd:.1f}% from peak (capital protection)")
    if session["dailyTrades"] >= cfg.MAX_DAILY_TRADES:
        reasons.append(f"{cfg.MAX_DAILY_TRADES} trades/day limit (Turtle rule)")
    return {"stop": len(reasons) > 0, "reasons": reasons}


def record_trade(session, won, pnl_amount):
    _reset_daily_if_needed(session)
    session["totalTrades"] += 1
    session["dailyTrades"] += 1
    session["dailyPnL"] += pnl_amount
    if won:
        session["consecutiveWins"] += 1
        session["consecutiveLosses"] = 0
    else:
        session["consecutiveLosses"] += 1
        session["consecutiveWins"] = 0
        session["lastLossAt"] = time.time()


def reset_risk(session, balance):
    """Self-heal: clear all counters after the risk pause cools down."""
    session["consecutiveLosses"] = 0
    session["consecutiveWins"] = 0
    session["dailyTrades"] = 0
    session["dailyPnL"] = 0.0
    session["peakBalance"] = balance
    session["stopStartedAt"] = 0.0


def cooldown_remaining(session, cooldown_min):
    """Ed Seykota: avoid revenge trading. Minutes left until entries allowed."""
    if not session.get("lastLossAt") or cooldown_min <= 0:
        return 0
    elapsed = (time.time() - session["lastLossAt"]) / 60
    return 0 if elapsed >= cooldown_min else int(cooldown_min - elapsed) + 1


# ─── Pattern analysis (stateless — pure candle math) ─────
def turtle_breakout(candles):
    PERIOD = 20
    if len(candles) < PERIOD + 2:
        return {"signal": None, "high20": None, "low20": None, "nearSignal": None, "breakoutStr": "NONE"}
    lookback = candles[-(PERIOD + 1):-1]
    current, prev = candles[-1], candles[-2]
    high20 = max(c["high"] for c in lookback)
    low20 = min(c["low"] for c in lookback)
    buy_bo = current["close"] > high20 and prev["close"] <= high20
    sell_bo = current["close"] < low20 and prev["close"] >= low20
    near_high = current["close"] > high20 * 0.995 and not buy_bo
    near_low = current["close"] < low20 * 1.005 and not sell_bo
    return {
        "signal": "BUY" if buy_bo else ("SELL" if sell_bo else None),
        "nearSignal": "BUY" if near_high else ("SELL" if near_low else None),
        "high20": round(high20, 6), "low20": round(low20, 6),
        "breakoutStr": "STRONG" if (buy_bo or sell_bo) else ("NEAR" if (near_high or near_low) else "NONE"),
    }


def livermore_structure(candles):
    if len(candles) < 12:
        return {"trend": "NEUTRAL", "strength": 0}
    last12 = candles[-12:]
    h1, h2 = last12[:6], last12[6:]
    h1_high, h2_high = max(c["high"] for c in h1), max(c["high"] for c in h2)
    h1_low, h2_low = min(c["low"] for c in h1), min(c["low"] for c in h2)
    higher_highs, higher_lows = h2_high > h1_high, h2_low > h1_low
    lower_highs, lower_lows = h2_high < h1_high, h2_low < h1_low
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
    if len(candles) < period + 1:
        return {"signal": None, "zscore": 0, "stretched": False}
    closes = [c["close"] for c in candles[-period:]]
    mean = sum(closes) / period
    std = (sum((c - mean) ** 2 for c in closes) / period) ** 0.5
    price = candles[-1]["close"]
    z = (price - mean) / std if std else 0
    return {"signal": "SELL" if z > threshold else ("BUY" if z < -threshold else None),
            "zscore": round(z, 2), "stretched": abs(z) > threshold}


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


def htf_trend(candles):
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


def analyze(candles, session):
    return {
        "turtle": turtle_breakout(candles),
        "livermore": livermore_structure(candles),
        "soros": soros_momentum(candles),
        "meanReversion": mean_reversion(candles),
        "session": dict(session),
    }
