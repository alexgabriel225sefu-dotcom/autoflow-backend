# Apex4Traders — release readiness

**Assessed at:** `cdbe833` on `claude/apex4traders-platform-v1`
**Date:** 2026-09-30
> **What "assessed at" means here.** The commit named is the one the tree was in
> when these numbers were produced. The commit that updates this line changes
> only documentation, so the numbers still hold at it — that is the convention,
> and it is the reason the SHA is a commit rather than "latest".


### Verification at this commit

| | |
|---|---|
| Backend | **162 / 162** test files |
| Frontend | **215 / 215** tests |
| Build | **clean**, 24 routes |
| Lint | **0 errors**, 8 warnings |
| `npm audit` | **0 vulnerabilities** |
| `pip-audit` | findings present and **unsuppressed** — see §"Python dependencies" in `docs/DEPLOYMENT_READINESS.md` |

| Gate | Status |
|---|---|
| **PRIVATE DEMO BETA** | **NOT YET** — X1 part-closed: reads proven 2026-09-30, controls and screens not |
| **PUBLIC BETA** | **NO** |
| **PUBLIC PAID LAUNCH** | **NO** |
| **LIVE TRADING** | **FALSE**, and out of scope by design |

The honest summary: the software is in good shape and the read side has now
been proven against a real cTrader demo account, but **private demo beta is
still not ready**. The remaining cTrader gate is the part a script cannot prove:
a human browser/phone walk-through of the screens and controls, plus preview
on real bars with `SMOKE_RULE_ID`.

---

## BETA READY — private demo beta

| # | Gate | Status | Evidence |
|---|---|---|---|
| 1 | Demo automation works | ⚠️ **the READS are verified; the controls are not** | 2026-10-01, account …456: the deployed server answered `canAutomate: true`, `liveExecutionEnabled: false`, badge `DEMO` for a real connected demo account. Start / pause / resume / stop have still never been sent to cTrader — they are covered only by `test_platform_http.py` and the dashboard tests. That is what is left of gate 1, and it is the only part of X1 that would *change* something at the broker rather than read from it. |
| 2 | cTrader demo OAuth works | ✅ | 2026-09-27: a real authorisation completed against cTrader and stored a working token for account …456. 2026-09-30: that token was still exchanging and reading, so the refresh path holds too. `test_platform_ctrader_link.py` covers the flow including the account-injection case. |
| 3 | Payment/licence tested **or** intentionally disabled | ✅ | Both. The webhook has 12 test groups; checkout is disabled behind `A4T_CHECKOUT_ENABLED`, which is off, and says so before it says anything about configuration. |
| 3b | Access model implemented, not just decided | ✅ | `free_demo` / `paid_live`, server-derived, all four combinations tested. Demo access needs no manual grant. |
| 3c | Health endpoints | ✅ | `/healthz`, `/readyz`, `/api/v1/system/status`. Tested, including the production refusals. **Answered from the deployed instance on 2026-10-01**: `/readyz` reported `status: ok`, `environment: production`, and every check ok (billing skipped by design, which is the correct answer while checkout is off). Both endpoints now carry `release.commit`, so an operator can tell which build replied. |
| 3d | Rate limiting is real across instances | ✅ | Shared `INCR` with a TTL; the per-process fallback fails readiness in production rather than being served quietly. |
| 4 | Legal blockers documented | ✅ | `docs/LEGAL_LAUNCH_BLOCKERS.md`, nine items, each a `[TO BE CONFIRMED]` in the product. |
| 5 | Production configuration documented | ✅ | `docs/PRODUCTION_RUNBOOK.md`, `docs/BETA_CONFIGURATION.md`, `docs/MANUAL_LICENCE_OPERATIONS.md`. |
| 6 | No critical security issue | ✅ | No token under `/api/v1/`; rate limiting on every route; webhook verifies before parsing; ownership is the storage key. |
| 7 | No live trading path | ✅ | `test_live_path_invariants.py`; `SUPPORTED_ORDER_TYPES = {MARKET}`; `automation.start` refuses a non-demo account. |
| 8 | Frontend tests pass | ✅ | 215 / 215 |
| 9 | Backend tests pass | ✅ | 169 / 169 files |
| 10 | Build passes | ✅ | 24 routes, TypeScript clean |
| 11 | Mobile navigation works | ✅ | 8 of 8 destinations at 390 px, 0 px overflow |
| 12 | Chart handles real connected data | ⚠️ **the data path is proven; nobody has looked at the chart with it** | 2026-10-01, account …456, deployed build `ad37fc64235c`: the read sequence passed **end to end, exit 0** — capability, balance (a `float`), positions, orders, and 199 closed EURUSD 15m bars with OHLC and a time on each, in ascending order, latest `1790824500` = 03:15:00 UTC and aligned to a 15m boundary — which is exactly the last CLOSED bar at the time of the run. **Two things are deliberately NOT claimed.** The price LEVELS have not been cross-checked against the broker's own chart, so a mis-scaling in the connector (it divides by `moneyDigits`) would produce plausible but wrong numbers and this run would not catch it; only the structure, ordering and timing are verified. And whether the chart component *renders* those bars has not been observed — that needs a browser, not a script. |
| 13 | No fake data appears | ✅ | `content.test.ts`; every empty state names its cause |

