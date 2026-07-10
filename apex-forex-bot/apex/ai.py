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


_MODE_INTRO = {
    "mean_reversion": ("Forex ranges far more than it trends, so your PRIMARY edge is MEAN REVERSION: "
                       "fade overbought/oversold extremes back to the mean (RSI + Bollinger Bands), and only "
                       "ride a move when the higher-timeframe trend is genuinely strong. This is the opposite "
                       "of a crypto breakout bot."),
    "trend": ("Your PRIMARY edge is TREND FOLLOWING (Livermore: trade WITH the tape): identify the "
              "higher-timeframe trend and enter only in its direction — buy pullbacks to value in an uptrend, "
              "sell rallies in a downtrend. NEVER fade the trend, never chase an extended move."),
    "breakout": ("Your PRIMARY edge is BREAKOUT trading (Turtle rules): enter when price breaks a fresh "
                 "20-bar high/low with momentum and volatility expansion behind it, ride the expansion, and "
                 "exit on the opposite channel break. Skip exhausted or unconfirmed breaks."),
}

_MODE_RULES = {
    "mean_reversion": """- BUY (fade oversold dip, min 3/5): price in lower BB (<30%), RSI≤35 or bullish divergence, Stoch RSI K low, price stretched below EMA20, no strong downtrend
- SELL (fade overbought spike, min 3/5): price in upper BB (>70%), RSI≥65 or bearish divergence, Stoch RSI K high, price stretched above EMA20, no strong uptrend
- CLOSE when price reverts to the BB mid (the mean = your target)
- TREND GUARD: in a strong trend (EMA50 vs EMA200 widely separated) do NOT fade against it — only buy dips in an uptrend / sell rallies in a downtrend, else HOLD""",
    "trend": """- BUY (min 3/5): EMA50>EMA200 with price above EMA200, HH+HL market structure, pullback to/below EMA20 with RSI 35–60 (dip, not crash), MACD histogram positive, bullish momentum in recent candles
- SELL (min 3/5): EMA50<EMA200 with price below EMA200, LH+LL structure, rally to/above EMA20 with RSI 40–65, MACD histogram negative, bearish momentum
- NO TREND = NO TRADE: if EMAs are flat/tangled or structure is mixed, HOLD
- CLOSE early only if market structure flips hard against the position; otherwise let SL/TP work""",
    "breakout": """- BUY (min 3/5): fresh break of the 20-bar high, momentum agrees (recent candles bullish), MACD histogram positive, Bollinger bandwidth expanding, RSI not exhausted (<80)
- SELL (min 3/5): fresh break of the 20-bar low, bearish momentum, MACD negative, bandwidth expanding, RSI >20
- Never chase: if the break happened several candles ago or RSI is already extreme, HOLD
- CLOSE on an opposite 20-bar channel break; otherwise let SL/TP work""",
}


