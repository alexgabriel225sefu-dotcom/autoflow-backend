# ⚡ Apex Trade Bot

AI-powered crypto trading bot with multi-exchange support, legendary trader strategies, and Telegram alerts.

## How it works

Every 5 minutes the bot runs one analysis cycle:

1. **Scanner** — scores all pairs in `SCAN_SYMBOLS` (momentum + volume) and picks the strongest one. If a position is open, it locks onto that symbol until the trade closes.
2. **Indicators** — computes RSI, Stochastic RSI, MACD, EMA 20/50/200, Bollinger Bands, ATR, volume ratio, and RSI divergence on the 5m chart.
3. **Legendary strategies** — runs the Turtle breakout (20-period high/low), Jesse Livermore market structure (HH/HL vs LH/LL), and George Soros momentum on the same candles.
4. **AI signal** — sends everything to Claude (or Groq, free) which returns `BUY / SELL / HOLD / CLOSE` with a confidence score and a 0–5 criteria score.
5. **Entry filters** — the signal must pass ALL of these before any trade opens:
   - confidence ≥ `MIN_CONFIDENCE` and criteria ≥ `MIN_CRITERIA`
   - volume ratio ≥ `MIN_VOLUME_RATIO`
   - not against a strong Livermore + Turtle consensus ("never fight the tape")
   - **1h trend filter** — no longs in a 1h downtrend, no shorts in a 1h uptrend (`HTF_FILTER`)
   - **loss cooldown** — after a losing trade, no new entries for `COOLDOWN_AFTER_LOSS_MIN` minutes (no revenge trading)
6. **Position sizing** — Druckenmiller multiplier scales the position 0.4×–2× based on conviction (AI confidence + breakout confirmation).

### Exit logic (cut losses short, let profits run)

| Stage | What happens |
|---|---|
| Entry | SL at `STOP_LOSS_PCT` (0.8%), TP at `TAKE_PROFIT_PCT` (1.6%) — or ATR-based if `ATR_BASED_SL=true` |
| +1R in profit | **Breakeven stop** — SL moves to entry + fees. The trade can no longer lose (`BREAKEVEN_AT_R`) |
| TP reached | **Runner mode** — instead of closing, the trailing stop tightens to `RUNNER_TRAIL_DIST` (0.5%) and the trade keeps riding the trend (`LET_WINNERS_RUN`) |
| Trail hit | Position closes as `TRAIL_PROFIT` — usually well above the original TP in a real trend |

### Capital protection (Paul Tudor Jones rules)

The bot stops opening new trades when any of these trigger (existing positions still close at SL/TP):

- 3 consecutive losses (wrong market conditions — wait)
- daily loss exceeds −3% of starting balance
- −20% drawdown from peak balance
- 10 trades already taken today (no overtrading)

## Realistic expectations

With default settings each winning trade adds roughly **+0.3–0.5% of your balance** (20% position × 1.6%+ move, minus 0.2% fees), and each loss costs ~0.2%. The edge comes from many small wins compounding plus the occasional runner that rides a big trend — not from doubling your money overnight. On a $100 account, a good week looks like **+2–5%**, and losing days are normal. Anyone promising more from a 5m bot is lying.

Paper trading now **includes exchange fees** (0.1% per side), so simulated results match what real trading would do.

## One-click Railway Deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/alexgabriel225sefu-dotcom/apex-trade-bot)

1. Click the button above
2. Login with GitHub
3. Add your Variables (see below)
4. Railway deploys the bot in ~30 seconds

## Required Variables

| Variable | Value |
|---|---|
| `LICENSE_KEY` | Your key from [aicashsystem.space](https://aicashsystem.space) |
| `EXCHANGE` | `binance` (recommended), `bybit`, `okx`, `kraken`, `kucoin`, `coinbase`, `bitget`, `mexc` |
| `BINANCE_API_KEY` | From Binance → Profile → API Management |
| `BINANCE_API_SECRET` | Shown once when you create the key |
| `GROQ_API_KEY` | Free from [console.groq.com](https://console.groq.com) |
| `PAPER_TRADING` | `true` to start (simulated), `false` for real money |

### Optional — Telegram alerts

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Your chat/group ID |

### Optional — Strategy tuning (defaults are sensible)

| Variable | Default | What it does |
|---|---|---|
| `RISK_PER_TRADE` | `0.20` | Fraction of balance used per trade (0.20 = 20%) |
| `STOP_LOSS_PCT` | `0.008` | Stop loss distance (0.8%) |
| `TAKE_PROFIT_PCT` | `0.016` | Take profit distance (1.6%) — runner mode can exceed it |
| `MIN_CONFIDENCE` | `62` | Minimum AI confidence to enter (raise for fewer, better trades) |
| `MIN_CRITERIA` | `3` | Minimum criteria score 0–5 from the AI |
| `MIN_VOLUME_RATIO` | `0.7` | Minimum volume vs average to enter |
| `HTF_FILTER` | `true` | Block trades against the 1h trend (EMA50) |
| `HTF_TIMEFRAME` | `1h` | Timeframe used by the trend filter |
| `COOLDOWN_AFTER_LOSS_MIN` | `15` | Minutes without new entries after a loss |
| `BREAKEVEN_AT_R` | `1.0` | Move SL to breakeven after this many R of profit (0 = off) |
| `LET_WINNERS_RUN` | `true` | At TP, switch to tight trailing instead of closing |
| `RUNNER_TRAIL_DIST` | `0.005` | Trailing distance in runner mode (0.5%) |
| `TRAILING_STOP` | `true` | Trailing stop active from entry |
| `TRAILING_STOP_DIST` | `0.015` | Normal trailing distance (1.5%) |
| `FEE_PCT` | `0.001` | Exchange fee per side, used in paper trading (0.1%) |
| `ATR_BASED_SL` | `false` | SL/TP from volatility (1.5×/3× ATR) instead of fixed % |
| `SCAN_SYMBOLS` | `SOLUSDT,XRPUSDT,DOGEUSDT,TRXUSDT,ADAUSDT` | Pairs the scanner rotates between |
| `TIMEFRAME` | `5m` | Analysis timeframe |

### Tuning profiles

**Conservative** (fewer trades, higher win rate):
```
MIN_CONFIDENCE=72
MIN_CRITERIA=4
MIN_VOLUME_RATIO=1.0
COOLDOWN_AFTER_LOSS_MIN=30
```

**Default / balanced** — just deploy, no extra variables needed.

**Aggressive** (more trades, bigger swings — only with money you can lose):
```
MIN_CONFIDENCE=58
RISK_PER_TRADE=0.30
COOLDOWN_AFTER_LOSS_MIN=5
```

## FAQ

**Why is the bot holding instead of trading?**
That's the filters doing their job. Check the logs — every HOLD prints the reason (low confidence, weak volume, 1h trend filter, cooldown, or daily stop). Chop kills accounts; waiting is a position.

**Why did it close below my take profit?**
The trailing stop locked in profit when price reversed. Over many trades this beats holding to a fixed TP that price never quite touches.

**Why did profits change after updating?**
Paper trading now subtracts real exchange fees (0.2% round trip), so numbers are honest. Old paper results were overstated.

**Can I run it on more/other coins?**
Yes — set `SCAN_SYMBOLS` to any comma-separated list of USDT pairs available on your exchange.

## License

Requires a valid license key. Purchase at [aicashsystem.space](https://aicashsystem.space).
