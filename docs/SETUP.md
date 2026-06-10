# Setup Guide — Apex Forex Bot

Get the bot running in **under 15 minutes**. No coding required.

---

## Step 0 — Create a free OANDA practice account

The bot needs OANDA for market data (even in paper mode) — the practice
account is free and takes 3 minutes:

1. Go to [oanda.com](https://www.oanda.com) → **Try a free demo**
2. After signing up, log in to the **fxTrade Practice** portal
3. Go to **Manage API Access** → generate a **Personal Access Token** — copy it
4. Note your **Account ID** (format: `101-001-1234567-001`, shown in My Account)

> The practice account trades fake money on real prices. You only need a
> funded live account when you decide to go live, much later.

---

## Option A — Railway (recommended, ~$5/month)

### 1. Create the deployment

1. Click the **Deploy on Railway** button in the [README](../README.md)
2. Log in with a free GitHub account
3. When Railway asks for **Root Directory**, type: `apex-forex-bot`

### 2. Create your Telegram bot

1. Message [@BotFather](https://t.me/BotFather) → `/newbot`, pick a name
2. Copy the **token** (looks like `123456:ABC-DEF...`)
3. Message [@userinfobot](https://t.me/userinfobot) — it replies with your **chat ID**

### 3. Add variables in Railway

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | The token from BotFather |
| `TELEGRAM_CHAT_ID` | Your ID from @userinfobot |
| `GROQ_API_KEY` | Free key from [console.groq.com](https://console.groq.com) |
| `LICENSE_KEY` | From your purchase email |

Click **Deploy**.

### 4. Finish setup from Telegram

Open your bot in Telegram and send:

```
/setup
```

The wizard asks for your OANDA token + account ID (the message is auto-deleted
for safety), paper mode preference, and your currency pair. Done.

---

## Option B — Run locally

Requirements: Python 3.10+

```bash
cd apex-forex-bot
pip install -r requirements.txt
cp .env.example .env   # fill in your values
python main.py
```

The dashboard starts at [http://localhost:3000](http://localhost:3000).

---

## Going live (real money)

1. Open a **live** OANDA account and fund it
2. Generate a live API token (live portal → Manage API Access)
3. Send your bot: `/setkeys OANDA_API_TOKEN=<live_token> OANDA_ACCOUNT_ID=<live_id>`
4. `/env live` then `/paper off`

Start small. Recommended first live balance: **$100–$500**. Keep risk at the
default 2% per trade.

---

## Next steps

- [CONFIG.md](CONFIG.md) — every setting explained
- [STRATEGIES.md](STRATEGIES.md) — how the bot decides to trade
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — if something doesn't work
- [FAQ.md](FAQ.md) — common questions
