# Orchestrator Phase 1: repository audit

Read-only audit done before proposing any branch protection or automation.
Everything here was observed on 2026-10-23 unless marked **not verified**.
Nothing in this document has been applied.

## 1. Repository facts

| Fact | Observed |
|---|---|
| Visibility | **Public** |
| Default branch | `main` (stale: `claude/apex4traders-platform-v1` is 593 commits ahead; `AGENTS.md` itself is not on `main`) |
| Branch protection | **None** on `main`, `claude/apex4traders-platform-v1`, `claude/arcads-external-api-gExX7`, `claude/arcads-external-api-gexx7-6n4pr9` (API answers "Branch not protected") |
| Rulesets | None |
| Auto-merge | Disabled at repository level (good; keep it so) |
| Merge methods allowed | Squash and merge commit |
| Open PRs | #5 (`claude/arcads-external-api-gExX7` into `main`), #6 (`claude/apex4traders-platform-v1` into `main`, stale title) |
| Open issues | 0 before this work |
| Session token permissions | admin / maintain / push / triage (creating labels worked) |

Consequences: nothing today stops a force-push to a deploy branch, and because
the repository is public every issue and comment is untrusted input
(`docs/ORCHESTRATOR_PROTOCOL.md` §5).

## 2. Branch roles

| Branch | Role | Deploys? |
|---|---|---|
| `claude/apex4traders-platform-v1` | Platform + web development; Render services `apex4traders-api` and `apex4traders-web` track it | **Manual only** (both services: `autoDeploy: no`, trigger off) |
| `claude/arcads-external-api-gexx7-6n4pr9` | Telegram bot + sales site development | No |
| `claude/arcads-external-api-gExX7` | Render deploy branch for the sales site / bot | **Yes: `AGENTS.md` says every commit deploys.** `render.yaml` declares `autoDeploy: true` for `autoflow-backend`. The live service's setting was **not verified** here |
| `main` | Default branch, old, divergent | Only `docker-publish.yml` runs on a push to it |
| `codex/*` | Codex working branches | No |

The platform's production is deployed by the owner's explicit trigger, from
`claude/apex4traders-platform-v1`. A PR into that branch therefore cannot reach
production on its own.

## 3. Workflow audit

Eleven workflow files exist on the platform branch. GitHub also lists
`deploy-bot.yml` and `deploy-forex-bot.yml` (present on `main`),
`deploy-ref-bot.yml` (source **not read**), and `deploy-affiliate-bot.yml`
(disabled).

| Workflow | Triggers | Secrets / write | Notes |
|---|---|---|---|
| `tests.yml` | push + PR on the two **arcads** branches; manual | none; `contents: read` | See §4 |
| `production-health.yml` | hourly cron; manual | none; read-only | Unauthenticated GETs against the Render URLs |
| `backtest.yml` | manual; push to `gExX7` on two paths | `TWELVE_DATA_KEY` | |
| `tuning.yml` | manual; push to `gExX7` on its own path | `TWELVE_DATA_KEY` | |
| `docker-publish.yml` | manual; push to `main` or `gExX7` under `apex-forex-bot/**` | `packages: write` (GHCR) | Publishes images on a push |
| `railway-create-template.yml`, `railway-diagnose.yml`, `railway-inspect.yml`, `railway-template.yml` | manual; push to `gExX7` on their own paths | `RAILWAY_TOKEN`; `railway-template.yml` has `contents: write` | Legacy Railway path. Bodies **not read** |
| `check-forex-logs.yml` | manual (`vm_ip` input) | `ORACLE_SSH_KEY` | Reads logs over SSH |
| `deploy-bot.yml`, `deploy-forex-bot.yml` (on `main`) | manual (`vm_ip` input) | `ORACLE_SSH_KEY` | Check out `gExX7`, SSH to an Oracle VM. First 40 lines read only |
| `deploy-web.yml` | manual | none | Named "Deploy Web to Vercel" but only echoes; Render does the deploy |

Findings:

1. **No workflow deploys the platform.** Render is triggered from the dashboard
   or API by the owner.
2. **Workflows that hold secrets run when `gExX7` changes** (and, for some, when
   specific paths change). A queue task that edits `.github/workflows/**` or the
   `scripts/railway-*.js` files, or that pushes to `gExX7`, touches that boundary.
   The protocol forbids both for queue tasks.
3. `pull_request` runs from forks get no secrets, which is why `tests.yml` can
   safely run on any PR.

## 4. `tests.yml` audit

It is a sound workflow that does not cover the platform.

| Issue | Detail | Effect |
|---|---|---|
| Wrong branches | Triggers only on the two `arcads` branches | **No CI on `claude/apex4traders-platform-v1`**, on `claude/issue-*`/`codex/issue-*` branches, or on a PR into `main`. A PR into the platform branch gets no check |
| No web job | No `npm test`, `tsc`, lint or `next build` for `web/` | The 687 web tests are never run by CI |
| Stale labels | Job names say "61 security tests" and "98 test files"; there are now 213 Python test files | Misleading, and brittle as required-check names |
| Different runner | CI runs `python -m pytest -q`; `AGENTS.md` and the protocol mandate `apex-forex-bot/tests/run_all.py` | Equivalence of the two was **not verified** |
| Good | `contents: read`, no secrets, 10/25 minute timeouts, config-drift check | Keep |

