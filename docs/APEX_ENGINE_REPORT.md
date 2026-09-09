# APEX AI Trader Engine — implementation report

§78 of the master prompt. Written against what is in the repository, not
against what was planned.

## LIVE TRADING NOT YET APPROVED

Stated first because it is the answer to §78.18. Nothing in this work enables
live trading, and nothing in it should be taken as evidence that the engine is
profitable. The decision layer has never made a live decision; the position
manager has never managed a live position. Both need a shadow period against
real market conditions before anyone argues about switching them on.

## 1. What already existed

More than the brief assumes. The parts the brief treats as things to build were
already here and already sound:

- **A central risk engine.** `gates.authorize_order` was already the single
  gate every new position passed, already ordered cheapest-first so a denial
  never burns an idempotency claim, and already failing closed on entitlement,
  unverified environment, halted risk and lost ownership.
- **Idempotency** (`ledger.py`), **single-writer ownership** (`ownership.py`),
  and **server-side environment resolution** that reports whether a LIVE
  reading came from the broker or from our own stored flag.
- **An append-only journal** with strategy and risk versions stamped on every
  event.
- **A rate-limit-aware data layer.** `candle_cache.py` and `markets.py` exist
  because cTrader allows 5 historical requests per second *per connection
  regardless of user count*.
- **An expected-value layer** with real calibration, currently in shadow.
- **115 tests**, including one that discovers Mini App routes so a new one
  cannot be added unscoped.

## 2. What was reused rather than rewritten

- `strategies.detect_regime` — kept whole. It classifies from ratios rather
  than absolute thresholds, so it works on EURUSD, gold and an index without a
  per-symbol table, and its 400-bar reference window exists because a 100-bar
  base converges with the present after ninety minutes and stops detecting the
  regime it is measuring. `regime.py` wraps it.
- `gates.py` — extended, not replaced.
- `trade_events.py` — extended with eight event types.
- `ai.py` — left in place; `ai_schema.py` sits in front of it.
- `sentinel.py` — already most of §29's cost control.

## 3. What was added

| Module | Purpose |
|---|---|
| `setups.py` | `SetupCandidate`, five statuses, a legal-transition table, tri-state evidence |
| `regime.py` | Stable vocabulary, the measurements behind each reading, explicit `UNKNOWN` |
| `ranking.py` | A documented weighted score; unmeasured components excluded, not zeroed |
| `decision.py` | `NO_TRADE` / `WATCH` / `CANDIDATE` / `ENTER_PROPOSED` with stable reason codes |
| `ai_schema.py` | Validates a model reply against the *question*, not only its shape |
| `thesis.py` | The reason a trade was taken, frozen at entry |
| `position_manager.py` | `HOLD` / `TIGHTEN` / `REDUCE` / `EXIT` proposals from thesis state |
| `portfolio.py` | Exposure and correlation, called by the risk engine |

## 4. What was changed

- **`gates.authorize_order` now checks exposure, correlation and data
  freshness.** Those checks existed and lived inside the autonomous loop, so an
  autonomous entry was checked and a manual `/buy` was not. Placement is
  deliberate: after the risk-guard check, because "trading is paused" is more
  useful to a client than "you already hold two dollar shorts"; before the
  ledger claim, because a denial must not burn one.
- **`user_loop`'s inline correlation arithmetic is gone.** It calls the same
  function. Its remaining job there is the decline *record*, which a denial
  raised inside gates would reach too late to attribute to that candidate.
- **The position manager runs in shadow** beside the live exit policy.

## 5. What was removed

Nothing. No component was replaced and no working functionality deleted.

## 6. The problem this was pointed at

From the live demo account, last 15 closed trades:

```
win rate        60%          the entry engine is not the problem
profit factor   1.10
average win     18.88
average loss    25.63        36% larger than the average win
```

`BREAKEVEN_AT_R = 1.0` plus a 1R trail, against a target at 2.4R. A winner has
to travel 2.4R without a 1R pullback after 2R; in a ranging market it rarely
does. The journal carries the fingerprints — USDJPY `+0.26`, NZDUSD `-0.56`,
EURUSD `-1.98`.

The thesis-driven manager is the principled fix: hold while the reason holds,
act when it stops. **It is not switched on.** Replacing one untested policy
with another is a different bet, not an improvement.

