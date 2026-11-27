# Live readiness

Live trading is implemented behind a closed release switch and stays off. This
file is a checklist against `docs/LIVE_EXECUTION_SPECIFICATION.md`, what is still
open, and the sequence an owner would follow to open the switch later. It
authorises nothing. The spec's own answer to "can we turn it on?" is still no,
because its section 12 items marked OPEN below are not true.

Assessed at `claude/apex4traders-platform-v1` plus the `claude/live-readiness`
change. Nothing here was exercised against a real broker.

## Checklist

DONE = implemented and tested. PARTIAL = implemented in part, gap named.
MISSING = not built. "Test" names a file under `apex-forex-bot/tests/`.

| Spec | Requirement | Status | Code | Test |
|---|---|---|---|---|
| 1 | Release switch closed by default, one exact value opens it | DONE | `entitlement.live_execution_enabled` | `test_platform_live_invariants`, `test_live_readiness` [1][2] |
| 1 | Repo defaults can select or place nothing live | DONE (new proof) | all locks | `test_live_readiness` [1] scans deploy/env files and runs the doors |
| 0 | Three locks, each tested alone | DONE | `ctrader_link.live_allowed`, `entitlement.capability`, `automation._preflight` | `test_platform_live_invariants`, `test_platform_entitlement` |
| 2 | Grant only from a verified payment webhook | DONE | `billing.handle_event`, `live_gate.note_confirmed_payment` | `test_platform_live_gate`, `test_billing_integrity` |
| 2 | Entitlement records what was bought | DONE | `live_gate._paid_ok` (price, currency, term, plan) | `test_platform_live_gate` |
| 2 | Recorded consent, separate from sign-up terms | DONE (mechanism) | `live_gate.accept_current`, `audit.record_consent_change` | `test_platform_live_gate` |
| 2 | Consent re-affirmable | DONE (new) | `live_gate.accept_current` re-records after expiry; `withdraw_consent` | `test_live_readiness` [3] |
| 2 | Consent expires | DONE (new, provisional length) | `live_gate.consent_fresh`, `CONSENT_MAX_AGE_S` | `test_live_readiness` [3] |
| 2 | Per-client kill outranks entitlement and stops a running loop | DONE (new) | orders refuse at the first gate; `automation.live_wind_down_reason` ends the loop on the next supervisor pass (`A4T_SUPERVISE_INTERVAL_S`, default 180 s) | `test_platform_emergency`, `test_live_readiness` [4] |
| 2 | Legal text, tax, refund, pricing sign-off | OPEN | owner decisions D5, D6, L1-L8 | none possible |
| 3 | Mode re-verified at start | DONE | `automation._preflight` via `ctrader_link.verify_selected_mode` | `test_platform_mode_verify` |
| 3 | Re-verified on reconnect and refresh | DONE by a stronger rule: re-verified on every order | `live_execution.guard_engine_order` | `test_platform_mode_verify`, `test_platform_live_execution` |
| 3 | Unconfirmed mode is `unknown` and refused | DONE | `entitlement.account_mode`, `MODE_UNVERIFIED` | `test_platform_mode_verify` |
| 3 | Mode change under a running loop: stop and notify | PARTIAL | account change or disconnect now winds the loop down (new); a broker-side flip of the same account refuses each order but does not end the loop | `test_live_readiness` [4] |
| 3 | Mode never writable from a request body | DONE | `ctrader_link.select_account` is the only writer | `test_platform_ctrader_link` |
| 4 | Account id from the caller's own link record | DONE | `ctrader_link.get_ctrader_connection` | `test_platform_live_execution` |
| 5 | A stop exists | DONE | `ruledoc.validate`, `risk_gates._g_stop`, `bridge.stop_and_target` | `test_platform_risk_gates` |
| 5 | Risk per trade capped on live | PARTIAL | enforced at start (`engine_config.live_refusals`, 1 percent) and by engine sizing; the order-time `risk_gates` check runs only in `live_execution.place()`, which has no production caller | `test_platform_live_rule_guard`, `test_platform_risk_gates` |
| 5 | Max open positions | DONE | engine holds one position unless the account's own setting is raised, which the platform never writes | `test_platform_live_rule_guard` |
| 5 | Max daily loss | DONE | `engine_config.translate` (`max_daily_loss_pct`, platform ceiling 4 percent), `gates.authorize_order` risk guard | `test_daily_loss_headroom`, `test_rule_reaches_engine` |
| 5 | Max drawdown | DONE at platform floor | engine `MAX_DD_PCT` 25 percent; RuleDoc has no drawdown field | `test_platform_risk_gates` |
| 5 | Max daily trades | PARTIAL | `max_trades_day` applied; the spec's `5/4` counting question was not re-audited on the engine counter | `test_rule_reaches_engine` |
| 5 | Correlated exposure | DONE (USD-side proxy) | `portfolio.check` in `gates.authorize_order` | `test_portfolio_gate` |
| 5 | Exposure per instrument, slippage ceiling, order expiry, flatten-on-limit | DONE as refusal | a live rule carrying one does not start (`LIVE_TERM_NOT_ENFORCED`); not enforced | `test_platform_live_rule_guard` |
| 5 | Spread ceiling | DONE | `max_spread_pips` | `test_rule_reaches_engine` |
| 5 | News and session filters | MISSING | no news source on the platform | none |
| 5 | Only MARKET orders, refused at activation | DONE | `bridge.SUPPORTED_ORDER_TYPES`, `ruledoc` | `test_platform_risk_gates` [11] |
| 5 | Every gate fails closed, every refusal journalled with a code | DONE | `risk_gates.authorize`, `live_execution._refused` | `test_platform_risk_gates`, `test_platform_live_execution` |
| 6 | Claim before the broker, never released on unknown | DONE | `live_ledger` (door `place`); engine ledger never releases | `test_platform_live_ledger`, `test_platform_live_execution` |
| 6 | Claim key derived from the decision (symbol, side, strategy, bar) | PARTIAL | `live_ledger.setup_key` does; the engine path's `ledger.request_id` keys on intent in a 120 s bucket | `test_platform_live_ledger` |
| 6 | Shared backend mandatory for live | DONE | `live_ledger` and `audit` refuse at import without one; engine claim fails closed on live | `test_platform_live_ledger`, `test_engine_live_fail_closed` |
| 6 | Restart reconciliation of an unknown order | PARTIAL | positions are re-read from the broker on restart and the claim stays held; an UNKNOWN claim is never resolved to filled or rejected (see Q4) | `test_platform_loop_supervisor` |
| 7 | Audit: orders, refusals, entitlement, consent, mode checks | DONE | `audit.py` | `test_platform_audit` |
| 7 | Append-only | DONE (tamper-evident hash chain; a store admin can still rewrite, `audit.verify` detects it) | `audit._append`, `audit.verify` | `test_platform_audit` |
| 7 | Wind-downs audited | DONE (new) | `gate=live_wind_down` | `test_live_readiness` [4] |
| 8 | Per-client stop, says whether it flattens | DONE | `automation.stop`, `_flatten_answer` (declines to flatten, says so) | `test_stop_sentence_truthful` |
| 8 | Per-instrument and global stop, no deploy needed, no store needed for the env one | DONE | `emergency.py`, `scripts/emergency_stop.py` | `test_platform_emergency`, `test_live_gate_drill` |
| 8 | Halt on own uncertainty and wind down | DONE for what the supervisor reads (emergency store, gate, account, rule); ledger or broker outages refuse the order but do not end the loop | `automation.live_wind_down_reason` | `test_live_readiness` [4] |
| 9 | Shared order-rate counters, per-client order cap, refuse on fallback | DONE | `order_rate.py` | `test_platform_order_rate` |
| 9 | Broker-side order throughput limits | OPEN | broker fact, see Q4 | none |
| 10 | Switch lives outside the app release | DONE | environment variable | `test_platform_live_invariants` |
| 11 | Operator's own account first, capped size | DONE (code) | `live_pilot.py`, fail closed when unconfigured | `test_platform_live_execution` [19b] |
| 11 | Demo smoke X1 passed | OPEN | `docs/CTRADER_DEMO_SMOKE_TEST.md` | needs owner and broker |
| client | Web says live is unavailable while closed; withdraw button | DONE (new button) | `web/.../live-access.tsx`, `live/page.tsx` | `live-access.test.tsx` |
| 12 | Drill exercised, not only tests | PARTIAL | script half done, owner half in `docs/LIVE_DRILL.md` is blank | `test_live_gate_drill` |
| 12 | Restore exercised (X8) | DONE per `docs/RELEASE_READINESS.md` (2026-10-05) | `scripts/dr_drill.py` | not re-run here |
| 12 | Monitoring X7 | OPEN | nothing scrapes `/readyz` yet | none |
| 12 | Separate security review of this implementation | OPEN | not done | none |

