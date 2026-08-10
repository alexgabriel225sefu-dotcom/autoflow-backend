# Apex4Traders (formerly Apex Trading Suite / AI Cash System) — Master Context

## Business Overview
- **Brand:** Apex4Traders (rebrand in progress — old brand was Apex Trading Suite, by AI Cash System)
- **Website:** aicashsystem.space is CLOSED/inactive (owner shut it down). No live site currently — rebranding to apex4traders, new site not yet built.
- **Type:** Hosted AI trading bot, sold as a one-time license
- **Tagline:** Fully-hosted AI trading bot, controlled from Telegram — nothing to install.
- **Mission:** Give traders a 24/7 AI-powered bot that trades their own broker account for them, with zero setup friction.

## Products & Pricing

| Product | Price | Description |
|---------|-------|-------------|
| **Apex Forex Bot** | ~$500 one-time (unconfirmed exact figure, was $497) | AI-powered forex trading bot, hosted by us 24/7. Trades major/minor FX pairs + gold via cTrader. |

**Crypto bot retired — not offered anymore.** Ignore/remove references to "Apex Crypto Bot" in any new marketing content going forward.

## How it works
- Customer buys a license (via Digistore24 checkout) → gets a license key + Telegram activation link by email.
- Customer opens the bot in Telegram, connects their own cTrader account (any cTrader-compatible broker — IC Markets, Pepperstone, FxPro, etc.) with a single command (`/ctrader`), demo or live.
- The bot analyzes the market with AI (Claude/Groq) using multiple strategies (trend following, mean reversion, breakout) and trades automatically — no VPS, no computer left running, fully hosted on our servers.
- Everything is controlled from Telegram: risk %, stop-loss/take-profit, strategy, pairs, on/off.

## What this is NOT
- **Not source code delivered.** Customers do not receive or self-host any code — this is a hosted SaaS/license model.
- **Not Binance/OANDA.** Both bots connect exclusively through cTrader.
- **Not a course.** There is no "AI Automation" education product anymore — that business was retired. Do not reference courses, modules, Make.com, or WhatsApp/Instagram bot training in any marketing content.
- **Not a guaranteed-profit system.** Trading carries real risk of loss; never imply guaranteed returns or a "100% win rate."

## Target Audience
- Retail traders (18–45) who want automated trading without coding or constant monitoring
- Both total beginners (want simplicity) and experienced traders (want a tool they can tune)
- Pain points: don't have time to watch charts all day, don't trust "black box" bots, don't want to run a VPS
- Platforms: TikTok, Instagram, YouTube Shorts, X/Twitter

## Brand Voice
- **Tone:** Direct, confident, results-focused, zero fluff — but honest about risk (never overpromise returns)
- **Style:** Street-smart meets professional, like a friend who found a genuinely useful tool
- **Language:** English (primary marketing), Romanian for local/direct communication
- **Avoid:** "Guaranteed profits," "100% win rate," "get rich quick," corporate speak, hype with no substance

## Aesthetic / Visual Identity
- **Colors:** Dark background (#09090b), red/coral accent (#e63946 → #ff6b7a), light text (#e4e4e7)
- **Style:** Premium, dark-mode, minimalist, modern SaaS aesthetic — hooded/masked trader figure with neon-glow crypto/forex motifs is the established visual identity (see bot avatar art)
- **Fonts:** system-ui / Clash Display + Satoshi (site-dependent)

## Key Selling Points
1. Fully hosted 24/7 — nothing to install, no VPS, no computer left running
2. Connects to the customer's own cTrader broker account — never touches their funds (trade-only, no withdrawal access)
3. AI-driven signals (Claude/Groq) combined with proven strategies (trend, mean-reversion, breakout)
4. Controlled entirely from Telegram — simple commands, no dashboard login needed
5. One-time payment, no subscription
6. Demo account first, switch to live whenever ready

## Competitive Advantage
- No self-hosting/VPS required (unlike most retail trading bots)
- Real AI signal generation, not just fixed indicator rules
- Per-instrument risk protection (a bad streak on one pair doesn't freeze the whole account)
- Transparent trade journal (`/report`) for every closed trade

## Revenue Model
- One-time license sales: $297 (crypto), $497 (forex)
- In-house affiliate program (Supabase `affiliates`/`referral_sales` tables, own signup/dashboard/payout flow at `/api/affiliates/*`) — commission tracked via the `ref` query param captured on the homepage and passed through Dodo Payments checkout metadata. Default 30% commission unless overridden per affiliate.
- Separate: 14 outside Telegram trading-signal channels each got their own Dodo Payments discount-tracking code + dedicated checkout links (0.01% discount, `times_used` counter only) — these are informal one-off partners, not signed up in the in-house program.

## Tech Stack (Backend)
- **Runtime:** Node.js / Express (server.js) + two separate Python trading bots (crypto, forex)
- **Database:** Supabase (PostgreSQL) + Redis (bot session state)
- **AI:** Anthropic Claude (Haiku), Groq (Llama fallback)
- **Payments:** Dodo Payments (Merchant of Record, primary — integrated in `server.js` via `/api/checkout/create-session` + `/dodo-webhook`). Dodo has NO built-in affiliate marketplace (would need a third-party like Affonso/Rewardful to expose the offer to outside affiliates). Digistore24 code kept in place but the account was REJECTED for this product (not just "dormant" — reason not yet confirmed, ask owner before assuming why). CopeCart account was separately abandoned mid-KYC. Stripe code kept only as a fallback for as long as `DODO_PAYMENTS_API_KEY` is unset — fully retired otherwise.
- **Email:** Brevo
- **Broker integration:** cTrader Open API (both bots)
- **Deployment:** Render (three services — main site, forex bot, crypto bot)

## API Keys (stored in .env — NEVER commit)
- `ARCADS_API_KEY` — Arcads video/image generation
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- `ANTHROPIC_API_KEY`, `GROQ_API_KEY`
- `DIGISTORE24_IPN_PASSPHRASE`
- `BREVO_API_KEY`

## Marketing Goals
- No live site currently (old site closed, rebrand to apex4traders not yet built) — current focus is finding a growth/marketing co-founder, not direct-to-site traffic
- Convert future visitors to a ~$500 forex bot purchase (crypto bot retired)
- Build audience on TikTok, Instagram, YouTube Shorts showing the bot actually trading

## Content Channels
- TikTok (primary — UGC style, 9:16)
- Instagram Reels (9:16)
- YouTube Shorts (9:16)
- Email list (Brevo)

## Disclaimer
Trading carries a real risk of loss, including total loss of capital. Past or simulated results do not guarantee future performance. This is automation software, not financial advice — never imply guaranteed returns in any generated content.
