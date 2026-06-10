# Configuration Guide

Every setting the bot accepts. Set them three ways (highest priority first):

1. **Telegram commands** — saved to `runtime.json`, survive restarts
2. **Environment variables** — Railway Variables tab or `.env` file
3. **Built-in defaults** — sensible values, listed below

---

## Telegram commands

| Command | What it does |
|---|---|
| `/setup` | Guided wizard: exchange → keys → pair |
| `/config` | Show all current settings |
| `/status` | Live balance, position, PnL |
| `/exchange <name>` | Switch exchange (e.g. `/exchange bybit`) |
| `/paper on\|off` | Toggle paper / live trading |
| `/risk <1-50>` | Risk % per trade (e.g. `/risk 20`) |
| `/symbol <PAIR>` | Trading pair (e.g. `/symbol BTCUSDT`) |
| `/setkeys KEY=val ...` | Set API keys — *message auto-deleted* |
| `/start` / `/stop` | Resume / pause trading |
| `/help` | Command list |

---

## Core variables

| Variable | Default | Description |
|---|---|---|
| `LICENSE_KEY` | — | Your license from the purchase email (**required**) |
| `EXCHANGE` | `binance` | One of: `binance` `bybit` `okx` `kraken` `kucoin` `coinbase` `bitget` `mexc` |
| `TRADE_SYMBOL` | `SOLUSDT` | Pair to trade when scanner is off |
| `TIMEFRAME` | `5m` | Candle interval for analysis |
| `PAPER_TRADING` | `false` | `true` = simulated money (recommended to start) |
| `PAPER_BALANCE` | `100` | Starting balance in paper mode |

## AI providers

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | Free at [console.groq.com](https://console.groq.com). At least one AI key is required. |
| `ANTHROPIC_API_KEY` | — | Optional. Used first if set (Claude Haiku); Groq is the fallback. |

## Telegram

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | From [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | — | From [@userinfobot](https://t.me/userinfobot) |
| `DASHBOARD_URL` | — | Public URL shown in alerts (optional) |

## Risk management

| Variable | Default | Description |
|---|---|---|
| `RISK_PER_TRADE` | `0.20` | Fraction of balance per trade (0.20 = 20%) |
| `STOP_LOSS_PCT` | `0.008` | Fixed stop loss (0.8%) |
| `TAKE_PROFIT_PCT` | `0.016` | Fixed take profit (1.6%) — 1:2 risk/reward |
| `MIN_CONFIDENCE` | `62` | Minimum AI confidence (0–100) to enter |
| `MIN_CRITERIA` | `3` | Minimum entry criteria score (0–5) |
| `MIN_VOLUME_RATIO` | `0.7` | Minimum volume vs 20-period average |
| `MIN_NOTIONAL` | `10.0` | Skip live orders below this USD value |

## Trailing stop & ATR

| Variable | Default | Description |
|---|---|---|
| `TRAILING_STOP` | `true` | Stop loss follows price to lock in profit |
| `TRAILING_STOP_DIST` | `0.01` | Trail distance (1%) |
| `ATR_BASED_SL` | `false` | Use volatility-based SL/TP instead of fixed % |
| `ATR_SL_MULT` | `1.5` | Stop loss = 1.5 × ATR |
| `ATR_TP_MULT` | `3.0` | Take profit = 3 × ATR |

## Multi-symbol scanner

| Variable | Default | Description |
|---|---|---|
| `MULTI_SYMBOL` | `true` | Scan several pairs, trade the strongest setup |
| `SCAN_SYMBOLS` | `SOLUSDT,XRPUSDT,DOGEUSDT,TRXUSDT,ADAUSDT` | Comma-separated watchlist |

## Loop & misc

| Variable | Default | Description |
|---|---|---|
| `LOOP_INTERVAL_MS` | `300000` | Analysis interval (5 minutes) |
| `PORT` | `3000` | Dashboard port (Railway sets this automatically) |
| `LICENSE_SERVER` | `https://aicashsystem.space` | License verification endpoint |

## Exchange credentials

| Exchange | Variables |
|---|---|
| Binance | `BINANCE_API_KEY`, `BINANCE_API_SECRET` (+ `BINANCE_TESTNET=true` optional) |
| Bybit | `BYBIT_API_KEY`, `BYBIT_API_SECRET` (+ `BYBIT_TESTNET=true` optional) |
| OKX | `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE` |
| Kraken | `KRAKEN_API_KEY`, `KRAKEN_API_SECRET` |
| KuCoin | `KUCOIN_API_KEY`, `KUCOIN_API_SECRET`, `KUCOIN_API_PASSPHRASE` |
| Coinbase | `COINBASE_API_KEY` (key name), `COINBASE_API_SECRET` (EC private key PEM) |
| Bitget | `BITGET_API_KEY`, `BITGET_API_SECRET`, `BITGET_API_PASSPHRASE` |
| MEXC | `MEXC_API_KEY`, `MEXC_API_SECRET` |

> **Never enable withdrawal permission** on any exchange API key. Spot trading only.

---

## Recommended starter profile

```env
PAPER_TRADING=true
RISK_PER_TRADE=0.10
MIN_CONFIDENCE=70
```

Conservative: lower risk per trade, higher confidence bar. Loosen once you've
watched the bot trade on paper for at least a week.
