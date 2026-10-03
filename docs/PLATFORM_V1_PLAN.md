# Apex4Traders Platform v1 — inventory and plan

**Branch:** `claude/apex4traders-platform-v1`, started from `8e26e4fc8`
**Phase 1 — audit.** Nothing in the execution path changes in this commit.

This document says what EXISTS in the code, not what the documentation claims.
Every statement below was verified by reading the source directly.

---

## 1. What was found — a verified inventory

### Two backends, not one

| | What it is | Role |
|---|---|---|
| `server.js` | Node/Express, 3,513 lines | Sales site + Stripe + email + unrelated products (heygen, creatify, tiktok). **NOT the trading backend.** |
| `apex-forex-bot/` | Python | The execution engine. Its own HTTP server in `apex/bot.py` (`ThreadingHTTPServer` + `BaseHTTPRequestHandler`), not Flask or FastAPI. |

HTTP routes that already exist in `apex/bot.py`:
`/api/session`, `/api/session/logout`, `/api/app/ask`, `/api/app/automation`,
`/api/app/close`, `/api/voice`, `/api/stripe/webhook`, `/app`, `/go`.

### Frontend: `web/` is Next.js, not `public/`

- **Next.js 15, app router**, TypeScript, Tailwind, shadcn/ui, Radix,
  framer-motion, lucide-react.
- Existing pages: `/` (landing), `/configurator`, `/terms`, `/privacy`.
- A single API route: `src/app/api/create-payment-intent/route.ts`.
- `public/*.html` are static marketing pages served by `server.js` — they are
  **not** the application.

**Decision:** the platform is built in `web/`, on the existing stack. No second
framework is introduced.

### What is already built and will be REUSED

These are not rewritten. They are the foundation.

| Module | Lines | What it provides |
|---|---|---|
| `apex/gates.py` | 319 | `authorize_order` / `authorize_close` — **the single gate**. Entitlement, broker environment, demo/live. |
| `apex/ctrader_oauth.py` | 488 | Full OAuth: signed state, CSRF, `handle_callback`, `broker_gate_reason`, stateless refusal in production. |
| `apex/user_store.py` | 1,002 | `encrypt_value` / `decrypt_value` (Fernet), CAS on the journal, startup refused without a key. |
| `apex/access.py` | 238 | Licensing: `is_allowed`, `allowed_state`, `grant`, `revoke`, admins. |
| `apex/http_session.py` | — | Cookie sessions: `create`, `valid`, `revoke`, `set_cookie_value`. |
| `apex/http_security.py` | — | CSP, `RateLimiter`, HTTPS detection. Limiters already defined. |
| `apex/ledger.py` | 166 | **Idempotency**: `request_id`, `claim`, `record`, `release`. This IS the ExecutionRequest deduplication. |
| `apex/brokers/ctrader.py` | 1,459 | Connector: rate limiter (5/s historical, 50/s the rest), slippage ceiling, positions. |
| `apex/setups.py` | 208 | `SetupCandidate` with `READY` / `WATCH` / `INVALID` — very close to a Decision. |
| `apex/strategy_api.py` | 284 | `Market` (candles, indicators, position, price, balance, timeframe) — close to a MarketSnapshot. |

### What does NOT exist and has to be built

RuleDoc, a complete MarketSnapshot, a rule Decision, ExecutionRequest,
JournalEntry, the condition library, the platform REST API, the screens.

---

## 2. Two architectural problems found during the audit

### 2.1 Name collision: `Decision` already exists

`apex/gates.py:47` defines `class Decision` — the **authorisation** verdict:
`(allowed, reason, detail)`. It answers "may this order proceed?".

The brief asks for a `Decision` that answers a different question: "what does
the rule say?" — `BUY / SELL / CLOSE / HOLD / REJECT`.

Two classes named `Decision` on the same order path, with different meanings,
is a real trap: reading `decision.allowed` on the wrong one raises
`AttributeError` on a good day and quietly confuses a reviewer on a bad one.

**Decision, with a deliberate deviation from the brief's naming:** the rule
verdict is called **`RuleDecision`**, in the new `apex/platform/` package.
`gates.Decision` stays untouched. A test asserts the two cannot be confused.
If `Decision` is preferred anyway, it can be renamed — but the recommendation
is not to.

### 2.2 `strategy_api.Market` covers ~60% of a MarketSnapshot

It has: candles, symbol, indicators, strategy data, open position, price,
balance, timeframe.

Compared with the brief, it lacks: spread, session, pending orders, equity,
exposure, account state, an explicit timestamp.

**Decision:** `MarketSnapshot` is a new type that **contains** a `Market` for
compatibility with existing strategies, rather than replacing it. The current
engine keeps receiving a `Market`; the new evaluator receives a
`MarketSnapshot`.

---

## 3. The phased plan

| Phase | What | Does it touch execution? |
|---|---|---|
| 1 | Audit + this document | No |
| 2 | Contracts: RuleDoc, MarketSnapshot, RuleDecision, ExecutionRequest, JournalEntry + validators + tests | No |
| 3 | Pure evaluator + the condition library | No |
| 4 | Backend API (auth, licence, ownership, RuleDoc, preview, journal) | No |
| 5 | cTrader account connection, demo-first | No |
| 6 | Frontend MVP in `web/` | No |
| 7 | Controlled integration — only through `ExecutionRequest` → `gates` | **Yes, the last one** |
| 8 | Hardening: mutation tests, AST audit, security | No |

Phases 1–6 do not touch the execution path at all. Phase 7 is the only one
that does, and only through the existing gate.

---

