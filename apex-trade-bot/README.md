# ⚡ Apex Trade Bot

AI-powered crypto trading bot with multi-exchange support, legendary trader strategies, and Telegram alerts.

## Features
- **AI Signals** — Claude Haiku + Groq (free fallback) for trade decisions
- **Multi-symbol scanner** — picks the best pair automatically (SOL, XRP, DOGE, TRX, ADA)
- **Legendary strategies** — Turtle Breakout, Jesse Livermore, George Soros, Stan Druckenmiller, Paul Tudor Jones
- **Trailing Stop** — locks in profit as price moves in your favour
- **Paper Trading** — simulated money, zero real risk to start
- **Telegram alerts** — every open, close, heartbeat, and strategy stop
- **Live Dashboard** — web UI showing balance, P&L, open position, trade history

## One-click Railway Deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/alexgabriel225sefu-dotcom/apex-trade-bot)

1. Click the button above
2. Login with GitHub
3. Add your Variables (see below)
4. Railway deploys the bot in ~30 seconds

## Required Variables

| Variable | Value |
|---|---|
| `LICENSE_KEY` | Your key from [aicashsystem.space](https://aicashsystem.space) |
| `EXCHANGE` | `binance` (recommended) or `bybit` |
| `BINANCE_API_KEY` | From Binance → Profile → API Management |
| `BINANCE_API_SECRET` | Shown once when you create the key |
| `GROQ_API_KEY` | Free from [console.groq.com](https://console.groq.com) |
| `PAPER_TRADING` | `true` to start (simulated), `false` for real money |

### Optional (Telegram alerts)
| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Your chat/group ID |

## License

Requires a valid license key. Purchase at [aicashsystem.space](https://aicashsystem.space).
