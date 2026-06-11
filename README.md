# 💱 Apex Forex Bot

AI-powered forex trading bot. **OANDA + MetaTrader 5. Telegram-controlled. Zero config files.**

Two ways to connect (3Commas-style — trades appear live in the app you already use):
- **OANDA** — direct API, easiest setup, free practice account
- **MetaTrader 5** — via the included ApexBridge EA: IC Markets, Pepperstone, or any MT5 broker ([guide](docs/METATRADER.md))

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/alexgabriel225sefu-dotcom/autoflow-backend)

---

## Deploy in 3 steps

### Step 1 — Click the button above
- Login with GitHub (free account)
- When Railway asks for **Root Directory** → type `apex-forex-bot`

### Step 2 — Add 4 variables
In the Railway **Variables** tab:

| Variable | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Create a bot at [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | Message [@userinfobot](https://t.me/userinfobot) → it replies with your ID |
| `GROQ_API_KEY` | Free key at [console.groq.com](https://console.groq.com) (takes 1 minute) |
| `LICENSE_KEY` | From your purchase email |

Click **Deploy**.

### Step 3 — Open Telegram
Find your bot and send:
```
/setup
```
The bot walks you through connecting your **free OANDA practice account**
(market data + paper trading) — and later your live account if you choose.

---

## What you can do from Telegram

| Command | Action |
|---|---|
| `/setup` | Guided setup wizard (OANDA → paper → pair) |
| `/broker oanda\|mt` | Switch between OANDA API and MetaTrader bridge |
| `/start` | Start trading |
| `/stop` | Pause trading |
| `/status` | Live balance, position, PnL, market hours |
| `/config` | Show all current settings |
| `/env practice\|live` | Switch OANDA environment |
| `/paper on\|off` | Toggle paper / live mode |
| `/risk 2` | Set risk % per trade (0.5–10) |
| `/sl 15` / `/tp 30` | Stop loss / take profit in pips |
| `/symbol EUR_USD` | Change currency pair |
| `/setkeys KEY=value` | Update credentials *(message auto-deleted)* |

---

## Features
- **OANDA v20 API** — practice + live, free practice account for data
- **MetaTrader 5 bridge** — ApexBridge EA executes on any MT5 broker; trades, SL and TP visible on your chart
- **7 major pairs scanner** — EUR_USD, GBP_USD, USD_JPY, AUD_USD, USD_CAD + custom
- **Pip-based risk** — SL/TP in pips, 2% risk per trade default, leverage-aware sizing with margin cap
- **Spread guard** — skips entries when the spread is too wide
- **Market hours aware** — sleeps over the weekend, knows active sessions (London/NY/Tokyo/Sydney)
- **Legendary strategies** — Turtle breakout, Livermore structure, Soros momentum, mean reversion, Druckenmiller sizing, PTJ/Seykota defense
- **AI signals** — Anthropic (primary) + Groq (free fallback)
- **Smart entries** — 1h trend filter (never fight the big trend), post-loss cooldown, counter-trend veto
- **Smart exits** — breakeven stop at +1R (trade becomes risk-free), runner mode that lets winners run past TP on a tight trail
- **Risk controls** — trailing stop, daily −3% stop, −20% drawdown stop, loss-streak stop
- **Live web dashboard** — equity curve, win rate, profit factor, pips per trade

---

## Documentation

| Guide | What's inside |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | Step-by-step deployment + OANDA account |
| [docs/METATRADER.md](docs/METATRADER.md) | MetaTrader 5 / IC Markets integration |
| [docs/CONFIG.md](docs/CONFIG.md) | Every setting + all Telegram commands |
| [docs/STRATEGIES.md](docs/STRATEGIES.md) | How the bot decides to trade |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Fixes for common problems |
| [docs/FAQ.md](docs/FAQ.md) | Common questions |

---

## Tests

```bash
python tests/test_forex.py        # pip math, sizing, margin, market hours
python tests/test_mtbridge.py     # MetaTrader bridge protocol
python tests/test_indicators.py   # indicator math
python tests/test_strategies.py   # strategies + risk circuit breakers
python tests/test_ai.py           # AI signal layer (no network needed)
```

---

## Safety

Start with paper trading (the default). The bot runs on **your** Railway
account with **your** OANDA token — the seller has zero access to your
credentials. Never enable more permissions than the bot needs.

> Forex trading with leverage is risky. Past results do not guarantee future
> performance. Never trade money you can't afford to lose.

## License

Requires a valid license key. Purchase at [aicashsystem.space](https://aicashsystem.space).
