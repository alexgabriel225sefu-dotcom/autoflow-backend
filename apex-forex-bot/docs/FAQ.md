# Frequently Asked Questions

### Do I need to know how to code?
No. Deployment is click-through (Railway button) and all configuration
happens through Telegram. The source code is yours to read or modify, but
you never have to touch it.

### What does it trade?
Forex majors with a USD leg, plus metals (gold, silver, platinum, palladium),
through your own cTrader account. Nothing else — crypto, indices, stock CFDs
and crosses without a USD leg are refused, each for a specific reason set out
in [ASSETS.md](ASSETS.md).

### How much money do I need to start?
$0. A free **cTrader demo account** gives you real market data and the
bot trades a simulated balance. When you go live, $100–$500 is a sensible
start.

### Is profit guaranteed?
No — and leveraged forex can lose money quickly if unmanaged. That's exactly
why the bot enforces 2% risk per trade, a margin cap, daily −3% stop,
−20% drawdown stop, and a loss-streak stop. Risk controls are the product.
Never trade money you can't afford to lose.

### What are the ongoing costs?
- **Railway hosting:** ~$5/month
- **cTrader account:** free demo; live account has no monthly fee (the
  broker earns from the spread)
- **Groq AI key:** free tier is sufficient
- **From us:** $0 — the $497 is one-time, no subscription

### Why cTrader?
cTrader Open API is free, available internationally, and works with many
regulated brokers (IC Markets, Pepperstone, FxPro, ...). A single OAuth
integration covers clients worldwide — no VPS, no plugins, no MetaTrader
hacks needed for cloud trading.

### Which pairs can it trade?
Any instrument your cTrader account offers — all majors, crosses, and even
gold (XAUUSD). The default scanner watches EURUSD, GBPUSD, USDJPY,
AUDUSD, USDCAD.

### What leverage does it use?
Your account's leverage (default assumption 1:30, the EU retail cap). The
bot sizes positions from your **risk %**, not from maximum leverage — the
margin cap just prevents oversizing.

### Can the bot withdraw my money?
No. The cTrader OAuth token only allows trading and account reads. Withdrawals
require logging in to your broker directly.

### Where are my credentials stored?
Only on **your** server (Railway environment + `runtime.json` on your
instance). They are never sent to us. The `/setkeys` and wizard messages are
auto-deleted from Telegram after processing.

### How many trades per day should I expect?
Typically 0–3. Forex moves at macro pace and the bot is selective by
design. It also sleeps on weekends, automatically.

### What happens during news events?
Spreads widen sharply around big news (NFP, CPI, central-bank decisions) —
the spread guard automatically skips entries during those windows.

### What happens if my server restarts?
Paper balance and open positions persist in `state.json`; settings in
`runtime.json`. The bot resumes where it left off.

### Refunds?
Digital source code delivered instantly — all sales final, as stated at
checkout. If something doesn't work, contact support and we'll get you
running.
