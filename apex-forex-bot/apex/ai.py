"""AI signal generation (port of ai.js). Anthropic primary, Groq free fallback."""
import re
import json
import requests
from apex import config as cfg
from apex import forex

_anthropic_client = None


def _context_line():
    """One extra line of market context for the AI prompt — sentiment for
    crypto (Fear & Greed), upcoming high-impact events for forex. This is
    informational context the AI weighs alongside the technicals, never a
    standalone prediction and never a hard block on its own."""
    try:
        if getattr(cfg, "PRODUCT", "forex") == "crypto":
            from apex import sentiment
            fg = sentiment.fear_greed()
            if not fg:
                return "- Market sentiment: unavailable right now — weigh technicals only"
            return (f"- Crypto Fear & Greed Index: {fg['value']}/100 ({fg['label']}) — "
                    "context only: extreme readings often precede mean-reversion, "
                    "but do not treat this as a standalone signal")
        else:
            from apex import news
            currencies = [c for c in re.split(r"[_/]", cfg.SYMBOL) if c]
            events = news.upcoming(currencies, hours=12, limit=3)
            if not events:
                return "- Upcoming high-impact news (next 12h): none scheduled"
            lines = "; ".join(f"{e['title']} ({e['currency']}) in {e['in_min']}m" for e in events)
            return (f"- Upcoming high-impact news (next 12h): {lines} — "
                    "reduce confidence or stand aside if entry timing lands near release time")
    except Exception:
        return "- Market context: unavailable this tick — weigh technicals only"


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        # The SDK's default timeout is 600s — a slow/hung Anthropic call would
        # stall a user's trading tick that long before falling back to Groq
        # (get_signal only falls back on an exception, not on latency). Cap it
        # short so a slow API degrades to the fallback instead of freezing.
        _anthropic_client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY, timeout=20.0)
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
    "fibonacci": ("Your PRIMARY edge is FIBONACCI trading: identify the current swing and trade bounces "
                  "off key retracement levels (38.2%, 50%, 61.8%). Enter when price reaches a Fibonacci level "
                  "with confirmation from RSI and candle structure."),
    "fvg": ("Your PRIMARY edge is FAIR VALUE GAP (FVG) trading: identify 3-candle imbalance zones where "
            "price moved too fast (gap between candle 1 and candle 3), and enter when price returns to fill "
            "these gaps — institutional footprints of aggressive moves."),
    "ifvg": ("Your PRIMARY edge is INVERSE FVG trading: identify FVGs that have already been filled (invalidated) "
             "and now act as rejection zones — price gets repelled from these zones, providing reversal entries."),
    "supply_demand": ("Your PRIMARY edge is SUPPLY & DEMAND zone trading: identify areas where institutional "
                      "orders created strong impulsive moves (big candle bodies with high momentum), and enter "
                      "when price returns to the origin of that move — the supply/demand zone."),
    "liquidity_sweep": ("Your PRIMARY edge is LIQUIDITY SWEEP trading: identify false breakouts past swing "
                        "highs/lows (stop hunts) where price sweeps liquidity pools and reverses. Enter on the "
                        "reversal for high-probability mean-reversion back into the range."),
    "evc": ("Your PRIMARY edge is EQUILIBRIUM VOLUME CANDLE (EVC) trading: identify candles with balanced "
            "buyer/seller volume at key price levels (small body, equal wicks, average volume), signaling "
            "indecision that resolves into a directional move. Enter on the resolution."),
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
    "fibonacci": """- BUY (min 3/5): price touching a Fibonacci retracement level (38.2%, 50%, 61.8%) in an upswing, RSI not overbought, bullish candle pattern at level, higher-timeframe trend supports
- SELL (min 3/5): price touching a Fibonacci level in a downswing, RSI not oversold, bearish candle at level, trend supports
- HOLD if price is between levels with no clear reaction
- CLOSE at the next Fibonacci extension (127.2% or 161.8%) or if price breaks back through the entry level""",
    "fvg": """- BUY (min 3/5): price has returned to a bullish FVG zone, showing signs of holding (wick rejection, small body), market structure bullish (UPTREND), RSI not extreme
- SELL (min 3/5): price has returned to a bearish FVG zone with rejection signals, market structure bearish, RSI not oversold
- HOLD if price is not in any FVG zone or the zone is stale (>30 candles old)
- CLOSE when the gap is fully filled (price exits the other side of the zone) or at the origin of the impulse""",
    "ifvg": """- BUY (min 3/5): price rejected at an invalidated bearish FVG (it filled and is now acting as support), bullish candle structure, momentum turning up
- SELL (min 3/5): price rejected at an invalidated bullish FVG (now resistance), bearish candle, momentum turning down
- HOLD if no IFVG rejection is occurring
- CLOSE at the next structure level or if the IFVG zone is broken through cleanly""",
    "supply_demand": """- BUY (min 3/5): price at a demand zone (base of a strong bullish impulse), RSI not overbought, candle showing wick rejection from zone, higher-timeframe trend not strongly bearish
- SELL (min 3/5): price at a supply zone (origin of strong bearish impulse), RSI not oversold, rejection candle visible, trend not strongly bullish
- HOLD if price is in no-man's land between zones
- CLOSE if price breaks cleanly through the zone (the zone is invalidated) — do not hold a loser in a broken zone""",
    "liquidity_sweep": """- BUY (min 3/5): price swept below a swing low (stop hunt), closed back above it (reversal confirmed), ideally with a long lower wick and increased volume
- SELL (min 3/5): price swept above a swing high, closed back below it, with rejection wick
- HOLD if no sweep has occurred or price hasn't yet closed back inside the range
- CLOSE at the opposite end of the range or at a key resistance/support — the reversal target is the other side of the range that was swept""",
    "evc": """- BUY (min 3/5): equilibrium volume candle (small body, balanced wicks, normal volume) at a key level, followed by bullish resolution (next candle closes above EVC high)
- SELL (min 3/5): EVC at a key level with bearish resolution (next candle closes below EVC low)
- HOLD if no equilibrium candle is present or resolution hasn't occurred yet
- CLOSE at the next significant level or if momentum fades (RSI extreme); EVC trades typically target 1:2 RR""",
}


