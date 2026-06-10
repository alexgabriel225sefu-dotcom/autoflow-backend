# Configuration Guide

Settings come from three places (highest priority first):

1. **Telegram commands** — saved to `runtime.json`, survive restarts
2. **Environment variables** — Railway Variables tab or `.env` file
3. **Built-in defaults** — listed below

---

## Telegram commands

| Command | What it does |
|---|---|
| `/setup` | Guided wizard: OANDA → paper → pair |
| `/config` | Show all current settings |
| `/status` | Live balance, position, PnL, market hours, sessions |
| `/env practice\|live` | Switch OANDA environment |
| `/paper on\|off` | Toggle paper / live trading |
| `/risk <0.5-10>` | Risk % per trade (e.g. `/risk 2`) |
| `/sl <pips>` | Stop loss in pips (e.g. `/sl 15`) |
| `/tp <pips>` | Take profit in pips (e.g. `/tp 30`) |
| `/symbol <PAIR>` | Currency pair (e.g. `/symbol GBP_USD`) |
| `/setkeys KEY=val ...` | Set credentials — *message auto-deleted* |
| `/start` / `/stop` | Resume / pause trading |
| `/help` | Command list |

---

## Core variables

| Variable | Default | Description |
|---|---|---|
| `LICENSE_KEY` | — | Your license from the purchase email (**required**) |
| `OANDA_API_TOKEN` | — | Personal Access Token from OANDA (**required**) |
| `OANDA_ACCOUNT_ID` | — | e.g. `101-001-1234567-001` (**required**) |
| `OANDA_ENV` | `practice` | `practice` or `live` — must match your token |
| `TRADE_SYMBOL` | `EUR_USD` | Pair to trade when scanner is off |
| `TIMEFRAME` | `5m` | Candle interval: `1m` `5m` `15m` `30m` `1h` `4h` `1d` |
| `PAPER_TRADING` | `true` | Simulated balance (data still comes from OANDA) |
| `PAPER_BALANCE` | `1000` | Starting balance in paper mode |

## AI providers

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | Free at [console.groq.com](https://console.groq.com). At least one AI key required. |
| `ANTHROPIC_API_KEY` | — | Optional. Used first if set; Groq is the fallback. |

## Telegram

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | From [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | — | From [@userinfobot](https://t.me/userinfobot) |
| `DASHBOARD_URL` | — | Public URL shown in alerts (optional) |

## Risk management

| Variable | Default | Description |
|---|---|---|
| `RISK_PER_TRADE` | `0.02` | Fraction of balance risked per trade (2% — forex standard) |
| `STOP_LOSS_PIPS` | `15` | Stop loss distance in pips |
| `TAKE_PROFIT_PIPS` | `30` | Take profit distance (1:2 risk/reward) |
| `LEVERAGE` | `30` | Account leverage (used for margin-aware sizing) |
| `MARGIN_CAP` | `0.5` | Never use more than 50% of available margin |
| `MAX_SPREAD_PIPS` | `3.0` | Skip entries when spread is wider than this |
| `MIN_CONFIDENCE` | `65` | Minimum AI confidence (0–100) to enter |
| `MIN_CRITERIA` | `3` | Minimum entry criteria score (0–5) |

## Trailing stop & ATR

| Variable | Default | Description |
|---|---|---|
| `TRAILING_STOP` | `true` | Stop follows price to lock in profit |
| `TRAILING_STOP_PIPS` | `10` | Trail distance in pips |
| `ATR_BASED_SL` | `false` | Volatility-based SL/TP instead of fixed pips |
| `ATR_SL_MULT` | `1.5` | Stop loss = 1.5 × ATR |
| `ATR_TP_MULT` | `3.0` | Take profit = 3 × ATR |

## Multi-pair scanner

| Variable | Default | Description |
|---|---|---|
| `MULTI_SYMBOL` | `true` | Scan several pairs, trade the strongest setup |
| `SCAN_SYMBOLS` | `EUR_USD,GBP_USD,USD_JPY,AUD_USD,USD_CAD` | Comma-separated watchlist |

## Loop & misc

| Variable | Default | Description |
|---|---|---|
| `LOOP_INTERVAL_MS` | `300000` | Analysis interval (5 minutes) |
| `PORT` | `3000` | Dashboard port (Railway sets this automatically) |
| `LICENSE_SERVER` | `https://aicashsystem.space` | License verification endpoint |

---

## Recommended starter profile

```env
PAPER_TRADING=true
RISK_PER_TRADE=0.01
MIN_CONFIDENCE=70
```

1% risk and a higher confidence bar while you watch the bot trade on paper
for a week or two. The defaults (2% / 65) are already conservative by
industry standards — never go above 5% risk per trade with leverage.
