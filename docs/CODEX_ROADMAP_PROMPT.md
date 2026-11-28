# Codex prompt: product roadmap, your ten items

Paste everything below the line into Codex. It is self-contained. The owner's
instruction (2026-11-04) is that Codex pushes its changes to the working branch
`claude/apex4traders-platform-v1`; that is why this differs from the queue rule
of one branch per issue. Where this file and `AGENTS.md` disagree on the branch,
this file wins for these ten items only. Every prohibition in `AGENTS.md` still
applies.

---

You are Codex, working on the Apex4Traders platform in
`alexgabriel225sefu-dotcom/autoflow-backend`. The owner wants the platform to
feel like a serious, premium company product, not a cheap SaaS. Claude Code is
building ten other roadmap items in parallel. You build the ten below.

## Read first, in this order

1. `AGENTS.md`
2. `docs/CODEX_CLAUDE_PROTOCOL.md`
3. `docs/LIVE_EXECUTION_SPECIFICATION.md` (so you know what you must not touch)
4. `docs/DESIGN_DIRECTION.md`, then look at two existing pages under
   `web/src/app/(app)/` (for example `performance` and `positions`) and copy
   their patterns. The web app is not the Next.js you know: read the relevant
   guide in `web/node_modules/next/dist/docs/` before writing web code.

## Where you work

- Branch: `claude/apex4traders-platform-v1`. Push to it directly, in small
  commits (one item, or one coherent slice of an item, per commit).
- Before every push: `git pull --rebase origin claude/apex4traders-platform-v1`.
  If the rebase conflicts in a file you do not own (list below), keep the other
  side's change and re-apply yours on top.
- Never push to `main` or to `claude/arcads-external-api-gExX7`.
- Do not edit `.github/workflows/**`, `render.yaml` or `server.js`. Do not
  deploy. Do not turn on any environment variable or flag.

## Hard limits (a violation means stop and report)

- No change that loosens a live gate or `tests/test_platform_live_invariants.py`.
  You may add checks that make live stricter. You may not remove or soften one.
- Nothing you build may send an order to a broker. Backtests, replay, forward
  testing and the risk map read data and write records; they never place orders.
- No payment, licence or entitlement code. No secrets in the repo.
- No promise of profit anywhere in the UI or copy. Backtest and replay screens
  carry this sentence, verbatim: "Backtest results are hypothetical and do not
  predict future performance."
- A failed or missing read is shown as failed or unknown, never as zero or as
  "no data means fine". This is the repository's strongest rule; the existing
  pages and `tests/test_product_copy.py` enforce it.
- Amounts have no currency unless the server says so.

## File ownership (to avoid collisions)

You own, and Claude does not edit:

- new backend modules you create under `apex-forex-bot/apex/platform/` named for
  your items (`backtest*`, `replay*`, `forward*`, `risk_guard*`, `risk_map*`,
  `incidents*`, `health_score*`, `overfit*`, `multi_account*`, `rule_layer*`);
- new web routes you create: `web/src/app/(app)/replay`, `backtest`, `forward`,
  `risk`, `incidents`, and their components under `web/src/components/`.

Shared files (append only, keep the diff small, rebase carefully):
`apex-forex-bot/apex/platform/api.py` (route table), `web/src/lib/api.ts`
(types), `web/src/components/app/nav.ts`, `web/src/app/routes.test.ts`.

Claude owns, and you do not edit: the rule builder and its storage, the
decision log and explanation, the journal, notifications, the dashboard layout,
settings, presets, strategy health, approvals and audit export.

## Definition of done, for every item

- Tests first where practical. Add tests next to the code. The full set must pass
  before each push: from `apex-forex-bot`, `python3 tests/run_all.py`; from
  `web`, `npx tsc --noEmit`, `npx eslint .`, `npx vitest run`, `npx next build`.
  (`src/test/e2e.test.ts` needs the Python `_cffi_backend` module; it can fail
  locally for that reason alone. CI is the judge.)
- Every new route is classified in `web/src/app/routes.test.ts` and, if it is
  an API route, rate limited like its neighbours.
