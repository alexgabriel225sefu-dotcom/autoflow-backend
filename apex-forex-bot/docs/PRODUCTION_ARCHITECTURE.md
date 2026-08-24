# Apex — Production Architecture

**Status of this document: ACTIVE.** It describes what the executable code
does. Where it disagrees with the code, the code is right and this file is a
bug — the whole point of writing it down is that the two can be compared.

**One product: FOREX.** One trading domain, one execution pipeline, one
deployable trading service.

---

## 1. Services

| Service | State | What it is | Deployed by |
|---|---|---|---|
| `apex-forex-bot/` | **ACTIVE** | The trading bot. Python, cTrader Open API, Telegram-controlled. The only thing that can place an order. | `apex-forex-bot/render.yaml` (Render web service, `rootDir: apex-forex-bot`, `buildFilter: apex-forex-bot/**`) |
| `server.js` + `public/` | **ACTIVE** | Sales site, Stripe checkout, licence issuance and verification. Places no orders. | root `render.yaml` (Render, `node server.js`) |
| `ruflo-mcp/` | **ACTIVE** | Operator MCP server. Read-mostly control plane; financial actions route through the bot's own gates. | `ruflo-mcp/render.yaml` |
| `web/`, `html/`, `my-video/`, `freelance-projects/`, `scripts/` | **NOT FOR PRODUCTION** | Marketing assets, experiments and one-off scripts. Nothing deploys them. | — |

**REMOVED** (deleted, not archived — git history holds them): `apex-crypto-bot/`,
`apex-trade-bot/`, `apex-trade-api/`, `apex-trade-web/`, `apex-trade-mobile/`,
`apex-trade-ml/`, the root `railway.json`, and `.github/workflows/deploy-bot.yml`.
Each was a second trading implementation or a way to deploy one. See §9.

---

## 2. The order pipeline — the only way an order reaches a broker

Every interface converges here. `broker.place_order()` is called from exactly
two places in `user_loop.py`, both immediately after `gates.authorize_order()`
returns allowed.

```
Telegram  ─┐
MCP        │
Mini App   ├──> user_loop.force_trade()  ─┐
Voice      │                              │
AI assist ─┘                              ├──> gates.authorize_order()
                                          │      1 identity (server-derived)
Auto-Pilot / strategy ────────────────────┘      2 entitlement / licence
                                                 3 risk guard
                                                 4 ownership lease
                                                 5 idempotency claim
                                                        │
                                                        v
                                              broker.place_order()
                                                        │
                                                        v
                                              ledger.record() + audit event
                                                        │
                                                        v
                                              persisted position snapshot
```

**No interface has its own broker path.** Verified: `miniapp_api.py`,
`voice_api.py`, `ops_api.py`, `control_actions.py` and `ruflo-mcp/` contain no
`place_order`, no `close_position` and no broker construction. They call
`force_trade` / `force_close` like everything else.

Closes converge the same way on `gates.authorize_close()` — user close,
Telegram, MCP, Mini App, strategy exit, protective stop, weekend flatten,
emergency sweep and restart recovery.

`authorize_close` deliberately has **different** semantics from
`authorize_order`: refusing to close is not the safe direction. It still
enforces ownership and idempotency, but a close is never refused for reasons
that only make sense when opening risk.

---

## 3. Fail-closed rules

The governing principle: **UNKNOWN is not SAFE.** Where the system cannot
determine an answer, it refuses — except where refusing would itself be the
harm, and those exceptions are listed.

| Condition | Behaviour | Where |
|---|---|---|
| `PRODUCT` is not `forex` | **startup refused** | `config.py` |
| `TOKEN_ENCRYPTION_KEY` unset in production | **startup refused** | `user_store.py` |
| No shared Redis backend in production | **startup refused** | `user_store.py` |
| `JWT_SECRET` unset in production | **startup refused** | `server.js` |
| No secret for config encryption | **refuses to encrypt/decrypt** | `server.js::_botConfigKey` |
| Stateless OAuth callback in production | **startup refused** | `ctrader_oauth.py` |
| Licence store unreachable, first activation | **503 → deny** | `server.js::/api/verify-license` |
| Licence verifier unreachable, first activation | **deny** | `telegram.py::_license_ok` |
| Ownership lease unreadable, live account | **no order** | `gates.authorize_order` |
| Redis unreachable, live account | **no order** (`COORDINATION_UNAVAILABLE`) | `ledger.claim(fail_closed=True)` |
| Entitlement unknown | **no order** | `gates.authorize_order` |
| Instrument not `forex.is_tradeable` | **no order** | every entry path |
| Minimum lot would exceed configured risk | **no order** | `forex.floor_risk_ok` |
| Broker response ambiguous after an order | **no retry**, reconcile first | `broker_result_ambiguous` |

### The two deliberate fail-OPEN paths

Both are documented at the point of decision, because an undocumented
asymmetry gets "fixed" into a symmetry by the next person.

1. **Licence revalidation** (`telegram.py::_revalidate_license`). A client who
   has already been verified keeps access when the verifier cannot answer.
   Only an explicit `{valid:false}` on a **2xx** revokes. A 5xx does not —
   the licence endpoint answers 503 with that same body when its store is
   unreachable, and reading the body without the status would revoke every
   paying customer for the length of an outage.
2. **News / calendar feeds** (`news.py`, `cot.py`). An unreachable calendar
   does not halt trading. It does not grant anything either — it removes a
   restriction, and the risk guards are unaffected.

The first activation of a stranger and the revalidation of a known client
therefore fail in **opposite directions**, and that is correct: unknown means
"no new information" in both cases; it just points different ways depending on
whether the party has ever been verified.

---

## 4. Licence lifecycle

