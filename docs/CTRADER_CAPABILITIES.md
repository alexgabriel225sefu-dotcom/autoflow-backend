# cTrader — what we use and what we do not

**Source:** direct introspection of the installed `ctrader-open-api==0.9.2`,
compared against `apex-forex-bot/apex/brokers/ctrader.py`. Nothing here is an
assumption — every field below was read out of the protobuf descriptor.

| | |
|---|---|
| Request types offered by the API | **40** |
| Used | **15** |
| Fields on `ProtoOANewOrderReq` | **23** |
| Used | **8** |
| Order types | **6** (`MARKET`, `LIMIT`, `STOP`, `STOP_LOSS_TAKE_PROFIT`, `MARKET_RANGE`, `STOP_LIMIT`) |
| Used | **1** (`MARKET`) |
| Rate limiting in the connector | **none** |

**The conclusion:** the platform is not limited by cTrader. It uses ~37% of it.

---

# PART 1 — Unused order fields

The most value for the least effort: these are fields on a message the
connector already sends. No new plumbing, no new endpoint.

| Field | What it does | Why it matters |
|---|---|---|
| `guaranteedStopLoss` | the broker **guarantees** the exit price, even across a gap | the direct answer to the NFP incident of 4 September: the stop was overshot by 11.1 pips (**51% beyond**). With a guaranteed stop, the exit would have been at price. **The most sellable field on this list.** |
| `trailingStopLoss` | trailing managed **by the broker** | today the loop moves the stop manually (the `STOP_MOVED` events, every few minutes). With trailing at the broker: fewer API requests, and **the trailing continues while the automation is stopped or being redeployed** |
| `slippageInPoints` + `baseSlippagePrice` | maximum accepted slippage (with `MARKET_RANGE`) | the order **refuses** to fill at a bad price instead of swallowing anything |
| `clientOrderId` | an idempotency key **at the broker** | the idempotency ledger already exists in the code; the broker offers one natively. Double protection against duplicate orders |
| `label` / `comment` | a label on the order | orders become identifiable in the cTrader interface and in the broker's reports — the client sees their trades marked |
| `limitPrice` / `stopPrice` | the price for pending orders | see Part 3 |
| `timeInForce` / `expirationTimestamp` | how long the order lives | an order that expires by itself if the setup does not materialise |
| `stopTriggerMethod` | trigger on bid / ask / trade | avoids false triggers on a widened spread |
| `relativeStopLoss` / `relativeTakeProfit` | SL/TP relative to the fill | **careful:** the comment in the code says these failed with "invalid precision" on non-FX. That is why the absolute amend is done after the fill. Check before retrying. |

---

# PART 2 — The 25 unused requests

The mandatory fields are the real ones from the descriptor.
`ctidTraderAccountId` is implicit everywhere (the connector has it as
`self._ctid()`).

## HIGH priority — these close bugs or sell the platform

### `ProtoOAOrderListReq` → `Res`
`fromTimestamp`, `toTimestamp`
The history of **orders**, including rejected and cancelled ones.
**Why it matters:** the journal reads only **deals**. A rejected order produces
no deal, so it is invisible — exactly why the two USDCHF orders of
6 September disappeared silently. This would have shown them immediately.

### `ProtoOAExpectedMarginReq` → `Res`
`symbolId`, optional `volume`
The margin required **before** the order is sent.
**Why it matters:** it would have caught the overshoot on XAUUSD (3.01% real
risk against a 2.48% target, because of the minimum lot) **before** entry, not
after.

### `ProtoOAMarginCallListReq` → `Res` · `ProtoOAMarginCallUpdateReq` → `Res`
`marginCall` (for the update)
The broker's margin call thresholds, and updating them.
**Why it matters:** a real, verifiable safety net that can be stated honestly
in marketing. It is not a promise of profit — it is a protection.

### `ProtoOACashFlowHistoryListReq` → `Res` — ⚠️ DELIBERATELY FORBIDDEN
`fromTimestamp`, `toTimestamp`
Deposits, withdrawals, swap, commissions.

**DO NOT IMPLEMENT IT without the owner's decision.**
`tests/test_positioning_claims.py` explicitly forbids the string
`CashFlowHistory` anywhere in `apex/`, so that *"we cannot touch your money"*
is a **structural fact**, not a promise: the platform does not merely refrain
from moving money — it does not even look at its movements.

**The real tension:** without it, P&L is incomplete — overnight swap and
commissions do not appear in the journal, and a client comparing against the
broker's statement will find discrepancies.

It is a positioning trade-off, not a technical one: **complete accounting**
against **"we do not even look"**. The owner decides. If they choose the
accounting, the positioning test must be updated in the same commit, with the
reason written down.

### `ProtoOASubscribeLiveTrendbarReq` → `Res`
`period`, `symbolId`
Candles **pushed** by the server, rather than requested.
**Why it matters:** it removes most of the pressure on the limit of 5 historical
requests/second. A practical precondition for having more clients.

## MEDIUM priority — new capabilities

