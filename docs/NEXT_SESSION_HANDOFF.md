# Apex4Traders — handoff

**State at:** `1e428f100` on `claude/apex4traders-platform-v1`
**Date:** 2026-09-23

Read this first, then `docs/RELEASE_READINESS.md`. Everything else is detail.

---

## 1. Where this actually is

A rule-driven trading automation platform, connected to cTrader, that runs on
**demo accounts only**. The software is in good shape. **Nothing has ever run
against a real broker**, and that single fact is the difference between this
and a private beta.

| | |
|---|---|
| Tests | 159 backend files, 175 web tests, build clean, lint 0 errors |
| Private demo beta | **NOT YET** — blocked on X1 |
| Public beta | **NO** |
| Taking money | **NO** — checkout off, no approved price |
| Live trading | **NO**, and not implemented |

## 2. The one thing to do next

**Run `docs/CTRADER_DEMO_SMOKE_TEST.md` against a real cTrader demo
account.** Eleven steps, plus a script that automates the read side of four
of them and refuses to run against anything that is not a demo account.

It closes gates 1, 2 and 12 in `docs/RELEASE_READINESS.md` — the three that
matter most, because they are the product. It also needs a Supabase project
(X3) and a registered OAuth redirect URI (X4), which are configuration rather
than work.

Nothing in the code is known to be missing for those gates. They are
**unproven**, which is a different thing from broken, and must not be
reported as the same thing.

## 3. What is blocked on the owner, not on engineering

| # | Decision | Effect while unanswered |
|---|---|---|
| D1–D3, D5 | Price, currency, SKU, plan shape, tax | Checkout answers 503 |
| D6 | Is paid access part of beta at all? | Choosing "no" removes D1–D3 and D5 from the beta gate entirely |
| L1–L2 | Legal entity, address, company number, governing law | Placeholders in the product |
| L3 | Support contact address | The old one belonged to another brand and was removed, not replaced |
| L4 | Refund policy | The webhook already revokes on refund |
| L6–L8 | Hosting, data region, sub-processors, retention, data-subject rights | Placeholders |

`grep -rn "TO BE CONFIRMED" web/src` shows them in the product.
`docs/LEGAL_LAUNCH_BLOCKERS.md` and `docs/PAYMENT_AND_LICENCE_DECISIONS.md`
have the detail.

## 4. Decisions already taken, that a next session must not undo

**Demo access is free, and it is free in the code.** A client with no licence
record is `free_demo` and can build, activate and run a rule on a demo
account. A licence means `paid_live`. A **revoked** licence still blocks
everything, including demo — that is the one lever support has, and a free
tier that routed around it would be decorative.

**A paid plan unlocks nothing in this release.** `paid_live` + a live account
is refused exactly as `free_demo` + a live account is, because there is no
execution path behind it. All four combinations are tested. If somebody
"fixes" this by relaxing a check, `tests/test_platform_entitlement.py` fails.

**Live trading is refused in three independent places** — the environment
gate, the entitlement layer reading the stored link record, and the resolved
connection's own mode. Each is tested with the other two disabled, because
removing one of them left every test green the first time.

**The server decides what a client may do.** `GET /api/v1/me` carries an
`execution` block. The UI renders it. Do not reassemble that verdict in the
browser from a licence state and an account mode: it is one decision, and a
second implementation of it is one that can disagree with the server that
actually refuses.

**Nothing is invented.** No broker data, no market data, no balances, no
positions, no performance. An empty list is a fact and says so; an
unavailable read says which. `tests/test_product_copy.py` and
`src/app/content.test.ts` enforce the copy side of this.

## 5. Conventions this codebase actually follows

- **Every material change has a test, and the test is mutated to prove it
  fails.** 24 mutations in phases E–H, 24 killed. One survived the first
  round and the test was strengthened rather than the mutation dropped.
- **Refusals carry a code the UI branches on**, never English to match
  against.
- **Transport modules do transport.** `apex/platform/*` is tested with no
  socket anywhere near it; `apex/bot.py` reads a request and writes a reply.
- **Unknown is a third value.** The evaluator's three-valued logic, and
  `account_mode`'s `unknown`, are never folded into `false` or `demo`.
- **Fail closed.** `user_store._is_production()` treats anything
  unrecognised as production.
- **English in the repository**, except `AGENTS.md` and
  `docs/CODEX_REVIEW_A_B_C.md`, which are agent-coordination and historical
  records. `tests/test_product_copy.py` has the full allowlist with reasons.

## 6. Known gaps, stated rather than hidden

| Gap | Where |
|---|---|
| `/readyz` has never answered from a deployed instance | `docs/LAUNCH_QA_REPORT.md` |
| An active rule cannot be edited; editing must create a version | same |
| No volume and no indicator overlay on the chart, both for stated reasons | same, and `docs/CHART_DEPENDENCY_DECISION.md` |
| Several rule fields are recorded but not enforced by the engine | labelled at the input in the rule builder |
| Webhook idempotency is weaker without Redis | `docs/PRODUCTION_RUNBOOK.md` §2 |
| Checkout creation is a Next.js route with no verified session | `web/src/app/api/create-payment-intent/route.ts` — must move behind the platform API before it is ever enabled |

## 7. Hard limits

- **Do not merge to `main`.** It is old and divergent.
- **Do not deploy publicly.**
- **Do not enable live trading**, and do not add a path towards it. It is a
  separate milestone with its own review.
- **Do not put a secret in a commit, a log, a document, a screenshot or a
  test.** `apex/redact.py` masks known shapes on the way out; that is a
  safety net, not the plan.
- **Do not invent broker data**, and do not replace a failed integration with
  a fixture.
- **Do not report something as working that has not been run.** The whole
  point of the release documents is that they distinguish *tested* from
  *unproven*, and one sentence that blurs the two undoes all of it.

## 8. Where things are

```
apex-forex-bot/apex/platform/   the platform: api, entitlement, health,
                                ctrader_link, automation, evaluator, billing,
                                licence, ratelimit, store
apex-forex-bot/scripts/         operational scripts, including the smoke test
apex-forex-bot/tests/           159 files, run with tests/run_all.py
web/src/app/                    Next.js routes; (app)/ is the signed-in shell
web/src/components/app/         shell, tables, rule builder, plain language
web/src/lib/api.ts              the one way the client talks to the backend
docs/                           decisions, runbooks, readiness
```

Read `docs/RELEASE_READINESS.md` for the gates,
`docs/PRODUCTION_RUNBOOK.md` for operating it, `docs/BETA_CONFIGURATION.md`
for standing up a beta, and `docs/CTRADER_DEMO_SMOKE_TEST.md` for the thing
to do next.
