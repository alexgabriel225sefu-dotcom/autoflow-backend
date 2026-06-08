"""AI signal generation (port of ai.js). Anthropic primary, Groq free fallback."""
import re
import json
import requests
from apex import config as cfg

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
    pos = (f"{open_position['side']} @ ${open_position['entryPrice']} | "
           f"PnL: {open_position.get('pnlPct', 0):.2f}%") if open_position else "NONE"

    prompt = f"""You are a professional trader with 20 years of experience applying the rules of the great traders: Turtle breakout, Livermore structure, Soros momentum, PTJ defense. Analyze ALL the data and give a precise signal.

## MARKET DATA — {cfg.SYMBOL} ({cfg.TIMEFRAME})
### Price & Trend
- Current price: ${ind['price']}
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
- Volume ratio: {ind['volumeRatio']}x
- High 24h: {ind['high24h']} | Low 24h: {ind['low24h']}

### Last 5 candles
{recent}
{_legendary_section(strategy_data)}
## ACCOUNT
- Balance: ${balance:.2f} USDT
- Open position: {pos}

## ENTRY RULES
- SL: {cfg.STOP_LOSS_PCT * 100}% | TP: {cfg.TAKE_PROFIT_PCT * 100}% | Risk: {cfg.RISK_PER_TRADE * 100}%
- Minimum confidence: {cfg.MIN_CONFIDENCE}%
- BUY criteria (min 3/5): bullish trend, RSI<50 or bullish div, MACD up, volume>1.2x, price below EMA20
- SELL criteria (min 3/5): bearish trend, RSI>50 or bearish div, MACD down, volume>1.2x, price above EMA20
- BONUS +1 criterion if Turtle=STRONG BUY/SELL OR Livermore confirms direction OR Soros momentum aligned
- Do not trade against Livermore trend with strength >0.8

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
    print("[AI ❌] All AI sources failed — HOLD")
    return {"action": "HOLD", "confidence": 0, "reasoning": "AI error",
            "riskLevel": "HIGH", "keyFactors": [], "criteriaScore": 0}