Consequence for the queue: until `tests.yml` is extended, **CI green means
nothing for platform work**. This must be fixed before any required status check
is configured, otherwise a required check that never runs would block every PR.

## 5. Proposed branch protection (NOT applied)

Order matters: workflow first, protection second.

| Step | Change | Who |
|---|---|---|
| 1 | Extend `tests.yml`: add `claude/apex4traders-platform-v1` to push/PR; add `pull_request` for `claude/issue-*` and `codex/issue-*` targeting it; add a `web` job (`npm ci`, `npm test`, `npx tsc --noEmit`, `npm run build`); rename jobs to stable names (`node`, `python`, `web`, `config-drift`). Confirm `pytest` collects what `run_all.py` runs | PR, owner merges |
| 2 | `claude/apex4traders-platform-v1`: block force-push and deletion; require the `python` and `web` status checks **on pull requests only**. Do **not** require a PR for direct pushes yet: interactive sessions still push to it | owner, repository settings |
| 3 | `claude/arcads-external-api-gExX7`: block force-push and deletion; require `python` + `node`. It deploys on every push, so it is the most valuable branch to protect | owner |
| 4 | `main`: block force-push and deletion; require a PR. It is stale, so this is hygiene rather than safety | owner |
| 5 | Keep repository auto-merge **disabled**; keep "require approval" for the owner on money-path PRs (CODEOWNERS is an option; not created) | owner |

Not proposed: required reviewers (a single-owner repository cannot satisfy
two-reviewer rules), and signed-commit enforcement (agents do not hold keys).

## 6. Do the intended issue-label triggers work?

| Trigger | Finding |
|---|---|
| GitHub Actions `issues: labeled` | GitHub supports the event, but a workflow for an `issues` event is read from the **default branch**. That is `main`, where the owner has ruled that nothing is merged. An Actions-based label trigger would need its workflow file on `main`. From GitHub's documented behaviour; the page was **not re-fetched** in this session |
| Claude scheduled task, GitHub trigger | The official page (fetched this session) lists only **pull request** and **release** events. Issue events and issue label filters are **not documented**. A public bug report claims an "Issue opened" trigger exists in the UI and does not fire for issues created by a routine. **Not verifiable from this session**: it needs a look at the claude.ai scheduled-task UI |
| Codex | The GitHub integration documents `@codex review` and other `@codex` comments **on pull requests** only. Issue, assignment and label triggers are not documented |

Conclusion: a **label-driven event trigger is not supported by any documented
path** today. The workable design is **polling**: a scheduled task reads
`ready` issues. That is what the protocol assumes.

## 7. Permissions and subscription limits

| Item | Finding |
|---|---|
| Repository access from this session | Read/write via the session's GitHub proxy; labels created |
| GitHub Actions settings, secrets, workflow permissions | **Blocked by the proxy** ("not permitted"). Not readable here |
| Claude GitHub App installed on the repository | **Not verifiable** (the installation endpoint answered 401). Owner: `github.com/settings/installations` |
| Branch protection writes | Not attempted |
| Claude scheduled tasks | Draw from subscription usage. At the limit, runs are rejected until the window resets; "usage credits" overage is metered (**costs money, must stay off**). Hourly caps: 100 scheduled runs per account; GitHub events beyond the cap are dropped. No automatic retry after a rejection is documented. Source: `code.claude.com/docs/en/routines` |
| Codex | Local messages and cloud tasks share one plan allowance (five-hour window plus weekly limits). Subscription authentication for `codex exec` in GitHub Actions is **not documented**; API keys are the documented CI path and cost money. Whether the owner's plan includes Codex scheduled tasks or GitHub triggers is **unknown** |

## 8. Codex integration status

**Not integrated, not tested.** No Codex cloud task has run against this
repository. Codex has pushed branches manually (`codex/*`), driven by the owner
copying briefs. Do not describe Codex as integrated until Phase 2 step 5 below
has produced a real cloud task result.

## 9. Phase 2 (needs the owner's explicit approval)

1. Owner checks the Claude GitHub App installation and the scheduled-task UI for
   an issue trigger (§6, §7).
2. PR: extend `tests.yml` (§4, §5 step 1).
3. Owner applies branch protection (§5 steps 2-4).
4. Owner opens one low-risk test issue, labels it `ready` + `apex-claude`; one
   manual dry run of the polling procedure from an interactive session.
5. Owner comments `@codex review` on a PR, then starts one `@codex` cloud task;
   record the real outcome here.
6. Only then: create the polling scheduled task (hourly, read-only first).