### `ProtoOASubscribeDepthQuotesReq` / `ProtoOAUnsubscribeDepthQuotesReq`
optional `symbolId`
Order book depth.
**Why it matters:** you measure real liquidity before entry and refuse trades
the market cannot absorb. **No retail automation does this.**

### `ProtoOAAmendOrderReq` / `ProtoOACancelOrderReq` → an event (not a `Res`)
`orderId`; the amend accepts `volume`, `limitPrice`, `stopPrice`, `expirationTimestamp`
Modify or cancel a pending order.
**Careful:** these answer with a `ProtoOAExecutionEvent`, not with a `Res` — use
the same terminal-event wait as `place_order`.

### `ProtoOAGetTickDataReq` → `Res`
`symbolId`, `type`, `fromTimestamp`, `toTimestamp`
Tick-level history.
**Why it matters:** real backtesting. The current one uses candles.

### `ProtoOADealListByPositionIdReq` · `ProtoOAOrderListByPositionIdReq`
`positionId` (+ an interval for the first)
All the deals/orders of one position.
**Why it matters:** a position built out of several fills is currently
reconstructed by guesswork. These give it exactly.

### `ProtoOADealOffsetListReq` → `Res`
`dealId`
Which deal closed which deal.
**Why it matters:** required for a correct tax report (FIFO). Without it, the
report is an approximation.

### `ProtoOAAssetListReq` · `ProtoOAAssetClassListReq` · `ProtoOASymbolCategoryListReq`
the account only
The complete instrument universe.
**Why it matters:** we trade **8 pairs**. The connector already downloads the
entire list from the broker (`ProtoOASymbolsListReq`, line ~389) and throws it
away: indices, commodities, CFD shares. Widening the universe is configuration,
not new code.

## LOW priority — utilities

| Request | Fields | Note |
|---|---|---|
| `ProtoOASymbolsForConversionReq` | `firstAssetId`, `lastAssetId` | correct currency conversion for non-USD accounts |
| `ProtoOAGetCtidProfileByTokenReq` | `accessToken` | the client's profile (name, id) |
| `ProtoOAOrderDetailsReq` | `orderId` | the details of a single order |
| `ProtoOAUnsubscribeSpotsReq` / `UnsubscribeLiveTrendbarReq` | `symbolId` / `period` | unsubscribe — hygiene when the universe changes |
| `ProtoOAAccountLogoutReq` | the account | a clean disconnect |
| `ProtoOAVersionReq` | — | the API version |
| `ProtoOARefreshTokenReq` | `refreshToken` | **already handled** in `apex/ctrader_oauth.py` — not a gap |

---

# PART 3 — The order types

Only `MARKET` is used.

| Type | What it allows |
|---|---|
| `MARKET_RANGE` | a market order that refuses to fill beyond the maximum slippage |
| `LIMIT` | entry at a better price, **watched by the broker** |
| `STOP` | entry on a breakout beyond a level |
| `STOP_LIMIT` | a breakout, but with a maximum accepted price |
| `STOP_LOSS_TAKE_PROFIT` | a pure protection order |

**The architectural change:** today the automation has to be **awake at exactly
the right moment**, and the loop runs every few seconds. With pending orders,
the strategy places the order at the level and **the broker waits**. Fewer
missed setups, less dependence on uptime, fewer API requests.

---

# PART 4 — ⚠️ The hole to plug first

**The connector has no rate limiting at all.** None.

cTrader enforces **5 historical requests/second** and 50 non-historical/second
**per connection, regardless of how many clients** use it.

With one user it works by luck. This is not a feature to add later — it is the
precondition for the platform to support a second client.

---

# THE RECOMMENDED ORDER OF WORK

| # | What | Why now |
|---|---|---|
| 1 | ✅ **Rate limiter** — DELIVERED | sliding window, per connection, two budgets |
| 2 | **`guaranteedStopLoss` + `slippageInPoints`** | one field each, the most visible value |
| 3 | **`trailingStopLoss` at the broker** | removes the `STOP_MOVED` loop; the trailing survives restarts |
| 4 | **`ProtoOAOrderListReq` in the journal** | makes rejected orders visible; closes the USDCHF class of bug |
| 5 | **`ProtoOAExpectedMarginReq`** before every order | catches risk overshoots before entry |
| 6 | **`clientOrderId`** | idempotency at the broker, on top of the one in the code |
| 7 | **Pending orders** (`LIMIT`/`STOP`) | the architectural change |
| 8 | ~~`CashFlowHistoryList`~~ | **blocked by a product guarantee** — see Part 2. A positioning decision, not an engineering one. |

Steps 2–6 are fields and requests on infrastructure that already exists. OAuth,
protobuf, reconnection and pagination are written and tested.

## Rules for agents

- **The zone:** everything to do with this lives in
  `apex-forex-bot/apex/brokers/`. One agent in there at a time.
- **`gates.authorize_order` / `authorize_close` remain the only gates** to an
  order. No new capability bypasses them.
- Every new capability needs a test in `tests/`, not in `apex/`.
- The full suite must pass before a commit.
- Messages that answer with an **event** (`AmendOrder`, `CancelOrder`) need the
  same terminal-event wait as `place_order` — see `_is_terminal_execution`.
