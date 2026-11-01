# Apex4Traders status

Kept by the coordinator (Claude Code), who is the only writer of this file, so
two branches never edit it at once. It is a summary: the state of a task is its
issue labels and its latest `HANDOFF` comment (`docs/ORCHESTRATOR_PROTOCOL.md`
section 7). `docs/NEXT_SESSION_HANDOFF.md` stays the platform's narrative.

Team rules and how work is picked up: issue #73 (the protocol wins where they
differ; the owner decided on 2026-11-01 that this file is kept).

Last update: 2026-11-01 (second update). Everything below is what was observed on that date;
"unverified" means nobody looked.

## Running now

| Piece | State |
|---|---|
| API (`apex4traders-api`) | `c1fb8ee` (#66). Redeployed 2026-11-01 14:23 UTC when `A4T_OPERATOR_USER_IDS` was set at the owner's request. `/readyz` 200 |
| Web (`apex4traders-web`) | Last deployed by Claude at `01aaa04` (2026-10-30). Later web changes (#62 guided setup, #64 operator audit page) are deployed: **unverified** |
| Live trading | Closed. `/healthz` reported live execution off on 2026-10-30; no flag was touched since |
| Owner's demo loop (XAUUSD) | Blocked since the trial licence expired on 2026-11-01; the owner is now an operator (licensed, no expiry) and **has to press Start** on Trade. Not verified that it runs |

## Done (merged into `claude/apex4traders-platform-v1`)

- #53 spot-subscribe fix, daily-loss headroom for the minimum lot, pre-Start min-lot warning
- #54, #55 status pills, compact start bar, button and card polish
- #56 first-run checklist, help page, error routes, account export/delete UI, journal CSV
- #57 trial-expiry behaviour proven, Stripe sandbox runbook, owner action list
- #58 operator alerts, structured logs, load-test harness, runtime env check
- #59 Playwright smoke suite, crash/lease recovery tests
- #60 engine: live 1% cap at order time, SL/TP with the order, order line logging, live fail-closed gates
- #61 account export/delete API, auth-flood guard, fail-closed limiter, RLS migration, key rotation
- #62 to #66 guided automation setup, operator audit (API and page), operator licence, honest automation state, weekend idle

## In progress

| Item | State |
|---|---|
| Issue #13 queue how-to | Draft PR #87 from `claude/issue-13-queue-howto`; docs only; `run_all.py` 254/254 |
| Issue #70 erasure coverage | Draft PR #90: Redis-path erasure test and key-kind coverage; `run_all.py` 255/255; CI green. Finding: `billing:review` records are not erased, owner decision in #89 |
| Issue #71 operator list | Draft PR #91: `check_runtime_env.py` row, tests, `OWNER_ACTIONS.md` section D; `run_all.py` 254/254; CI pending |
| PR #15 Codex L1 live ledger | Draft, **do not merge**, now conflicts with the platform branch. Owner decision |
| PR #6, #5 (to `main`) | Owner only; not touched |

## Next (issues; only the owner applies `ready`)

| Issue | Agent | Note |
|---|---|---|
| #69 smoke-test SL/TP with the order on a real demo account | owner places trades | P1: the change is live on the owner's demo and was never seen against cTrader |
| #67 persist the position snapshot before the send | claude | `needs-owner`: order path |
| #68 re-read the lease at send time on live | claude | `needs-owner`: order path |
| #89 decide whether erasure and export cover `billing:review` records | owner, then claude | `needs-owner`: payment records, legal retention |
| #72 tests for orders/live/license pages, menu focus | codex | `ready`; low; Codex starts it manually (protocol section 9) |

Owner backlog (labels `backlog` and `priority:*`, none `ready` yet): P0 #74 npm
advisories in the root app, #75 Stripe webhook secret handling (`needs-owner`),
#76 `/health` returns 404, #77 delete `autoflow-backend.zip`, #78 payment
provider eligibility (`needs-owner`); P1 #79 to #84; P2 #85, #86.

## Owner-only items still open (`docs/OWNER_ACTIONS.md`)

- Run `sql/003_rls_server_tables.sql` in Supabase; set `SUPABASE_SERVICE_ROLE_KEY` on the API
- External uptime monitor on `/healthz` and `/readyz`; `OPS_ALERT_WEBHOOK_URL`
- Google/Apple sign-in providers, SMTP/Resend sender domain
- Stripe test-mode pass (`docs/STRIPE_SANDBOX_RUNBOOK.md`); checkout stays off
- Company, VAT, lawyer, final terms/privacy/refund text, support address (deferred by the owner until the first revenue)

## Rules in force

Branches off `claude/apex4traders-platform-v1`, PRs into it; never `main` or
`claude/arcads-external-api-gExX7`. No secrets, no env var changes, no live
flags, no loosening of `live_gate` or `test_platform_live_invariants.py`, no
edits to `.github/workflows`, `render.yaml` or `server.js`. Merging is the
owner's.
