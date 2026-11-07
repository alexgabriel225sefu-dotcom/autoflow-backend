# Apex4Traders — foundations implementation plan

**Branch:** `claude/apex4traders-platform-v1` · **Base commit:** `329dcd8bd`
**Scope:** everything needed to take the platform from "the demo path works"
to "a private beta can be run safely".

**Live trading is excluded from this plan.** There is no live loop, no live
account selection, no live order path and no hidden live flag, and none is
added by any phase below. `LIVE TRADING READY` is a separate future milestone
and stays false.

Nothing in this document changes application behaviour. It records what was
found by reading the repository, and what the following phases will change.

---

## 1. Current implementation status

### Verified present

Read from the code, not from the previous documents.

| Area | Where | State |
|---|---|---|
| Supabase identity | `apex/platform/identity.py` | Remote token verification, 60 s cache, `AuthFailed` vs `AuthUnavailable` separated |
| Owner-scoped storage | `apex/platform/store.py` | Ownership is the storage key, not a post-load check |
| cTrader OAuth | `apex/platform/ctrader_link.py` | `begin` / `handle_callback` / `complete`; the callback parks the code and returns a nonce, completion is authenticated |
| Encrypted broker tokens | `apex/user_store.py` | Fernet; startup refuses plaintext unless `APP_ENV=dev` **and** `ALLOW_PLAINTEXT_DEV_STORAGE` |
| Rules | `apex/platform/ruledoc.py`, `store.py`, `api.py` | CRUD, validation, activation, versioning; an active doc is frozen |
| Condition registry | `apex/platform/conditions.py`, `conditions_context.py` | 12 conditions, served at `GET /api/v1/conditions` |
| Evaluator | `apex/platform/evaluator.py` | Pure, three-valued (true / false / unknown), no short-circuit |
| Read-only broker views | `apex/platform/broker_read.py` | accounts, positions, orders, candles; `{connected, status}` contract; errors scrubbed of tokens |
| Journal | `apex/platform/journal.py`, `journal_store.py` | Records evaluations including the ones that place nothing |
| Notifications | `apex/platform/notifications.py` | Query, mark-read, mark-all-read |
| Preview | `apex/platform/preview.py` | Evaluates supplied candles; creates no order and writes no execution journal |
| Demo automation | `apex/platform/automation.py`, `bridge.py` | start / pause / resume / stop; demo only |
| API transport | `apex/bot.py:504` `_platform_api()` | Mounted at `/api/v1/`; forwards only `Authorization` |
| Web client | `web/src/` | Next.js 16, React 19, TS, Tailwind v4; 21 routes |
| Tests | `apex-forex-bot/tests/` (153 files), `web/src/**/*.test.*` (6 files, 63 tests) | All passing at `329dcd8bd` |

### Verified absent

| Gap | Evidence |
|---|---|
| Rate limiting on `/api/v1/*` | `_platform_api()` in `apex/bot.py` runs **before** any limiter. `http_security.RateLimiter` exists and is applied to `LOGIN`, `MINIAPP`, `WEBHOOK`, `GO` — none of them covers the platform API |
| Payment → licence wiring | `apex/platform/licence.py::grant()` has **no production caller**. `web/src/app/api/create-payment-intent/route.ts` creates a PaymentIntent and returns a client secret; nothing ever grants a licence from a payment |
| Market chart | No chart component anywhere in `web/src` |
| Position close / amend endpoints | Not in `apex/platform/api.py` |
| Backtesting | Not in `apex/platform/` |
| Multi-account automation | `automation.py` holds one state per user |
| Live trading | Absent by design |

### Known-stale artefacts

- **`AGENTS.md` (repo root)** still describes the project as "bot de trading
  forex pe Telegram" and names the old branch. It is agent-coordination
  content, in Romanian by prior decision, but its facts are wrong.
- **`web/README.md`** says under *What is not built*: "A market data feed for
  previews. Preview evaluates candles you supply; it does not fetch them."
  The `accounts/{ctid}/candles` endpoint has existed since `e1f991f42`.
