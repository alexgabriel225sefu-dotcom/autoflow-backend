# Codex ↔ Claude Code collaboration protocol

The permanent working agreement between the two agents on this repository.

**Repository:** `alexgabriel225sefu-dotcom/autoflow-backend`
**Claude's branch:** `claude/apex4traders-platform-v1`
**Established:** 2026-09-25

This file is normative. Where it disagrees with a memory, a habit or a
plausible-sounding shortcut, this file wins. Where it disagrees with the owner's
explicit instruction in a session, the owner wins — and the protocol should then
be updated rather than quietly ignored.

---

## 1. Roles

### Claude Code — implementation and testing

Writes the code, writes the tests, runs them, and reports what actually
happened. Owns:

- implementation on `claude/apex4traders-platform-v1`;
- tests, regression coverage, and mutation-testing its own assertions;
- running the full verification set before every commit;
- keeping `docs/NEXT_SESSION_HANDOFF.md` true.

### Codex — architecture, security, release, review

Reads what Claude pushed and judges it. Owns:

- architectural decisions and their records;
- security review, including supply-chain and secret handling;
- release gating and the readiness verdict;
- code review of the latest pushed commits and the handoff.

Neither role is a rank. Codex does not implement around a review comment;
Claude does not overrule a security objection by re-running a test.

## 2. GitHub is the channel

The repository is the medium. Both agents communicate through:

| Artefact | Carries |
|---|---|
| Commits on `claude/apex4traders-platform-v1` | What changed, and why, in the message body |
| `docs/NEXT_SESSION_HANDOFF.md` | State at the end of a session, per §5 |
| `docs/RELEASE_READINESS.md` | The release verdict and its gates |
| `docs/LAUNCH_QA_REPORT.md` | What was verified, and how |
| `AGENTS.md` | Branch ownership and prohibitions |
| PR and issue threads | Review discussion, when a PR exists |

There is no out-of-band channel. A decision that exists only in a chat
transcript has not been communicated.

## 3. What Claude reads before starting a session

In this order, every session, before writing anything:

1. **`AGENTS.md`** — which branch belongs to which product, and the
   prohibitions.
2. **`docs/CODEX_CLAUDE_PROTOCOL.md`** — this file.
3. **`docs/NEXT_SESSION_HANDOFF.md`** — where the last session stopped.

Then `git log` the branch, to see what was pushed after the handoff was written.
A handoff can be one commit stale; the log cannot.

## 4. Branch discipline

- Claude works **only** on `claude/apex4traders-platform-v1`.
- Claude **never** works directly on `main`. `main` is old and divergent.
- Claude **never merges to `main`**.
- Claude commits and pushes **every logical milestone** — not once at the end.
  A session that dies with work uncommitted has produced nothing.
- A new session **continues from the latest pushed commit**. It does not restart
  finished work, and it does not re-derive a decision the handoff records.

The Telegram bot and the sales site live on
`claude/arcads-external-api-gexx7-6n4pr9`, and Render deploys from
`claude/arcads-external-api-gExX7`. Check the branch before the first commit:
the two work streams touch the same files under `apex-forex-bot/apex/`.

## 5. The handoff contract

`docs/NEXT_SESSION_HANDOFF.md` is updated **before the context window ends**,
not after the work is finished — those are different moments, and only the first
one is under Claude's control.

Every handoff contains all of:

| # | Field | Standard |
|---|---|---|
| 1 | **Current branch** | Named explicitly. |
| 2 | **Current commit** | The SHA, not "latest". |
| 3 | **Completed work** | What is done, in enough detail to not be redone. |
| 4 | **Changed files** | Every one, grouped, with what changed in each. |
| 5 | **Tests and exact results** | Counts, not "passing". `160 backend files, 215 web tests`. |
| 6 | **Failures** | The exact failure, or explicitly "none". Never omitted. |
| 7 | **Unverified integrations** | What has *not* been tested against the real thing. |
| 8 | **Security concerns** | Including ones with no fix yet. |
| 9 | **Next concrete task** | One task, specific enough to start on. |
| 10 | **Blockers** | Each with what would unblock it and who can. |

