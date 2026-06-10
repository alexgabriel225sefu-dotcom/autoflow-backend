# Setup Guide — Apex Trade Bot

Get the bot running in **under 10 minutes**. No coding required.

---

## Option A — Railway (recommended, ~$5/month)

### 1. Create the deployment

1. Click the **Deploy on Railway** button in the [README](../README.md)
2. Log in with a free GitHub account
3. When Railway asks for **Root Directory**, type: `apex-trade-bot-py`

### 2. Create your Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, pick any name and username
3. Copy the **token** BotFather gives you (looks like `123456:ABC-DEF...`)
4. Message [@userinfobot](https://t.me/userinfobot) — it replies with your **chat ID**

### 3. Add variables in Railway

In your Railway project → **Variables** tab, add:

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

The wizard walks you through everything: exchange → API keys → trading pair.
You start in **paper trading mode** (simulated money) by default — nothing real is at risk.

---

## Option B — Run locally

Requirements: Python 3.10+

```bash
cd apex-trade-bot-py
pip install -r requirements.txt
cp ../.env.example .env   # or create .env manually
python main.py
```

Minimal `.env`:

```env
LICENSE_KEY=APEX-XXXX-XXXX-XXXX
GROQ_API_KEY=gsk_...
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=999999
PAPER_TRADING=true
```

The dashboard starts at [http://localhost:3000](http://localhost:3000).

---

## Getting exchange API keys (for live trading)

> Skip this while paper trading. You only need keys to trade real money.

### Binance (recommended)
1. Binance → Profile → **API Management** → Create API
2. Enable **Spot Trading** only. Do **NOT** enable withdrawals.
3. Send the keys to your bot: `/setkeys BINANCE_API_KEY=... BINANCE_API_SECRET=...`
   (the message is auto-deleted from chat for safety)

The same flow works for Bybit, OKX, Kraken, KuCoin, Coinbase, Bitget, and MEXC —
see [CONFIG.md](CONFIG.md) for each exchange's variable names.

**Security rule: never enable withdrawal permission on any API key.** The bot
only needs to read prices and place spot orders.

---

## Going live (real money)

When you're happy with paper results:

```
/paper off
```

Start small. Recommended first live balance: **$50–$200**.

---

## Next steps

- [CONFIG.md](CONFIG.md) — every setting explained
- [STRATEGIES.md](STRATEGIES.md) — how the bot decides to trade
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — if something doesn't work
- [FAQ.md](FAQ.md) — common questions
