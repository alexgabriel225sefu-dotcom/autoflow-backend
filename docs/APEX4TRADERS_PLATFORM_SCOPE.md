# Apex4Traders — what it is, what it does, and where it stops

Scope document. It describes the platform as it is, not as it might become.

---

## 1. What Apex4Traders is

**A platform for building and controlling trading automation rules.** A client
builds rules from named conditions with published formulas, sees exactly what
each rule would decide before starting it, and can stop it at any moment.

### What it is not

| Not | Why the distinction matters |
|---|---|
| **A Telegram bot** | Telegram is not the login, not the identity, not the control surface, and not required for any function. A client without a Telegram account uses the platform in full. |
| **A broker** | We hold no money, open no accounts, and are not a counterparty. The trading account belongs to the client, at their broker, through cTrader. |
| **A signal service** | We send no recommendations. The platform executes the rules a client writes; if the rule is silent, the platform is silent. |
| **Investment advice** | We do not assess whether a strategy suits anyone, promise no returns, and publish no performance statistics. |

### cTrader is infrastructure, not the product

cTrader is the layer through which the platform connects to the client's
account, reads market data, and — once the client starts automation — sends
orders. The client sees it once, at connection time. It is not the brand and
not the interface, and it is not hidden either: the connection screen states
plainly that execution happens through a cTrader account the client connects
and can disconnect.

---

## 2. What is implemented today

| Capability | State | Notes |
|---|---|---|
| **Supabase Auth** | complete | Email and password, confirmation, reset. The platform identity is `supabase_user_id`. |
| **cTrader OAuth** | complete | Three-step flow with an authenticated completion. Tokens are encrypted at rest and never reach the frontend. |
| **Accounts** | complete | List connected accounts, select one, disconnect; demo and live marked explicitly. |
| **Positions** | read-only | Open positions, with the account and its mode. |
| **Orders** | read-only | Pending orders. |
| **Candles** | read-only | Market data for preview, through the same connector and the same cache the execution engine uses. |
| **RuleDoc / Rule Builder** | complete | 12 conditions, validation, activation that freezes a version, versioning. |
| **Preview on real data** | complete | Evaluates a rule against candles fetched from the connected account. Places nothing, records nothing. |
| **Journal** | complete | 12 distinct statuses; filter by account, instrument, period, rule and status; paged. |
| **Notifications** | complete | An in-platform centre. No Telegram. |
| **Demo automation** | complete | Start, pause, resume, stop — demo accounts only. Idempotent and journalled. |

The web client has **18 platform pages**: landing, sign up, login, email
confirmation, password reset, auth callback, dashboard, licence, connect
cTrader, accounts, rules, rule builder, rule detail, positions, orders,
journal, notifications, settings. Each is backed by a real endpoint; no screen
shows fabricated data. (The project also carries pre-existing `terms`,
`privacy` and `configurator` pages from outside the platform.)

---

## 3. What is not implemented

| Missing | Detail |
|---|---|
| **Live trading** | Not "disabled" — **not implemented**. No branch of code starts a live loop. |
| **Public deployment** | The platform runs locally and in staging. It is not published. |
| **Payments / commercial licensing** | `licence.grant()` is called manually on the server. There is no checkout, billing or renewal. |
| **Real execution on a live account** | See V2 and V3 below. |
| **Physical removal of the legacy Telegram code** | The legacy code exists and still works. See below. |

### Why the Telegram code was not deleted

`apex/telegram.py` (6742 lines), `apex/ctrader_oauth.py` and the `chat_id`-keyed
stores are intact, because **clients onboarded through Telegram have their
tokens stored there** and deleting it would strand them.

What was done instead:

- `apex/ctrader_oauth.py` carries a **DEPRECATED** header explaining why it
  could not be reused: it is keyed by `chat_id`, it signs the OAuth state with
  the bot token, and it completes the account link inside the callback.
- A test asserts through the AST that **no module in `apex/platform/` imports
  telegram** — across the whole package, not only the file someone happened to
  look at.
- A deployment with no `TELEGRAM_BOT_TOKEN` runs the platform in full.

The old code is **legacy and not part of Apex4Traders v1.**

---

## 4. What the cTrader Open API can do

The distinction that matters here is not "what cTrader allows" — it allows
everything below. It is **what we exposed**, and especially what we wired but
deliberately did not expose.

