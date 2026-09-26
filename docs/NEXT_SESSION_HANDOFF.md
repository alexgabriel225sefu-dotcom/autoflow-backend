# Apex4Traders — handoff

**State at:** `6f35dcd7f` on `claude/apex4traders-platform-v1`
**Date:** 2026-09-26

Read **`docs/CODEX_CLAUDE_PROTOCOL.md`** first — it is the normative working
agreement and it defines the contract this document has to satisfy. Then this
file, then `docs/RELEASE_READINESS.md`. Everything else is detail.

---

## 1. Where this actually is

A rule-driven trading automation platform, connected to cTrader, that runs on
**demo accounts only**. The software is in good shape. **Nothing has ever run
against a real broker**, and that single fact is the difference between this
and a private beta.

| | |
|---|---|
| Tests | 160 backend files, 215 web tests, build clean, lint 0 errors, 0 npm vulnerabilities |
| Private demo beta | **NOT YET** — blocked on X1 |
| Public beta | **NO** |
| Taking money | **NO** — checkout off, no approved price |
| Live trading | **NO**, and not implemented |

## 1b. What phases A–E of 2026-09-25 changed

Four audits were run that had never been run. Each found something real.

| Audit | Finding |
|---|---|
| `npm audit` | **1 critical + 5 high.** Two unauthenticated RCEs in `next`, plus a middleware/proxy bypass — and this app enforces auth in middleware, so that one was an authentication bypass here. Fixed: next 16.2.7 → 16.3.6, now 0 vulnerabilities. |
| Route audit | **`/configurator` was gated.** It is the previous checkout's return URL, kept so an old receipt does not 404, and it was redirecting those visitors to a login page for an account they do not have. Fixed. |
| Copy-audit self-audit | **The allowlist was a hole 25 files wide.** Per-file exemptions meant `/terms` was exempt from the rule banning the old brand's support address. 14 of 25 entries needed no exemption at all. Restructured to per-rule. |
| `pip-audit` | Advisories in `cryptography`, `protobuf`, `pyOpenSSL`, `Twisted` — **all hard-pinned by `ctrader-open-api==0.9.2`**, whose newest release is 0.9.2 (0.9.3 was yanked). Not bumped, and the reason is in `docs/DEPLOYMENT_READINESS.md` §6. |

And the deployment picture was read from the live Render account for the first
time. **There is no service for this platform.** See §1c.

## 1c. Deployment: nothing on this branch is deployed

Three Render services exist; all three deploy `claude/arcads-external-api-gExX7`
and none has `web/` as its root directory. So no commit on this branch reaches
any URL — including the Fernet-token masking in `apex/redact.py`, which
protects the **legacy bot's** logs and is not live because it is on the wrong
branch for the service that runs that bot.

`docs/DEPLOYMENT_READINESS.md` has the full picture: what two services would be
needed, every variable as a name and a placeholder, and the fact that the health
check path is empty on all three existing services so Render has no signal to
restart on.

No service was created or changed. That is an owner decision with a cost.

## 1d. How to re-run the browser pass

The audit harness lives in the scratchpad, not the repository, and it survives
between sessions in this container:

```
scratchpad/audit/serve.py    real apex.platform.api.handle() + a GoTrue stand-in, port 3001
scratchpad/audit/shoot.js    21 routes at 1440x900, 7 at 390x844
scratchpad/audit/verify.js   signed-OUT public/protected classification
```

```bash
export AUDIT_DATA_DIR=<scratchpad>/audit/data
cd <scratchpad>/audit && python3 serve.py &          # 3001
cd web && NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:3001 \
  NEXT_PUBLIC_SUPABASE_ANON_KEY=audit-anon-key \
  NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:3001 \
  npm run build && PORT=3000 npm run start &
cd <scratchpad>/audit && node shoot.js && node verify.js
```

