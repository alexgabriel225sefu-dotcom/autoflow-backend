# Setup Guide — Apex Forex Bot

Get the bot running in **under 15 minutes**. No coding required.

---

## Step 0 — Create a free cTrader demo account

The bot connects to any cTrader broker (IC Markets, Pepperstone, FxPro, ...).
A free demo account gives you real market data and risk-free practice:

1. Sign up at your preferred cTrader broker (e.g. IC Markets, Pepperstone)
2. Create a **demo** trading account (free, instant)
3. You'll link the account to the bot via OAuth in Step 4 below

> The demo account trades fake money on real prices. You only need a
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

The wizard walks you through mode selection (demo or live), then send
`/ctrader` to connect your cTrader account via OAuth. Done.

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

1. Open a **live** cTrader account at your broker and fund it
2. Send `/ctrader` to your bot — tap Authorize and log in with your live account
3. Select the live account when prompted
4. The bot confirms "LIVE" mode and starts trading

Start small. Recommended first live balance: **$100–$500**. Keep risk at the
default 2% per trade.

---

## Next steps

- [CONFIG.md](CONFIG.md) — every setting explained
- [STRATEGIES.md](STRATEGIES.md) — how the bot decides to trade
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — if something doesn't work
- [FAQ.md](FAQ.md) — common questions
