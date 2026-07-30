"""Legendary-trader strategy engine (port of strategies.js).

Turtle breakout, Livermore structure, Soros momentum, PTJ/Seykota defense,
Druckenmiller position sizing.
"""
import time
from datetime import date

_sessions = {}  # user_id → per-user session dict (thread-safe: each user has its own)
_symbol_sessions = {}  # (user_id, symbol) → per-symbol loss-streak dict

def _default_session():
    return {
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

session = _default_session()  # legacy compat for single-user code paths

def get_session(user_id=None):
    if user_id is None:
        return session
    if user_id not in _sessions:
        s = _default_session()
        # Restore the persisted copy so a restart can't wipe the circuit
        # breakers (daily loss/trade counters, consecutive losses, peak
        # balance for the drawdown limit) mid-day.
        try:
            from apex import user_store
            saved = user_store.load(user_id).get("strategy_session")
            if isinstance(saved, dict):
                s.update({k: saved[k] for k in s if k in saved})
        except Exception:
            pass
        _sessions[user_id] = s
    return _sessions[user_id]


def _persist_session(user_id):
    if user_id is None:
        return
    try:
        from apex import user_store
        user_store.update(user_id, {"strategy_session": dict(get_session(user_id))})
    except Exception as e:
        print(f"[STRATEGY:{user_id}] session persist failed: {e}")


def rebase_peak(delta, user_id=None):
    """Shift the drawdown peak by an external cash movement.

    peakBalance exists to measure TRADING drawdown, so a deposit or withdrawal
    has to move it too. Leaving it alone means the breaker compares the new
    account against a peak that included money the user has since taken out:
    withdrawing a $6,309 account down to $10 reads as -99.8%, trips "capital
    protection stop" on every tick, and nothing clears it — not /resetstats,
    not a restart, and no setting the operator can change. The loop already
    rebases dash["startBalance"] on the same event; this is the half that was
    missing.

    Withdrawing below the old peak floors it at the new balance rather than
    going negative, so the breaker starts measuring from the real capital base.
    """
    s = get_session(user_id)
    if s.get("peakBalance") is None:
        return
    try:
        s["peakBalance"] = max(0.0, float(s["peakBalance"]) + float(delta))
    except (TypeError, ValueError):
        return
    _persist_session(user_id)
    print(f"[STRATEGY:{user_id or '?'}] drawdown peak rebased by {float(delta):+.2f} "
          f"→ {s['peakBalance']:.2f} (deposit/withdrawal, not a trading loss)")


def reset_peak(balance, user_id=None):
    """Drop the drawdown peak to `balance` — the clean-slate path behind
    /resetstats, which promises stats "start fresh from this moment" but used
    to leave the persisted peak untouched, so a stale peak could keep the bot
    halted straight through a reset the user believed had cleared it."""
    s = get_session(user_id)
    try:
        s["peakBalance"] = max(0.0, float(balance))
    except (TypeError, ValueError):
        return
    _persist_session(user_id)
    print(f"[STRATEGY:{user_id or '?'}] drawdown peak reset → {s['peakBalance']:.2f}")


def _default_symbol_session():
    return {"consecutiveLosses": 0, "consecutiveWins": 0, "lastLossAt": 0.0}


def _symbol_key(user_id, symbol):
    return f"{user_id}::{(symbol or '').upper()}"


def get_symbol_session(user_id, symbol):
    """Per-(user, symbol) loss streak — a whipsaw on one instrument must not
    freeze trading on every other instrument the account watches."""
    key = _symbol_key(user_id, symbol)
    if key not in _symbol_sessions:
        s = _default_symbol_session()
        try:
            from apex import user_store
            saved = user_store.load(key).get("symbol_session")
            if isinstance(saved, dict):
                s.update({k: saved[k] for k in s if k in saved})
        except Exception:
            pass
        _symbol_sessions[key] = s
    return _symbol_sessions[key]


def _persist_symbol_session(user_id, symbol):
    key = _symbol_key(user_id, symbol)
    try:
        from apex import user_store
        user_store.update(key, {"symbol_session": dict(get_symbol_session(user_id, symbol))})
    except Exception as e:
        print(f"[STRATEGY:{key}] symbol session persist failed: {e}")


def _reset_daily_if_needed(user_id=None):
    s = get_session(user_id)
    today = date.today().isoformat()
    if s["lastResetDay"] != today:
        s["dailyTrades"] = 0
        s["dailyPnL"] = 0.0
        s["dailyPnLPct"] = 0.0
        s["lastResetDay"] = today
        print(f"[STRATEGY:{user_id or '?'}] 🌅 New day — counters reset.")


_SEYKOTA_COOLDOWN_MIN = 60  # after 3 losses in a row, stand aside this long, then clear the streak


def should_stop(balance, start_balance, max_daily_loss_pct=3.0,
                max_dd_pct=20.0, user_id=None, symbol=None,
                seykota_cooldown_min=_SEYKOTA_COOLDOWN_MIN):
    """Circuit breaker — per-user when user_id is provided.

    The Seykota "3 losses in a row" rule is scoped to `symbol` (when given):
    a whipsaw on one instrument stands aside on THAT instrument only, instead
    of freezing the whole account while a completely different pair might
    have a perfectly good setup right now. Daily loss % and drawdown from
    peak stay account-wide — those protect total capital, not a single
    instrument. No cap on trades/day — a good setup is a good setup
    regardless of how many came before it today.
    """
    _reset_daily_if_needed(user_id)
    s = get_session(user_id)
    reasons = []
    if s["peakBalance"] is None or balance > s["peakBalance"]:
        s["peakBalance"] = balance
    loss_s = get_symbol_session(user_id, symbol) if symbol else s
    if loss_s["consecutiveLosses"] >= 3:
        # Time-boxed, not permanent: this only clears on a WIN, and the bot
        # can't win a trade it's forbidden from entering — that deadlocked a
        # user for 37+ hours in production. Stand aside for the cooldown, then
        # clear the streak so a fresh run of losses is needed to re-trigger it.
        elapsed_min = (time.time() - loss_s["lastLossAt"]) / 60 if loss_s["lastLossAt"] else seykota_cooldown_min
        if elapsed_min >= seykota_cooldown_min:
            loss_s["consecutiveLosses"] = 0
            _persist_session(user_id) if not symbol else _persist_symbol_session(user_id, symbol)
        else:
            left = int(seykota_cooldown_min - elapsed_min) + 1
            where = f"{symbol}: " if symbol else ""
            reasons.append(f"{where}3 consecutive losses — standing aside {left}m more (Seykota rule)")
    daily_dd_pct = (s["dailyPnL"] / start_balance) * 100 if start_balance else 0
    if daily_dd_pct < -abs(max_daily_loss_pct):
        reasons.append(f"Daily loss exceeded -{abs(max_daily_loss_pct):g}% "
                       f"(${abs(s['dailyPnL']):.2f}) — daily stop")
    peak_dd = ((balance - s["peakBalance"]) / s["peakBalance"]) * 100 if s["peakBalance"] else 0
    if peak_dd < -abs(max_dd_pct):
        reasons.append(f"Drawdown from peak: {peak_dd:.1f}% (limit {abs(max_dd_pct):g}%) — capital protection stop")
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


def soros_momentum(candles, velocity_thr=None):
    if len(candles) < 8:
        return {"momentum": 0, "direction": "NEUTRAL", "velocity": 0}
    if velocity_thr is None:
        try:
            from apex import config as _cfg
            velocity_thr = 1.0 if getattr(_cfg, "PRODUCT", "forex") == "crypto" else 0.3
        except Exception:
            velocity_thr = 0.3
    recent = candles[-8:]
    wins = sum(1 for c in recent if c["close"] > c["open"])
    bull_pct = wins / len(recent)
    closes = [c["close"] for c in recent]
    velocity = (closes[-1] - closes[0]) / closes[0] * 100
    if bull_pct >= 0.75 and velocity > velocity_thr:
        return {"momentum": bull_pct, "direction": "BULLISH", "velocity": velocity}
    if bull_pct <= 0.25 and velocity < -velocity_thr:
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
        mult *= 1.3
    elif confidence >= 80 and criteria_score >= 4:
        mult *= 1.1
    elif confidence < 75 or criteria_score < 3:
        mult *= 0.6
    if turtle and turtle.get("breakoutStr") == "STRONG":
        mult *= 1.2
    if livermore and (livermore.get("strength") or 0) >= 0.8:
        mult *= 1.1
    return min(1.2, max(0.4, mult))


def record_trade(won, pnl_amount, start_balance, user_id=None, symbol=None):
    """Account-wide daily P&L/trade counters always update here. The
    consecutive-loss streak (Seykota rule) is tracked per `symbol` when given,
    so it no longer bleeds across instruments."""
    s = get_session(user_id)
    s["totalTrades"] += 1
    s["dailyTrades"] += 1
    s["dailyPnL"] += pnl_amount
    s["dailyPnLPct"] = (s["dailyPnL"] / start_balance) * 100 if start_balance else 0
    loss_s = get_symbol_session(user_id, symbol) if symbol else s
    if won:
        loss_s["consecutiveWins"] += 1
        loss_s["consecutiveLosses"] = 0
    else:
        loss_s["consecutiveLosses"] += 1
        loss_s["consecutiveWins"] = 0
        loss_s["lastLossAt"] = time.time()
    icon = "✅" if won else "❌"
    tag = f"{symbol} " if symbol else ""
    print(f"[STRATEGY:{user_id or '?'}] {icon} {tag}Streak: {loss_s['consecutiveLosses']} losses / "
          f"{loss_s['consecutiveWins']} wins | Today: {s['dailyTrades']} trades | "
          f"Daily PnL: {'+' if s['dailyPnL'] >= 0 else ''}${s['dailyPnL']:.4f}")
    _persist_session(user_id)
    if symbol:
        _persist_symbol_session(user_id, symbol)


def cooldown_remaining(cooldown_min, user_id=None, symbol=None):
    """Ed Seykota: after a loss, the worst trade is the revenge trade.
    Returns minutes left until entries are allowed again (0 = clear).
    Scoped to `symbol` when given (see should_stop/record_trade)."""
    s = get_symbol_session(user_id, symbol) if symbol else get_session(user_id)
    if not s["lastLossAt"] or cooldown_min <= 0:
        return 0
    elapsed = (time.time() - s["lastLossAt"]) / 60
    return 0 if elapsed >= cooldown_min else int(cooldown_min - elapsed) + 1


def cooldown_remaining(cooldown_min, user_id=None):
    """Ed Seykota: after a loss, the worst trade is the revenge trade.
    Returns minutes left until entries are allowed again (0 = clear)."""
    s = get_session(user_id)
    if not s["lastLossAt"] or cooldown_min <= 0:
        return 0
    elapsed = (time.time() - s["lastLossAt"]) / 60
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


def resample(candles, ratio=12):
    """Aggregate M5 candles into a higher timeframe (12 → H1)."""
    out = []
    for i in range(0, len(candles) - ratio + 1, ratio):
        grp = candles[i:i + ratio]
        out.append({"time": grp[0].get("time"), "open": grp[0]["open"],
                    "close": grp[-1]["close"],
                    "high": max(c["high"] for c in grp),
                    "low": min(c["low"] for c in grp),
                    "volume": sum(c.get("volume", 0) for c in grp)})
    return out


def detect_regime(candles):
    """Classify the market so the AUTO strategy can pick the right engine.

    Self-calibrating (ratios, not absolute thresholds), so it works the same
    on EURUSD, gold or an index:
      trending  — clear structure + separated EMAs → trend following
      ranging   — flat, mean-reverting conditions  → mean reversion
      volatile  — ATR ≫ its own recent norm        → breakout, half risk
      quiet     — ATR ≪ norm                       → stand aside
    """
    if len(candles) < 130:
        return {"regime": "unknown", "vol_ratio": 1.0, "label": "warming up"}
    trs = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        trs.append(max(c["high"] - c["low"], abs(c["high"] - p["close"]),
                       abs(c["low"] - p["close"])))
    atr_now = sum(trs[-14:]) / 14
    # Long reference window: a 100-bar base converges with the present after
    # ~1.5h of a new regime and stops detecting it. 400 bars (~33h of M5)
    # anchors "normal" firmly enough to flag both dead and violent tape.
    base_w = min(400, len(trs))
    atr_base = sum(trs[-base_w:]) / base_w
    vol_ratio = atr_now / atr_base if atr_base else 1.0

    closes = [c["close"] for c in candles]
    k50, k200 = 2 / 51, 2 / 201
    e50 = sum(closes[:50]) / 50
    e200 = sum(closes[:200]) / 200 if len(closes) >= 200 else e50
    for px in closes[50:]:
        e50 = px * k50 + e50 * (1 - k50)
    for px in closes[200:]:
        e200 = px * k200 + e200 * (1 - k200)
    sep_pct = abs(e50 - e200) / closes[-1] * 100 if closes[-1] else 0
    liv = livermore_structure(candles)

    if vol_ratio >= 1.8:
        return {"regime": "volatile", "vol_ratio": round(vol_ratio, 2),
                "label": f"high volatility ({vol_ratio:.1f}× normal) — breakout mode, half risk"}
    if vol_ratio <= 0.42:
        return {"regime": "quiet", "vol_ratio": round(vol_ratio, 2),
                "label": f"very low volatility ({vol_ratio:.1f}× normal) — standing aside"}
    # EMA-separation cutoff for "trending". 0.18% is FX-scale; crypto EMAs sit
    # 1-5%+ apart almost always, so on crypto that gate is always true and the
    # regime never comes back "ranging". Raise it for the crypto build so the
    # trend/range split is meaningful.
    try:
        from apex import config as _cfg
        sep_thr = 0.9 if getattr(_cfg, "PRODUCT", "forex") == "crypto" else 0.30
    except Exception:
        sep_thr = 0.18
    if sep_pct >= sep_thr and liv.get("trend") in ("BULLISH", "BEARISH") and liv.get("strength", 0) >= 0.55:
        return {"regime": "trending", "vol_ratio": round(vol_ratio, 2),
                "label": f"{liv['trend'].lower()} trend — trend following"}
    return {"regime": "ranging", "vol_ratio": round(vol_ratio, 2),
            "label": "ranging market — mean reversion"}