def get_signal(ind, balance, open_position, strategy_data=None, mode="mean_reversion"):
    """Rule-based signal is PRIMARY. AI confirms or blocks — never initiates."""
    mode = (mode or "mean_reversion").lower()
    if mode not in _MODE_INTRO:
        mode = "mean_reversion"

    rule_sig = signal_for_mode(mode, ind, strategy_data, open_position)
    rule_action = rule_sig.get("action", "HOLD")
    rule_conf = rule_sig.get("confidence", 0)

    if rule_action in ("CLOSE", "HOLD"):
        print(f"[AI] {mode} rule-based: {rule_action} {rule_conf}%")
        return rule_sig

    # Rule says BUY/SELL — ask AI to confirm (optional filter)
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
    pos = "NONE"  # hide position from AI to prevent directional bias
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

### Smart Money Concepts
- Fibonacci: trend={ind.get('fibonacci', {}).get('trend', 'N/A')}, nearest level={ind.get('fibonacci', {}).get('nearest', 'N/A')} @ {ind.get('fibonacci', {}).get('nearestPrice', 'N/A')}, signal={ind.get('fibonacci', {}).get('signal', 'NONE')}
- FVG (Fair Value Gap): signal={ind.get('fvg', {}).get('signal', 'NONE')}, gaps found={ind.get('fvg', {}).get('count', 0)}
- Inverse FVG: signal={ind.get('ifvg', {}).get('signal', 'NONE')}, zones={len(ind.get('ifvg', {}).get('zones', []))}
- Supply/Demand: signal={ind.get('supplyDemand', {}).get('signal', 'NONE')}
- Liquidity Sweep: signal={ind.get('liquiditySweep', {}).get('signal', 'NONE')}, type={ind.get('liquiditySweep', {}).get('type', 'none')}, swept={ind.get('liquiditySweep', {}).get('swept', 'N/A')}
- EVC (Equilibrium Volume): signal={ind.get('evc', {}).get('signal', 'NONE')}, equilibrium={ind.get('evc', {}).get('equilibrium', False)}

### Last 5 candles
{recent}

### Market Context
{_context_line()}

## ACCOUNT
- Balance: ${balance:.2f} USD | Leverage: 1:{cfg.LEVERAGE:g}
- Open position: {pos}

## ENTRY RULES — {STRATEGY_MODES[mode]['label'].upper() if mode in STRATEGY_MODES else 'MEAN REVERSION'}
- SL: {cfg.STOP_LOSS_PIPS:g} pips | TP: {cfg.TAKE_PROFIT_PIPS:g} pips | Risk: {cfg.RISK_PER_TRADE * 100:g}% per trade
- Minimum confidence: {cfg.MIN_CONFIDENCE}%
{_MODE_RULES[mode]}
- Leverage is 1:{cfg.LEVERAGE:g} — size for stability, not for chasing volatility
- Weigh the Market Context line above like any other input: it can lower your
  confidence or tip a borderline call, but the technicals still lead — it is
  not a prediction and never justifies a trade the technicals don't support