- **`/terms`, `/privacy`, `/configurator`** carry the previous product's copy.
  See §5.
- **`components/ui/modern-payment-form.tsx`** — unused, `$297`, 7 lint errors.

### Lint baseline

`npx eslint src` reports **13 errors, 9 warnings**:

| Count | Rule | Where |
|---|---|---|
| 8 | `@typescript-eslint/no-explicit-any` | `modern-payment-form.tsx` (7), `create-payment-intent/route.ts` (1) |
| 3 | `react-hooks/set-state-in-effect` | `shell.tsx` (2), `use-api.ts` (1) |
| 2 | `@next/next/no-html-link-for-pages` | `rules/page.tsx`, `rules/new/page.tsx` |
| 7 (warn) | `@next/next/no-img-element` | `modern-payment-form.tsx` |

`npm run lint` has never been part of the commit gate. It becomes one from
Phase 1.

---

## 2. Remaining launch blockers

Ordered by what stops a private beta first.

### B1 — No rate limiting on the platform API (security)

Every `/api/v1/*` route is unmetered, including `ctrader/connect`,
`rules/{id}/activate`, `rules/{id}/preview`, `automation/*` and
`accounts/{ctid}/candles`. Preview and candles are the expensive ones: candles
consume the broker's 5-requests-per-second historical budget, which is **per
connection, shared across every client on that connection**. One client in a
loop degrades the platform for all of them.

### B2 — Payment cannot grant a licence (product)

There is no webhook and no server-side grant. A buyer today pays and receives
nothing the platform recognises. The frontend must never be able to grant a
licence, so this has to be a verified webhook on the backend.

### B3 — Legal and product copy (legal)

`/terms` and `/privacy` are linked from the live landing page footer and
describe a **cryptocurrency source-code product** called Apex Trade Bot, with
a contact address at a different domain. `/configurator` is reachable by URL.

### B4 — In-memory rate limiting and per-process state (infrastructure)

`RateLimiter` is explicit that it is per-process. `user_store` refuses to start
without Redis/Upstash **unless** `ALLOW_LOCAL_BACKEND_DEV=true` with
`APP_ENV=dev`. A production deployment must have a shared backend, or
ownership and order idempotency become per-container.

### B5 — No chart (usability)

A trader cannot see the market the rule is evaluating. The data endpoint
exists; the view does not.

### B6 — The interface is still engineer-facing (usability)

Verdicts read `HOLD` / `REJECT`, conditions read `price_vs_ma`, and the
dashboard leads with `STOPPED`. Correct, but not the language of the person
using it.

### B7 — Production configuration is undocumented (operations)

No runbook, no enumerated environment variables, no health check contract, no
key-rotation or incident procedure.

---

## 3. Exact files that will change

Phase by phase. Files not listed are not touched.

### Phase 1 — design system and shell

```
web/src/app/globals.css                     retheme to the approved palette
web/src/components/brand/logo.tsx           NEW — monogram + wordmark, SVG
web/src/components/app/shell.tsx            sidebar, top bar, bottom nav, drawer
web/src/components/app/status-bar.tsx       account / demo / automation / connection
web/src/components/app/nav.ts               navigation model
web/src/app/contrast.test.ts                palette assertions follow the new tokens
web/src/app/shell.test.tsx                  NEW — responsive nav, focus, reachability
web/src/lib/use-api.ts                      fix react-hooks/set-state-in-effect
web/src/app/(app)/rules/page.tsx            next/link (lint)
web/src/app/(app)/rules/new/page.tsx        next/link (lint)
```

### Phase 2 — dashboard

```
web/src/app/(app)/dashboard/page.tsx
web/src/components/app/plain.ts             NEW — engine state → trader language
web/src/app/(app)/dashboard/page.test.tsx   NEW — one test per state
```

### Phase 3 — chart

```
web/package.json                            one charting dependency
web/src/components/chart/candles.tsx        NEW
web/src/components/chart/candles.test.tsx   NEW
docs/CHART_DEPENDENCY_DECISION.md           NEW — licence, bundle, SSR, network
```

