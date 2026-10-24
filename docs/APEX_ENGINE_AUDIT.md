# APEX AI Trader Engine — repository audit and plan

Phases 0–3 of the master implementation prompt. Written before any file was
modified, from reading the repository rather than assuming its shape.

## 0. What this repository is

A single-process Python trading platform. No framework, no ORM, no build step.

| Concern | Reality |
|---|---|
| Language | Python 3, stdlib only for HTTP (`ThreadingHTTPServer` in `bot.py`) |
| Frontend | One file: `apex/static/terminal.html`, a Telegram Mini App |
| Store | Redis (Upstash REST or `REDIS_URL`), via `apex/user_store.py`. No ORM |
| SQL | `sql/002_trade_events.sql` only — an optional archive, nothing reads it |
| Broker | cTrader Open API over a hand-rolled socket (`apex/brokers/ctrader.py`) |
| Transport to UI | REST + SSE (`apex/stream.py`). No WebSocket |
| Auth | Telegram `initData` HMAC, verified server-side on every route |
| Deploy | Render, `render.yaml`, one web process |
| Tests | 115 files under `tests/`, plain asserts, `tests/run_all.py` |

The prompt's target directory names (`market-data/`, `scanner/`, …) are not
adopted. §4 explicitly allows adapting to an established architecture, and this
one is flat single-purpose modules under `apex/`. New modules follow that.

## 1. Component classification

### KEEP — authoritative, safe, well-tested

| Module | Role | Why it stands |
|---|---|---|
| `gates.py` | Central risk engine (§14) | Already the single gate. Fails closed on entitlement, unverified environment, halted risk, lost ownership, duplicate claim. Ordered cheapest-first so a denial never burns an idempotency claim |
| `ledger.py` | Idempotency (§20) | Claim-based, `fail_closed=live` |
| `ownership.py` | Single-writer lease | Prevents two containers managing one account |
| `account_mode.py` | LIVE/DEMO/UNVERIFIED (§15) | Resolves server-side from the broker, reports its source; a stored reading is never treated as confirmation |
| `trade_events.py` | Append-only journal (§21, §22, §23) | Stamps `schema`, `risk_version`, `strategy_version`. Bounded at 2000/user |
| `candle_cache.py` | Historical-request cache | Exists because cTrader allows 5 historical req/s **per connection regardless of user count** |
| `ev.py` | Expected-value + calibration (§42) | Real measurement, currently shadow mode at 27/30 labelled trades |
| `settings_policy.py` | Three trust tiers | `OPERATOR_SETTABLE` / `REMOTE_SETTABLE` / `MINIAPP_SETTABLE` + `MINIAPP_FORBIDDEN` |
| `stream.py` | SSE fan-out | Makes no broker calls; publishes in-memory dash plus one shared market snapshot |
| `markets.py` | Shared market snapshot | One fetch serves every client — the rate limit again |

### EXTEND — right idea, missing the engine's requirements

| Module | Gap against the prompt |
|---|---|
| `gates.py` | No exposure, correlated-exposure, margin, spread, or market-data-freshness check (§14, §30, §31). Those live in `user_loop` today, so a future caller can reach the broker without them |
| `strategies.py` | `detect_regime` returns `trending/ranging/volatile/quiet` — no `UNKNOWN`, no `BREAKOUT`, no `REVERSAL`, and no evidence object (§8) |
| `ai.py` | Parses the LLM reply loosely; `_validate_verdict` checks the action but there is no declared schema, no `reason_codes`, no `invalidation_conditions`, no `uncertainties` (§12, §40) |
| `sentinel.py` | Caches an AI verdict and refreshes on feature drift — this is most of §29's cost control, but it is keyed per symbol/action, not per candidate |
| `trade_events.py` | Has decision/order/position events but no `SETUP_DETECTED`, `CANDIDATE_RANKED`, `THESIS_*` types |
| `copilot.py` | Answers FACT/OBSERVATION/ANALYSIS/UNKNOWN/REFUSED already (§63); needs the new decision objects wired in |

### REFACTOR — correct behaviour trapped inside a 4800-line function

| Location | Problem |
|---|---|
| `user_loop._loop` lines ~1975–2020 | The Auto-Pilot scanner. Ranks candidates by **confidence alone**, keeps only the single best, and discards every rejected candidate without recording it. §10 wants deterministic multi-factor ranking; §61 wants the rejections kept so "why didn't APEX trade" can be answered |
| `user_loop._loop` entry block | Setup detection, decision, and execution are one straight line of code. There is no `SetupCandidate` object, so nothing can be ranked, explained, replayed, or tested in isolation (§9, §11) |
| `_manage_trailing` | Correct implementation of a **policy that is losing money** — see below |

### REPLACE — nothing

