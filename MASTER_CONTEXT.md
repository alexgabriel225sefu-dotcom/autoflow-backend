# Apex Trading Suite (AI Cash System) — Master Context

## Business Overview
- **Brand:** Apex Trading Suite, by AI Cash System
- **Website:** https://aicashsystem.space
- **Type:** Hosted AI trading bots, sold as a one-time license
- **Tagline:** Fully-hosted AI trading bots, controlled from Telegram — nothing to install.
- **Mission:** Give traders a 24/7 AI-powered bot that trades their own broker account for them, with zero setup friction.

## Products & Pricing

| Product | Price | Description |
|---------|-------|-------------|
| **Apex Crypto Bot** | $297 one-time | AI-powered crypto trading bot, hosted by us 24/7. Trades BTC, ETH, SOL, XRP, LTC, ADA, DOGE, DOT, LINK, BCH via cTrader. |
| **Apex Forex Bot** | $497 one-time | AI-powered forex trading bot, hosted by us 24/7. Trades major/minor FX pairs + gold via cTrader. |

## How it works
- Customer buys a license (via Stripe Checkout) → gets a license key + Telegram activation link by email.
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

## Tech Stack (Backend)
- **Runtime:** Node.js / Express (server.js) + two separate Python trading bots (crypto, forex)
- **Database:** Supabase (PostgreSQL) + Redis (bot session state)
- **AI:** Anthropic Claude (Haiku), Groq (Llama fallback)
- **Payments:** Stripe is the ONLY processor (account acct_1TSAWQGpBbs5xtI5 / ApexTradingSuite). `/api/checkout/create-session` uses Stripe; with no Stripe key configured it returns "Payments are not configured" rather than falling back to anything. REMOVED, and not dormant: Dodo Payments (they rejected the business), Digistore24 (also rejected — its IPN handler, signature check and thank-you page are gone), and BOTH affiliate programs. There is no affiliate program of any kind now: the in-house one (13 /api/affiliates/* routes, signup + dashboard pages, Stripe Connect onboarding, payout requests, commission ledger) and the Endorsely integration (tracking script, referral metadata, payout tracker) were both removed on 2026-08-20 — they had been running side by side on the same signup page, which put one sale in two commission ledgers. `ref` survives in Checkout metadata as plain provenance and is attributed to nobody. CopeCart was abandoned mid-KYC. Stripe is NOT usable as a native in-Telegram payment provider (owner confirmed via BotFather), so Telegram checkout has to be a Stripe Checkout link opened in-browser.
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
- Drive traffic to aicashsystem.space (homepage sells both bots directly)
- Convert visitors to a $297 crypto bot or $497 forex bot purchase
- Build audience on TikTok, Instagram, YouTube Shorts showing the bot actually trading

## Content Channels
- TikTok (primary — UGC style, 9:16)
- Instagram Reels (9:16)
- YouTube Shorts (9:16)
- Email list (Brevo)

## Disclaimer
Trading carries a real risk of loss, including total loss of capital. Past or simulated results do not guarantee future performance. This is automation software, not financial advice — never imply guaranteed returns in any generated content.