### Phase 4 — rule builder

```
web/src/components/app/rule-form.tsx        progressive disclosure, steps
web/src/components/app/condition-editor.tsx human names from the registry
web/src/app/(app)/rules/new/page.tsx        stepper
web/src/components/app/rule-form.test.tsx   NEW
```

### Phase 5 — rule detail and preview

```
web/src/app/(app)/rules/[id]/page.tsx
web/src/app/(app)/rules/[id]/page.test.tsx
```

### Phase 6 — payment and licence

```
docs/PAYMENT_AND_LICENCE_DECISIONS.md       NEW
apex/platform/billing.py                    NEW — verified webhook → licence
apex/platform/api.py                        webhook route, unauthenticated by design
apex/platform/licence.py                    revoke/suspend path
apex-forex-bot/tests/test_platform_billing.py NEW
web/src/app/api/create-payment-intent/route.ts  env-driven, no hardcoded amount
```

### Phase 7 — copy

```
web/src/app/terms/page.tsx
web/src/app/privacy/page.tsx
web/src/app/configurator/page.tsx
docs/LEGAL_LAUNCH_BLOCKERS.md               NEW
```

### Phase 8 — production readiness

```
apex/http_security.py                       platform limiter presets
apex/bot.py                                 apply limits at the /api/v1 mount
apex/platform/api.py                        structured refusal for rate limits
docs/PRODUCTION_RUNBOOK.md                  NEW
web/env.example, apex-forex-bot/env.example documented variables
apex-forex-bot/tests/test_platform_rate_limit.py NEW
```

### Phases 9–10 — QA and release decision

```
docs/LAUNCH_QA_REPORT.md                    NEW
docs/RELEASE_READINESS.md                   NEW
```

---

## 4. Dependency risks

| Risk | Assessment |
|---|---|
| **Charting library** | The only new runtime dependency planned. It must be MIT or similar, must not phone home, must work with SSR disabled, and must not ship a vendor logo. `lightweight-charts` is the candidate; the decision is recorded in `docs/CHART_DEPENDENCY_DECISION.md` before it is installed. If no candidate clears those tests, the chart is drawn with inline SVG instead and the phase still ships. |
| **Stripe SDK** | Already a dependency (`stripe@^22`). Used only server-side. The webhook handler must verify signatures itself rather than trusting a parsed body. |
| **`@supabase/ssr` 0.10** | Cookie format is internal to the library. Nothing in this plan depends on that format. |
| **Next.js 16** | `web/AGENTS.md` warns it differs from training data. Every new API used is checked against `node_modules/next/dist/docs/` first. |
| **In-memory `RateLimiter`** | Correct for one instance, wrong for several. Phase 8 documents this as a deployment constraint rather than pretending otherwise. A distributed limiter is a later decision. |
| **cTrader historical budget** | 5 req/s per connection, shared. Rate limiting the candles endpoint is protection for the broker connection, not just for the server. |

---

## 5. Decisions that require owner approval

These are blockers that no amount of implementation can close. Each is
implemented with an explicit placeholder and documented, never guessed.

| # | Decision | Why it cannot be chosen here |
|---|---|---|
| D1 | **Price and currency** | `29700` USD is the previous product's price for a source-code sale. This product is a subscription-shaped platform. Implemented as `A4T_PRICE_MINOR` / `A4T_CURRENCY` with no default. |
| D2 | **SKU / product identifier** | `"apex-bot"` names the old product. Implemented as `A4T_SKU`. |
| D3 | **Plan model** | One-off, monthly, or trial-then-paid. Determines whether licences carry an expiry and whether a renewal webhook must extend them. |
| D4 | **Legal entity, jurisdiction, registered address** | Required on Terms. |
| D5 | **Support contact address** | `support@aicashsystem.space` belongs to a different brand. |
| D6 | **Refund policy** | The current Terms say "all sales are final once the source code has been delivered". That sentence describes a product that no longer exists. |
| D7 | **Whether paid access is enabled at beta at all** | A private demo beta can ship with checkout disabled and licences granted manually. That is the lower-risk path and it removes D1–D3 and D6 from the beta gate. |
| D8 | **Production domain and OAuth redirect URI** | cTrader compares the redirect byte for byte; it must be registered before OAuth works off localhost. |
| D9 | **Palette confirmation** | The palette below is taken from the brief. It replaces the cyan-on-graphite system shipped in `31ab46c7d`. |

