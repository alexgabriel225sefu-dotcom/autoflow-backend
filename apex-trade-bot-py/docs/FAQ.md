# Frequently Asked Questions

### Do I need to know how to code?
No. Deployment is click-through (Railway button), and all configuration
happens through Telegram commands. The source code is yours to read or modify
if you want — but you never have to touch it.

### How much money do I need to start?
$0. Start in **paper trading mode** — the bot trades simulated money against
real live prices. When you go live, $50–$200 is a sensible first balance.

### Is profit guaranteed?
No, and run from anyone who says otherwise. Crypto is volatile and all
trading carries risk of loss. The bot enforces strict risk rules (daily
−3% stop, 20% drawdown stop, loss-streak stop) to keep losses controlled,
but it cannot eliminate risk. Never trade money you can't afford to lose.

### What are the ongoing costs?
- **Railway hosting:** ~$5/month (bot runs 24/7)
- **Groq AI key:** free tier is sufficient
- **From us:** $0 — no subscription, the $297 is one-time

### Which exchanges are supported?
Binance, Bybit, OKX, Kraken, KuCoin, Coinbase, Bitget, MEXC. Switch any time
with `/exchange <name>`.

### Can the bot withdraw my money?
No. The bot only needs spot-trading permission. **Never enable withdrawal
permission** when creating your exchange API key — then it's technically
impossible, even if your keys leaked.

### Where are my API keys stored?
Only on **your** server (Railway environment + `runtime.json` on your
instance). They are never sent to us. The `/setkeys` Telegram message is
auto-deleted after processing.

### Will other people see my trades or my Telegram chat?
No. You create your own private Telegram bot via @BotFather. Each customer
runs their own isolated bot instance — there is no shared infrastructure.

### How many trades per day should I expect?
Typically 0–5. The bot requires AI confidence ≥ 62%, a 3/5 criteria score,
and volume confirmation simultaneously — most cycles end in HOLD. That
selectivity is a feature, not a bug.

### Can I run multiple pairs?
Yes — the built-in scanner (on by default) watches 5 pairs and trades the
strongest setup. Customize with `SCAN_SYMBOLS`. One position at a time, by
design (risk concentration control).

### Can I change the strategy?
Yes — you own the full source. Strategy logic lives in `apex/strategies.py`
and entry rules in `apex/ai.py`. See [STRATEGIES.md](STRATEGIES.md) for how
the pieces fit together.

### What happens if the AI service goes down?
The bot returns HOLD and waits for the next cycle. It never trades without a
signal. Open positions remain protected by their stop loss / take profit.

### What happens if my server restarts?
Paper balance and open-position state persist in `state.json`; settings
persist in `runtime.json`. The bot picks up where it left off.

### How do I update to a newer version?
Pull the latest code (or redeploy from the repo) — your `.env` /
Railway variables and runtime settings are untouched.

### How do I stop everything?
`/stop` pauses trading instantly (positions keep their SL/TP). To shut down
completely, stop the Railway deployment. To go back to simulated money:
`/paper on`.

### Refunds?
Because this is digital source code delivered instantly, all sales are final
— this is stated at checkout. If something doesn't work, contact support and
we'll get you running.
