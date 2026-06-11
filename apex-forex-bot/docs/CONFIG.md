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
| `/broker oanda\|mt` | OANDA API or MetaTrader bridge ([guide](METATRADER.md)) |
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
| `BROKER` | `oanda` | `oanda` (direct API) or `mt` (MetaTrader 5 bridge) |
| `OANDA_API_TOKEN` | — | Personal Access Token from OANDA (required for `oanda`) |
| `OANDA_ACCOUNT_ID` | — | e.g. `101-001-1234567-001` (required for `oanda`) |
| `OANDA_ENV` | `practice` | `practice` or `live` — must match your token |
| `MT_BRIDGE_SECRET` | — | Shared secret for the ApexBridge EA (required for `mt`) |
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
| `MIN_CONFIDENCE` | `62` | Minimum AI confidence (0–100) to enter |
| `MIN_CRITERIA` | `3` | Minimum entry criteria score (0–5) |

## Entry filters (anti-chop)

| Variable | Default | Description |
|---|---|---|
| `HTF_FILTER` | `true` | Block trades against the 1h trend (EMA50). Off in MT mode. |
| `HTF_TIMEFRAME` | `1h` | Timeframe used by the trend filter |
| `COOLDOWN_AFTER_LOSS_MIN` | `15` | Minutes without new entries after a losing trade |

## Exit management (cut losses, let profits run)

| Variable | Default | Description |
|---|---|---|
| `TRAILING_STOP` | `true` | Stop follows price to lock in profit |
| `TRAILING_STOP_PIPS` | `10` | Trail distance in pips |
| `BREAKEVEN_AT_R` | `1.0` | At +1R profit, move SL to entry +1 pip — the trade can no longer lose. `0` = off |
| `LET_WINNERS_RUN` | `true` | At TP, switch to a tight trail instead of closing (paper mode; live brokers execute their server-side TP) |
| `RUNNER_TRAIL_PIPS` | `6` | Trail distance once runner mode is active |
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
| `DASHBOARD_TOKEN` | — | Protects the web dashboard. Open with `?token=...`. **Without it, balance and trade history are public on your Railway URL** |
| `LICENSE_SERVER` | `https://aicashsystem.space` | License verification endpoint |

---

## Tuning profiles

**Conservative** (fewer trades, higher win rate — watch on paper first):
```env
PAPER_TRADING=true
RISK_PER_TRADE=0.01
MIN_CONFIDENCE=70
MIN_CRITERIA=4
COOLDOWN_AFTER_LOSS_MIN=30
```

**Default / balanced** — just deploy, no extra variables needed (2% risk, 62% confidence).

**More active** (more entries, bigger swings — only with money you can lose):
```env
MIN_CONFIDENCE=58
RISK_PER_TRADE=0.03
COOLDOWN_AFTER_LOSS_MIN=5
```

Never go above 5% risk per trade with leverage — one bad week wipes the account.
