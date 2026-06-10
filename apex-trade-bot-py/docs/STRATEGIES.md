# Strategy Guide — How the Bot Decides

Every 5 minutes the bot runs a full analysis pipeline. A trade only opens when
**technical indicators, legendary-trader strategies, and the AI** all align —
and none of the risk-management circuit breakers have tripped.

```
candles ──► indicators ──► strategies ──► AI signal ──► filters ──► trade
                                              ▲
                              risk circuit breakers (can veto everything)
```

---

## 1. Technical indicators (`apex/indicators.py`)

| Indicator | What it measures |
|---|---|
| RSI (14) + Stoch RSI | Overbought / oversold momentum |
| MACD (12/26/9) | Trend momentum shifts |
| EMA 20 / 50 / 200 | Short, medium, long-term trend |
| Bollinger Bands (20, 2σ) | Volatility + position in range |
| ATR (14) | Volatility for stop placement |
| Volume ratio | Current vs 20-period average volume |
| RSI divergence | Price/momentum disagreement (reversal warning) |
| Market structure | UPTREND / DOWNTREND / SIDEWAYS classification |

## 2. Legendary-trader strategies (`apex/strategies.py`)

### 🐢 Turtle Breakout (Richard Dennis)
Buys when price closes above the 20-period high, sells below the 20-period
low. The classic trend-following system that turned novices into millionaires
in the 1980s.

### 📐 Livermore Structure (Jesse Livermore)
Compares the last two 6-candle halves. Higher-highs + higher-lows = BULLISH
(85% strength); lower-highs + lower-lows = BEARISH. The bot **never trades
against** a Livermore trend stronger than 80%.

### 💡 Soros Momentum (George Soros)
Counts bullish candles in the last 8 and measures price velocity. 75%+ green
candles with positive velocity = momentum regime worth riding.

### 📉 Mean Reversion (Z-score)
Measures how many standard deviations price has stretched from its 20-period
average. Beyond ±2σ, a snap-back becomes likely — the AI is warned the move
is extended.

### 🎯 Druckenmiller Sizing (Stanley Druckenmiller)
"It's not whether you're right or wrong, it's how much you make when you're
right." Position size scales from **0.4× to 2.0×** of base risk:
- Confidence ≥ 85 + 5/5 criteria → ×1.5
- STRONG Turtle breakout → ×1.3
- Livermore strength ≥ 0.8 → ×1.1
- Confidence < 75 or weak criteria → ×0.6

## 3. AI signal (`apex/ai.py`)

All of the above is fed to an AI model (Claude Haiku, or Groq Llama for free)
which returns:

```json
{"action": "BUY|SELL|HOLD|CLOSE", "confidence": 0-100,
 "criteriaScore": 0-5, "reasoning": "...", "riskLevel": "LOW|MEDIUM|HIGH"}
```

A trade requires **all** of:
- confidence ≥ `MIN_CONFIDENCE` (default 62)
- criteria score ≥ `MIN_CRITERIA` (default 3 of 5)
- volume ratio ≥ `MIN_VOLUME_RATIO` (default 0.7×)
- not vetoed by the PTJ filter (below)

If every AI provider is unreachable, the bot returns **HOLD** — it never
trades blind.

## 4. Protection rules (circuit breakers)

These can stop all trading regardless of how good a signal looks:

| Rule | Trigger | Inspired by |
|---|---|---|
| Loss streak stop | 3 consecutive losses | Ed Seykota |
| Daily stop | Daily loss exceeds −3% | Paul Tudor Jones |
| Drawdown stop | −20% from peak balance | Capital preservation |
| Overtrading stop | 10 trades in one day | Turtle rules |
| Counter-trend veto | BUY against strong BEARISH structure (or inverse) | PTJ |
| Dust stop | Balance under $1 | — |

Daily counters reset at midnight automatically.

## 5. Exit management

- **Stop loss / take profit** set at entry (fixed % or ATR-based, 1:2 R:R default)
- **Trailing stop** ratchets the SL upward as price moves in your favor —
  profit gets locked in, never given back past the trail distance
- **AI CLOSE** — the AI can close a position early if conditions reverse

---

## Multi-symbol scanner

When `MULTI_SYMBOL=true` (default), every cycle scores the watchlist
(RSI extremity 40% + volume surge 40% + MACD activity 20%) and analyzes the
strongest pair. While a position is open, the bot locks onto that symbol.

## Tuning cheatsheet

| Goal | Change |
|---|---|
| Fewer, higher-quality trades | `MIN_CONFIDENCE=75`, `MIN_CRITERIA=4` |
| Smaller risk | `/risk 10` |
| Wider stops in volatile markets | `ATR_BASED_SL=true` |
| Single pair only | `MULTI_SYMBOL=false`, `/symbol BTCUSDT` |