## 4. Constraints respected

- No deployment, no live trading, no environment changes.
- `PAPER_TRADING`, `CTRADER_ENV`, the default broker — untouched.
- `gates.authorize_order` / `authorize_close` remain the only way to the
  broker. No second path is created.
- The cTrader connector is reused, not rewritten.
- Tokens are stored encrypted through `user_store.encrypt_value` and never
  appear in an API response.
- No fabricated data in the interface: real states ("Not connected", "No active
  automation") instead of invented numbers.
- The existing suite runs with `python apex-forex-bot/tests/run_all.py`.
  **pytest is not installed in this environment** — the project's official
  runner, declared in `AGENTS.md`, is used instead, and that is recorded here
  rather than changing the tests.

---

## 5. Left for the operator to decide

1. **`RuleDecision` vs `Decision`** — see 2.1. `RuleDecision` is recommended.
2. **Where the platform API lives.** The HTTP server in `apex/bot.py` is
   hand-written. Add the routes there (consistent, no new dependencies) or
   introduce a separate service? The first is recommended: `http_session` and
   `http_security` are already there, and a second path would double the
   authentication surface.

---

# Direction change — Telegram removed, Supabase Auth as the identity

Decided by the operator after Phase 3. Both questions left open above are now
closed: `RuleDecision` stayed `RuleDecision`, and the platform API lives in
`apex/platform/api.py`, mounted in the existing server.

## What changed in the model

The platform identity is **`supabase_user_id`**. Not `chat_id`.

That was possible without rewriting the engine for one reason, verified in the
code: `user_loop.py` has 18 references to Telegram and **zero to `chat_id`** —
it uses `user_id` as an opaque string, which is all `user_store` ever required.
A Supabase id is also a string. The engine cannot tell the difference.

## What is implemented and verified

| Module | The rule it enforces |
|---|---|
| `platform/identity.py` | a misconfiguration is never a permission |
| `platform/store.py` | you cannot read a document without saying whose it is |
| `platform/licence.py` | an unknown entitlement is not an entitlement |
| `platform/api.py` | authenticated · owned · licensed · honest |

Verification at the time of writing: **150/150** files in
`python3 apex-forex-bot/tests/run_all.py`. Mutation testing on the new code:
19/19 (evaluator), 18/18 (identity + storage), 14/15 (API — one equivalent
mutant, documented in the commit).

### Why the token is verified against Supabase rather than locally

Contrary to the usual advice, and for three reasons: revocation actually works
(a locally verified JWT stays valid until it expires, so a signed-out client or
a banned account keeps trading); it survives Supabase's signing-key migration
(HS256 with a shared secret on older projects, asymmetric via JWKS on newer
ones); and it adds no dependency — `requests` is already pinned, `PyJWT` is not.

The cost is one network call per request, amortised by a 60-second cache. The
cache's own cost is stated openly: a token revoked seconds ago still works
until its entry expires. That is why **every destructive operation asks with
`fresh=True`**.

## Required environment variables

`apex-forex-bot/.env.example` **could not be modified** — it is covered by a
deny rule on `.env*` files in the operator's permission settings. The rule was
respected, not circumvented. Add manually:

```
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_ANON_KEY=<public anon key>
```

`SUPABASE_URL` already exists in `render.yaml`. `SUPABASE_ANON_KEY` is new.

It is the **anon** key, not `SUPABASE_SERVICE_KEY`. The service key bypasses
Row Level Security; it must not be used to verify a session and must never
reach anywhere a client can read it.

## Telegram inventory — measured, not assumed

24 files under `apex/` touch Telegram or `chat_id`:

| File | `chat_id` | `telegram` | What it means |
|---|---|---|---|
| `telegram.py` | 953 | 85 | the bot itself, 6,742 lines |
| `ctrader_oauth.py` | 33 | 21 | **the OAuth flow is keyed by `chat_id`** |
| `access.py` | 33 | 2 | the admin/allowed lists |
| `stripe_license.py` | 25 | 4 | entitlement by `chat_id` |
| `bot.py` | 24 | 67 | the HTTP server + the Telegram wiring |
| `user_loop.py` | 0 | 18 | notifications only — the engine is clean |
| `gates.py` | 0 | 2 | the gate is nearly clean |

**Nothing had been deleted or isolated at the time of writing.** The new path
was built alongside the old one, and the new flow does not import
`telegram.py`.

## What remained at the end of this phase

> **Historical note.** The list below reflects the state when this document was
> written. Items 1–4 have since been implemented. For the current state see
> `docs/PLATFORM_V1_RELEASE_CHECKLIST.md`, which is kept up to date.

1. **Notification port** — `user_loop` sent directly to Telegram. An in-platform
   notification interface was needed (notification centre, activity feed), with
   Telegram reduced to an optional adapter.
2. **cTrader OAuth on the web** — `ctrader_oauth.py` is keyed by `chat_id` and
   redirects back into Telegram. A web callback bound to `supabase_user_id` was
   needed, with the token encrypted and never returned to the frontend.
3. **Broker-dependent endpoints** — `accounts`, `positions`, `orders`,
   `journal`, `notifications`, `preview`. They answered 501 UNSUPPORTED.
4. **Frontend** in `web/` (Next.js 16, Tailwind, shadcn already present):
   sign up/login, dashboard, Rule Builder, preview, positions, activity,
   journal, licence, settings.
5. **Telegram isolation** — a compatibility layer marked deprecated, which the
   new flow does not import.

No deployment. No live trading. `PAPER_TRADING`, `CTRADER_ENV` and the default
broker remain untouched.
