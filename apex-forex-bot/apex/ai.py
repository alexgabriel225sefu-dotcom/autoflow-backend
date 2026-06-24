"""AI signal generation (port of ai.js). Anthropic primary, Groq free fallback."""
import re
import json
import requests
from apex import config as cfg
from apex import forex

_anthropic_client = None


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    return _anthropic_client


def _extract_json(text):
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("No JSON in response")
    return json.loads(m.group(0))


def _call_groq(prompt):
    if not cfg.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY missing")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        json={"model": "llama-3.3-70b-versatile",
              "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 400, "temperature": 0},
        headers={"Authorization": f"Bearer {cfg.GROQ_API_KEY}", "Content-Type": "application/json"},
        timeout=15)
    text = r.json()["choices"][0]["message"]["content"].strip()
    print("[AI] ✅ Groq (free) — signal generated")
    return _extract_json(text)


def _call_anthropic(prompt):
    models = ["claude-haiku-4-5-20251001", "claude-3-5-haiku-20241022", "claude-3-haiku-20240307"]
    for model in models:
        try:
            msg = _get_anthropic().messages.create(
                model=model, max_tokens=400, temperature=0,
                messages=[{"role": "user", "content": prompt}])
            text = msg.content[0].text.strip()
            print(f"[AI] ✅ Anthropic {model}")
            return _extract_json(text)
        except Exception as err:
            status = getattr(err, "status_code", None) or getattr(getattr(err, "response", None), "status_code", "N/A")
            print(f"[AI ❌] Anthropic {model} | Status: {status} | {err}")
            if status in (400, 401):
                break
    raise RuntimeError("Anthropic unavailable")


def _legendary_section(strategy_data):
    if not strategy_data:
        return ""
    t = strategy_data["turtle"]
    lv = strategy_data["livermore"]
    so = strategy_data["soros"]
    mr = strategy_data.get("meanReversion", {})
    se = strategy_data["session"]
    lv_strength = f"{lv['strength'] * 100:.0f}%" if lv.get("strength") is not None else "N/A"
    so_mom = f"{so['momentum'] * 100:.0f}%" if so.get("momentum") is not None else "N/A"
    so_vel = f"{so['velocity']:.3f}%" if so.get("velocity") is not None else "N/A"
    return f"""
## LEGENDARY TRADERS ANALYSIS
### 🐢 Turtle Trading (Richard Dennis / Eckhardt)
- Breakout signal: {t.get('signal') or 'NONE'} | Strength: {t.get('breakoutStr')}
- 20-period High: {t.get('high20')} | 20-period Low: {t.get('low20')}
- Near breakout: {t.get('nearSignal') or 'NO'}

### 📐 Jesse Livermore (Pivot Structure)
- Trend structure: {lv.get('trend')} ({lv.get('reason', 'N/A')})
- Signal strength: {lv_strength}
- Rule: if trend=BULLISH confirm BUY; if BEARISH confirm SELL; NEUTRAL be cautious

### 💡 George Soros (Reflexivity / Momentum)
- Momentum direction: {so.get('direction')}
- Bullish candles: {so_mom} of last 8
- Price velocity: {so_vel}

### 📉 Mean Reversion (Z-score vs SMA20)
- Z-score: {mr.get('zscore', 0)} | Stretched: {'YES — price extended, expect snap-back' if mr.get('stretched') else 'no'}
- Reversion signal: {mr.get('signal') or 'NONE'}

### 📊 Current session (Ed Seykota rules)
- Consecutive losses: {se.get('consecutiveLosses')} (stop at 3)
- Consecutive wins: {se.get('consecutiveWins')}
- Trades today: {se.get('dailyTrades')}/10
- Daily PnL: {'+' if se.get('dailyPnL', 0) >= 0 else ''}${se.get('dailyPnL', 0):.4f}"""


