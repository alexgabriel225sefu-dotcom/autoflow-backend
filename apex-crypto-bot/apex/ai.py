"""AI signal generation — crypto edition. Anthropic primary, Groq free fallback.

A per-symbol signal cache shares one AI call/min across all users on the same
pair, so 100 clients on BTCUSDT cost a single Groq request per minute.
"""
import re
import json
import time
import requests
from apex import config as cfg

_anthropic_client = None
_signal_cache = {}      # symbol → {ts, signal}
_CACHE_TTL = 55         # seconds (under the 60s tick)


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


def _call_groq(prompt, user_key=None):
    key = user_key or cfg.GROQ_API_KEY
    if not key:
        raise RuntimeError("GROQ_API_KEY missing")
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 400, "temperature": 0},
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=15)
        r.raise_for_status()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if user_key and status in (401, 429):
            err = RuntimeError("GROQ_KEY_INVALID" if status == 401 else "GROQ_KEY_QUOTA")
            err.user_key = True
            raise err
        raise
    text = r.json()["choices"][0]["message"]["content"].strip()
    print("[AI] ✅ Groq — signal generated")
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
            print(f"[AI ❌] Anthropic {model} | {status} | {err}")
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
### 🐢 Turtle (Dennis/Eckhardt)
- Breakout: {t.get('signal') or 'NONE'} | Strength: {t.get('breakoutStr')}
- 20-period High: {t.get('high20')} | Low: {t.get('low20')}
### 📐 Livermore (Structure)
- Trend: {lv.get('trend')} ({lv.get('reason', 'N/A')}) | Strength: {lv_strength}
- Rule: BULLISH confirms BUY; BEARISH confirms SELL; do NOT fight strength>0.8
### 💡 Soros (Momentum)
- Direction: {so.get('direction')} | Bullish candles: {so_mom} of last 8 | Velocity: {so_vel}
### 📉 Mean Reversion (Z-score vs SMA20)
- Z-score: {mr.get('zscore', 0)} | Stretched: {'YES — expect snap-back' if mr.get('stretched') else 'no'}
### 📊 Session (Seykota)
- Consecutive losses: {se.get('consecutiveLosses')} | Wins: {se.get('consecutiveWins')} | Trades today: {se.get('dailyTrades')}"""


def _build_prompt(ind, balance, open_position, strategy_data, symbol, timeframe):
    def fnum(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    macd_h = fnum(ind.get("macdHist"))
    recent = "\n".join(
        f"{i+1}. {c['direction']} O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']} (body: {c['bodyPct']}%)"
        for i, c in enumerate(ind["recentCandles"]))
    pos = (f"{open_position['side']} @ {open_position['entryPrice']} | "
           f"PnL: {open_position.get('pnlPct', 0):.2f}%") if open_position else "NONE"
    return f"""You are a professional crypto trader with 20 years of experience applying the rules of the great traders: Turtle breakout, Livermore structure, Soros momentum, PTJ defense. Analyze ALL the data and give a precise signal.

## MARKET DATA — {symbol} ({timeframe})
### Price & Trend
- Current price: {ind['price']}
- EMA 20: {ind['ema20']} | EMA 50: {ind['ema50']} | EMA 200: {ind['ema200']}
- Trend EMA20/50: {ind['emaTrend']} | EMA50/200: {ind['ema200Trend']}
- Price vs EMA20: {ind['priceVsEma20']} | Structure: {ind['marketStructure']}
### Momentum
- RSI(14): {ind['rsi']} | Stoch RSI K: {ind['stochRsiK']} D: {ind['stochRsiD']}
- MACD Histogram: {ind['macdHist']} {'bullish' if macd_h > 0 else 'bearish'}
- RSI divergence: {ind['divergence']}
### Volatility & Volume
- ATR: {ind['atrPct']}% | BB Bandwidth: {ind['bb_bandwidth']}% | BB Position: {ind['bb_position']}%
- Volume ratio: {ind['volumeRatio']}x | High: {ind['high24h']} | Low: {ind['low24h']}
### Last 5 candles
{recent}
{_legendary_section(strategy_data)}
## ACCOUNT
- Balance: ${balance:.2f} USDT
- Open position: {pos}

## ENTRY RULES
- SL: {cfg.STOP_LOSS_PCT * 100:g}% | TP: {cfg.TAKE_PROFIT_PCT * 100:g}% | Risk: {cfg.RISK_PER_TRADE * 100:g}% per trade
- Minimum confidence: {cfg.MIN_CONFIDENCE}% | Min criteria: {cfg.MIN_CRITERIA}/5
- BUY criteria (min 3/5): bullish trend, RSI<50 or bullish div, MACD up, volume>1.2x, price near/below EMA20
- SELL criteria (min 3/5): bearish trend, RSI>50 or bearish div, MACD down, volume>1.2x, price near/above EMA20
- BONUS +1 if Turtle=STRONG OR Livermore confirms OR Soros momentum aligned
- Do not trade against Livermore trend with strength >0.8

