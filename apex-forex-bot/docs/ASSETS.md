# What Apex trades, and why not more

**Forex only.** Spot FX majors with a USD leg, plus metals — on one cTrader
account, through one connection, behind one set of safety gates.

There is no asset-class question and no `/assets` command. There is one class,
so there is nothing to choose.

---

## The list

| Class | Examples | Traded |
|---|---|---|
| Spot FX with a USD leg | EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD | ✅ |
| Metals | XAUUSD, XAGUSD, XPTUSD, XPDUSD | ✅ |
| FX crosses without a USD leg | GBPJPY, EURGBP, AUDCHF | ❌ |
| Crypto CFDs | BTCUSD, ETHUSD, SOLUSD… | ❌ |
| Indices | US30, NAS100, GER40, JPN225 | ❌ |
| Stock / ETF CFDs | AAPL, TSLA, SPY | ❌ |

`forex.is_tradeable()` is the single gate. Every entry path — Auto-Pilot,
`/symbol`, `/watch`, manual `/buy`, MCP `open_trade`, the Mini App — goes
through it, so a refusal cannot be routed around by picking a different
interface.

The Auto-Pilot universe (`cfg.FX_UNIVERSE`) is a subset of what is *tradeable*:
it is a budget, not a whitelist. The broker connection is a single socket with
a lock held across each round-trip, so every extra symbol lengthens the tick.

---

## Why each refusal exists

These are not caution. Each one is a specific way the bot would be **wrong
without saying so** — which is worse than a refused order.

**Crypto — the product was retired.** It is refused at the instrument gate
rather than merely left out of the universe, because a stored watchlist, a
typed `/symbol`, or an Auto-Pilot basket saved during the period when the
merged build offered crypto would otherwise put a coin straight back into the
order path. `cfg.CROSS_PRODUCT_BLOCK` additionally scrubs such symbols out of
stored user records on load, so an old account self-heals instead of carrying
a dead slot in its scan budget.

**Indices, stocks and ETFs — no trading calendars.** FX is one continuous
session Sunday evening to Friday evening, and `forex.is_market_open()` models
exactly that. Equity indices are not: Frankfurt is 08:00–16:30 UTC, US cash
equities 14:30–21:00, Tokyo 00:00–06:00, and every exchange has its own
holidays. The bot would believe Frankfurt is open at 03:00 and send orders
into a closed book.

**FX crosses without a USD leg — no quote-currency conversion.**
`forex.calc_units()` accepts a `quote_usd_rate` and **nothing passes one**.
For USD-quoted instruments that is harmless. For a cross it is not: the margin
cap valued one unit of GBPJPY at its raw price of ~190 (as if those were
dollars) instead of its true ~$1.21, and sized the position at roughly **1/31
of the intended risk** — $0.54 where the client had asked for $16.22 — or
refused outright as "account too small" on a smaller balance. Same defect
shape as the equities case, and it went unnoticed longer because GBPJPY was on
a quick-pick button.

Adding any of these back means adding the missing machinery first: per-exchange
calendars, a real quote→USD rate feed, and a scanning design that does not
serialise every symbol through one locked socket.

---

## Market hours — a recorded assumption

`forex.is_market_open()` treats the week as opening Sunday ~21:00 UTC and
closing Friday ~21:00 UTC, and the Friday flatten runs before that close.

This is the standard FX week, not a per-broker measurement. A broker whose
hours differ would need those bounds adjusted. The conservative failure mode if
the assumption is wrong is **no trading**, which loses opportunity rather than
money — and the weekend-gap flatten exists precisely because a position ridden
into a closed market can reopen far past its own stop.

---

## Per-instrument, never per-build

Anything that varies by instrument is resolved **from the instrument**, at the
point of use. It is never derived from a process-level product flag.

| Resolved from | Function |
|---|---|
| Leverage | `user_loop.leverage_for_symbol()` — the broker's real per-symbol tier, with a static fallback; an explicit client setting wins |
| Flash-spike threshold | `user_loop.flash_spike_pct_for()` |
| Spread ceiling (%) | `user_loop.max_spread_pct_for()` — off unless an operator sets one |
| Pip size, pip value, lot floor, rounding | `forex.pip_size()`, `pip_value_per_unit()`, `min_units()`, `round_units()` |
| Price decimals for SL/TP | `CtraderBroker._digits()` — read from the broker's symbol details |
| Volume minimum and step | `CtraderBroker._vol_rules()` — read from the broker |

This table is the rule the crypto merge broke repeatedly and the audit had to
fix four separate times: a value that describes an *instrument* was being read
off the *build*. On a single-product build such a branch is not merely
mistuned — it is dead, and its absence is silent.
