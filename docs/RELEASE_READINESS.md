# Apex4Traders — release readiness

**Assessed at:** `ce8496ac3` on `claude/apex4traders-platform-v1`
**Date:** 2026-09-23

| Gate | Status |
|---|---|
| **PRIVATE DEMO BETA** | **NOT YET** — blocked on X1 |
| **PUBLIC BETA** | **NO** |
| **PUBLIC PAID LAUNCH** | **NO** |
| **LIVE TRADING** | **FALSE**, and out of scope by design |

The honest summary: the software is in good shape and **nothing has been
proved against a real broker**. Every gate below that depends on a live
cTrader account is unverified, and that is one gate, not a detail.

---

## BETA READY — private demo beta

| # | Gate | Status | Evidence |
|---|---|---|---|
| 1 | Demo automation works | ⚠️ **unverified against a broker** | Start / pause / resume / stop are covered by `test_platform_http.py` and by dashboard tests. Never run against cTrader. |
| 2 | cTrader demo OAuth works | ⚠️ **unverified** | `test_platform_ctrader_link.py` covers the flow including the account-injection case. No real authorisation has been completed. |
| 3 | Payment/licence tested **or** intentionally disabled | ✅ | Both. The webhook has 12 test groups; checkout is disabled behind `A4T_CHECKOUT_ENABLED`, which is off. |
| 4 | Legal blockers documented | ✅ | `docs/LEGAL_LAUNCH_BLOCKERS.md`, nine items, each a `[TO BE CONFIRMED]` in the product. |
| 5 | Production configuration documented | ✅ | `docs/PRODUCTION_RUNBOOK.md`, `docs/BETA_CONFIGURATION.md`, `docs/MANUAL_LICENCE_OPERATIONS.md`. |
| 6 | No critical security issue | ✅ | No token under `/api/v1/`; rate limiting on every route; webhook verifies before parsing; ownership is the storage key. |
| 7 | No live trading path | ✅ | `test_live_path_invariants.py`; `SUPPORTED_ORDER_TYPES = {MARKET}`; `automation.start` refuses a non-demo account. |
| 8 | Frontend tests pass | ✅ | 167 / 167 |
| 9 | Backend tests pass | ✅ | 155 / 155 files |
| 10 | Build passes | ✅ | 24 routes, TypeScript clean, lint 0 errors |
| 11 | Mobile navigation works | ✅ | 8 of 8 destinations at 390 px, 0 px overflow |
| 12 | Chart handles real connected data | ⚠️ **unverified** | Every failure state is tested. The success state has never had real candles in it. |
| 13 | No fake data appears | ✅ | `content.test.ts`; every empty state names its cause |

**Verdict: NOT YET.** Gates 3–11 and 13 are met. Gates 1, 2 and 12 are all the
same blocker — **X1, a real cTrader demo account** — and they are the three
that matter most, because they are the product.

### What closes it

One session on a real cTrader demo account, working through §"Manual
verification still required" in `docs/LAUNCH_QA_REPORT.md`. If all nine steps
pass, gates 1, 2 and 12 close and this becomes **BETA READY**. Also needed:
a Supabase project (X3) and a registered redirect URI (X4), both of which are
configuration rather than work.

Nothing in the code is known to be missing for those gates. They are unproven,
which is a different thing from broken, and must not be reported as the same
thing.

---

## PUBLIC LAUNCH READY

| # | Gate | Status |
|---|---|---|
| 1 | Owner-approved pricing | ❌ D1, D2, D3, D5 |
| 2 | Owner-approved legal, contact, refund | ❌ L1–L4, L6–L8 |
| 3 | Verified payment webhook works | ❌ X5 — tested with a local signature, never a real delivery |
| 4 | Licences granted correctly | ⚠️ correct in test; depends on gate 3 |
| 5 | Production Redis / Upstash | ❌ X2 |
| 6 | Production OAuth redirect works | ❌ X4 |
| 7 | HTTPS and domain | ❌ X6 |
| 8 | Rate limiting enabled | ✅ — shared counters, with a reported per-process fallback |
| 9 | Monitoring | ⚠️ X7 — `/healthz` and `/readyz` exist and are tested; nothing scrapes them yet |
| 10 | Demo onboarding manually tested | ❌ X1 |
| 11 | Five external testers complete the flow | ❌ X9 |
| 12 | All critical issues closed | ✅ none open |

**Verdict: NO.** Nine of twelve are open, and most are decisions or
infrastructure rather than code.

---

## LIVE TRADING READY — **FALSE**

Out of scope and deliberately not made easier. The properties that keep it
false, all tested:

- `automation.start` refuses any account that is not demo.
- `ctrader_link.live_allowed()` requires production **and** an explicit flag.
- `bridge.SUPPORTED_ORDER_TYPES` is `{MARKET}`;
  `bridge.SUPPORTED_CONSTRAINTS` is empty — an order the rule asked for and
  the path cannot honour is refused, never downgraded.
- `test_live_path_invariants.py` asserts one execution path and one writer of
  the demo/live flag.
- The dashboard renders live accounts as disabled options labelled
  "not available", and renders no automation control for a non-demo
  selection.

Making this true is a separate milestone with its own review. No phase in this
work moved towards it.

---

## The shortest path to a private beta

1. **Owner:** decide D6 — is paid access part of beta? If no, D1–D3 and D5
   leave the beta gate entirely and checkout stays off.
2. **Owner:** create or name the production Supabase project (X3).
3. **Owner:** register the production OAuth redirect URI in the cTrader
   portal (X4), and provide `CTRADER_CLIENT_ID` / `CTRADER_CLIENT_SECRET`.
4. **Owner:** provision Redis or Upstash (X2).
5. **Engineering:** deploy to a non-public URL with the runbook's environment.
6. **Together:** work through the nine manual steps on a real demo account.
7. Re-assess this document.

Items 1–4 are the critical path, and none of them is engineering work.

## The shortest path to a public paid launch

Everything above, then: L1–L4 and L6–L8 from the owner; D1–D3 and D5 from the
owner; move checkout creation behind the authenticated platform API; register
the Stripe endpoint and take one real delivery end to end (X5); HTTPS and
domain (X6); monitoring (X7); exercise a restore once (X8); five external
testers (X9).

---

## What was built in this work, for the record

| Phase | Commit | What |
|---|---|---|
| 0 | `d3126aa54` | Foundations plan |
| 1 | `dd250280c` | Design system, brand lockup, shell |
| 2 | `a9e8eabca` | Trader-first dashboard, plain language |
| 3 | `d106f98e2` | Read-only market chart, no dependency |
| 4 | `3c00ead74` | Rule builder with progressive disclosure |
| 5 | `cb449673f` | Rule detail and preview |
| 6 | `b30b91a9c` | Verified payment-to-licence |
| 7 | `82edd6044` | Product and legal copy |
| 8 | `ce8496ac3` | Rate limiting, runbook |
| 9–10 | `1925e49af` | QA report, release readiness |
| E | this commit | Health endpoints, shared rate-limit counters, beta and licence runbooks |

Tests went from 44 to 167 in the web client and from 153 to 155 files in the
backend. Lint went from 13 errors to 0. Unreadable controls went from 15 to 0.
Mobile destinations went from 1 of 8 to 8 of 8.