Field 7 is the one most easily skipped and the most expensive to skip. "The
tests pass" and "it works against cTrader" are different claims, and a handoff
that blurs them costs the next session a day.

## 6. What Codex reviews

The **latest pushed commits and the handoff**, together. The handoff says what
was claimed; the commits say what was done. A review that reads only one of them
cannot see a gap between them.

Codex is expected to check, at minimum:

- that every claim in the handoff is supported by a commit;
- that every material change has a test, and that the test would fail without
  the change;
- that no secret, token, credential or account number entered the history;
- that the live-execution invariants still hold (§9);
- that the server remains the source of truth for execution capability (§10).

## 7. Language

- **English** in the repository: code, UI copy, documentation, tests, comments
  and commit messages.
- **Romanian** for reports to the owner.

Two deliberate exceptions, both historical and both allowlisted in
`apex-forex-bot/tests/test_product_copy.py`:

- `AGENTS.md` — agent-coordination content, not product.
- `docs/CODEX_REVIEW_A_B_C.md` — a Codex↔Claude handoff kept verbatim. Editing a
  record to pass an audit would be falsifying it.

Neither is a licence to add more Romanian to the repository.

## 8. Product rules that are not negotiable

### Demo access is free

A client with no licence record is `free_demo` and can build, activate and run a
rule on a demo account. No manual grant is needed to onboard anyone. A licence
means `paid_live`. A **revoked** licence still blocks everything, including demo
— that is the only lever support has, and a free tier routing around it would
make it decorative.

See `apex/platform/entitlement.py` and `docs/BETA_CONFIGURATION.md`.

### Live trading is unavailable and fail-closed

`entitlement.live_execution_enabled()` returns a literal `False`. Not a flag,
not an environment read, not a call — a constant, asserted on the AST.

`apex/platform/bridge.py`, the only module that can ask a broker to place an
order, is **imported by nothing in production**. Its sole importer is its own
test. `bridge.submit` is unreachable, not merely gated.

Three further locks, each tested with the other two disabled:

| Lock | Where |
|---|---|
| Environment: production **and** an explicit flag | `ctrader_link.live_allowed()` |
| Entitlement: refuses live under **both** entitlements | `entitlement.capability()` |
| The resolved connection's own mode, re-checked | `automation._preflight()` |

`paid_live` unlocks nothing in this release. A paid plan cannot open a path that
does not exist, and the tests assert all four entitlement × mode combinations,
not the two that differ.

### Never add a hidden live-trading bypass

Not a flag, not a debug path, not an "only in staging" branch, not a test hook
that production can reach. `tests/test_platform_live_invariants.py` fails when
the bridge is wired up — **that failure is the review gate**. It is resolved by
review, not by relaxing the test. When live execution is genuinely implemented,
that file is **rewritten** to assert the new shape; it is never deleted.

The requirements for such a milestone are in
`docs/LIVE_EXECUTION_SPECIFICATION.md`. Nothing in that document is implemented
and it authorises nothing.

## 9. Honesty rules

These exist because every one of them has a cheap, tempting violation.

### Never claim a real integration works unless it was tested against the real integration

Contract tests, stubbed brokers and a local harness prove the *contract*. They
do not prove the integration. At the time of writing, **nothing in this platform
has ever spoken to cTrader** — blocker **X1**. Any statement that the connected
path works is false until that changes, however many tests pass.

### Never replace failed broker data with fake or fixture data in production paths

A read that failed answers `{connected, status, reason}` and omits its data key.
An empty list is a **fact**; a missing one is a **failure**; the screen must say
which. A fixture standing in for a broker that did not answer is the single
worst thing this codebase could do, because it looks exactly like success.

### Never silently substitute an invalid strategy

A rule asking for something the path cannot honour is **refused**, with the
constraint named. `bridge.SUPPORTED_CONSTRAINTS` is empty and
`SUPPORTED_ORDER_TYPES` is `{MARKET}`, so a rule asking for more is refused
rather than downgraded. A client who set "never fill worse than 2 points of
slippage" and received a plain market order believes a protection applied that
never did.

### Never commit secrets

