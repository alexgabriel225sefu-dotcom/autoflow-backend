# Rule field enforcement

Every field a client can see on the Rule terms screen is in one of three
positions. The screen must never present a setting as governing the loop when
it does not, so each field is either carried into the engine, refused before
activation, or **named to the client as not applied, per rule**.

`apex/platform/engine_config.py` does the carrying and the naming.
`apex-forex-bot/tests/test_rule_reaches_engine.py` measures it against a real
start and fails if any of it drifts, in either direction.

## What reaches the engine

| Field | Engine setting | Note |
| --- | --- | --- |
| `symbols` | `symbol` | The **first** one only. The rest are named as not applied. |
| `timeframe` | `timeframe` | |
| `sizing.riskPercent` | `risk` | The most consequential field in the document. |
| `stopLoss` (`pips`) | `sl_pips`, `atr_stops` off | Exact. |
| `stopLoss` (`atr`) | `atr_stops` on | The switch, not the multiple — the multiple is named as not applied. |
| `takeProfit` (`pips`) | `tp_pips` | Exact. |
| `trailingStop.enabled` | `trailing` | On/off. The distance is the engine's. |
| `breakEven` | `breakeven_r` | `0` when off. |
| `limits.maxDailyTrades` | `max_trades_day` | |
| `limits.maxSpreadPips` | `max_spread_pips` | |

## What is validated but does not reach the engine

Named to the client with the reason, never approximated.

| Field | Why not |
| --- | --- |
| `takeProfit` (`rr`) | The engine has no reward-to-risk setting; it derives the target from the stop. A pip target is applied exactly. |
| `schedule` | The engine filters by trading session, not by the days and UTC windows a rule records. Validated so the terms are well formed. |
| `limits.maxOpenPositions` | A demo account holds one position at a time in this release, whatever the rule says. |
| `entry` / `exit` conditions | The engine chooses entries and exits with its own strategies. **This is the largest remaining gap** and the next milestone. |
| `sides` | The engine takes both directions when its strategy signals them. |
| `order.*` | Slippage ceilings and order expiry are not applied by this release's execution path. |

## What is refused before activation

| Field | Why |
| --- | --- |
| `order.type` other than `MARKET` | `bridge.SUPPORTED_ORDER_TYPES` is `{MARKET}`. Refusing at activation beats refusing at execution. |
| A rule with no stop | `ruledoc.validate`: a rule without a stop has no defined risk. |

## A correction worth recording

`trailingStop` and `breakEven` were refused when enabled, on the grounds that
"no platform runtime path trails broker stops yet". That was true of the
platform and false of the product: the engine the platform starts has always
trailed and moved stops to break even, from the account's own settings — the
`STOP_MOVED` lines in any day's logs are it doing so. Since the rule's own
switches are now what the engine is given, refusing them would refuse two
settings that work.

The same reasoning retired the claim that `takeProfit` was allowed because
"the execution bridge already converts it into the order target price".
`bridge.py` is imported by nothing in production. A pip target is applied
because `engine_config` writes `tp_pips`, which is a different and checkable
reason.