```
Stripe checkout ('apex-forex' — the only SKU)
      │
      v
webhook ──> _fulfillOrder()
              │  refuses any product that is not 'apex-forex' and alerts the
              │  operator; it does NOT mint a key for an unknown product
              v
        licences table (active:true written ONLY here, on payment)
              │
              v
        FORX-XXXX-XXXX-XXXX emailed with a Telegram deep link
              │
              v
        /start FORX-… ──> _license_ok() ──> POST /api/verify-license
                                              1 HMAC signature
                                              2 licences row: refunded?
                                                trial expired? not paid?
                                              3 store unreachable → 503
```

A valid HMAC signature is **not** proof of payment — a refunded customer, an
expired trial and an abandoned checkout all hold a permanently valid
signature. Only the licences row knows, which is why an unreachable store
denies rather than falls through.

`APEX-` keys (the retired crypto product) are no longer minted **or verified**.

---

## 5. Demo vs live

`paper` is not the broker environment. Four separate facts:

| Fact | Stored as | Meaning |
|---|---|---|
| Broker | `broker` | which adapter |
| Account | `ctrader_account_id` | which account at that broker |
| Environment | `ctrader_env` | `demo` or `live` — the broker's own answer |
| Execution mode | `paper` | simulated fills vs real orders |

Live requires an explicit, persistent activation step the client takes
themselves. It is never a side effect of connecting an account, and the
onboarding mode buttons cannot reach it (`ob:mode:real` maps to
`_handle_paper(off)`, not to live activation).

An unknown account environment or unknown live entitlement means **no live
orders**.

---

## 6. Redis / Upstash

Redis is production coordination, not a cache. It holds:

- **ownership leases** — which container manages which account (Lua CAS renewal)
- **order idempotency claims** — `SET NX`, cross-container
- **entitlement and access state**
- **critical user fields** — compare-and-set with `expect_version`; the
  allowlist is `user_store.CRITICAL_FIELDS` and includes
  `open_position_snapshot`, the record of a live position across a restart

A local JSON store is **development only** and startup refuses it outside a
declared dev environment: per-container entitlement, ownership and idempotency
are worse than none, because they look like they work.

---

## 7. Position recovery and multi-instance

**The broker is authoritative for position state.** Local state is a cache
that can be stale or wrong.

On restart, `recovery_verdict(live_position, got_answer)` returns one of:

- `ADOPT` — broker has a position we did not know about; take it over
- `KEEP_TRACKED` — we could not get an answer; keep managing, do not assume
- `CONFIRMED_CLOSED` — broker confirms flat; journal the close

Assume Render runs more than one instance. One logical owner per account,
enforced by the ownership lease, revalidated **at the last possible moment**
before each order — the deploy overlap is measured in seconds and so is the
gap between lease renewal and order submission.

A lost broker response is never blindly retried: `broker_result_ambiguous()`
routes it to a screen with no retry button, and reconciliation decides.

---

## 8. Required environment

Startup fails without these in production.

**`apex-forex-bot`**: `PRODUCT=forex`, `TELEGRAM_BOT_TOKEN`,
`TOKEN_ENCRYPTION_KEY`, `ADMIN_CHAT_IDS` (or `ADMIN_CHAT_ID`), and a shared
Redis (`REDIS_URL` or `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`).

**`server.js`**: `JWT_SECRET`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `BOT_EMAIL_SECRET`,
`ADMIN_CHAT_ID` and/or `ADMIN_EMAIL` (without at least one, operator alerts
are undeliverable and say so loudly).

No production secret has a fallback value. No admin identity is hardcoded —
operators come from `ADMIN_CHAT_IDS` / `ADMIN_CHAT_ID` / `TELEGRAM_CHAT_ID`,
and an empty admin list is reported at startup rather than defaulted.

---

## 9. What was removed, and why it could not stay

| Removed | Why |
|---|---|
| `apex-crypto-bot/` | Retired product. Deleted rather than disabled — a disabled mode is still a mode. |
| `apex-trade-bot/` | Node exchange bot (Binance, Bybit, OKX, KuCoin, Kraken…). CI published it as the customer-facing `apex-crypto` image and the sales site handed buyers a Railway command to deploy it. |
| `apex-trade-api/` | Fell back to a JWT secret committed in this repository, only **warned** about missing required vars instead of refusing to start, and **auto-started a live Binance trading engine on boot** when API keys were present — no licence, ownership, idempotency or risk gate. |
| `apex-trade-web/`, `-mobile/`, `-ml/` | The rest of that stack. |
| root `railway.json` | Deployed `apex-trade-api`. |
| `.github/workflows/deploy-bot.yml` | Deployed `apex-trade-bot` to an Oracle Cloud VM. |
| `/bot-access` route | Streamed trading-bot source as a ZIP to any holder of an HMAC-valid key. |
| `apex/sentiment.py` | The Alternative.me **crypto** Fear & Greed index, weighted 0.4 in a **forex** conviction score. |
| crypto Stripe SKU, `APEX-` key minting and verification | The bot those keys unlocked no longer exists. |

---

## 10. Known limits

Stated because a limit nobody wrote down gets rediscovered as a bug.

- **Market hours are the standard FX week**, not a per-broker measurement.
  A broker with different hours needs the bounds in `forex.is_market_open()`
  adjusted. Failure mode if wrong: no trading (loses opportunity, not money).
- **Sizing has no quote→USD conversion.** This is why FX crosses without a USD
  leg, indices and equities are refused. See `docs/ASSETS.md`.
- **Scan budget.** One broker socket, one lock held per round-trip. The
  Auto-Pilot cap is a budget on work, not a preference.
- **Existing `APEX-` licence holders** cannot be served by this product. That
  is a commercial decision, not a technical one — see the hardening report.