Respond ONLY with valid JSON:
{{"action":"BUY"|"SELL"|"HOLD"|"CLOSE","confidence":<0-100>,"reasoning":"<max 2 sentences>","riskLevel":"LOW"|"MEDIUM"|"HIGH","keyFactors":["f1","f2","f3"],"criteriaScore":<0-5>}}"""

    ai_sig = None
    try:
        ai_sig = _call_anthropic(prompt)
    except Exception:
        try:
            ai_sig = _call_groq(prompt)
        except Exception as err:
            print(f"[AI ❌] AI unavailable ({err}) — using rule signal")

    if ai_sig is None:
        print(f"[AI] {mode} rule-only: {rule_action} {rule_conf}%")
        return rule_sig

    ai_action = ai_sig.get("action", "HOLD")
    if ai_action == rule_action:
        rule_sig["confidence"] = min(88, rule_conf + 8)
        rule_sig.setdefault("keyFactors", []).append("AI confirms")
        print(f"[AI] {mode} rule+AI agree: {rule_action} {rule_sig['confidence']}%")
        return rule_sig
    if ai_action == "HOLD":
        rule_sig["confidence"] = max(55, rule_conf - 5)
        print(f"[AI] {mode} rule {rule_action}, AI neutral → {rule_sig['confidence']}%")
        return rule_sig
    # AI contradicts → block
    print(f"[AI] {mode} rule {rule_action} BLOCKED by AI ({ai_action})")
    return {"action": "HOLD", "confidence": 45, "criteriaScore": 1,
            "reasoning": f"Rule {rule_action} blocked — AI sees {ai_action}",
            "riskLevel": "LOW", "keyFactors": ["rule-AI disagreement"]}


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
        score -= 1; factors.append("Price confirms bearish below EMAs")

    # Volume amplifies the existing direction
    if vol_r >= 1.3 and score != 0 and ind.get("hasVolume", True):
        score += 1 if score > 0 else -1
        factors.append(f"Volume spike ({vol_r:.1f}x)")

    abs_score = abs(score)
    confidence    = min(85, 52 + abs_score * 8)
    criteria_score = min(5, abs_score + 1)

    if score >= 3:
        return {"action": "BUY",  "confidence": confidence, "criteriaScore": criteria_score,
                "reasoning": f"Rule-based: {', '.join(factors)}", "riskLevel": "MEDIUM",
                "keyFactors": factors}
    if score <= -3:
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

    # Already in a trade → let SL/TP handle exit. Only close early if price
    # has overshot well past the mean (profit-taking zone, not midline).
    if open_position:
        side = open_position.get("side")
        if side == "BUY" and bb_pos >= 65:
            return {"action": "CLOSE", "confidence": 72, "criteriaScore": 3,
                    "reasoning": "Mean reversion: price overshot past mean — taking profit",
                    "riskLevel": "LOW", "keyFactors": ["overshot mean"]}
        if side == "SELL" and bb_pos <= 35:
            return {"action": "CLOSE", "confidence": 72, "criteriaScore": 3,
                    "reasoning": "Mean reversion: price overshot past mean — taking profit",
                    "riskLevel": "LOW", "keyFactors": ["overshot mean"]}
        return {"action": "HOLD", "confidence": 55, "criteriaScore": 2,
                "reasoning": "Holding mean-reversion trade — riding to TP",
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

    _mr_thr = 3
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
        pullback_buy = score > 0 and price <= ema20 * 1.005 and 35 <= rsi_v <= 65
        pullback_sell = score < 0 and price >= ema20 * 0.995 and 35 <= rsi_v <= 65
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


def fibonacci_signal(ind, strat=None, open_position=None):
    """FIBONACCI engine: trade bounces off key retracement/extension levels."""
    fib = ind.get("fibonacci") or {}
    signal = fib.get("signal")
    trend = fib.get("trend", "NEUTRAL")
    nearest = fib.get("nearest", "N/A")

    if open_position:
        return {"action": "HOLD", "confidence": 55, "criteriaScore": 2,
                "reasoning": "Fibonacci: holding position, SL/TP manage exit",
                "riskLevel": "LOW", "keyFactors": []}

    if not signal:
        return {"action": "HOLD", "confidence": 42, "criteriaScore": 0,
                "reasoning": f"No Fibonacci level reaction (nearest: {nearest})",
                "riskLevel": "LOW", "keyFactors": []}

    factors = [f"price at Fib {nearest}", f"swing trend {trend}"]
    rsi_v = float(ind.get("rsi") or 50)
    if signal == "BUY" and rsi_v < 45:
        factors.append(f"RSI supports ({rsi_v:.0f})")
    elif signal == "SELL" and rsi_v > 55:
        factors.append(f"RSI supports ({rsi_v:.0f})")

    return {"action": signal, "confidence": 72, "criteriaScore": 3,
            "reasoning": f"Fibonacci {signal}: {', '.join(factors)}",
            "riskLevel": "MEDIUM", "keyFactors": factors}


def fvg_signal(ind, strat=None, open_position=None):
    """FVG engine: trade into unfilled Fair Value Gaps."""
    fvg = ind.get("fvg") or {}
    signal = fvg.get("signal")

    if open_position:
        return {"action": "HOLD", "confidence": 55, "criteriaScore": 2,
                "reasoning": "FVG: holding, waiting for gap fill target",
                "riskLevel": "LOW", "keyFactors": []}

    if not signal:
        return {"action": "HOLD", "confidence": 42, "criteriaScore": 0,
                "reasoning": "No price in FVG zone",
                "riskLevel": "LOW", "keyFactors": []}

    factors = [f"price inside {'bullish' if signal == 'BUY' else 'bearish'} FVG"]
    structure = ind.get("marketStructure", "SIDEWAYS")
    if (signal == "BUY" and structure == "UPTREND") or (signal == "SELL" and structure == "DOWNTREND"):
        factors.append("aligned with market structure")

    return {"action": signal, "confidence": 70, "criteriaScore": 3,
            "reasoning": f"FVG {signal}: {', '.join(factors)}",
            "riskLevel": "MEDIUM", "keyFactors": factors}


def ifvg_signal(ind, strat=None, open_position=None):
    """Inverse FVG engine: trade rejections from invalidated gaps."""
    ifvg = ind.get("ifvg") or {}
    signal = ifvg.get("signal")

    if open_position:
        return {"action": "HOLD", "confidence": 55, "criteriaScore": 2,
                "reasoning": "IFVG: holding position",
                "riskLevel": "LOW", "keyFactors": []}

    if not signal:
        return {"action": "HOLD", "confidence": 42, "criteriaScore": 0,
                "reasoning": "No Inverse FVG rejection detected",
                "riskLevel": "LOW", "keyFactors": []}

    factors = ["price rejected at invalidated FVG zone"]
    return {"action": signal, "confidence": 68, "criteriaScore": 3,
            "reasoning": f"Inverse FVG {signal}: {', '.join(factors)}",
            "riskLevel": "MEDIUM", "keyFactors": factors}


def supply_demand_signal(ind, strat=None, open_position=None):
    """Supply & Demand zone engine: trade entries at institutional zones."""
    sd = ind.get("supplyDemand") or {}
    signal = sd.get("signal")

    if open_position:
        return {"action": "HOLD", "confidence": 55, "criteriaScore": 2,
                "reasoning": "Supply/Demand: holding, SL/TP manage exit",
                "riskLevel": "LOW", "keyFactors": []}

    if not signal:
        return {"action": "HOLD", "confidence": 42, "criteriaScore": 0,
                "reasoning": "Price not at a supply/demand zone",
                "riskLevel": "LOW", "keyFactors": []}

    zone_type = "demand" if signal == "BUY" else "supply"
    factors = [f"price at {zone_type} zone"]
    rsi_v = float(ind.get("rsi") or 50)
    if signal == "BUY" and rsi_v < 50:
        factors.append(f"RSI not overbought ({rsi_v:.0f})")
    elif signal == "SELL" and rsi_v > 50:
        factors.append(f"RSI not oversold ({rsi_v:.0f})")

    return {"action": signal, "confidence": 72, "criteriaScore": 3,
            "reasoning": f"Supply/Demand {signal}: {', '.join(factors)}",
            "riskLevel": "MEDIUM", "keyFactors": factors}


def liquidity_sweep_signal(ind, strat=None, open_position=None):
    """Liquidity Sweep engine: trade reversals after stop hunts."""
    ls = ind.get("liquiditySweep") or {}
    signal = ls.get("signal")

    if open_position:
        return {"action": "HOLD", "confidence": 55, "criteriaScore": 2,
                "reasoning": "Liquidity sweep: riding reversal",
                "riskLevel": "LOW", "keyFactors": []}

    if not signal:
        return {"action": "HOLD", "confidence": 42, "criteriaScore": 0,
                "reasoning": "No liquidity sweep detected",
                "riskLevel": "LOW", "keyFactors": []}

    sweep_type = ls.get("type", "unknown")
    swept = ls.get("swept", "N/A")
    factors = [f"{sweep_type} detected", f"swept level: {swept}"]
    return {"action": signal, "confidence": 74, "criteriaScore": 4,
            "reasoning": f"Liquidity Sweep {signal}: {', '.join(factors)}",
            "riskLevel": "MEDIUM", "keyFactors": factors}


def evc_signal(ind, strat=None, open_position=None):
    """EVC engine: trade off equilibrium volume candles at key levels."""
    evc_data = ind.get("evc") or {}
    signal = evc_data.get("signal")

    if open_position:
        return {"action": "HOLD", "confidence": 55, "criteriaScore": 2,
                "reasoning": "EVC: holding position",
                "riskLevel": "LOW", "keyFactors": []}

    if not signal:
        eq = evc_data.get("equilibrium", False)
        if eq:
            return {"action": "HOLD", "confidence": 50, "criteriaScore": 1,
                    "reasoning": "Equilibrium candle detected but no directional bias",
                    "riskLevel": "LOW", "keyFactors": ["equilibrium candle"]}
        return {"action": "HOLD", "confidence": 42, "criteriaScore": 0,
                "reasoning": "No equilibrium volume candle",
                "riskLevel": "LOW", "keyFactors": []}

    level = evc_data.get("level", "N/A")
    factors = [f"equilibrium candle at {level}", f"body ratio: {evc_data.get('bodyRatio', 'N/A')}"]
    return {"action": signal, "confidence": 68, "criteriaScore": 3,
            "reasoning": f"EVC {signal}: {', '.join(factors)}",
            "riskLevel": "MEDIUM", "keyFactors": factors}


def auto_engine(ind, strat, open_position):
    """AUTO fallback for calls where the mode wasn't pre-resolved by regime
    detection (the live loop resolves 'auto' via strategies.detect_regime;
    /backtest and any direct signal_for_mode('auto') land here). Follow a
    confirmed Livermore trend, otherwise fade the range with mean reversion —
    previously this silently ran pure mean reversion, which loses in trends."""
    strat = strat or {}
    liv = strat.get("livermore") or {}
    if liv.get("trend") in ("BULLISH", "BEARISH") and (liv.get("strength") or 0) >= 0.6:
        return trend_signal(ind, strat, open_position)
    return mean_reversion_signal(ind, open_position)


# ── Strategy-mode registry (used by the loop, Telegram and the backtester) ──
STRATEGY_MODES = {
    "auto": {
        "label": "Auto (regime-adaptive)",
        "blurb": "detects the market regime live — trend, range, high/low volatility — and switches to the right engine automatically, halving risk in violent markets and standing aside in dead ones. Recommended.",
        "engine": lambda ind, strat, pos: auto_engine(ind, strat, pos),
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
    "fibonacci": {
        "label": "Fibonacci",
        "blurb": "trades bounces off key Fibonacci retracement (38.2%, 50%, 61.8%) and extension levels from the current swing.",
        "engine": lambda ind, strat, pos: fibonacci_signal(ind, strat, pos),
    },
    "fvg": {
        "label": "Fair Value Gap (FVG)",
        "blurb": "enters when price returns to an unfilled imbalance gap — institutional footprint left by aggressive moves.",
        "engine": lambda ind, strat, pos: fvg_signal(ind, strat, pos),
    },
    "ifvg": {
        "label": "Inverse FVG",
        "blurb": "trades rejections at invalidated FVGs — zones that initially attracted price but failed and now repel it.",
        "engine": lambda ind, strat, pos: ifvg_signal(ind, strat, pos),
    },
    "supply_demand": {
        "label": "Supply & Demand",
        "blurb": "identifies institutional accumulation/distribution zones and enters when price returns to them with reduced risk.",
        "engine": lambda ind, strat, pos: supply_demand_signal(ind, strat, pos),
    },
    "liquidity_sweep": {
        "label": "Liquidity Sweep",
        "blurb": "detects stop hunts — false breaks past swing highs/lows that reverse — and enters on the reversal for high-probability trades.",
        "engine": lambda ind, strat, pos: liquidity_sweep_signal(ind, strat, pos),
    },
    "evc": {
        "label": "EVC (Equilibrium Volume)",
        "blurb": "identifies balanced volume candles at key price levels — indecision that resolves into a directional move.",
        "engine": lambda ind, strat, pos: evc_signal(ind, strat, pos),
    },
}


def signal_for_mode(mode, ind, strat=None, open_position=None):
    m = STRATEGY_MODES.get((mode or "mean_reversion").lower(), STRATEGY_MODES["mean_reversion"])
    return m["engine"](ind, strat, open_position)