### The palette this plan implements

| Token | Value | Use |
|---|---|---|
| Deep midnight plum | `#111322` | Page background |
| Graphite | `#171B25` | Surfaces |
| Petrol teal | `#0B5960` | Primary action fill, with off-white text |
| Seafoam mint | `#A5E7C5` | Positive / long / confirmed |
| Soft lilac | `#C7B8FF` | Informational highlight |
| Warm off-white | `#F4F0E8` | Primary text |
| Muted slate | derived | Secondary text |
| Coral | derived | Warning and destructive only |

Note that petrol teal is dark: it carries off-white text, not dark text. The
contrast test is updated to assert the pairs this system actually uses rather
than the ones the previous system used.

---

## 6. Definition of beta launch

A **private demo beta**: invited testers, demo accounts only, no public
marketing, checkout either verified or deliberately disabled.

All of the following must be true:

1. A tester can sign up, confirm their email, sign in and reset a password.
2. A tester can connect a cTrader **demo** account through OAuth and select it.
3. A live account cannot be selected, and no code path starts a live loop.
4. A tester can build a rule, validate it, preview it, activate it, and start,
   pause, resume and stop demo automation.
5. Positions, orders, journal and notifications read from the broker, and every
   unavailable state says why.
6. The chart renders real candles from the candles endpoint, and says so when
   it cannot.
7. No invented data anywhere: no balance, position, profit or performance
   number that did not come from the broker.
8. No cTrader token appears in any client-visible payload.
9. Rate limiting is enabled on the platform API.
10. Licences are granted **only** by a verified server-side path.
11. Legal blockers are documented, and no page claims a policy the owner has
    not approved.
12. Backend suite, frontend suite, build and lint all pass.
13. Every primary destination is reachable at 390 px with no horizontal
    overflow and no unreadable control.
14. Production configuration is documented, even if not yet provisioned.

**Not required for beta:** public pricing, a finished refund policy, a
production domain, multi-instance deployment, monitoring, backtesting.

## 7. Definition of production launch

A **public paid launch**. Everything in §6, plus:

1. Owner-approved price, currency, SKU and plan model (D1–D3).
2. Owner-approved legal entity, jurisdiction, contact and refund policy
   (D4–D6).
3. A verified payment webhook, proven idempotent, that grants exactly one
   licence per paid event and can revoke on refund.
4. A shared Redis or Upstash backend — `ALLOW_LOCAL_BACKEND_DEV` unset.
5. Production cTrader application with the production redirect URI registered.
6. HTTPS on the production domain.
7. Rate limits tuned, with limits per authenticated user as well as per IP.
8. Health checks and alerting on backend failure.
9. A documented backup and recovery procedure that has been exercised once.
10. Key rotation procedure documented for `TOKEN_ENCRYPTION_KEY`, Supabase keys
    and cTrader credentials.
11. At least five external testers have completed the full flow end to end.
12. No critical or high security issue open.

## 8. Live trading — excluded

Live trading is **not** part of this implementation and is not made easier by
it. No phase adds a live loop, a live account selection, a live order path or a
hidden live flag.

The properties that keep this true are already tested and stay tested:

- `automation.start` refuses a non-demo account.
- `ctrader_link.live_allowed()` requires production **and** an explicit flag.
- `tests/test_live_path_invariants.py` asserts there is one execution path and
  one writer of the demo/live flag.
- `bridge.SUPPORTED_ORDER_TYPES` is `{MARKET}` and
  `bridge.SUPPORTED_CONSTRAINTS` is empty, so an order the rule asked for and
  the path cannot honour is refused rather than downgraded.

`LIVE TRADING READY` remains **false** at the end of every phase in this plan.
