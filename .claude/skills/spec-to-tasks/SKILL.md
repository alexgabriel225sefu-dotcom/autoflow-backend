---
name: spec-to-tasks
description: Before coding a non-trivial feature, write a short PRD, an architecture/design note, and a task breakdown, then wait for approval. Use when the user asks to plan a feature, write a spec, break work into tasks, or start something larger than a tight bugfix.
---

# Spec → architecture → tasks

Planning structure inspired by MetaGPT's PRD and design-doc flow (MIT, Copyright (c) 2024 Chenglin Wu). This skill is an original, compact rewrite. It does not run MetaGPT.

Use this **before writing product code** when the work is a feature, a migration, a new API, or anything that would touch several files. Skip it for a typo, a one-line guard, or a bug that `fix-a-bug` can handle.

## Apex safety (mandatory)

- Never edit `.github/workflows`, `render.yaml`, `live_gate`, or `test_platform_live_invariants.py`.
- If the design would require changing those files, or enabling live trading, say so in **Unclear / blocked** and stop. Do not propose enabling live trading or placing real orders.
- Never put secrets in the spec.
- For large work: deliver the three documents, then **wait for approval** before coding. Show a UI mockup if the change is user-visible.
- Marketing or user-facing copy in the spec must not include profit claims, fake discounts, or Telegram.

## Where to write

Create a working folder the user can keep or discard, for example `docs/plans/<feature-slug>/` or `.plans/<feature-slug>/` if the repo already uses one of those. Do not invent a new docs system if one exists. Do not commit until the user wants that.

Files:

- `prd.md`
- `design.md`
- `tasks.md`

## 1. Product requirements (`prd.md`)

Keep it short enough to read in a few minutes.

- **Original request** — the user's words, unchanged.
- **Goals** — up to three orthogonal goals.
- **Non-goals** — what this change will not do.
- **User stories** — 3 to 5, scenario-based ("As a … I want … so that …").
- **Requirements** — a numbered pool, each with priority `P0` / `P1` / `P2` and a one-line acceptance check.
- **Copy and compliance** — any user-visible text, pricing ($497 licence, 30% affiliate if relevant), demo vs live, disclaimers.
- **Unclear** — questions that would change the design. If a P0 is unclear, stop and ask; do not invent the answer.

Skip competitive analysis unless the user asked for it.

## 2. Design (`design.md`)

- **Approach** — how you will do it in *this* repo, and the hard points (auth, billing, broker, data). Name existing modules you will reuse.
- **Files to touch** — relative paths, including tests. Call out anything you will *not* touch (protected files).
- **Interfaces** — types, routes, events, or tables. Prefer a small mermaid `classDiagram` or a TypeScript/Python signature block over prose.
- **Call flow** — mermaid `sequenceDiagram` for the main success path and one failure path (rejected webhook, unauthorized tenant, risk-limit hit).
- **Data and migrations** — what is stored, backward compatibility, how to roll back.
- **Risks** — live-trading leakage, RLS, Stripe idempotency, secret handling, load. Mitigations that are part of this work, not "later."
- **Test plan** — unit / integration / UI, all demo-safe.
- **Unclear** — remaining questions.

If you cannot design it without editing a protected file or enabling live trading, stop here.

## 3. Tasks (`tasks.md`)

An ordered checklist. Each task is small enough to finish in one sitting:

- ID, title, depends-on
- Where (paths)
- Done when (a test or a visible check)
- Notes (demo only, needs approval, etc.)

Put foundation work first (types, fixtures, failing tests), then implementation, then verification. Do not start task 1 until the user approves the plan for large changes.

## After approval

Implement in task order. Prefer `fix-a-bug` / `test-until-green` while coding. If reality diverges from the design, update the three files in a sentence or two rather than silently drifting.
