# ⚡ Apex Trade Bot — Python

AI-powered crypto trading bot. **8 exchanges. Telegram-controlled. Zero config files.**

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/alexgabriel225sefu-dotcom/autoflow-backend)

---

## Deploy in 3 steps

### Step 1 — Click the button above
- Login with GitHub (free account)
- When Railway asks for **Root Directory** → type `apex-trade-bot-py`

### Step 2 — Add 3 variables
In the Railway **Variables** tab:

| Variable | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Create a bot at [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | Message [@userinfobot](https://t.me/userinfobot) → it replies with your ID |
| `GROQ_API_KEY` | Free key at [console.groq.com](https://console.groq.com) (takes 1 minute) |

Click **Deploy**.

### Step 3 — Open Telegram
Find your bot and send:
```
/setup
```
The bot will guide you through everything — exchange, API keys, trading pair. Done.

---

## What you can do from Telegram

| Command | Action |
|---|---|
| `/setup` | Guided setup wizard (exchange → keys → symbol) |
| `/start` | Start trading |
| `/stop` | Pause trading |
| `/status` | Live balance, position, PnL |
| `/config` | Show all current settings |
| `/exchange binance` | Switch exchange |
| `/paper on\|off` | Toggle paper / live mode |
| `/risk 20` | Set risk % per trade |
| `/symbol BTCUSDT` | Change trading pair |
| `/setkeys KEY=value` | Update API keys *(message auto-deleted)* |

---

## Features
- **8 exchanges** — Binance, Bybit, OKX, Kraken, KuCoin, Coinbase, Bitget, MEXC
- **Paper trading** — simulated money, zero risk while you test
- **Legendary strategies** — Turtle breakout, Livermore structure, Soros momentum, mean reversion, Druckenmiller sizing, PTJ/Seykota defense
- **AI signals** — Anthropic (primary) + Groq (free fallback)
- **Risk controls** — stop-loss, take-profit, trailing stop, daily/drawdown limits
- **Live web dashboard** — equity curve, win rate, profit factor, trade history, live position (at `/` on your Railway URL)

---

## Documentation

| Guide | What's inside |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | Step-by-step deployment (Railway + local) |
| [docs/CONFIG.md](docs/CONFIG.md) | Every setting + all Telegram commands |
| [docs/STRATEGIES.md](docs/STRATEGIES.md) | How the bot decides to trade |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Fixes for common problems |
| [docs/API.md](docs/API.md) | Dashboard JSON API + connector interface |
| [docs/FAQ.md](docs/FAQ.md) | Common questions |

---

## Tests

```bash
python tests/test_indicators.py        # indicator math
python tests/test_strategies.py       # strategies + risk circuit breakers
python tests/test_ai.py               # AI signal layer (no network needed)
python tests/test_telegram_commands.py # Telegram command handling
```

---

## Safety

Start with paper trading (the bot defaults to paper mode). When going live, test with a small amount first. The bot runs on **your** Railway account with **your** keys — the seller has zero access to your credentials.

> Crypto trading is risky. Past results do not guarantee future performance.