- Loading, empty, error and "could not be read" states all exist and are tested.
- Mobile width (390px) works; no horizontal scroll.
- No emoji in the UI. Icons come from the existing icon set.
- English in code, UI, tests and commit messages.
- When an item is finished, add one line to `docs/NEXT_SESSION_HANDOFF.md` under
  a heading "Roadmap, Codex items" with the item number and the commit.

## Your ten items (numbers match the owner's list)

3. **Strategy Replay.** Candle-by-candle view of a past window for a strategy or
   rule: when the setup appeared, which conditions were true, when a position
   would have opened, how the stop would have moved, why it closed, and which
   data was available at that moment. Needs a server read for candles over a
   past time window (none exists yet; build it, bounded and rate limited). Draw
   with the existing chart component (`web/src/components/chart/`), with play,
   pause and step controls. Read-only.
4. **Realistic backtest.** Variable spread, commission, swap, slippage, simulated
   latency, partial fills, trading sessions, news and weekend filters, rejected
   orders, bid versus ask, and missing or stale data. Outputs: net profit,
   drawdown, profit factor, expectancy, average win and loss, longest losing
   streak, recovery factor, equity curve, results per month, long versus short.
   Every assumption is listed on the result. State clearly what was NOT modelled.
5. **Forward testing.** A mode between backtest and demo: runs a strategy in real
   time, sends no orders, records what it would have done, compares the signal
   with the later executable price, computes hypothetical slippage, and shows
   signal, decision and execution as three separate things.
6. **Advanced Risk Guard.** Weekly loss limit, maximum drawdown, maximum
   consecutive losses, per-symbol exposure, pair correlation, slippage limit,
   cooldown after a loss, maximum trades per day, and "stop new entries only"
   next to the existing stop-all. Every block carries a human-readable reason and
   the name of the guard that fired. Additive and stricter only; do not change
   how the live gates in `live_execution` and `live_gate` decide.
7. **Portfolio Risk Map.** Aggregate risk across open positions: total risk in
   percent, long and short exposure, exposure per currency (USD, EUR, GBP and so
   on), correlated pairs, the loss if every stop is hit, a gap scenario, and
   concentration in one instrument. Words like "Three positions look separate,
   but together create 3.8% exposure to USD." Unreadable positions are said to be
   unreadable, never summed as zero.
8. **Multi-account control.** Design and isolation first. Before any UI: a short
   design note and tests that prove one user's accounts, data and kill switches
   never mix with another's, and that one account's kill switch does not touch
   the others. Then per-account risk and a global plus per-account kill switch.
   Do not expose the same strategy on several accounts until the isolation
   tests pass in CI.
9. **Broker-agnostic rule layer.** One definition of risk unit, pip, position
   size and stop logic across instruments, with correct handling of minimum lot,
   lot step, contract size, symbol digits and minimum stop distance. For cTrader:
   check demo or live at each reconnect, volume step, stop distance, reconnect
   state, token expiry warning and the real broker state. Reuse `apex/forex.py`;
   do not fork its maths.
11. **Incident Center.** A page listing broker disconnected, token expired, stale
    quotes, shared store unavailable, rate limit, order timeout, unknown broker
    outcome, automation paused, emergency stop. For each: when it started, what
    it affected, what the system did, whether the trader must act, and when it
    recovered. Incidents are derived from real events and stored; never invented.
12. **Automation health score.** A technical score, not a profit score: broker
    connected, data fresh, token valid, rule valid, risk guard active, shared
    store healthy, no unresolved incidents, last successful poll, last broker
    response. Show the parts, not only the number ("Warning: candle data is 48
    seconds old."). Unknown inputs lower confidence visibly; they are not
    counted as healthy.
16. **Anti-overfitting assistant.** Warn when a rule has too many conditions,
    when many combinations were tested, when there are too few trades, when only
    one period was used, when the rule is changed after every loss, or when the
    results come from a single period. It never generates signals; it protects
    the testing process. Wording is cautious ("Not enough evidence to judge this
    strategy.").

## Order I suggest

12 and 11 first (they share the incident records), then 7, 6, 9, then 4 and 5,
then 3, then 16, and 8 last. Use your judgement if a dependency says otherwise.

## When you stop

Commit and push what is finished. Leave a short note in
`docs/NEXT_SESSION_HANDOFF.md` saying which items are done, which are partial
and what the next step is. Report to the owner in Romanian.
