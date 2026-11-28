---
name: test-until-green
description: Write or extend tests for a change, run them, and iterate until they pass. Use when the user asks to add coverage, keep going until tests are green, verify a feature, or check a UI workflow behaves correctly.
---

# Test until green

Combines a tight verification loop (write tests, run, iterate) with a small "launch → health → drive → evidence → cleanup" path for user-facing checks.

Inspired by OpenHands end-to-end testing conventions (MIT, Copyright © 2025 OpenHands contributors) and the OpenMausBot verification-skill structure (Apache-2.0). Rewritten for a generic Node/Python app. Do not copy OpenHands or OpenMausBot internal CLIs.

## Apex safety (mandatory)

- Never edit `.github/workflows`, `render.yaml`, `live_gate`, or `test_platform_live_invariants.py`.
- Never enable live trading or place real orders. Never drive production customer data to "verify" a feature.
- Never skip or rewrite invariant tests to force a green result. If a test is wrong, say so and wait.
- Never commit secrets. Isolated test profiles and fixtures only.

## Pick the cheapest layer

Use the cheapest suite that actually exercises the changed boundary:

| Change | Prefer |
|---|---|
| Pure function, pricing, validation, state machine | Unit test |
| HTTP handler, Stripe webhook, Supabase query, auth | Integration test with fixtures or test containers |
| A user-visible flow in the web UI | A focused browser or UI test, or a manual verification pass below |
| Broker / cTrader / order routing | Existing demo-safe tests only; do not open a live market |

Do not mock away the unit under test. Mock *dependencies* (broker, Stripe, mail), not the function you claim to have fixed.

## Loop

1. Write or extend tests that state the invariant in plain words.
2. Run them. Read the failure; do not guess.
3. Change production code (or the test, if the test was wrong — say why).
4. Re-run. Repeat until green.
5. Run the nearest existing suite so you have not broken neighbors.
6. Stop. Summarize coverage and commands run.

If a command or selector does not exist, stop and say which prerequisite is missing. Do not invent scripts, APIs, or CSS coordinates.

## Optional UI verification pass

When the user wants proof of a real screen, not only CI:

1. **Launch** the app the way the repo already documents, with an isolated profile or local demo data. Wait for a reliable ready signal (health route, log line, or existing script).
2. **Doctor** — one read-only health check. If it fails, fix the environment first; do not click around a broken boot.
3. **Drive** one important workflow with stable names (roles, test ids, routes, commands). No recorded pixel coordinates.
4. **Evidence** — screenshot or log of the resulting state, plus any important side effect (row created, mail *not* sent, order *not* placed).
5. **Cleanup** — stop only what this run started. Keep the evidence.

At most three workflows per pass. Prefer demo accounts.

## Feature map (optional)

If the user asks to remember how to verify a feature, add a short note (not in protected files) with: path the user takes, how to drive it, what "pass" looks like, and one known gotcha. Update it when the UI changes; never hide a product failure by editing the map.
