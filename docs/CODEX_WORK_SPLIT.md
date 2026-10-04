# Work split to finish the platform

**Set by the owner on 2026-10-04.** He asked for the remaining work to be split
roughly in half between Codex and Claude, so that it finishes faster.

This **changes Codex's role**. `docs/CODEX_CLAUDE_PROTOCOL.md` §1 says Codex
reviews and does not implement. The protocol's own rule is that the owner wins
and the protocol is then updated rather than quietly ignored — §1 has been
amended, and this file is the standing work split it points at.

---

## The seam, so the two halves never touch the same file

| | Codex | Claude |
|---|---|---|
| Owns | `apex-forex-bot/**`, `web/src/middleware.ts`, `web/src/app/api/**`, infra | the rest of `web/src/**` |
| Proves by | tests, and a run against the real broker where it applies | a browser, at 1440px and 390px |
| Branch | its own, merged into `claude/apex4traders-platform-v1` by PR | `claude/apex4traders-platform-v1` |

Every task below names the files it touches. If a task needs a file on the
other side of the seam, say so in the PR rather than reaching across.

---

## Where the platform actually is

Read `docs/RELEASE_READINESS.md` for the gates — it is the authority and the
rest of this file does not restate it. In one paragraph: against a real cTrader
demo account the reads, preview on real bars and the automation controls are
all proven (2026-10-02, 16/16). The screens were walked in a browser on
2026-10-04 and three defects were found and fixed. Private demo beta is not
ready, and what is left is mostly **not** the trading engine.

---

# CODEX — six tasks

Ordered by what blocks a launch, not by size. C1 and C2 are the two that would
be embarrassing to ship; C4 is the one that is a risk control in name only.

## C1 — `PUT rules/{id}` silently destroys fields the body omits

**Files:** `apex-forex-bot/apex/platform/store.py` (`save_draft`),
`apex-forex-bot/apex/platform/api.py` (the `_RULE_RE` PUT branch), tests.

`save_draft` writes `dict(doc)` and pins only `userId`, `ruleDocId`, `state`
and `updatedAt`. Everything else is taken from the request body verbatim, so a
client that omits a field **deletes** it.

Reproduced on 2026-10-04 against a local instance of the real API:

```
POST   rules            -> ruleDocId, version 1, state draft
PUT    rules/{id}       -> body without "version"
POST   rules/{id}/activate
       {"ok": false, "code": "RULE_INVALID",
        "problems": ["version: must be an integer >= 1"]}
```

The rule is then stuck: it cannot be activated, and the field that would fix it
is not one any client knows it has to send.

Nothing in `web/src` issues a PUT today, so no user reaches this. That is the
reason it is C1 and not an emergency, and also the reason it has survived.

**Decide which contract this endpoint has** and make it that one:
either a merge over the stored document, or a whole-document replace that
validates completeness and **refuses** rather than dropping. Either is
defensible; silently dropping is not. Whichever you pick, `createdAt`,
`activatedAt` and `version` must not be loseable by omission.

**Done when:** a test asserts that a PUT omitting `version` either preserves it
or is refused, and that the rule is still activatable afterwards. Mutation-check
it — restore the old `dict(doc)` and the test must fail.

## C2 — checkout creation does not go through the platform API

**Files:** `web/src/app/api/create-payment-intent/route.ts`,
`apex-forex-bot/apex/platform/api.py` (`billing/checkout`),
`apex-forex-bot/apex/platform/billing.py`.

A Next.js route creates a payment intent with **no verified session**.
`docs/RELEASE_READINESS.md` already records that it "must move behind the
platform API before it is ever enabled". It is harmless today only because
`A4T_CHECKOUT_ENABLED` is off — which means the protection is a flag, not a
design.

`billing/checkout` on the platform API already authenticates with
`fresh=True` and currently answers `501 CHECKOUT_NOT_IMPLEMENTED`. That is the
right place for this.

**This is an architecture call, which is why it is yours.** Decide whether the
Next.js route is deleted outright or becomes a thin proxy that forwards the
bearer token, and write the decision down as an ADR before the code.

**Do not enable checkout.** The owner has not asked for it and D5 (tax) is
open. The deliverable is that when it *is* enabled, it is enabled on a path
that checks who is asking.

**Done when:** no unauthenticated path can create a payment intent, asserted by
a test, and the ADR records why the chosen shape was chosen.

## C3 — an unauthenticated POST to `/api/*` answers with HTML, not JSON

**Files:** `web/src/middleware.ts`.

The matcher is
`/((?!_next/static|_next/image|favicon.ico|.*\.(?:svg|png|jpg|webp)$).*)`,
so it covers `/api/*`. A POST without a session gets a **307 to `/login`**.
A browser follows it and the caller parses a login page as JSON.

Harmless while checkout is off, wrong the moment any API route is called by
something that is not a page. Ships with C2 because it is the same subject.

**Done when:** an unauthenticated API request gets a JSON body with a status
code, and page requests still redirect as they do now. Both asserted.

