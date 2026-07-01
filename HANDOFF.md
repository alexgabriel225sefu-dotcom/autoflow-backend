# HANDOFF — Apex Trade Bot (context for continuing in a new session)

> ## 🛑 FIRST THING, BEFORE ANYTHING ELSE
> **Run `git checkout claude/arcads-external-api-gExX7` immediately.**
> ALL of our work (cTrader, copilot, Market Pulse, news, legal, lead funnel — 1000+
> commits) lives ONLY on that branch. `main` is OLD and diverged: it still has
> OANDA, has NO cTrader, and does NOT even contain this file. If you are reading
> stale code (OANDA-only, no `/ctrader`, no `apex/market.py`), you are on the wrong
> branch — switch now. Render deploys from `claude/arcads-external-api-gExX7`
> (confirmed live via `/api/health` → `sale_ready:true`). Never work on `main`.
>
> After switching branches, read the rest of this file. It carries the
> **conversation** context (decisions, pending work, current bug) that isn't in code.

## What this project is
- **Apex Trade Bot** by **AI Cash Systems** (owner: Alex Otvos, Romania).
- Two Telegram trading bots sold as one-time licenses + a sales site + affiliate program.
  - `apex-crypto-bot/` — Python, Binance, **$297** crypto bot.
  - `apex-forex-bot/` — Python, **$497** forex bot.

> **⚠️ BROKER — read this, don't get confused:** the forex bot uses **cTrader**
> (the owner's cTrader account is hosted at **Pepperstone** — Pepperstone is just
> the broker where the cTrader account lives, NOT a separate integration). The bot
> connects via the **cTrader Open API** (`apex/brokers/ctrader.py`, `/ctrader`
> onboarding). **OANDA is a LEGACY option still in the code and defaults/help text,
> but it is NOT used** — do not "fix" the bot toward OANDA. `_make_broker()` picks
> the broker per-user: cTrader token present → cTrader; else OANDA token → OANDA;
> else paper → Yahoo. The owner trades via cTrader/Pepperstone. (Cleaning the
> stale OANDA-worded defaults/help to say cTrader is a nice-to-do, not urgent.)

  - `server.js` + `public/` — Node sales site, Stripe checkout, license delivery, affiliate API.
  - `apex-affiliate-bot/` — Telegram bot for affiliates (30% commission).

## Render services (deploys from the working branch)
- `autoflow-backend` — the Node site (`server.js`). `/api/health` → `sale_ready:true`.
- `autoflow-backend-2` — the **forex** bot (Python). Callback: `/api/ctrader/callback`.
- (crypto bot + affiliate bot are the other Python services.)
- Free tier: ~3 weeks/month uptime, suspends late-month, auto-resumes on the 1st.

## What is BUILT & live (all committed + tested)
- **Legal**: EU Art.16(m) withdrawal waiver at checkout + terms + emails; no-refund; cookie banner; refund/chargeback → license revoked.
- **Security**: payment-authoritative `/verify-license`; `/api/health` diagnostic.
- **Client onboarding** (both bots): welcome, Binance referral link, paper vs real, per-user AI keys (Groq/Gemini/Claude), any-coin/any-pair.
- **cTrader integration** (forex): OAuth onboarding (`/ctrader`, `/ctaccount`), sync protobuf connector, `_make_broker` wiring. OAuth hardened (query-param token exchange + `state` fallback). Scope configurable via `CTRADER_SCOPE`.
- **10 "copilot" features** (both bots): per-trade explanations in alerts; copilot mode (`/copilot on|off`, approve/reject buttons); smart "don't-trade" alerts; volatility-aware sizing (crypto); news guard + `/news`; flash-crash breaker.
- **Market Pulse** (`/market`): crypto = volatility/volume/trend/momentum + funding/long-short (Binance futures); forex = same + **session awareness** (Sydney/Tokyo/London/NY from UTC clock).
- **News**: FMP economic calendar support (set `NEWS_API_KEY`); default Forex Factory feed is blocked on Render datacenter IPs.
- **Marketing**: `public/promo.html` — on-brand animated 9:16 promo (bg `#060608`, red `#ff2d4f`, Clash Display + JetBrains Mono). Affiliate recruitment DMs + UGC scripts written (in chat history).
- **Lead funnel** (`public/free.html` + `POST /api/lead`): cold-DM traffic → free offer → email capture → shows promo → buy CTA. Preserves affiliate ref. **Owner's plan: send ~10k DMs pointing to `aicashsystem.space/free`** (NOT the $297 page directly).
  - To actually STORE leads, create the Supabase table (endpoint is fail-soft without it):
    ```sql
    create table if not exists leads (
      id bigserial primary key, email text not null,
      ref text, source text default 'free',
      created_at timestamptz default now()
    );
    ```

## PENDING / IN PROGRESS
1. **🔴 CURRENT BUG (unresolved): forex bot "stays in place" / repeats errors.**
   Suspected cause: the **news-feed fetch blocks the loop** — `news._load()` does a
   `requests.get(timeout=10)` to a host that may hang (not fast-403), freezing the
   tick for up to 10s every 30 min. Proposed fix (not yet applied): lower timeout,
   move the feed fetch to a background thread so it NEVER blocks the loop, add
   back-off on repeated failures. **Get the exact error first if possible.**
   Files: `apex-*/apex/news.py`, `apex-*/apex/user_loop.py`.
2. **cTrader KYC**: app status **"Submitted"** (~3 business days to "Active"). Trading
   scope needs "Active". For now set `CTRADER_SCOPE=accounts` (paper works on read-only
   data). When Active → `CTRADER_SCOPE=trading` for live orders. Then test `/ctrader`.
   Client ID/Secret already created at openapi.ctrader.com (owner has them).
   Redirect URI: `https://autoflow-backend-2.onrender.com/api/ctrader/callback`.
3. **`session_secrets:false`** on `/api/health` → set `JWT_SECRET` on `autoflow-backend`
   (affects affiliate login only, not sales).
4. **News real data**: set `NEWS_API_KEY` (free FinancialModelingPrep key) on both bots.

## Env vars to set (Render)
- forex bot (`autoflow-backend-2`): `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET`,
  `CTRADER_REDIRECT_URI=https://autoflow-backend-2.onrender.com/api/ctrader/callback`,
  `CTRADER_SCOPE=accounts` (→ `trading` after KYC).
- both bots: `NEWS_API_KEY=<FMP key>` (optional, makes `/news` show real events).
- site (`autoflow-backend`): `JWT_SECRET=<random 40+ chars>`.

## Business plan / strategy
- Growth model = **affiliate-driven** (like 3Commas), 30% commission — infra already built (`public/affiliate.html`, affiliate API, affiliate bot).
- Ads: `public/promo.html` screen-recorded for TikTok/Reels. Compliance: never promise guaranteed returns; say "risk-free paper testing", "you control the risk".
- Crypto bot is fully ready to sell now; forex live waits on cTrader KYC.

## Conventions
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` + `Claude-Session:` line.
- Keep files <500 lines; tests: `apex-forex-bot/tests/run_all.py` (7 files).
- Never commit secrets. Push to the working branch only.