## 7. Migrations, API, WebSocket, AI, cTrader

- **Migrations:** none. `sql/002_trade_events.sql` is unchanged.
- **API:** no new endpoints yet. The read models are not wired (see §9 below).
- **WebSocket:** unchanged. This repository uses SSE, deliberately — the feed
  is one-directional, and SSE needs no dependency and no framing. §35's
  authentication and scoping requirements are met by the existing transport.
- **AI:** `ai_schema.py` added in front of the existing integration. No model
  can propose a symbol nobody asked about, a reversed direction, or any field
  the platform computes.
- **cTrader:** `get_deal_history` added for the journal backfill;
  `get_closed_deal_pnl` now also returns exit price, entry price, post-close
  balance and close time, all of which were in the reply and being discarded.

## 8. Tests

121 files pass. Added in this work:

| File | Checks |
|---|---|
| `test_decision_engine.py` | 55 |
| `test_position_engine.py` | 42 |
| `test_portfolio_gate.py` | 24 |
| `test_shadow_manager.py` | 36 |
| `test_engine_failures.py` | 34 |
| `test_engine_active.py` | 47 |

Two test-writing rules came out of this session and are worth keeping:

1. **Assert on the parsed module, not its text.** Several docstrings name
   `gates.authorize_order` in order to say the module does *not* call it, and a
   substring search cannot tell an explanation from a call.
2. **Assert on paths, not occurrence counts.** A count of a phrase is a proxy
   that stops being one the moment two call sites start sharing a renderer.

## 9. What is NOT done

Stated plainly per §75 rather than left to be discovered.

| Phase | State |
|---|---|
| **18 — Mini App read models** | Not wired. The new decisions are journalled but do not reach a screen yet, so §61's "why didn't APEX trade" still shows what `DECISION_DECLINED` carried rather than the full ranked pass |
| **19 — WebSocket events** | Not wired for the new event types |
| **43/44 — backtest, walk-forward** | `walkforward.py` exists and was not extended |

### Now active (was pending in the first draft of this report)

| Phase | What changed |
|---|---|
| **7 — scanner** | `scanner.py` drives the scan. The loop's confidence-only ranking is gone; every watched instrument produces a `SetupCandidate` — including the ones skipped or unreadable — and the whole list goes through `ranking.rank` and `decision.evaluate_all`. The pass is journalled |
| **12 — AI orchestration** | `ai._validate_verdict` calls `ai_schema.safe_validate` before its own normaliser. A reply about a different instrument, a reversed direction, or one carrying a computed field is rejected and journalled as `ai.rejected` |
| **17 — thesis at entry** | The loop writes a thesis at the fill, from the scanner's own candidate when the direction matches. That is the only moment the real fill and the stop that was actually sent are both known |

Nothing is faked, stubbed, or partially wired in a way that could act. Being
active did not make any of these able to execute — `test_engine_active.py`
asserts that on the parsed modules.

## 10. Known limitations

1. **No WebSocket.** SSE by design; see §7 above.
2. **Margin is unknown.** `ProtoOATrader` carries balance, leverage and bonuses
   — not free margin or margin level. The risk engine reports it as unreported
   rather than reconstructing it from leverage and position size.
3. **EV calibration is not ready.** 27 of 30 labelled trades, and roughly 40%
   of journal rows carry no `confidence` so they cannot be labelled at all.
   Until it is ready no probability may be presented as measured.
4. **Correlation is a USD-direction proxy**, not a covariance estimate. It says
   nothing about EURGBP against EURCHF. Building a real one needs a window this
   platform does not keep.
5. **`REVERSAL` is not emitted.** Nothing here measures it, and inferring it
   from an RSI extreme would be a label the platform cannot defend.

## 11. How to get evidence for the exit-policy change

1. Set `SHADOW_POSITION_MANAGER=true` on Render.
2. Leave it a fortnight. It records only proposals that *differ* from what the
   live policy did, so the journal stays readable.
3. Read the `management.shadow` events against the trades that closed in the
   same window.
4. If the shadow would have held winners the live policy cut, that is the
   evidence. Then — and only then — change `BREAKEVEN_AT_R` and the trail.

That decision belongs to the operator, and this work does not pre-empt it.