## C4 — rule fields that are recorded but not enforced

**Files:** `apex-forex-bot/apex/platform/ruledoc.py`,
`apex-forex-bot/apex/platform/evaluator.py`,
`apex-forex-bot/apex/platform/execution.py`, tests.

`docs/NEXT_SESSION_HANDOFF.md` lists this as a known gap: "several rule fields
are recorded but not enforced by the engine", and the UI labels them at the
input. A label is an apology, not a control.

The fields to check include at least `limits.maxSpreadPips`,
`limits.maxDailyTrades`, `limits.maxExposurePercent`, `order.expiresAfterSec`,
`order.maxSlippagePoints`, `schedule.*`, `trailingStop`, `breakEven` — verify
the real list rather than trusting this one.

**First produce the list**: for each field, does the engine read it, and where?
Put it in `docs/` as a table. That table is the deliverable even if nothing is
implemented in the same pass, because right now nobody can answer the question.

**Then, for each field the engine ignores**, pick one and say which:
enforce it, or make `activate` **refuse** a rule that sets it. Not a third
option. A client who sets a maximum spread and gets trades at any spread has a
risk control that does not exist, and this product sells risk controls.

**Done when:** the table exists, and every field in it is either enforced with
a test or refused at activation with a test.

## C5 — nothing watches the health endpoints

**Files:** infra, plus `docs/PRODUCTION_RUNBOOK.md`.

Gate X7. `/healthz` and `/readyz` exist, are tested, and answer from the
deployed instance. Nothing scrapes them, so the first notice of an outage is a
customer.

Both carry `release.commit`, so a check can also catch a deploy that did not
take. `/readyz` returns per-check detail — alert on the check that failed, not
on "readyz is red".

**Done when:** an external check polls both services, alerts somewhere the
owner actually reads, and the runbook says what each alert means and what to do
about it. State in the PR what you used and what it costs — the owner's budget
for the whole launch is 200–300 EUR, so a free tier is a requirement, not a
preference.

## C6 — re-assess the pinned TLS stack

**Files:** `docs/DEPLOYMENT_READINESS.md` §6.

The broker connector pins a vulnerable TLS stack and the note says it cannot be
raised without X1. The broker half of X1 is now closed — the reads, preview and
the controls have all run against the real account. So the blocker on
re-assessing it has gone.

`ctrader-open-api` was dropped as a dependency and the generated `_pb2` stubs
were vendored into `apex/ctrader_proto/`, which freed four pins. Check whether
the remaining pin is still real.

**Done when:** `pip-audit` output is recorded with a verdict — raised, or
still pinned with the reason stated in a sentence an owner can act on.

---

# CLAUDE — the other half

Recorded here so the split is visible from one file, and so neither of us
starts the other's work.

- **M1. The screens with a connected account.** The 2026-10-04 walk-through ran
  with no broker connected, so every screen was in its not-connected state.
  Nobody has seen the chart with real bars (gate 12), a populated positions
  table, or a DEMO badge on a selected account. Needs a browser and a connected
  demo account.
- **M2. Rule versioning in the UI.** `POST rules/{id}/version` exists, is
  tested, and **nothing in `web/src` calls it** — while `rules/[id]/page.tsx`
  tells the reader that "editing it creates a new version as a draft". The page
  promises something it does not offer. Server side is done; this is UI.
- **M3. Waitlist email.** `waitlist.py` says plainly that it sends nothing and
  that claiming otherwise would be a falsehood. The landing page promises "one
  email when access opens". Today that promise cannot be kept.
- **M4.** Keep `docs/NEXT_SESSION_HANDOFF.md` and `docs/RELEASE_READINESS.md`
  true, which on 2026-10-04 they were not.

---

# Still only the owner

Neither agent can close these, and three of them gate a paid launch:

| # | What | Blocks |
|---|---|---|
| D5 | Tax handling | checkout |
| D6 | Is paid access part of the beta at all | the paid unlock |
| L1–L4, L6–L8 | Entity, address, governing law, support address, refund policy, hosting, data region, retention, data-subject rights | every `[TO BE CONFIRMED]` in the product |
| X3 | Production Supabase project | beta |
| X6 | Domain and HTTPS | public launch |
| X9 | Five external testers | public launch |

`grep -rn "TO BE CONFIRMED" web/src` shows the legal ones where a visitor sees
them.

---

# Rules that do not change

From `docs/CODEX_CLAUDE_PROTOCOL.md` and the owner's standing instructions.
The split moves who writes code; it moves none of this.

- **No live trading**, and no path towards it. Separate milestone, own review.
- **Checkout stays off** unless the owner asks for it.
- **No secret** in a commit, a log, a document, a screenshot or a test.
- **No invented broker data**, and no fixture standing in for a failed
  integration.
- **Nothing reported as working that has not been run.** Unproven and broken
  are different words and the release documents depend on the difference.
- Code, commits, documentation and product copy in **English**.
- Do not touch the legacy Telegram bot.