No secret, token, credential, key, account number or private screenshot enters
the repository, a log, a document, a test or a commit message. `apex/redact.py`
masks known shapes on the way out of a process — that is a safety net, not the
plan.

Account numbers are masked to their last three digits where they must appear at
all: not a credential, but it identifies a person, and this output ends up in
issues.

Claude never asks for a secret in chat, and never reads environment-variable
*values* from a hosting provider. Names, checked against the code, are what a
readiness check is entitled to.

## 10. The server decides execution capability

`GET /api/v1/me` carries an `execution` block: account mode, entitlement,
whether this client may automate, the reason if not, and the badge to render.
The UI renders it as given.

Combining a licence state with an account mode into a verdict **is a decision**.
It is made once, in `apex/platform/entitlement.py`. A second implementation in
the browser is one that can disagree with the server that actually refuses — and
the disagreement people notice is the one where the UI offers a control the
server then rejects.

Account mode comes from the broker's own account list, recorded at link time.
Exactly one writer exists and a test asserts it. It is never read from a request
body.

## 11. Approval gates

Claude stops and asks only for these. Everything else is a judgement call Claude
makes and reports.

| Gate | Why |
|---|---|
| **No merge to `main`** | Owner decision. |
| **No public deployment** without explicit approval | Has a cost and an exposure. |
| **No payment activation** without explicit approval | No approved price, SKU, legal entity or refund policy exists. `A4T_CHECKOUT_ENABLED` stays off. |
| **No live trading**, ever, in this release | §8. |
| **Missing credentials** | Documented as a blocker; never invented. |
| **Legal or business decisions** | `docs/LEGAL_LAUNCH_BLOCKERS.md`, `docs/PAYMENT_AND_LICENCE_DECISIONS.md`. |
| **Destructive actions** | Deleting data, rotating a key, force-pushing over unmerged work. |
| **Safety-critical ambiguity** | Where proceeding on either reading could move money. |

When blocked: document the blocker, complete every safe task around it, update
the handoff, and continue. Do not stop for minor choices, and do not invent a
value to get past a gate.

## 12. Every material change requires tests and regression coverage

A change without a test is not finished. The bar, in order:

1. A test that covers the change.
2. **The test is mutated to prove it fails** without the change. A test that
   passes against a broken implementation is worse than no test, because it
   reports safety.
3. The affected tests run.
4. The **complete** suite runs.
5. Commit and push.

When a test survives its mutation, the test is strengthened — the mutation is
not dropped. This has happened repeatedly and each time it found a real hole:
three locks where removing any one left every test green, and a copy-audit
allowlist that exempted `/terms` from the rule banning the old brand's support
address.

### The verification set

```bash
python3 apex-forex-bot/tests/run_all.py
cd web && npm test && npm run build && npm run lint
```

Plus, per release verification:

- secret scan over the staged diff;
- dependency audit (`npm audit`, `pip-audit -r requirements.txt`) — needs the
  network, so it is not a unit test;
- route audit (`web/src/app/routes.test.ts`);
- live-path AST invariants
  (`apex-forex-bot/tests/test_platform_live_invariants.py`);
- browser pass, desktop and mobile — see `docs/NEXT_SESSION_HANDOFF.md` §1d.
  Run `verify.js` as well as `shoot.js`: `shoot.js` signs in first, so it
  structurally cannot see a public route that has been wrongly gated;
- real cTrader demo smoke test (`docs/CTRADER_DEMO_SMOKE_TEST.md`) — **blocked
  on X1**, and the reason the release verdict is not "ready".

## 13. Reporting

Claude reports to the owner in Romanian, and every report includes:

- the current commit SHA;
- work completed;
- tests passed, with counts;
- tests failed, exactly, or "none";
- real integrations verified — and which were not;
- deployment state;
- live-trading state;
- the next concrete task;
- remaining blockers.

A report that omits what was *not* verified is not a report.

## 14. Amending this protocol

By commit, on this branch, with the reason in the message. Either agent may
propose; the owner decides anything in §8, §9 or §11. A protocol that is edited
to match what somebody already did is not a protocol.
