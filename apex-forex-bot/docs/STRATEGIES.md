# Strategy Guide — How the Bot Decides

Every 5 minutes (while the market is open) the bot runs a full analysis
pipeline. A trade only opens when **technical indicators, legendary-trader
strategies, and the AI** all align — and none of the risk circuit breakers
have tripped.

```
candles ──► indicators ──► strategies ──► AI signal ──► filters ──► trade
                                              ▲
              market hours · spread guard · risk circuit breakers (veto)
```

---

## Forex-specific guards (run before anything else)

| Guard | Behavior |
|---|---|
| **Market hours** | No analysis from Friday 21:00 UTC to Sunday 21:00 UTC — forex is closed on weekends |
| **Spread guard** | Entry skipped when the bid/ask spread exceeds `MAX_SPREAD_PIPS` (default 3) — wide spreads around news/rollover eat the edge |
| **Margin cap** | Position size never uses more than 50% of available margin, regardless of signal strength |

## 1. Technical indicators

RSI (14), Stoch RSI, MACD (12/26/9), EMA 20/50/200, Bollinger Bands, ATR,
tick-volume ratio, RSI divergence, and market-structure classification —
all computed on cTrader candles.

## 2. Legendary-trader strategies

### 🐢 Turtle Breakout (Richard Dennis)
Buys a close above the 20-period high, sells below the 20-period low. Trend
following works in forex precisely because central-bank cycles create long
trends.

### 📐 Livermore Structure (Jesse Livermore)
Higher-highs + higher-lows = BULLISH (85% strength); the reverse = BEARISH.
The bot **never trades against** a Livermore trend stronger than 80%.

### 💡 Soros Momentum (George Soros)
The man who broke the Bank of England: 75%+ directional candles in the last
8 with strong velocity = momentum regime worth riding.

### 📉 Mean Reversion (Z-score)
Currency pairs are famously range-bound. When price stretches beyond ±2σ
from its 20-period average, the AI is warned a snap-back is likely.

### 🎯 Druckenmiller Sizing
Position size scales 0.4×–2.0× of base risk with conviction: strong Turtle
breakout ×1.3, Livermore ≥0.8 ×1.1, weak setups ×0.6.

## 3. AI signal

Everything above — plus **active trading sessions** (London/New York overlap
has the best liquidity) and leverage context — goes to the AI (Claude Haiku,
or Groq Llama free). It must return a JSON verdict with confidence and a 0–5
criteria score. A trade requires confidence ≥ 62 **and** ≥ 3/5 criteria.

When the data source provides no forex tick volume (e.g. Twelve Data), the
volume criterion is automatically replaced with a Stoch RSI alignment check,
so the score stays reachable.

If every AI provider is down, the bot returns **HOLD** — it never trades blind.

## 3b. Entry filters (after the AI, before the order)

| Filter | Behavior |
|---|---|
| **1h trend filter** | EMA50 on the 1h chart: no BUY in a downtrend, no SELL in an uptrend. The single biggest chop-killer. (`HTF_FILTER`, off in MT mode) |
| **Loss cooldown** | After a losing trade, no new entries for 15 minutes — no revenge trading (`COOLDOWN_AFTER_LOSS_MIN`) |
| **Counter-trend veto** | Strong Livermore structure + Turtle breakout in the opposite direction forces HOLD |

## 4. Position sizing (pip-based)

```
risk_amount = balance × RISK_PER_TRADE        ($1,000 × 2% = $20)
units       = risk_amount / (SL_pips × pip_value_per_unit)
```

With a 15-pip stop on EUR_USD that's ~13,300 units — if the stop is hit you
lose ~$20, exactly the 2% you risked. Leverage only affects the margin cap,
never the risk.

## 5. Protection rules (circuit breakers)

| Rule | Trigger | Inspired by |
|---|---|---|
| Loss streak stop | 3 consecutive losses | Ed Seykota |
| Daily stop | Daily loss exceeds −3% | Paul Tudor Jones |
| Drawdown stop | −20% from peak balance | Capital preservation |
| Overtrading stop | 10 trades in one day | Turtle rules |
| Counter-trend veto | Trading against strong structure | PTJ |

## 6. Exit management (cut losses short, let profits run)

| Stage | What happens |
|---|---|
| Entry | SL 15 pips, TP 30 pips (1:2 R:R) — or ATR-based with `ATR_BASED_SL=true` |
| +1R in profit (+15 pips) | **Breakeven stop** — SL moves to entry +1 pip. The trade can no longer lose (`BREAKEVEN_AT_R`) |
| Trailing | Stop ratchets 10 pips behind price, locking profit as it moves |
| TP reached | **Runner mode** (paper trading) — instead of closing, the trail tightens to 6 pips and the trade rides the trend (`LET_WINNERS_RUN`). Exits as `TRAIL_PROFIT`, often well past the 30-pip TP |
| Live brokers | SL/TP are placed server-side at the broker (cTrader/MT5) — they protect you even if the bot goes offline |
| AI CLOSE | The AI can close early if conditions reverse |

## Realistic expectations

Each win at default settings is roughly **+2–4% of balance** (2% risk × 1:2
R:R, more with a runner), each loss −2%. Forex moves at macro pace:
0–3 trades per day is normal, and quiet days with zero trades are part of
the system. A good month on a $1,000 paper account looks like **+5–15%**,
with losing weeks in between. Anyone promising more from a 5-minute bot
is selling fiction.

---

## Tuning cheatsheet

| Goal | Change |
|---|---|
| Fewer, higher-quality trades | `MIN_CONFIDENCE=75`, `MIN_CRITERIA=4` |
| Lower risk | `/risk 1` |
| Wider stops for volatile pairs (GBP_JPY) | `/sl 25` `/tp 50`, or `ATR_BASED_SL=true` |
| Single pair only | `MULTI_SYMBOL=false`, `/symbol EUR_USD` |
| Avoid news spikes | Lower `MAX_SPREAD_PIPS=2` (spreads widen around news) |
