# Claude finalization brief

Continue from commit `2b7393f` on `codex/ctrader-oauth-readiness`. The deployed QA pass used demo account `#47765456` and release `5c6b40cc84d7`. Keep the existing automation error-cause fix in `apex-forex-bot/apex/platform/automation.py`.

The remaining launch blockers are:

1. Automation controls must reload `automation` immediately after Start, Pause, Resume, and Stop. Render the server response verbatim and show an error code/message when a control fails. Stop must state that existing positions remain at the broker.
2. `/rules/new` must persist `Approval Required`. The three choices are Signals Only, Approval Required, and Full Automation. Reject invalid values such as `aproval` before activation and test round-trip persistence.
3. The Dashboard Emergency control must open two separately confirmed demo-only actions: Stop only, and Stop and close positions. Never close by symbol. Re-read positions and say `Confirmed flat.` only after a verified empty read; otherwise say `Not confirmed flat.` with remaining position IDs and reasons.
4. `/positions` must open its detail view, expose Close only for demo accounts, confirm before POST, use positionId, and show the backend sentence verbatim. Live accounts must never receive a close control.
5. Restore the Performance page and API from authoritative closed trades. Today, 7 days, 30 days, and All time must change the result. Show Winning trades, Net, Profit factor, By strategy, and By instrument. Use `no losing trades`, never `Infinity`; groups with fewer than three trades say `too few to judge`. Broker read failures must be errors, never empty success.
6. Journal entries must distinguish provider rejection from internal engine failure. Do not label an internal exception `Broker Error`; keep safe, redacted causes only.
7. Verify mobile at 390x844. Dashboard, rules/new, positions, and performance must hydrate the authenticated demo account instead of remaining in Account/Loading skeletons.

Do not touch Telegram, payments, checkout, or live execution. Do not relax live-invariant tests. Keep product copy and code in English. Add regression tests for every defect and run the complete Python suite plus `npm test` and `npx tsc --noEmit` before opening or updating a PR. Report changed files, commits, test exit codes, deployment status, and anything not verified.