**Verdict: NOT YET.** Gates 2–11 and 13 are met. Gate 1 is partly open and
gate 12 is partly open, and both are what is left of **X1**. A static regression test, `test_ctrader_browser_walkthrough_contract.py`, now verifies that the required UI anchors for the browser pass remain present; it does not claim the human browser/phone pass has run.

X1 has moved. On **2026-10-01** the read side ran end to end against a real
cTrader demo account and **exited 0** — capability, balance, positions, orders
and 199 real 15m candles, from the deployed instance (`ad37fc64235c`), through
the same `broker_read` the product uses. The sentence "nothing has run against
a real broker" was true until 2026-09-30 and is not true now.

**That run exercised twelve steps, not thirteen.** The preview-on-real-bars
step did not fail; it never ran, because the account has no active rule to
preview. The evaluator has therefore still only ever seen synthetic candles.
The script now reports a skipped step as `SKIP` and repeats it in the summary,
because `exit 0` with a step missing had looked exactly like `exit 0` with
every step passing — and X1 is closed on the strength of that exit code.
Closing it needs one active rule and a re-run; nothing else.

Two things in X1 are still unproven, and they are not small:

- **The controls.** `automation.start` / pause / resume / stop have never been
  sent to cTrader. Every test of them is against a stub.
- **The screens.** A script cannot see a chart, a badge or an empty state. The
  eleven-step walk-through in `docs/CTRADER_DEMO_SMOKE_TEST.md` is still the
  only thing that closes that, and it needs a browser and a phone.

One further gap found by that run, now fixed in the smoke script rather than
in the product: the script asserted that a balance carries a currency.
`broker_read.account()` has no currency in its contract, nothing in `web/`
reads one, and the cTrader client has no asset-list call to derive one from.
The assertion was wrong, not the product — but it had passed for weeks against
a hand-written stub that invented the key.

Phases E–I changed the *shape* of that verdict without changing the verdict.
Before them, closing X1 would still have left a beta that needed a manual
licence grant per tester, had no health endpoint, rate-limited per process,
and logged broker tokens in a shape the runbook told operators to grep for.
Those are now done. What is left is the one thing that cannot be done from
here.

### What closes it

One session on a real cTrader demo account, working through
`docs/CTRADER_DEMO_SMOKE_TEST.md` — eleven steps, plus a script that
automates the read side of four of them and refuses to run against anything
that is not a demo account. If they pass, gates 1, 2 and 12 close and this
becomes **BETA READY**. Also needed:
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
| 5 | Production Redis / Upstash | ✅ — **X2 is done.** 2026-10-01, from the deployed instance: `shared_store` ok, `backend: redis`, `latencyMs: 7`, and `rate_limit_store` reports counters shared across instances rather than the per-process fallback |
| 6 | Production OAuth redirect works | ✅ — **X4 is done.** `ctrader_oauth` reports client id, secret and redirect URI configured; and it is not merely configured — a real authorisation completed THROUGH it on 2026-09-27 (`[link] begin` → `exchange.attempt` → `complete` 200, redirect `https://apex4traders-api.onrender.com/api/v1/ctrader/callback`) and the token it stored was still exchanging and reading on 2026-09-30 |
| 7 | HTTPS and domain | ❌ X6 |
| 8 | Rate limiting enabled | ✅ — shared counters, with a reported per-process fallback |
| 9 | Monitoring | ⚠️ X7 — `/healthz` and `/readyz` exist and are tested; nothing scrapes them yet |
| 10 | Demo onboarding manually tested | ❌ X1 — the reads are proven; no human has walked the screens |
| 11 | Five external testers complete the flow | ❌ X9 |
| 12 | All critical issues closed | ⚠️ the broker connector pins a vulnerable TLS stack and cannot be raised without X1 — `docs/DEPLOYMENT_READINESS.md` §6 |

