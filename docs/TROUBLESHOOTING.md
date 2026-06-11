# Troubleshooting

Fixes for the most common problems, in the order people usually hit them.

---

## Startup

### ❌ `LICENSE_KEY is not set` / `License invalid`
Add the `LICENSE_KEY` variable from your purchase email in Railway →
Variables, exactly as written (format `APEX-XXXX-XXXX-XXXX`), then redeploy.

### ❌ `No AI key found`
Add `GROQ_API_KEY` (free at [console.groq.com](https://console.groq.com)).

### ⚠️ `OANDA credentials missing`
The bot needs an OANDA token even for paper trading (that's where prices come
from). Create a free practice account at oanda.com → Manage API Access, then
send `/setup` to your Telegram bot.

---

## OANDA

### 401 Unauthorized
- Your token doesn't match the environment: practice tokens only work with
  `OANDA_ENV=practice`, live tokens with `live`. Check `/config`.
- Tokens can be revoked — generate a fresh one in the OANDA portal.

### `Insufficient authorization to perform request`
Your `OANDA_ACCOUNT_ID` belongs to a different environment or user. Copy the
exact ID from the portal of the same environment as your token.

### Prices look stale / no candles
- Forex closes on weekends (Friday 21:00 → Sunday 21:00 UTC). `/status`
  shows the market state — this is normal, the bot resumes automatically.
- OANDA practice occasionally lags a few seconds; this is harmless at the
  5-minute analysis interval.

### Order rejected: `MARKET_HALTED`
The instrument is closed (weekend/holiday) or halted around major news.
The bot skips and retries next cycle.

---

## Telegram

### Bot doesn't reply
1. `TELEGRAM_BOT_TOKEN` must match BotFather's token exactly (no spaces)
2. `TELEGRAM_CHAT_ID` must be **your** ID from @userinfobot
3. Message the bot first — bots can't initiate chats
4. Restart the deployment after changing variables

---

## Trading

### Bot never opens a trade
Check the logs — every HOLD prints its reason. The full entry checklist:

1. **Market open** — forex closes Friday ~21:00 UTC until Sunday 21:00 UTC.
2. **AI confidence ≥ 62** and **criteria ≥ 3/5** (printed with each signal).
3. **Spread ≤ `MAX_SPREAD_PIPS`** — widens around news and rollover.
4. **1h trend filter** — no BUY in a 1h downtrend, no SELL in a 1h uptrend
   (`⚡ 1h filter` in logs). Disable with `HTF_FILTER=false`.
5. **Loss cooldown** — 15 min without entries after a loss (`⏸️` in logs).
6. **Not against strong Livermore + Turtle structure** (`⚡ Signal filtered`).

Forex pairs move slower than crypto — expect 0–3 trades per day, sometimes
zero on quiet days. If it holds for **days** during active sessions, lower the
bar: `MIN_CONFIDENCE=58`, `MIN_CRITERIA=2`.

> Note: on older versions, Twelve Data mode could never trade because forex
> candles carry no tick volume and the AI's volume criterion was impossible
> to satisfy. This is fixed — volume is treated as neutral when the data
> source doesn't provide it. Update if you're on an old deploy.

### `Spread too wide — skip entry`
Working as intended. Spreads widen around news releases, the daily rollover
(~21:00 UTC), and the Sunday open. The bot waits for normal conditions.

### `Position size 0 — skip`
Balance too small for the stop distance. Either increase balance, widen
`/risk`, or check that `PAPER_BALANCE` isn't set to something tiny.

### `STRATEGY STOP: 3 consecutive losses`
The Seykota circuit breaker. Trading auto-resumes the next day (UTC), or
restart the deployment to reset the session.

---

## Dashboard

### URL shows nothing / 502
Railway → Settings → **Networking → Generate Domain**. Don't override `PORT`.

### Shows "connecting…" forever
The bot process crashed — check deploy logs. The page reconnects
automatically once the bot is back.

---

## Still stuck?

Email support with:
1. Your purchase email address
2. The last ~30 lines of your Railway logs
3. What you expected vs what happened
