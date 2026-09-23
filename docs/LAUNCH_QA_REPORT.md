# Apex4Traders — release candidate QA report

**Date:** 2026-09-23 · **Branch:** `claude/apex4traders-platform-v1`

## How this was run, and what that limits

The backend was the **real** `apex.platform.api.handle()` against a throwaway
`DATA_DIR` with a per-run encryption key, with token verification replaced by
a fixed test principal. The web app was a production build served by
`next start`, driven with Playwright/Chromium at 1440×900 and 390×844.

**No cTrader account was connected.** There is no broker credential in this
environment, so every screen below was exercised in its *not connected* state
— which is the correct state to audit, because it is what a new client sees,
but it means the connected path is **verified by unit and contract tests, not
by a live broker**. That distinction is carried through the tables below and
is the single largest gap in this report.

Screenshots are local artefacts under `ui-audit/` (git-ignored). No secrets
were committed.

---

## PASSED

### Automated suites

| Suite | Result |
|---|---|
| `python3 apex-forex-bot/tests/run_all.py` | **155 / 155 files** |
| `cd web && npm test` | **167 / 167 tests, 11 files** |
| `cd web && npm run build` | clean — 24 routes, TypeScript clean |
| `cd web && npm run lint` | **0 errors** (was 13) |

### Browser audit, 21 routes at 1440×900 and 7 at 390×844

| Check | Result |
|---|---|
| Routes rendering | **21 / 21** |
| Console errors | **0** |
| Horizontal overflow, mobile | **0 px** on every page checked |
| Unreadable filled controls | **0** (was 15) |
| Mobile destinations reachable | **8 / 8** (was 1 of 8) |
| External hosts contacted | **none** |
| `<iframe>` on any page | **0** |
| cTrader token in any `/api/v1/` response | **none** |

The only token-carrying response anywhere is Supabase's own
`/auth/v1/token` at sign-in — the identity provider's session, which must
reach the browser. Nothing under `/api/v1/` carries `access_token`,
`refresh_token`, `client_secret` or a Fernet-shaped value.

### Behaviour verified by test

| Area | Where |
|---|---|
| Sign-up, e-mail confirmation, sign-in, password reset, expired session | `src/lib/supabase/middleware.test.ts`, `src/test/e2e.test.ts` |
| Ownership isolation | `tests/test_platform_identity_store.py`, `src/test/e2e.test.ts` |
| cTrader OAuth, wrong callback user, token encryption, token redaction | `tests/test_platform_ctrader_link.py` |
| Demo account selection; live account refused | `tests/test_platform_http.py`, dashboard tests |
| Entitlement x account mode, all four combinations | `tests/test_platform_entitlement.py` |
| A paid plan does NOT unlock a live account in this release | same file |
| Each of the three live locks refuses on its own | same file |
| The UI and the backend refuse live trading in the same words | `src/app/content.test.ts` |
| The smoke script's refusals, redaction and read-only call sequence | `tests/test_smoke_harness.py` |
| Fernet-encrypted values never reach stdout | `tests/test_log_redaction.py` |
| Legacy identity, price, SKU and promises, repo-wide with a reasoned allowlist | `tests/test_product_copy.py` |
| Every public page states that live trading is off | same file |
| Checkout answers about the product, not the deployment | same file |
| Rule creation, validation, activation, versioning | `tests/test_platform_api.py`, `tests/test_platform_contracts.py` |
| Preview SETUP / HOLD / REJECT, unknown never folded into not-met | `src/app/(app)/rules/[id]/page.test.tsx` |
| Preview cannot place, close or amend — structural | same file, three assertions |
| Automation start / pause / resume / stop | `tests/test_platform_http.py` |
| Idempotency (orders) | `tests/test_ledger*.py` |
| Positions and orders unavailable states | dashboard tests, `market-panel.test.tsx` |
| Journal, notifications | `tests/test_platform_api.py` |
| Payment webhook, licence grant, duplicate, refund, wrong user | `tests/test_platform_billing.py` |
| Rate limiting, all seven buckets | `tests/test_platform_rate_limit.py` |
| Rate limit counters are shared, and the per-process fallback is reported | same file |
| Liveness, readiness, production refusals, no secret in a health payload | `tests/test_platform_health.py` |
| `/healthz` and `/readyz` over a real socket | `tests/test_platform_http.py` |
| Mobile navigation, focus, reduced motion, touch targets | `src/components/app/shell.test.tsx` |
| Visual contrast, in the real cascade | `src/app/contrast.test.ts` |
| No fake data, no old copy, no trackers, no iframes | `src/app/content.test.ts` |
| No live trading path | `tests/test_live_path_invariants.py` |

### Two bugs found by the tests during this work

1. **Polling drained a control budget.** The first rate-limit classification
   put every `ctrader/*` route in one tight bucket. The shell and the accounts
   page each poll `ctrader/status` every 60 s, so two open tabs exhausted it
   and a client could no longer disconnect their own account.
   `test_platform_http.py` failed on exactly that. Fixed, and pinned by a test.
2. **`bot` as a variable name.** The content test flagged `components/chart/
   candles.tsx`, where `bot` was the bottom of a candle body. Renamed.