## What this change added

1. Consent expires after `live_gate.CONSENT_MAX_AGE_S`. An old, undated or
   future-dated acceptance does not count; accepting again re-records it in the
   audit trail; `POST /live/withdraw` takes the caller's own acceptance back and
   is audited before anything is cleared.
2. The supervisor ends a RUNNING live loop when the switch closes, a halt
   applies, consent is withdrawn, the plan lapses, the pilot no longer lists the
   account, the selected account changes or disappears, or any of those reads
   fails. The record becomes BLOCKED with the reason, nothing is revived, the
   client is notified (positions are not closed, and the message says so) and
   the wind-down is audited.
3. `tests/test_live_readiness.py`: repo defaults place nothing live, opening the
   switch alone places nothing, and each new behaviour with the switch simulated
   open inside the test process only. Each behaviour was checked to fail when
   its code is removed.

## Open questions for the owner

- Q1. How long may a consent stay valid? 180 days is a provisional engineering
  default, not a legal position.
- Q2. Is the existing gate (accepted terms, licence, operator approval, pilot
  pair) enough, or must every live start also carry a fresh explicit
  confirmation naming the account and rule version?
- Q3. Legal text L1-L8, tax D5-D6, refund and entity: not mine to decide.
- Q4. Broker facts to confirm before relying on them: how an order sent just
  before a timeout can be matched to a decision (a client order id or label),
  which is what resolving an UNKNOWN claim needs; cTrader order-throughput
  limits; the per-symbol minimum order against the pilot cap; whether stops
  and targets stay server-side while a loop is halted.