Respond ONLY with valid JSON:
{{"action":"BUY"|"SELL"|"HOLD"|"CLOSE","confidence":<0-100>,"reasoning":"<max 2 sentences>","riskLevel":"LOW"|"MEDIUM"|"HIGH","keyFactors":["f1","f2","f3"],"criteriaScore":<0-5>}}"""


def _fetch(ind, balance, open_position, strategy_data, symbol, timeframe, user_key):
    prompt = _build_prompt(ind, balance, open_position, strategy_data, symbol, timeframe)
    # Anthropic is only worth trying when a key is actually configured — otherwise
    # we'd burn ~1-2s on a guaranteed failure every single tick. The client's own
    # Groq key (or the shared one) is the real brain.
    if cfg.ANTHROPIC_API_KEY:
        try:
            return sanitize(_call_anthropic(prompt))
        except Exception:
            pass
    try:
        return sanitize(_call_groq(prompt, user_key))
    except Exception as err:
        if getattr(err, "user_key", False):
            raise
        print(f"[AI ❌] Groq failed: {err}")
    return rule_based_fallback(ind, open_position)


def test_key(key):
    """Quick liveness check for a client's Groq key. Returns (ok, message)."""
    if not key or not key.startswith("gsk_"):
        return False, "Key must start with gsk_"
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                  "max_tokens": 5, "temperature": 0},
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=12)
        if r.status_code == 401:
            return False, "Key rejected (401) — copy it again from console.groq.com"
        if r.status_code == 429:
            return False, "Key is valid but already rate-limited (429)"
        r.raise_for_status()
        return True, "Key works"
    except Exception as e:
        return False, f"Could not reach Groq ({e})"


def get_signal(ind, balance, open_position, strategy_data=None,
               symbol=None, timeframe=None, user_key=None):
    symbol = symbol or cfg.SYMBOL
    timeframe = timeframe or cfg.TIMEFRAME
    # User's own key → call directly (their quota), no shared cache.
    if user_key:
        return _fetch(ind, balance, open_position, strategy_data, symbol, timeframe, user_key)
    # Shared cache per symbol — but never cache decisions while THIS user has a
    # position (CLOSE logic is position-specific). Cache only flat-scan signals.
    if open_position:
        return _fetch(ind, balance, open_position, strategy_data, symbol, timeframe, None)
    now = time.time()
    cached = _signal_cache.get(symbol)
    if cached and now - cached["ts"] < _CACHE_TTL:
        return cached["signal"]
    sig = _fetch(ind, balance, None, strategy_data, symbol, timeframe, None)
    _signal_cache[symbol] = {"ts": now, "signal": sig}
    return sig


_VALID = ("BUY", "SELL", "HOLD", "CLOSE")


def sanitize(raw):
    action = raw.get("action") if raw.get("action") in _VALID else "HOLD"
    try:
        confidence = float(raw.get("confidence"))
        criteria = float(raw.get("criteriaScore"))
    except (TypeError, ValueError):
        return {"action": "HOLD", "confidence": 0, "criteriaScore": 0,
                "reasoning": str(raw.get("reasoning", "malformed")), "riskLevel": "HIGH", "keyFactors": []}
    return {
        "action": action,
        "confidence": min(100, max(0, confidence)),
        "criteriaScore": min(5, max(0, criteria)),
        "reasoning": str(raw.get("reasoning", "")),
        "riskLevel": raw.get("riskLevel") if raw.get("riskLevel") in ("LOW", "MEDIUM", "HIGH") else "MEDIUM",
        "keyFactors": raw.get("keyFactors", [])[:5] if isinstance(raw.get("keyFactors"), list) else [],
    }


def rule_based_fallback(ind, open_position=None):
    def fnum(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    if open_position:
        return {"action": "HOLD", "confidence": 50, "criteriaScore": 2,
                "reasoning": "Rule-based: holding position", "riskLevel": "MEDIUM", "keyFactors": []}
    rsi_v = fnum(ind.get("rsi", 50))
    macd_h = fnum(ind.get("macdHist"))
    vol_r = fnum(ind.get("volumeRatio", 1.0))
    price, ema20, ema50 = fnum(ind.get("price")), fnum(ind.get("ema20")), fnum(ind.get("ema50"))
    score, factors = 0, []
    if rsi_v < 25:
        score += 3; factors.append(f"RSI extreme oversold ({rsi_v:.0f})")
    elif rsi_v < 38:
        score += 2; factors.append(f"RSI oversold ({rsi_v:.0f})")
    elif rsi_v > 75:
        score -= 3; factors.append(f"RSI extreme overbought ({rsi_v:.0f})")
    elif rsi_v > 62:
        score -= 2; factors.append(f"RSI overbought ({rsi_v:.0f})")
    if macd_h > 0:
        score += 1; factors.append("MACD bullish")
    elif macd_h < 0:
        score -= 1; factors.append("MACD bearish")
    above = price > ema20 > ema50 if (ema20 and ema50) else False
    below = price < ema20 < ema50 if (ema20 and ema50) else False
    if score >= 0 and above:
        score += 1; factors.append("Price above EMAs")
    elif score >= 0 and below:
        score -= 1; factors.append("Price below EMAs")
    elif score < 0 and above:
        score -= 1; factors.append("Overextended above EMAs")
    elif score < 0 and below:
        score += 1; factors.append("Discount below EMAs")
    if vol_r >= 1.3 and score != 0:
        score += 1 if score > 0 else -1
        factors.append(f"Volume spike ({vol_r:.1f}x)")
    abs_s = abs(score)
    conf = min(85, 50 + abs_s * 9)   # score 1 → 59%, score 2 → 68%, score 3 → 77%
    crit = min(5, abs_s + 1)          # score 1 → crit 2, score 2 → crit 3
    if score >= 1:
        return {"action": "BUY", "confidence": conf, "criteriaScore": crit,
                "reasoning": f"Rule-based: {', '.join(factors)}", "riskLevel": "MEDIUM", "keyFactors": factors}
    if score <= -1:
        return {"action": "SELL", "confidence": conf, "criteriaScore": crit,
                "reasoning": f"Rule-based: {', '.join(factors)}", "riskLevel": "MEDIUM", "keyFactors": factors}
    return {"action": "HOLD", "confidence": 40, "criteriaScore": 0,
            "reasoning": "Rule-based: no clear signal", "riskLevel": "LOW", "keyFactors": factors}