Chromium is at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`. Do **not**
run `playwright install`. Run `verify.js` too, not only `shoot.js`: `shoot.js`
signs in first, so it cannot see a public route that has been wrongly gated —
which is exactly the bug that was found.

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

## 5b. Live execution: the claim is now structural

`docs/LIVE_EXECUTION_SPECIFICATION.md` is what a live milestone must contain
before one real order is placed. Nothing in it is implemented and it authorises
nothing.

The central fact is stronger than "live trading is disabled":
`apex/platform/bridge.py`, the only module that can ask a broker to place an
order, **is imported by nothing in production** — its sole importer is its own
test. `bridge.submit` is unreachable, not gated.

`tests/test_platform_live_invariants.py` proves that on the AST, including the
transitive import closure of `automation`, the API and `preview`. It also
asserts `live_execution_enabled` returns a literal `False` with no name
referenced and nothing called, so it cannot quietly become configurable.

**When somebody wires the bridge up, that test fails. The failure is the review
gate — do not resolve it by relaxing the test.** The specification says the
file must be rewritten by that milestone, not deleted.

## 6. Known gaps, stated rather than hidden

| Gap | Where |
|---|---|
| `/readyz` has never answered from a deployed instance | `docs/LAUNCH_QA_REPORT.md` |
| An active rule cannot be edited; editing must create a version | same |
| No volume and no indicator overlay on the chart, both for stated reasons | same, and `docs/CHART_DEPENDENCY_DECISION.md` |
| Several rule fields are recorded but not enforced by the engine | labelled at the input in the rule builder |
| Webhook idempotency is weaker without Redis | `docs/PRODUCTION_RUNBOOK.md` §2 |
| Checkout creation is a Next.js route with no verified session | `web/src/app/api/create-payment-intent/route.ts` — must move behind the platform API before it is ever enabled |
| The broker connector pins a vulnerable TLS stack and cannot be raised | `docs/DEPLOYMENT_READINESS.md` §6 — needs X1 to verify any override |
| A POST to an `/api/` route without a session gets a 307 to `/login`, not JSON | The middleware matcher covers `/api/*`. Harmless while checkout is off; wrong contract if it is ever enabled |
| Nothing on this branch is deployed | §1c |

## 6b. Security concern with no fix yet: identifiers in the legacy bot

A tree-wide scan on 2026-09-26 found the owner's own cTrader account number
(`47765456`) and Telegram chat ids in tracked files. Protocol §9 forbids
committing account numbers, so this is recorded rather than passed over.

| File | What |
|---|---|
| `apex-forex-bot/apex/account_mode.py` | account number in a doc comment |
| `apex-forex-bot/apex/user_loop.py` | same |
| `apex-forex-bot/apex/copilot.py` | chat id in a doc comment |
| `apex-forex-bot/scripts/backfill_trades.py` | chat id in a usage example |
| `apex-forex-bot/scripts/mark_journal_artefacts.py` | chat id in a docstring |
| `apex-forex-bot/tests/test_access_gates_loop.py` | both ids as test fixtures |
| `HANDOFF.md` (root) | chat id in prose |

**Scope:** all of these are in the **legacy Telegram bot**, added between
2026-08-15 and 2026-09-03. The platform is clean — zero occurrences in
`apex-forex-bot/apex/platform/` or `web/src/`, asserted by scan.

**Not acted on, deliberately.** They are the owner's own identifiers rather
than a third party's; several are load-bearing test fixtures for the other
product; and purging them from history is a destructive rewrite that needs
approval. Changing another work stream's tests from this branch would also
conflict with whoever is working on it.

**For Codex to rule on:** whether these are acceptable (the owner's own ids, in
a private repository) or whether the bot's files should be scrubbed on its own
branch. If scrubbed, the test fixtures need synthetic ids and the history
question is separate from the working-tree question.

The secret scan itself was clean: the four pattern matches were documentation
showing regexes (`AKIA[0-9A-Z]{16}`, a Kubernetes `-----BEGIN PRIVATE KEY-----`
example, a PGP regex in an agent definition), none of them a real credential,
and none in the product.

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