- Q5. Should a wind-down ever close positions? Today it never does.
- Q6. News and session filters need a data source and a decision to buy one.
- Q7. Per-instrument exposure, slippage and expiry are refused on live rather
  than built; building them needs broker support.
- Q8. Pilot account, instruments and size cap are the owner's numbers.
- Q9. Should the engine path adopt the bar-based claim key (changes the live
  engine path, so it needs its own review)?
- Q10. Monitoring provider for X7.

## Sequence to open the switch (information only)

Nothing below is done by this repository, and no step is to be taken before the
OPEN rows above are closed.

1. Close the OPEN rows: owner sign-off, X1 demo smoke, monitoring, the owner half
   of the drill, a separate security review.
2. Publish the reviewed legal text (`A4T_LEGAL_PUBLISH`, then the operator's
   publish-current call) and set `A4T_OPERATOR_USER_IDS`. See
   `docs/LIVE_LAUNCH_CHECKLIST.md`.
3. For the operator's own account only: accept terms, record the licence,
   request a live connection, approve it.
4. Set the pilot: `A4T_LIVE_PILOT_PAIRS` (user:account), `A4T_LIVE_PILOT_SYMBOLS`,
   `A4T_LIVE_PILOT_MAX_UNITS` (not below the broker's minimum order).
5. Confirm `/readyz` is healthy with a shared backend and
   `scripts/emergency_stop.py status` answers.
6. Last: `APP_ENV=production`, `APEX_ALLOW_LIVE_ACCOUNTS` on, then
   `A4T_LIVE_EXECUTION` set to the exact value in `entitlement.LIVE_SWITCH_ON`.
7. Select that live account, start one rule at the smallest size, watch the
   audit trail (`audit.verify`) and journal, with
   `scripts/emergency_stop.py halt` ready.
8. To close: remove `A4T_LIVE_EXECUTION`. Orders refuse at once and running live
   loops end on the next supervisor pass.
9. Widening to a client is a code and test change to `live_pilot.py` with its
   own review, not a configuration change.