No component is being replaced. Every part of the prompt maps onto something
that exists or onto a genuinely new module.

### REMOVE — nothing yet

`webapp.py` holds a fallback copy of the old terminal HTML that is now dead
weight, but it is still referenced as a fallback and removing it is not part of
this work.

## 2. The measured problem this engine has to solve

From the live demo account (47765456), last 15 closed trades:

```
win rate        60%          <- the entry engine is fine
profit factor   1.10         <- essentially break-even
average win     18.88
average loss    25.63        <- 36% larger than the average win
largest loss    -89.40       largest win  +64.26
```

Settings are `sl_pips 25`, `tp_pips 60` — an intended 1:2.4. The realised ratio
is worse than 1:1. The mechanism is in `_manage_trailing`:

- `BREAKEVEN_AT_R = 1.0` moves the stop to entry at +1R
- `TRAILING_STOP = true` then keeps the stop one full risk-unit behind price

So a winner must travel 2.4R **without a 1R pullback after 2R** to reach its
target. Most trades are tagged `ranging`. The result is winners closed near 1R
while losers run the full stop, and the journal shows the fingerprints:
USDJPY `+0.26`, NZDUSD `-0.56`, EURUSD `-1.98`.

This is why §16 (position manager) and §18 (exit engine) are the highest-value
part of the prompt for this repository, not the scanner. A thesis-driven exit
replaces "move the stop on a fixed schedule" with "exit when the reason for the
trade stops being true", which is the only version that can hold a winner.

**No exit parameter is changed in this work without the operator deciding it.**
The engine records what it *would* have done (§46 shadow) so the change is made
on evidence.

## 3. Security and data-integrity findings

| Finding | Status |
|---|---|
| Client cannot set `paper`/`CTRADER_ENV`/`BROKER` | Already enforced — `MINIAPP_FORBIDDEN` |
| No route reads an owner from the request | Already enforced and asserted by `test_miniapp_isolation.py`, which *discovers* routes so a new one cannot be added unscoped |
| No hardcoded admin identity (§64) | To verify |
| Secrets never logged (§36) | `redact.py` exists; to re-verify against new modules |
| SSE subscription scoping (§35) | Identity from `initData` before any data access; no cross-account fan-out |
| `dash["positions"]` was never written | **Fixed this session** — five readers were consuming an empty list |
| Three disagreeing equity implementations | **Fixed this session** — one figure, from cTrader's own net unrealised P&L |
| Broker-closed trades journalled without exit, side, id, or post-trade balance | **Fixed this session**, plus `scripts/backfill_trades.py` for the history already written |

## 4. Implementation order

Phases follow the prompt but are ordered by value for *this* repository.

| Step | Module | Prompt § |
|---|---|---|
| 1 | `apex/setups.py` — `SetupCandidate`, statuses, invalidation | §9 |
| 2 | `apex/regime.py` — deterministic regimes incl. `UNKNOWN` + evidence | §8 |
| 3 | `apex/ranking.py` — deterministic, documented, testable score | §10 |
| 4 | `apex/decision.py` — `NO_TRADE`/`WATCH`/`CANDIDATE`/`ENTER_PROPOSED` + reason codes | §11, §26, §61 |
| 5 | `apex/ai_schema.py` — strict schema, reject-and-fail-closed | §12, §40 |
| 6 | `apex/thesis.py` — entry thesis, frozen at entry | §17 |
| 7 | `apex/position_manager.py` — thesis state → HOLD/TIGHTEN/REDUCE/EXIT proposals | §16, §18 |
| 8 | `gates.py` extension — exposure, correlation, freshness | §14, §30, §31 |
| 9 | Wire into `user_loop`, new event types, Mini App read models | §21, §34, §58 |
| 10 | Failure injection + concurrency tests | §48, §50 |

Nothing in steps 1–7 can execute. They produce proposals; `gates.authorize_order`
remains the only thing that can permit an order, and the execution controller
remains the only path to the broker.

## 5. Stated blockers

Per §75, recorded rather than worked around:

1. **No WebSocket.** The repository uses SSE, chosen because the feed is
   one-directional and it needs no dependency or framing. §35's event list is
   implemented over SSE; the authentication and scoping requirements are met.
   Adding a WebSocket process would be a deployment change with no capability
   gain here.
2. **`ProtoOATrader` carries no free margin or margin level.** §14 asks the
   risk engine to validate margin. It can validate exposure and balance; margin
   headroom is not readable from this broker API and is reported as unknown
   rather than computed from a guess.
3. **EV calibration is at 27/30 labelled trades** and roughly 40% of journal
   rows carry no `confidence`, so they cannot be labelled at all. Until it is
   ready, `calibrated_probability` has no measured base rate and the decision
   engine must not present a probability as measured.
