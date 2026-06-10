# Troubleshooting

Fixes for the most common problems, in the order people usually hit them.

---

## Startup

### ❌ `LICENSE_KEY is not set`
Add the `LICENSE_KEY` variable (from your purchase email) in Railway →
Variables, then redeploy. Format: `APEX-XXXX-XXXX-XXXX`.

### ❌ `License invalid`
- Check for typos — copy/paste the key exactly, including dashes
- Keys are single-machine; if you redeployed elsewhere, contact support
  with your purchase email

### ❌ `No AI key found`
Add at least one of `GROQ_API_KEY` (free, [console.groq.com](https://console.groq.com))
or `ANTHROPIC_API_KEY`.

### Bot starts then Railway shows "Crashed"
Open Railway → **Deployments → View Logs**. The last lines tell you which
variable is wrong. 90% of crashes are a missing/typo'd variable.

---

## Telegram

### Bot doesn't reply to commands
1. Confirm `TELEGRAM_BOT_TOKEN` matches the token BotFather sent (no spaces)
2. Confirm `TELEGRAM_CHAT_ID` is **your** ID from [@userinfobot](https://t.me/userinfobot)
3. You must message the bot **first** (`/start`) — bots can't initiate chats
4. Restart the deployment after changing variables

### No trade alerts arriving
Alerts only fire on opens/closes/heartbeats. If the bot is in HOLD (most of
the time — that's normal), there's nothing to send. Check `/status` to
confirm it's alive.

---

## Trading

### Bot never opens a trade
Usually correct behavior — the bot is picky by design. It needs confidence
≥ 62, 3/5 criteria, and acceptable volume *simultaneously*. To see more
action (and more risk): lower `MIN_CONFIDENCE` to 55 and `MIN_CRITERIA` to 2.
In paper mode, expect a few trades per day on volatile pairs.

### `Order notional below exchange minimum`
Exchanges require ~$10 minimum per order. Your balance × risk% is below that.
Either increase balance or raise `/risk`.

### `Balance too small — stop trading`
Live balance reads under $1. Check you funded the **Spot** wallet (not
Funding/Futures) on the correct exchange.

### `STRATEGY STOP: 3 consecutive losses`
Working as intended — the Seykota circuit breaker. Trading auto-resumes the
next day, or restart the deployment to reset the session.

### API key errors from the exchange (401 / signature)
- Re-send keys: `/setkeys BINANCE_API_KEY=... BINANCE_API_SECRET=...`
- Whitelist restriction: if you enabled IP whitelist on the exchange, remove
  it (Railway IPs rotate)
- OKX / KuCoin / Bitget also need the `*_API_PASSPHRASE`

---

## Dashboard

### Dashboard URL shows nothing / 502
- Railway → Settings → **Networking → Generate Domain** if you haven't
- The dashboard listens on Railway's `PORT` automatically — don't override it

### Dashboard shows "connecting…" forever
The bot process crashed — check the deploy logs. The page polls
`/api/status` every 5 s and reconnects automatically once the bot is back.

---

## Costs & limits

### Railway charges
~$5/month covers this bot comfortably. Set a usage limit in Railway →
Settings → Usage to be safe.

### Groq rate limits
The free tier is enough for the default 5-minute cycle. If you lower
`LOOP_INTERVAL_MS` aggressively you may hit limits — signals then fall back
to HOLD until the next cycle (never an unsafe trade).

---

## Still stuck?

Email support with:
1. Your purchase email address
2. The last ~30 lines of your Railway logs
3. What you expected vs what happened
