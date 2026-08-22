# What Apex trades, and why not more

One bot, three asset classes: **spot FX, metals, and crypto CFDs** — on one
cTrader account, through one connection, behind one set of safety gates.

---

## The client chooses

Once the broker account is linked — and only then, because that is when the
broker's actual instrument list is known — the client is asked what they want
traded: **forex**, **crypto**, or **both**. `/assets` changes it later, and
changing it rebuilds the Auto-Pilot basket on the spot rather than leaving the
old one running behind a new label.

The default for anyone who onboarded before the question existed is **both**.
Narrowing them silently would change what their bot does without asking.

A mixed basket is interleaved rather than concatenated (EURUSD, BTCUSD,
GBPUSD, ETHUSD…). The scan cap truncates the list, so an alphabetical pool
would hand a "both" client twelve currency pairs and no crypto at all.

## The list

| Class | Examples | Traded |
|---|---|---|
| Spot FX | EURUSD, GBPUSD, USDJPY, AUDUSD… | ✅ |
| Metals | XAUUSD, XAGUSD, XPTUSD, XPDUSD | ✅ |
| Crypto CFDs | BTCUSD, ETHUSD, SOLUSD, XRPUSD… | ✅ |
| Indices | US30, NAS100, GER40, JPN225 | ❌ |
| Equities | AAPL, TSLA, and the per-country lists | ❌ |
| ETFs, forwards, perpetuals | — | ❌ |

The gate is `forex.is_tradeable()`. `forex.is_crypto()` is a narrower
whitelist used by the crypto-only build.

---

## Why crypto was added

It used to be refused here, to keep two products apart: a forex bot at €497
and a crypto bot at $297.

That separation was protecting the wrong thing. The crypto build is a fork of
the same codebase, and it had fallen behind by **eight modules and every
hardening fix**:

```
gates.py         the single gate every order clears
ledger.py        idempotency — the thing that stops a duplicate order
ownership.py     the lease that stops two containers trading one account
account_mode.py  DEMO/LIVE verified against the broker, not a stored flag
ev.py            probability measured from the account's own closed trades
callback_guard, automation, backup, alert_policy
```

So "crypto has its own bot" meant, in practice, "crypto has the older bot" —
one that could open a position twice across a redeploy. Merging retires the
fork. One instrument list, one codebase, one set of fixes.

---

## Why indices and equities are still refused

Not caution, and not effort. Two things are genuinely missing, and both fail
**silently** rather than loudly:

**Trading calendars.** `forex.is_market_open()` implements one week: open
Sunday 21:00 UTC, closed Friday 21:00 UTC. Equities do not work that way — US
cash equities are 14:30–21:00 UTC, Tokyo is 00:00–06:00, every exchange has
its own holidays. The bot would believe Frankfurt is open at 03:00 and send
orders into a closed book.

**Quote-currency conversion.** `forex.calc_units()` accepts a
`quote_usd_rate`, and nothing passes one. For USD-quoted instruments that is
harmless. For SE Equities in SEK, JP in JPY, HK in HKD, position size would be
wrong by the exchange rate — a risk calculation quietly off by 10x is worse
than a refused order.

Adding those two is what "trade everything the broker offers" actually
requires, plus a different scanning design (see below).

---

## Weekend hours — a recorded assumption

Crypto here follows the **forex week**: the market gate closes it at the
weekend, and the Friday flatten closes crypto positions along with everything
else.

That is correct for **Pepperstone**, where crypto CFDs close with the forex
week — observed by the owner on the live platform, not measured by this
codebase. It is a property of that broker's product, not of crypto.

**If a broker offers weekend crypto**, two things need to become
per-instrument rather than global:

1. `forex.is_market_open()` — currently takes only a timestamp. It would need
   the symbol.
2. The weekend flatten window in `user_loop` (`in_weekend_window`) — currently
   applies to every open position.

Until then the failure mode is conservative: no weekend crypto trading. That
costs opportunity, not money. Pinned by `tests/test_crypto_in_forex.py` §9, so
whoever changes it has to change the test and read this first.

---

## The scan cap

`autopilot_universe` is capped at **12 symbols**.

This is a limit on WORK, not a preference. The broker connection is a single
pooled socket with a lock held across each round-trip, so symbols are scanned
in series: every extra one lengthens the tick. Twelve keeps a full scan
comfortably inside the interval. Past roughly twenty, the loop becomes slower
than the signals it is looking for.

Raising it meaningfully is not a config change — it needs a cheap pre-filter
(rank by volatility and spread from a lightweight feed) so that candles are
only pulled for a shortlist. That is a project, not a constant.

---

## What changes per instrument class

| | FX / metals | Crypto |
|---|---|---|
| Default regime when unclear | mean reversion | trend following |
| Pip size | convention (0.0001 / 0.01 / 0.1) | derived from price magnitude |
| Market hours | forex week | forex week *(broker-dependent — see above)* |
| Safety gates | identical | identical |

These are decided **per symbol**, not per build. A bot holding both classes at
once cannot answer "what kind of thing is this" from a process-level flag.

The first version of this document claimed that as a general property when
only the regime default had actually been changed. An audit found the rest
still gated on `PRODUCT == "crypto"`, and each one was a case where the FX
value does not merely mistune crypto — it disables it:

| Threshold | FX value | On crypto, if left at the FX value |
|---|---|---|
| Leverage (margin cap) | 30x | Cap checks a number the broker will not use. A position the code reports as 8.7% of the account needs 52% at the broker's real 5x |
| Flash-spike guard | 1.2% | Ordinary BTC candles trip it, so entries are refused as a matter of course — the bot looks like it simply never trades crypto |
| Regime EMA separation | 0.30% | BTC clears it almost always, so its regime reads "trending" permanently and mean-reversion never fires |
| Mean-reversion trend cutoff | 0.5% | Same shape: turns mean-reversion into a trend-only engine |
| Trend pullback band | ±0.05% | Never triggers on a crypto uptrend — the bot waits forever |
| Momentum velocity | 0.3 | Mistuned rather than disabling |

All are now resolved from the instrument. The signal engines read it from the
indicator dict rather than a new argument, because the strategy dispatch table
has a fixed three-argument shape; `indicators.analyze(candles, symbol)` stamps
it, and callers that pass no symbol keep the previous behaviour exactly.

Pinned by `tests/test_crypto_in_forex.py` §10, including the arithmetic for
the margin case — so a future change that reintroduces a build-level flag
fails a test rather than quietly disabling an asset class.

---

## Adding an instrument class later

1. Widen `forex.is_tradeable()`.
2. Confirm `forex.pip_size()` is right for it — the magnitude fallback is
   usually correct, but check against the broker's own tick size.
3. If it is not USD-quoted, pass `quote_usd_rate` into `calc_units()`.
4. If it does not trade the forex week, make the market gate and the flatten
   window symbol-aware.
5. Decide its default regime.
6. Add it to `tests/test_crypto_in_forex.py`, including what must still be
   **refused**.

Steps 3 and 4 are the ones that fail quietly. Do not skip them because a first
trade looks fine — a USD-quoted instrument on a 24/5 exchange will hide both
bugs indefinitely.
