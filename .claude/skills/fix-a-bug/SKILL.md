---
name: fix-a-bug
description: Reproduce a reported bug with a failing test, fix the underlying cause, and run tests until they are green. Use when the user reports a bug, pastes an error, or asks to fix a failing behavior in the Apex4Traders / autoflow-backend codebase.
---

# Fix a bug

Workflow inspired by the xAI cookbook `bug-report-to-fix` example (Copyright (c) 2025 X.AI LLC, Beta Testing License). This skill is an original rewrite for a Node/Python product repo. It does not include the sample checkout project.

## Apex safety (mandatory)

- Never edit `.github/workflows`, `render.yaml`, `live_gate`, or `test_platform_live_invariants.py`.
- Never enable live trading or place real orders. Use demo or fixture data only.
- Never weaken, skip, or delete live-trading invariant tests to make a suite pass.
- Never commit secrets, tokens, or `.env` files. Do not print secret values.
- Prefer the smallest change that fixes the cause. If the fix is large or touches billing, auth, or order placement, show a short plan and wait for approval.

## Steps

1. **Baseline.** Find how this area is tested (repo scripts, `package.json`, `pytest`, `npm test`, a named suite). Run the smallest relevant suite *before* you change anything. Note what already fails.
2. **Locate.** Start from the symptom (error message, route, screenshot, log). Read the files involved and follow calls with search. Identify the function or module that should have prevented the bug.
3. **Failing test first.** Add or extend a test that reproduces the report. Run it and confirm it fails for the right reason. A fix without a failing test first is not done.
4. **Fix the cause**, not the symptom. Smallest change that works. Match the style of the file you are editing (indentation, quotes, naming). Do not add a dependency unless the fix truly requires it, and do not drive-by refactor.
5. **Go green.** Re-run the new test, then the surrounding suite. Iterate until everything you ran is green. If an unrelated test was already failing at baseline, say so; do not "fix" it unless the user asked.
6. **Report.** Two or three sentences: what was wrong, what you changed, and which tests you ran.

## Conventions

- Put the test next to existing tests for that module, in the same framework (`node:test`, Jest, pytest, etc.).
- Name the test after the behavior, in plain words.
- Money and balances stay in integer minor units if the codebase already does that.
- Stripe, auth, and tenant/RLS bugs need a test for the negative case (wrong tenant, unsigned webhook, double refund) as well as the happy path.
- Do not hit live broker or live Stripe; use recorded fixtures or the project's test mode.