| cTrader capability | Our connector | Exposed by platform v1 |
|---|---|---|
| **OAuth** (authorize, token, refresh) | yes | **yes** — the connection flow |
| **List accounts** | yes | **yes** — `/accounts` |
| **Market data** (trendbars, bid/ask) | yes | **partly** — candles yes, live quotes no |
| **Positions** | yes | **yes**, read-only |
| **Orders** | yes | **yes**, read-only |
| **Place order** | yes | **through the engine only** — no platform endpoint places an order directly |
| **Close position** | yes | **no** — no endpoint closes a position |
| **Amend SL/TP** | yes | **no** |
| **History** (deal history) | yes | **no** — the platform journal is separate and covers its own decisions |
| **Balance / equity** | yes | **partly** — balance via `/accounts/{id}`; live equity no |

The middle column is full. The right-hand one is not, and that is deliberate:
every exposed capability is a surface that must be guarded, and the ones that
add nothing to v1 stay unwired.

---

## 5. Versions

### V1 — demo / paper platform *(current)*

A client signs up, connects a cTrader demo account, builds rules, previews them
on real data, starts automation on demo, and sees everything in the journal.
Nothing touches real money.

### V2 — real execution on a cTrader demo account

Orders actually reach cTrader on the demo account, through the existing engine.
The difference from V1 is not a new feature but **earned confidence**: the
journal has to show that every order sent was the one the rule asked for, with
the stop the rule asked for.

### V3 — live trading

Only after an **audit** and **legal review**. This is not a checkbox: it
requires reviewing the execution path, the risk limits, the terms of service,
and the regulatory obligations of the jurisdiction being operated in.

---

## 6. About execution — stated plainly

**The platform can, technically, place orders through cTrader.** The connector
has `place_order`, `close_position` and `amend_sltp`, and the engine uses them.
Claiming otherwise would be untrue.

**In the current version live trading is not enabled.** Three independent
refusals stand in the way, and each is covered by tests:

1. `ctrader_link.live_allowed()` requires `APP_ENV=production` **and**
   `APEX_ALLOW_LIVE_ACCOUNTS=true`. Neither alone is enough.
2. Selecting a live account is refused when that is false — for reading too,
   not only for trading.
3. `automation._preflight()` refuses any account whose mode is not `demo`.

**Every execution goes through the same chain.** No exceptions, no shortcuts:

- `ownership.may_trade` — the instance asking is the one that owns the account;
- `gates.authorize_order` — entitlement, broker environment, risk, limits;
- `gates.audit` — the gate's decision is recorded;
- `ledger.claim` / `record` — idempotency, taken **before** the broker call;
- only then `broker.place_order`;
- and all of it lands in the journal, refusals included.

**There is no parallel path to the broker.** The platform modules import no
broker, no gate and no ledger — they hand the work to the controller that
already has them. Tests that walk the AST assert this for `broker_read.py`,
`preview.py`, `bridge.py` and `automation.py`: the absence of those calls is a
property of the code, not a promise in a comment.

---

## 7. Diagram

```
   ┌──────────┐
   │   User   │  browser, Apex4Traders
   └────┬─────┘
        │  Supabase session (Bearer)
        ▼
   ┌──────────────────┐
   │  Apex Platform   │  /api/v1 — auth, ownership, licence
   │                  │  RuleDoc, journal, notifications
   └────┬─────────────┘
        │  RuleDoc + MarketSnapshot
        ▼
   ┌──────────────────┐
   │   Rule Engine    │  pure evaluator — no clock, no network
   │                  │  Decision: BUY / SELL / CLOSE / HOLD / REJECT
   └────┬─────────────┘
        │  ExecutionRequest   (only BUY and SELL get this far)
        ▼
   ┌──────────────────┐
   │   Risk Gates     │  ownership · authorize_order · audit · ledger
   │                  │  any refusal stops here and is journalled
   └────┬─────────────┘
        │
        ▼
   ┌──────────────────┐
   │   cTrader API    │  connection · data · execution
   └──────────────────┘
```

HOLD, REJECT, an invalid configuration or a constraint that cannot be honoured
all stop **before** the gates. They never become an order.

---

## 8. What we tell the client

- Apex4Traders executes rules you configure yourself.
- It is not financial advice and we do not manage money.
- Execution happens through a cTrader account you connect and can disconnect at
  any time.
- Trading carries risk, including the loss of your capital.
- We promise no returns and publish no performance statistics.