---

## FAILED

**None.** No check in this report is failing at `ce8496ac3`.

---

## BLOCKED — missing owner decision

These cannot be closed by writing code. Each is implemented with an explicit,
greppable placeholder.

| # | Blocked | Detail |
|---|---|---|
| D1–D3, D5 | Price, currency, SKU, plan shape, tax | `docs/PAYMENT_AND_LICENCE_DECISIONS.md`. Checkout answers 503 until set. |
| D6 | Whether paid access is in beta at all | Choosing "no" removes D1–D3 and D5 from the beta gate entirely. |
| L1–L2 | Legal entity, registered address, company number, governing law | `docs/LEGAL_LAUNCH_BLOCKERS.md` |
| L3 | Support contact address | The old one belonged to another brand and was removed, not replaced. |
| L4 | Refund policy | The webhook already revokes on refund; entitlement is not a code question. |
| L6–L8 | Hosting provider, data region, sub-processors, retention, data-subject rights | |
| D9 | Palette confirmation | Implemented from the brief. `contrast.test.ts` asserts the roles it uses. |

Run `grep -rn "TO BE CONFIRMED" web/src` to see them in the product.

---

## BLOCKED — missing external configuration

Cannot be verified in this environment. Each needs infrastructure that does
not exist here.

| # | Blocked | What it blocks |
|---|---|---|
| X1 | **A real cTrader demo account** — procedure and harness now exist in `docs/CTRADER_DEMO_SMOKE_TEST.md`, unrun | The entire connected path: OAuth end to end, account selection with real accounts, positions and orders with data, the chart with real candles, a preview on live bars, and automation actually running. All are covered by contract tests; none has been exercised against cTrader in this session. |
| X2 | **Shared Redis or Upstash** | Cross-instance ownership, order idempotency and webhook idempotency. Locally the store runs in `ALLOW_LOCAL_BACKEND_DEV` mode, which production must not use. |
| X3 | **A production Supabase project** | Real sign-up, real confirmation e-mail, real password reset. The local harness stands in for GoTrue. |
| X4 | **A registered production OAuth redirect URI** | cTrader compares byte for byte; OAuth cannot work off localhost until it is registered. |
| X5 | **A Stripe endpoint and its signing secret** | The webhook is tested with a locally generated signature. It has never received a real Stripe delivery. |
| X6 | **HTTPS on a production domain** | |
| X7 | **Monitoring and alerting** | Not provisioned. The runbook lists what to watch. |
| X8 | **An exercised restore** | The backup is a plan until a restore has been performed once. |
| X9 | **Five external testers** | A public-launch gate. |

---

## Known limitations, stated rather than hidden

- **Rate limiting falls back to per process.** Counters are `INCR` with a TTL
  in the shared backend, so instances share one window. When the backend
  cannot answer, the limiter counts in one process and the effective limit
  becomes N times the configured one for N instances. That fallback is
  reported, not hidden: `/readyz` answers `rate_limit_store: fail` in
  production whenever it is in force.
- **Webhook idempotency degrades without Redis.** `user_store.claim` cannot
  answer, and the fallback is a read-then-write, which is not atomic across
  instances. The grant is idempotent in effect — same user, same plan — so
  the damage is bounded, but the guarantee is weaker.
- **No volume on the chart.** `broker_read._shape()` keeps OHLC and time only.
  The chart says so instead of drawing a flat row.
- **No indicator overlays.** An EMA computed in the browser would be a second
  implementation of what the evaluator computes, and the two would disagree
  at the edges. A chart that disagrees with the verdict beside it is worse
  than a chart without a line.
- **`/readyz` has never run against a real deployment.** The checks are
  covered by `tests/test_platform_health.py`, including the production
  refusals, but no instance of this platform has yet been deployed for one to
  answer from.
- **`/rules/{id}` cannot edit.** Editing an active rule must create a new
  draft version; that flow is not built.
- **`AGENTS.md` is deliberately Romanian.** Its facts were corrected in this
  phase — it now names both products, both branches, and the platform's own
  prohibitions. Whether an agent-coordination file should be in Romanian at
  all is an owner decision, not a cleanup one, and it has not been taken.

---

## Manual verification still required before a private beta

Moved to `docs/CTRADER_DEMO_SMOKE_TEST.md`, which has the full procedure, the
script that automates the read side of it, and what a pass and a failure each
mean. The short version, in order, on a real cTrader **demo** account:

1. Sign up, receive the confirmation e-mail, confirm, sign in.
2. Connect the demo account through OAuth; confirm the callback returns only
   a nonce and the link completes as the signed-in user.
3. Select the demo account. Confirm a live account, if one exists, cannot be
   selected.
4. Confirm positions, orders and the chart render real data, and that the
   chart's bar count and latest timestamp match the broker.
5. Build a rule, validate it, preview it on real bars, activate it.
6. Start automation. Confirm the journal records evaluations including the
   ones that place nothing.
7. Pause, resume, stop. Confirm each is reflected in the status strip.
8. Disconnect the account. Confirm every read returns to *not connected*.
9. Repeat steps 1–8 on a phone.