def get_signal(ind, balance, open_position, strategy_data=None):
    def fnum(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    rsi_v, srsi_k, macd_h, vol_r, bb_pos = (fnum(ind.get(k)) for k in
                                            ("rsi", "stochRsiK", "macdHist", "volumeRatio", "bb_position"))
    recent = "\n".join(
        f"{i+1}. {c['direction']} O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']} (body: {c['bodyPct']}%)"
        for i, c in enumerate(ind["recentCandles"]))
    pos = (f"{open_position['side']} @ {open_position['entryPrice']} | "
           f"PnL: {open_position.get('pnlPips', 0):.1f} pips") if open_position else "NONE"
    sessions = ", ".join(forex.active_sessions()) or "between sessions"

    # Twelve Data forex has no tick volume — swap the dead criterion for Stoch RSI
    has_volume = ind.get("hasVolume", True)
    vol_line = (f"- Volume ratio: {ind['volumeRatio']}x" if has_volume
                else "- Volume: N/A (this data source has no forex tick volume — judge on price action, do NOT treat as low liquidity)")
    vol_crit = "tick volume>1.2x" if has_volume else "Stoch RSI K aligned with direction"

    prompt = f"""You are a professional FOREX trader with 20 years of experience. Forex ranges far more than it trends, so your PRIMARY edge is MEAN REVERSION: fade overbought/oversold extremes back to the mean (RSI + Bollinger Bands), and only ride a move when the higher-timeframe trend is genuinely strong. This is the opposite of a crypto breakout bot. Analyze ALL the data and give a precise signal.

## MARKET DATA — {cfg.SYMBOL} ({cfg.TIMEFRAME})
- Active sessions: {sessions} (liquidity is best when London/New York overlap)
### Price & Trend
- Current price: {ind['price']}
- EMA 20: {ind['ema20']} | EMA 50: {ind['ema50']} | EMA 200: {ind['ema200']}
- Trend EMA20/50: {ind['emaTrend']} | Trend EMA50/200: {ind['ema200Trend']}
- Price vs EMA20: {ind['priceVsEma20']}
- Market structure: {ind['marketStructure']}

### Momentum
- RSI (14): {ind['rsi']}
- Stoch RSI K: {ind['stochRsiK']} | D: {ind['stochRsiD']}
- MACD Histogram: {ind['macdHist']} {'bullish' if macd_h > 0 else 'bearish'}
- RSI divergence: {ind['divergence']}

### Volatility & Volume
- ATR: {ind['atrPct']}% of price
- BB Bandwidth: {ind['bb_bandwidth']}% | Position in BB: {ind['bb_position']}%
{vol_line}
- High 24h: {ind['high24h']} | Low 24h: {ind['low24h']}

### Last 5 candles
{recent}
## ACCOUNT
- Balance: ${balance:.2f} USD | Leverage: 1:{cfg.LEVERAGE:g}
- Open position: {pos}

## ENTRY RULES — MEAN REVERSION FIRST
- SL: {cfg.STOP_LOSS_PIPS:g} pips | TP: {cfg.TAKE_PROFIT_PIPS:g} pips | Risk: {cfg.RISK_PER_TRADE * 100:g}% per trade
- Minimum confidence: {cfg.MIN_CONFIDENCE}%
- BUY (fade oversold dip, min 3/5): price in lower BB (<30%), RSI≤35 or bullish divergence, Stoch RSI K low, price stretched below EMA20, no strong downtrend
- SELL (fade overbought spike, min 3/5): price in upper BB (>70%), RSI≥65 or bearish divergence, Stoch RSI K high, price stretched above EMA20, no strong uptrend
- CLOSE when price reverts to the BB mid (the mean = your target)
- TREND GUARD: in a strong trend (EMA50 vs EMA200 widely separated) do NOT fade against it — only buy dips in an uptrend / sell rallies in a downtrend, else HOLD
- Leverage is 1:{cfg.LEVERAGE:g} — size for stability, not for chasing volatility

Respond ONLY with valid JSON:
{{"action":"BUY"|"SELL"|"HOLD"|"CLOSE","confidence":<0-100>,"reasoning":"<max 2 sentences>","riskLevel":"LOW"|"MEDIUM"|"HIGH","keyFactors":["f1","f2","f3"],"criteriaScore":<0-5>}}"""

    try:
        return _call_anthropic(prompt)
    except Exception:
        pass
    try:
        return _call_groq(prompt)
    except Exception as err:
        print(f"[AI ❌] Groq failed: {err}")
    sig = mean_reversion_signal(ind, open_position)
    print(f"[AI] Mean-reversion fallback: {sig['action']} {sig['confidence']}%")
    return sig


def rule_based_fallback(ind, open_position=None):
    """Deterministic signal when all AI sources are unavailable."""
    def fnum(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    rsi_v   = fnum(ind.get("rsi", 50))
    macd_h  = fnum(ind.get("macdHist"))
    vol_r   = fnum(ind.get("volumeRatio", 1.0))
    price   = fnum(ind.get("price"))
    ema20   = fnum(ind.get("ema20"))
    ema50   = fnum(ind.get("ema50"))

    score = 0
    factors = []

    # RSI — extreme levels get stronger weight
    if rsi_v < 25:
        score += 3; factors.append(f"RSI extreme oversold ({rsi_v:.0f})")
    elif rsi_v < 38:
        score += 2; factors.append(f"RSI oversold ({rsi_v:.0f})")
    elif rsi_v > 75:
        score -= 3; factors.append(f"RSI extreme overbought ({rsi_v:.0f})")
    elif rsi_v > 62:
        score -= 2; factors.append(f"RSI overbought ({rsi_v:.0f})")

    # MACD histogram direction
    if macd_h > 0:
        score += 1; factors.append("MACD bullish")
    elif macd_h < 0:
        score -= 1; factors.append("MACD bearish")

    # EMA trend — context-aware: amplifies the existing bias, doesn't override it
    above_emas = price > ema20 > ema50 if (ema20 and ema50) else False
    below_emas = price < ema20 < ema50 if (ema20 and ema50) else False
    if score >= 0 and above_emas:
        score += 1; factors.append("Price above EMAs")
    elif score >= 0 and below_emas:
        score -= 1; factors.append("Price below EMAs (bearish)")
    elif score < 0 and above_emas:
        score -= 1; factors.append("Price overextended above EMAs")
    elif score < 0 and below_emas:
        score += 1; factors.append("Price at discount below EMAs")

    # Volume amplifies the existing direction
    if vol_r >= 1.3 and score != 0 and ind.get("hasVolume", True):
        score += 1 if score > 0 else -1
        factors.append(f"Volume spike ({vol_r:.1f}x)")

    abs_score = abs(score)
    confidence    = min(85, 52 + abs_score * 8)
    criteria_score = min(5, abs_score + 1)

    if score >= 2:
        return {"action": "BUY",  "confidence": confidence, "criteriaScore": criteria_score,
                "reasoning": f"Rule-based: {', '.join(factors)}", "riskLevel": "MEDIUM",
                "keyFactors": factors}
    if score <= -2:
        return {"action": "SELL", "confidence": confidence, "criteriaScore": criteria_score,
                "reasoning": f"Rule-based: {', '.join(factors)}", "riskLevel": "MEDIUM",
                "keyFactors": factors}
    return {"action": "HOLD", "confidence": 42, "criteriaScore": max(0, abs_score),
            "reasoning": "Rule-based: no clear signal", "riskLevel": "LOW", "keyFactors": factors}


def mean_reversion_signal(ind, open_position=None):
    """FOREX-specific MEAN REVERSION engine (the real Crypto↔Forex difference).

    Forex ranges far more than it trends, so this fades extremes back to the
    mean instead of chasing breakouts like the crypto trend-following engine:
      • BUY  an oversold dip at the lower Bollinger Band (RSI/StochRSI low)
      • SELL an overbought spike at the upper band (RSI/StochRSI high)
      • EXIT when price reverts to the BB midline (target reached)
      • SKIP counter-trend fades when the market is strongly trending
    """
    def fnum(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    rsi_v  = fnum(ind.get("rsi"), 50)
    bb_pos = fnum(ind.get("bb_position"), 50)   # 0 = lower band, 100 = upper band
    srsi_k = fnum(ind.get("stochRsiK"), 50)
    price  = fnum(ind.get("price"))
    ema50  = fnum(ind.get("ema50"))
    ema200 = fnum(ind.get("ema200"))
    bw     = fnum(ind.get("bb_bandwidth"), 0)
    div    = (ind.get("divergence") or "NONE").upper()

    # Already in a trade → exit once price has reverted to the mean (the target).
    if open_position:
        side = open_position.get("side")
        if side == "BUY" and bb_pos >= 50:
            return {"action": "CLOSE", "confidence": 70, "criteriaScore": 3,
                    "reasoning": "Mean reversion: price reverted to BB mid — take profit",
                    "riskLevel": "LOW", "keyFactors": ["reverted to mean"]}
        if side == "SELL" and bb_pos <= 50:
            return {"action": "CLOSE", "confidence": 70, "criteriaScore": 3,
                    "reasoning": "Mean reversion: price reverted to BB mid — take profit",
                    "riskLevel": "LOW", "keyFactors": ["reverted to mean"]}
        return {"action": "HOLD", "confidence": 50, "criteriaScore": 1,
                "reasoning": "Holding mean-reversion trade, waiting for reversion to the mean",
                "riskLevel": "LOW", "keyFactors": []}

    # Flat bands = no edge; don't fade noise.
    if bw < 0.05:
        return {"action": "HOLD", "confidence": 40, "criteriaScore": 0,
                "reasoning": "Bollinger bands too tight — no mean-reversion edge",
                "riskLevel": "LOW", "keyFactors": []}

    score = 0
    factors = []

    # Distance from the mean (Bollinger position) — the core of the strategy.
    if bb_pos <= 15:
        score += 2; factors.append(f"price at/below lower BB ({bb_pos:.0f}%)")
    elif bb_pos <= 30:
        score += 1; factors.append(f"price near lower BB ({bb_pos:.0f}%)")
    elif bb_pos >= 85:
        score -= 2; factors.append(f"price at/above upper BB ({bb_pos:.0f}%)")
    elif bb_pos >= 70:
        score -= 1; factors.append(f"price near upper BB ({bb_pos:.0f}%)")

    # RSI extreme confirms the stretch.
    if rsi_v <= 30:
        score += 2; factors.append(f"RSI oversold ({rsi_v:.0f})")
    elif rsi_v <= 40:
        score += 1; factors.append(f"RSI low ({rsi_v:.0f})")
    elif rsi_v >= 70:
        score -= 2; factors.append(f"RSI overbought ({rsi_v:.0f})")
    elif rsi_v >= 60:
        score -= 1; factors.append(f"RSI high ({rsi_v:.0f})")

    # Stoch RSI as a faster confirmation.
    if srsi_k <= 20:
        score += 1; factors.append("Stoch RSI oversold")
    elif srsi_k >= 80:
        score -= 1; factors.append("Stoch RSI overbought")

    # Divergence confirms an imminent reversal.
    if div == "BULLISH" and score > 0:
        score += 1; factors.append("bullish divergence")
    elif div == "BEARISH" and score < 0:
        score -= 1; factors.append("bearish divergence")

    abs_score = abs(score)
    confidence = min(85, 50 + abs_score * 7)
    crit = min(5, abs_score)

    # Strong-trend guard: fading a strong trend is how mean-reversion bots blow up.
    # Only fade in the trend's direction (buy dips in an uptrend, sell rallies in a downtrend).
    trend_sep = abs(ema50 - ema200) / price * 100 if price else 0
    if trend_sep > 0.5:
        uptrend = ema50 > ema200
        if not ((score >= 3 and uptrend) or (score <= -3 and not uptrend)):
            return {"action": "HOLD", "confidence": 45, "criteriaScore": crit,
                    "reasoning": f"Strong trend — skipping counter-trend fade ({', '.join(factors) or 'neutral'})",
                    "riskLevel": "MEDIUM", "keyFactors": factors}

    if score >= 3:
        return {"action": "BUY", "confidence": confidence, "criteriaScore": crit,
                "reasoning": f"Mean reversion BUY: {', '.join(factors)}",
                "riskLevel": "MEDIUM", "keyFactors": factors}
    if score <= -3:
        return {"action": "SELL", "confidence": confidence, "criteriaScore": crit,
                "reasoning": f"Mean reversion SELL: {', '.join(factors)}",
                "riskLevel": "MEDIUM", "keyFactors": factors}
    return {"action": "HOLD", "confidence": 42, "criteriaScore": crit,
            "reasoning": f"No mean-reversion extreme ({', '.join(factors) or 'neutral'})",
            "riskLevel": "LOW", "keyFactors": factors}