**Verdict: NO.** Nine of twelve are open, and most are decisions or
infrastructure rather than code.

---

## LIVE TRADING READY — **FALSE**

Out of scope and deliberately not made easier. The properties that keep it
false, all tested:

- `automation.start` refuses any account that is not demo, and does so twice
  over: the entitlement layer refuses from the stored link record, and the
  resolved connection is checked again. Each is tested with the other
  disabled, so neither can quietly disappear behind the other.
- `entitlement.capability()` refuses a live account under **both**
  entitlements. A paid plan unlocks nothing here, because there is nothing
  behind it to unlock.
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
3. ~~**Owner:** register the production OAuth redirect URI in the cTrader
   portal (X4)~~ — **done.** Configured, and a real authorisation has
   completed through it.
4. ~~**Owner:** provision Redis or Upstash (X2)~~ — **done.** Redis answers
   from production at 7 ms.
5. **Engineering:** deploy to a non-public URL with the runbook's environment.
6. **Together:** work through the nine manual steps on a real demo account.
7. Re-assess this document.

Of items 1–4, **3 and 4 are now done** and verified from the deployed
instance (2026-10-01). What remains on the critical path is item 1, which is a
decision only the owner can make, and item 6 — the manual walk-through, which
needs a browser and a phone and cannot be done from a script.

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
| E | `319f58d0c` | Health endpoints, shared rate-limit counters, beta and licence runbooks |
| F | `8fcefa39b` | free_demo / paid_live entitlement, server-derived execution capability |
| G | `b95dff0e6` | cTrader demo smoke-test harness; Fernet tokens added to log redaction |
| H | `fb064679f` | Repo-wide copy audit with a reasoned allowlist; checkout answers about the product |
| I | `1e428f100` | Final verification and release decisions |
| J | `e057ffb16` | Handoff |
| A–E (25 Sep) | `d8f03196f`…`495fed056` | Critical framework CVEs, per-rule copy exemptions, route audit, AST live invariants, live spec, dependency audits |
| Broker reads | `9c97154` / `759a58f` | First real cTrader broker reads recorded: capability, balance, positions, orders and 199 EURUSD 15m candles |
| Smoke preview fix | `b94fc8a` | The smoke test's preview step can now exercise a real rule on broker candles |
| Release identity | `50eae57` / `65ddd67` | Health responses expose safe release metadata; smoke docs require checking deployed commit before broker tests |
| MT4/MT5 spike | `cdbe833` | MT4 and MT5 read-only cloud provider skeletons, hidden from routes/UI, with provider safety tests |

Tests went from 44 to 175 in the web client and from 153 to 159 files in the
backend. Lint went from 13 errors to 0. Unreadable controls went from 15 to 0.
Mobile destinations went from 1 of 8 to 8 of 8.

---

## The four release decisions, stated plainly

| Decision | Answer | Who can change it |
|---|---|---|
| **Ship a private demo beta now?** | **No.** X1 is part-closed: the reads are proven against a real broker (2026-09-30, account …456), the automation controls and the screens are not | Engineering, by running the eleven-step walk-through in `docs/CTRADER_DEMO_SMOKE_TEST.md` in a browser |
| **Ship a public beta?** | **No.** Nine of twelve public-launch gates are open | Owner, for the decisions; engineering, for X2–X9 |
| **Take money?** | **No.** Checkout is off, no price is approved, and the route refuses | Owner — D1, D2, D3, D5, D6 |
| **Enable live trading?** | **No, and not by a flag.** It is not implemented. `LIVE_TRADING_ENABLED` has no execution path behind it and `/readyz` refuses to start if it is set | A separate milestone with its own review |

None of these is blocked on code that is missing and unwritten. Three are
blocked on the owner, and one on a cTrader demo account.