def get_signal(ind, balance, open_position, strategy_data=None, mode="mean_reversion"):
    def fnum(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    mode = (mode or "mean_reversion").lower()
    if mode not in _MODE_INTRO:
        mode = "mean_reversion"
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

    prompt = f"""You are a professional FOREX trader with 20 years of experience. {_MODE_INTRO[mode]} Analyze ALL the data and give a precise signal.

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

## ENTRY RULES — {STRATEGY_MODES[mode]['label'].upper() if mode in STRATEGY_MODES else 'MEAN REVERSION'}
- SL: {cfg.STOP_LOSS_PIPS:g} pips | TP: {cfg.TAKE_PROFIT_PIPS:g} pips | Risk: {cfg.RISK_PER_TRADE * 100:g}% per trade
- Minimum confidence: {cfg.MIN_CONFIDENCE}%
{_MODE_RULES[mode]}
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
    sig = signal_for_mode(mode, ind, strategy_data, open_position)
    print(f"[AI] {mode} rule fallback: {sig['action']} {sig['confidence']}%")
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
        if side == "BUY" and bb_pos >= 60:
            return {"action": "CLOSE", "confidence": 70, "criteriaScore": 3,
                    "reasoning": "Mean reversion: price reverted past BB mid — take profit",
                    "riskLevel": "LOW", "keyFactors": ["reverted past mean"]}
        if side == "SELL" and bb_pos <= 40:
            return {"action": "CLOSE", "confidence": 70, "criteriaScore": 3,
                    "reasoning": "Mean reversion: price reverted past BB mid — take profit",
                    "riskLevel": "LOW", "keyFactors": ["reverted past mean"]}
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
    # 0.5% is an FX "strong trend" cutoff; crypto sits above it almost always,
    # which would turn mean-reversion into a trend-only engine and kill genuine
    # range fades. Raise the cutoff for crypto.
    _mr_crypto = getattr(cfg, "PRODUCT", "forex") == "crypto"
    if trend_sep > (2.0 if _mr_crypto else 0.5):
        uptrend = ema50 > ema200
        if not ((score >= 3 and uptrend) or (score <= -3 and not uptrend)):
            return {"action": "HOLD", "confidence": 45, "criteriaScore": crit,
                    "reasoning": f"Strong trend — skipping counter-trend fade ({', '.join(factors) or 'neutral'})",
                    "riskLevel": "MEDIUM", "keyFactors": factors}

    # Crypto hits single clean extremes (BB edge OR RSI extreme = score 2) far
    # more usefully than forex, which needs the full stack to fade safely. A
    # score-3 gate left the crypto bot idle for hours in ranging markets, so
    # enter at score 2 on crypto (conf 64 ≥ MIN_CONFIDENCE). Forex stays at 3.
    _mr_thr = 2 if _mr_crypto else 3
    if score >= _mr_thr:
        return {"action": "BUY", "confidence": confidence, "criteriaScore": crit,
                "reasoning": f"Mean reversion BUY: {', '.join(factors)}",
                "riskLevel": "MEDIUM", "keyFactors": factors}
    if score <= -_mr_thr:
        return {"action": "SELL", "confidence": confidence, "criteriaScore": crit,
                "reasoning": f"Mean reversion SELL: {', '.join(factors)}",
                "riskLevel": "MEDIUM", "keyFactors": factors}
    return {"action": "HOLD", "confidence": 42, "criteriaScore": crit,
            "reasoning": f"No mean-reversion extreme ({', '.join(factors) or 'neutral'})",
            "riskLevel": "LOW", "keyFactors": factors}


def trend_signal(ind, strat=None, open_position=None):
    """TREND FOLLOWING engine (Livermore/Soros): trade WITH the tape.

    Buy pullbacks in a confirmed uptrend, sell rallies in a confirmed
    downtrend. Never fade. Exits ride SL/TP; a structure flip closes early.
    """
    def fnum(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    strat = strat or {}
    liv = strat.get("livermore") or {}
    sor = strat.get("soros") or {}
    rsi_v = fnum(ind.get("rsi"), 50)
    price = fnum(ind.get("price"))
    ema20 = fnum(ind.get("ema20"))
    ema50 = fnum(ind.get("ema50"))
    ema200 = fnum(ind.get("ema200"))
    macd_h = fnum(ind.get("macdHist"))

    up = ema50 > ema200 and price > ema200
    dn = ema50 < ema200 and price < ema200

    # In a trade → close early only if the structure flips against us.
    if open_position:
        side = open_position.get("side")
        flip = (side == "BUY" and liv.get("trend") == "BEARISH" and fnum(liv.get("strength")) >= 0.8) or \
               (side == "SELL" and liv.get("trend") == "BULLISH" and fnum(liv.get("strength")) >= 0.8)
        if flip:
            return {"action": "CLOSE", "confidence": 72, "criteriaScore": 3,
                    "reasoning": "Trend following: market structure flipped against the position",
                    "riskLevel": "MEDIUM", "keyFactors": ["structure flip"]}
        return {"action": "HOLD", "confidence": 55, "criteriaScore": 2,
                "reasoning": "Riding the trend — SL/TP manage the exit",
                "riskLevel": "LOW", "keyFactors": []}

    score, factors = 0, []
    if up:
        score += 2; factors.append("uptrend (EMA50>EMA200, price above)")
    elif dn:
        score -= 2; factors.append("downtrend (EMA50<EMA200, price below)")
    if liv.get("trend") == "BULLISH" and fnum(liv.get("strength")) >= 0.55:
        score += 1; factors.append("HH+HL structure")
    elif liv.get("trend") == "BEARISH" and fnum(liv.get("strength")) >= 0.55:
        score -= 1; factors.append("LH+LL structure")
    if sor.get("direction") == "BULLISH":
        score += 1; factors.append("bullish momentum")
    elif sor.get("direction") == "BEARISH":
        score -= 1; factors.append("bearish momentum")
    # Entry timing: pullback to value, not a chase. Buy dips (price at/under
    # EMA20 with RSI cooled off), sell rallies mirrored. Crypto trends harder
    # and its RSI runs hotter, so a forex-tight pullback band (RSI 35-60, price
    # ≤ EMA20+0.05%) almost never triggers on a crypto uptrend — widen the band
    # and shave the score threshold for the crypto build so it actually rides
    # trends instead of waiting forever.
    _crypto = getattr(cfg, "PRODUCT", "forex") == "crypto"
    if _crypto:
        pullback_buy = score > 0 and price <= ema20 * 1.004 and 38 <= rsi_v <= 70
        pullback_sell = score < 0 and price >= ema20 * 0.996 and 30 <= rsi_v <= 62
        thr = 3
    else:
        pullback_buy = score > 0 and price <= ema20 * 1.002 and 35 <= rsi_v <= 62
        pullback_sell = score < 0 and price >= ema20 * 0.998 and 38 <= rsi_v <= 65
        thr = 3
    if pullback_buy:
        score += 1; factors.append(f"pullback to EMA20 (RSI {rsi_v:.0f})")
    if pullback_sell:
        score -= 1; factors.append(f"rally to EMA20 (RSI {rsi_v:.0f})")
    if (macd_h > 0) and score > 0:
        score += 1; factors.append("MACD confirms")
    elif (macd_h < 0) and score < 0:
        score -= 1; factors.append("MACD confirms")

    conf = min(86, 50 + abs(score) * 7)
    crit = min(5, abs(score))
    if score >= thr and pullback_buy:
        return {"action": "BUY", "confidence": conf, "criteriaScore": crit,
                "reasoning": f"Trend following BUY: {', '.join(factors)}",
                "riskLevel": "MEDIUM", "keyFactors": factors}
    if score <= -thr and pullback_sell:
        return {"action": "SELL", "confidence": conf, "criteriaScore": crit,
                "reasoning": f"Trend following SELL: {', '.join(factors)}",
                "riskLevel": "MEDIUM", "keyFactors": factors}
    return {"action": "HOLD", "confidence": 44, "criteriaScore": crit,
            "reasoning": f"No trend entry ({', '.join(factors) or 'no confirmed trend / no pullback'})",
            "riskLevel": "LOW", "keyFactors": factors}


def breakout_signal(ind, strat=None, open_position=None):
    """TURTLE BREAKOUT engine: trade 20-bar channel breaks with confirmation.

    Enter on a fresh break of the 20-bar high/low when momentum agrees; an
    opposite break closes the position (classic channel exit).
    """
    def fnum(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    strat = strat or {}
    tur = strat.get("turtle") or {}
    sor = strat.get("soros") or {}
    rsi_v = fnum(ind.get("rsi"), 50)
    macd_h = fnum(ind.get("macdHist"))
    bw = fnum(ind.get("bb_bandwidth"))

    if open_position:
        side = open_position.get("side")
        opposite = "SELL" if side == "BUY" else "BUY"
        if tur.get("signal") == opposite:
            return {"action": "CLOSE", "confidence": 74, "criteriaScore": 3,
                    "reasoning": "Turtle exit: opposite 20-bar channel break",
                    "riskLevel": "MEDIUM", "keyFactors": ["opposite breakout"]}
        return {"action": "HOLD", "confidence": 55, "criteriaScore": 2,
                "reasoning": "Riding the breakout — SL/TP manage the exit",
                "riskLevel": "LOW", "keyFactors": []}

    sig = tur.get("signal")
    if not sig:
        return {"action": "HOLD", "confidence": 42, "criteriaScore": 0,
                "reasoning": "No 20-bar channel break",
                "riskLevel": "LOW", "keyFactors": []}

    score, factors = 2, [f"fresh 20-bar {'high' if sig == 'BUY' else 'low'} break"]
    if (sor.get("direction") == "BULLISH") == (sig == "BUY") and sor.get("direction") != "NEUTRAL":
        score += 1; factors.append("momentum agrees")
    if (macd_h > 0) == (sig == "BUY"):
        score += 1; factors.append("MACD agrees")
    if bw >= 0.12:
        score += 1; factors.append("volatility expanding")
    # Skip exhausted breaks — chasing a spike that already ran is the classic trap.
    if (sig == "BUY" and rsi_v >= 82) or (sig == "SELL" and rsi_v <= 18):
        return {"action": "HOLD", "confidence": 45, "criteriaScore": 1,
                "reasoning": f"Breakout already exhausted (RSI {rsi_v:.0f}) — not chasing",
                "riskLevel": "MEDIUM", "keyFactors": factors}

    if score >= 3:
        conf = min(86, 56 + score * 6)
        return {"action": sig, "confidence": conf, "criteriaScore": min(5, score),
                "reasoning": f"Turtle breakout {sig}: {', '.join(factors)}",
                "riskLevel": "MEDIUM", "keyFactors": factors}
    return {"action": "HOLD", "confidence": 46, "criteriaScore": min(5, score),
            "reasoning": f"Unconfirmed breakout ({', '.join(factors)})",
            "riskLevel": "LOW", "keyFactors": factors}


# ── Strategy-mode registry (used by the loop, Telegram and the backtester) ──
STRATEGY_MODES = {
    "auto": {
        "label": "Auto (regime-adaptive)",
        "blurb": "detects the market regime live — trend, range, high/low volatility — and switches to the right engine automatically, halving risk in violent markets and standing aside in dead ones. Recommended.",
        "engine": lambda ind, strat, pos: mean_reversion_signal(ind, pos),
    },
    "mean_reversion": {
        "label": "Mean Reversion",
        "blurb": "fades overbought/oversold extremes back to the mean (RSI + Bollinger). Best in ranging, sideways markets.",
        "engine": lambda ind, strat, pos: mean_reversion_signal(ind, pos),
    },
    "trend": {
        "label": "Trend Following",
        "blurb": "trades WITH the higher-timeframe trend, buying pullbacks in uptrends and selling rallies in downtrends (Livermore).",
        "engine": lambda ind, strat, pos: trend_signal(ind, strat, pos),
    },
    "breakout": {
        "label": "Turtle Breakout",
        "blurb": "enters on fresh 20-bar channel breaks with momentum confirmation, exits on the opposite break (Turtle).",
        "engine": lambda ind, strat, pos: breakout_signal(ind, strat, pos),
    },
}


def signal_for_mode(mode, ind, strat=None, open_position=None):
    m = STRATEGY_MODES.get((mode or "mean_reversion").lower(), STRATEGY_MODES["mean_reversion"])
    return m["engine"](ind, strat, open_position)
