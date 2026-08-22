# 💱 Apex Forex Bot

AI-powered trading bot — **forex, metals and crypto** on one account.
**cTrader + MetaTrader 5. Telegram-controlled. Zero config files.**

What it trades and what it deliberately refuses: [docs/ASSETS.md](docs/ASSETS.md).

Two ways to connect (3Commas-style — trades appear live in the app you already use):
- **cTrader** — free Open API, works with any cTrader broker worldwide (IC Markets, Pepperstone, FxPro…). SL/TP are placed server-side and positions are reconciled automatically after a restart
- **MetaTrader 5** — via the included ApexBridge EA: IC Markets, Pepperstone, or any MT5 broker ([guide](docs/METATRADER.md)). Paper + practice supported; live mode requires the `ALLOW_EXPERIMENTAL_LIVE=true` flag

---

## How this is deployed

**Render, from GitHub.** The blueprint is [`render.yaml`](render.yaml) in this
folder: a `web` service on the Starter plan (a trading bot must stay awake),
building and running from `rootDir: apex-forex-bot`, with `autoDeploy` on.

A commit to the tracked branch that touches `apex-forex-bot/**` builds and
restarts the service. Nothing else does — the build filter deliberately
excludes the other projects in this monorepo, because an unrelated commit
restarting the trading loop can orphan an open position mid-trade.

There is no deploy command, and nothing in the bot can deploy itself. `/deploy`
in Telegram reports what is running — service, branch, commit, uptime — and
cannot change it.

### Configuration

Set in the Render dashboard, under the service's **Environment**:

| Variable | Where to get it |
|---|---|
| `PRODUCT` | `forex` — the bot refuses to start without it |
| `TELEGRAM_BOT_TOKEN` | Create a bot at [@BotFather](https://t.me/BotFather) → `/newbot` |
| `ADMIN_CHAT_ID` | Message [@userinfobot](https://t.me/userinfobot) → it replies with your ID |
| `TOKEN_ENCRYPTION_KEY` | Fernet key — see [docs/CONFIG.md](docs/CONFIG.md). Startup is refused without it in production |
| `UPSTASH_REDIS_REST_URL` / `..._TOKEN` | Shared state. Startup is refused without a shared backend in production |
| `GEMINI_API_KEY` *(optional)* | Powers AI chat and voice control. Trading works without it |

Two of those refuse to start rather than degrade, on purpose: credentials in
plaintext and per-container state are both worse than an outage you can see.

### Step 3 — Open Telegram
Find your bot and send:
```
/setup
```
The bot walks you through connecting your **cTrader account**
(demo for risk-free testing, or live for real money) — and later switching accounts if you choose.

---

## What you can do from Telegram

| Command | Action |
|---|---|
| `/setup` | Guided setup wizard (cTrader → pair → risk) |
| `/ctrader` | Connect or reconnect your cTrader account (OAuth) |
| `/start` | Start trading |
| `/stop` | Pause trading |
| `/status` | Live balance, position, PnL, market hours |
| `/config` | Show all current settings |
| `/env practice\|live` | Switch demo/live mode |
| `/paper on\|off` | Toggle paper / live mode |
| `/risk 2` | Set risk % per trade (0.5–10) |
| `/sl 15` / `/tp 30` | Stop loss / take profit in pips |
| `/symbol EUR_USD` | Change currency pair |
| `/setkeys KEY=value` | Update credentials *(message auto-deleted)* |

---

## Features
- **cTrader Open API** — demo + live, any cTrader broker worldwide, server-side SL/TP
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
| [docs/SETUP.md](docs/SETUP.md) | Step-by-step deployment + cTrader account |
| [docs/METATRADER.md](docs/METATRADER.md) | MetaTrader 5 / IC Markets integration |
| [docs/CONFIG.md](docs/CONFIG.md) | Every setting + all Telegram commands |
| [docs/STRATEGIES.md](docs/STRATEGIES.md) | How the bot decides to trade |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Fixes for common problems |
| [docs/FAQ.md](docs/FAQ.md) | Common questions |

---

## Tests & backtest

```bash
python tests/run_all.py           # everything in one shot (6 suites, 70+ checks)

python tests/test_forex.py        # pip math, sizing, margin, market hours
python tests/test_brokers.py      # TD rate-limit retry, cross-pair sizing
python tests/test_ctrader.py      # cTrader symbol mapping, OAuth, broker selection
python tests/test_mtbridge.py     # MetaTrader bridge protocol
python tests/test_indicators.py   # indicator math
python tests/test_strategies.py   # strategies + risk circuit breakers
python tests/test_ai.py           # AI signal layer (no network needed)
```

**Backtest the real strategy** (the AI's entry rubric computed mechanically +
the exact live exit code from `apex/position.py`):

```bash
python backtest.py                          # uses your cTrader/TD key from .env
BT_SYMBOL=GBP_USD python backtest.py
BT_SYNTHETIC=true python backtest.py        # engine validation, no internet
```

It pays spread + slippage on every entry and reports win rate, profit factor,
net return, max drawdown and exit breakdown. The AI layer itself is not
simulated (live it filters *additional* trades), and past results never
guarantee future profit — treat the backtest as a sanity check, not a promise.

---

## Safety

Start on a demo account (the default). Switching to real money is an
activation, not a setting: it needs recorded risk acceptance, the account
environment as the BROKER reports it, and a typed single-use confirmation —
no button, API call or operator action can flip it on your behalf.

The bot connects to **your** cTrader account through the Open API, which
grants trading access and never withdrawal access. Broker tokens are
encrypted at rest, and the service refuses to start if the encryption key is
missing rather than storing them in the clear.

> Forex trading with leverage is risky. Past results do not guarantee future
> performance. Never trade money you can't afford to lose.

## License

Requires a valid license key. Purchase at [aicashsystem.space](https://aicashsystem.space).
