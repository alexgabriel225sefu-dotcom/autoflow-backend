# MT5 without a client-installed bridge — spike

**Status:** spike, not a feature. Nothing here is wired into the platform, no
route serves it, and the public UI makes no MT5 claim.

**Question asked:** can Apex4Traders support MetaTrader 5 with the same
experience as cTrader — web-first, phone and PC, the client connects an
account and we read it — without asking anyone to install an EA, a bridge, a
desktop connector, or run a VPS?

**Answer:** yes for reading, through a cloud vendor, at a real and stateable
privacy cost. No for execution, until several other things are true.

---

## 1. The constraint that decides everything

MetaTrader 5 has no first-party machine interface for third parties.
MetaQuotes ships:

- **MQL5** — Expert Advisors that run *inside a terminal somebody operates*.
- **Manager / Server API** — a C++/.NET library licensed **to brokers**. It
  carries root-level control of a trade server.
- **Web terminal** — a UI for humans.

There is no public MT5 REST API and therefore no MT5 API key to obtain
([metatraderapi.net, *How to Get an MT5 API Key (and Why MetaTrader Never
Gives You One)*](https://www.metatraderapi.net/blog/how-to-get-mt5-api-key/)).

So any MT5 integration is one of exactly four things, and three of them are
ruled out by the owner's constraints rather than by preference.

---

## 2. The four approaches

### Approach 1 — Broker direct API

Some individual brokers expose their own REST/FIX API alongside MT5.

| Question | Answer |
|---|---|
| Client installs anything? | No |
| Phone and PC? | Yes |
| Demo accounts? | Per broker |
| Read-only data? | Per broker |
| Candles? | Usually |
| Positions / order history? | Usually |
| Order placement? | Usually |
| Credentials | Per broker: API key, OAuth, or login |
| Credentials live | Our server |
| Vendor risk | None beyond the broker |
| Legal risk | Low — a direct relationship |
| Cost | Usually free |
| Time to MVP | Weeks **per broker** |
| Fit | Not V1 |

**Why it fails the requirement.** It is not "MT5 support", it is "support for
the six brokers we happened to integrate". Every new client asking for a
seventh broker is a new engineering project. This is the right answer
eventually for the largest two or three brokers, and the wrong shape for a
launch.

### Approach 2 — Cloud MT4/MT5 provider (e.g. MetaApi)

A vendor runs MetaTrader terminals in their own infrastructure and exposes
REST + WebSocket. The client gives us account credentials; the vendor connects
the terminal.

| Question | Answer |
|---|---|
| Client installs anything? | **No** |
| Phone and PC? | **Yes** — it is all server-side |
| Demo accounts? | Yes; the vendor can even create MT5 demo accounts |
| Read-only data? | **Yes, and enforced by the broker** — see §3 |
| Candles? | Yes — "read historical candles (OHLCV)" |
| Positions / order history? | Yes — "read trading history (deals and history orders)" |
| Order placement? | Yes — "execute trades" — *with a master password* |
| Credentials | MT5 **login + password + broker server name + platform** |
| Credentials live | **The vendor's infrastructure**, not ours |
| Vendor risk | **High** — they hold broker credentials and sit in the data path |
| Legal risk | Medium — see §5 |
| Cost | Per connected account, per month — **exact figure not obtained, must be confirmed before any commitment** |
| Time to MVP | Days for read-only |
| Fit | **V1.5 read-only, behind a flag** |

Sources:
- <https://metaapi.cloud/docs/client/> — "a powerful, fast, cost-efficient,
  easy to use and standards-driven cloud forex trading API for MetaTrader 4
  and MetaTrader 5 platform", via "standard-based REST and Websocket APIs".
- <https://metaapi.cloud/docs/provisioning/api/account/createAccount/> — the
  account-creation contract and the password semantics quoted in §3.
- <https://metaapi.cloud/docs/provisioning/api/generateAccount/createMT5DemoAccount/>
  — MT5 demo account creation.
- <https://github.com/metaapi/metaapi-python-sdk/blob/main/docs/metaApi/managingAccounts.rst>
  — SDK docs, same password note.

### Approach 3 — MT5 terminal / EA / local bridge / VPS

The client runs MetaTrader with our EA, or we run one per client on a VPS.

| Question | Answer |
|---|---|
| Client installs anything? | **Yes** — the thing we were told to avoid |
| Phone and PC? | **No.** MT5 desktop is Windows; a phone cannot host it |
| Demo accounts? | Yes |
| Read-only / candles / history / orders | Yes, all |
| Credentials | None leave the client's machine — **its one real advantage** |
| Vendor risk | None |
| Legal risk | Low |
| Cost | Our VPS fleet, or the client's patience |
| Time to MVP | Weeks, then permanent operational burden |
| Fit | **Rejected** |

**Why it is rejected.** It fails the stated requirement outright. Worth
recording that it is the only approach where the client's broker password
never leaves their own machine — so if the privacy cost in §5 is ever judged
unacceptable, this is what the alternative looks like, and it is expensive.

### Approach 4 — MT Manager API / broker partnership

| Question | Answer |
|---|---|
| Client installs anything? | No |
| Phone and PC? | Yes |
| Everything else | Yes — it is the most capable option by far |
| Credentials | A broker-issued manager account |
| Credentials live | Our server |
| Vendor risk | Extreme — manager access is **root on the broker's trade server** |
| Legal risk | **High** — contracts, and likely regulatory scope |
| Cost | Commercial negotiation |
| Time to MVP | Months, mostly not engineering |
| Fit | **Not now.** Possibly V2+, one broker at a time |

Manager/Server API is licensed to brokers, and essentially no retail broker
grants it to an outside SaaS ([b2broker, *Web API for MetaTrader*](https://b2broker.com/news/web-api-for-metatrader-how-does-it-work/)).
It is not a path a new platform can take.

---

## 3. The finding that makes this safe to try

MetaApi's account provisioning documents the password field as:

> "The password can be either **investor password for read-only access** or
> master password to enable trading features. Required for cloud account"
>
> — <https://metaapi.cloud/docs/provisioning/api/account/createAccount/>

This matters more than any code we could write.

An **investor password** is an MT4/MT5 credential that grants *viewing* —
balance, open positions, history — and **cannot place, modify or close an
order**. The refusal happens at the broker's trade server.

So a read-only MT5 connector is not read-only because our code has a flag
saying so. It is read-only because the credential cannot trade. That property
survives:

- a bug in our connector,
- a mistake in the platform's gates,
- a compromise of our vendor account,
- a compromise of the vendor.

A software flag survives none of those. This is the difference between a
safety claim and a safety property, and it is the reason this spike is worth
doing at all.

---

## 4. Recommendation

**Do this, in this order:**

1. **Read-only MT5 through MetaApi, investor password only, behind two env
   flags** (`A4T_MT5_SPIKE_ENABLED`, `A4T_MT5_SPIKE_VERIFIED`). Skeleton and
   safety gates are in this commit. No UI, no route, no credential collection.
2. **Prove it against one real MT5 demo account** before writing a line of
   UI — the shortest proof is in §8.
3. **Only then** design credential collection, which needs its own review: we
   would be asking clients to type a broker password into our web app.
4. **Execution stays out of scope** until there is a separate decision with
   its own gate. It requires a master password, which discards the entire
   safety argument in §3.

**Do not** pursue Manager API or per-broker APIs now.

---

## 5. Risks, stated rather than managed away

**Privacy — the big one.** The client hands a broker credential to a third
party. Even an investor password discloses every position, order and balance
to MetaApi and to us. This must be said to the client in the words above, not
buried in terms. Compare cTrader, where OAuth means the client's password
never leaves cTrader — the MT5 experience is *worse* on exactly the axis
clients care about, and we should not pretend otherwise.

**No scoped revocation.** An investor password cannot be revoked per
integration. The only revocation is changing it at the broker, which also
breaks every other tool the client uses it with.

**Vendor in the data path.** Their outage is our outage; their breach exposes
our clients' credentials. This is a dependency of a different character from,
say, a charting library.

**Cost.** Per-account, per-month. The exact figure was **not** obtained from a
primary source during this spike and must be confirmed before any commitment:
a per-account fee interacts badly with a free tier or a trial.

**Compliance.** Storing third-party broker credentials, even read-only ones,
is a category of data handling the platform does not currently do. Worth legal
input before collection, not after.

**Support surface.** "Which server name?" is a question most retail clients
cannot answer without being walked through it. Expect this to be the single
largest source of failed connections.

---

## 6. Where this fits

| Release | Scope |
|---|---|
| **V1** | cTrader only. MT5 absent from the UI entirely. |
| **V1.5** | MT5 **read-only** behind flags, proven on a demo account, credential model reviewed, client warned explicitly. |
| **V2** | Reconsider execution — separate decision, separate gate, master password, and everything in §5 re-argued. |

---

## 7. The connector contract

`apex/platform/brokers/base.py`. cTrader and MT5 plug into the same platform
surface so the risk gates are not duplicated — the details are in that file's
docstring, which is the authoritative version.

The shape:

```
capabilities()                                    -> Capabilities
list_accounts(user_id)
get_account_status(user_id, account_id)
get_positions(user_id, account_id)
get_orders(user_id, account_id)
get_candles(user_id, account_id, symbol, timeframe, limit)
```

`Capabilities` carries `supports_preview`, `supports_automation`,
`can_place_orders`, `credential_model` and `verified`. Every field is
required: a provider that forgets to say whether it can place orders fails to
construct, rather than inheriting a default that somebody later "fixes".

**There is no `place_order` in the contract.** That absence is the design.
Adding one is a reviewed edit to `base.py`, not something a provider can do by
defining a method.

`supports_automation` is False for MT5 read-only, because automation ends in
an order. `supports_preview` is True, because preview evaluates a rule and
decides nothing.

---

## 8. The shortest path to a real MT5 demo proof

1. Open a **demo** MT5 account at any broker. Note login, **investor**
   password, and the exact server name.
2. Create a MetaApi account; confirm current pricing and free-tier limits
   (§5 — this was not established here).
3. Add the account to MetaApi **using the investor password**, out of band —
   not through Apex4Traders, which has no UI for it.
4. Confirm by hand that their API returns account state, positions and
   candles, and that an order request is **refused** — that refusal is the
   whole safety argument, so it should be observed rather than assumed.
5. Only then implement `Mt5CloudProvider`'s accessors against their REST API,
   with tests driven by recorded fixtures.
6. Set `A4T_MT5_SPIKE_VERIFIED` only after step 4 has actually been seen.

Steps 1–4 involve no Apex4Traders code and need nothing committed.

---

## 9. Secrets and environment, for later

None of these exist yet and none are in the repo.

| Variable | Purpose |
|---|---|
| `A4T_MT5_SPIKE_ENABLED` | Admits the provider at all. Off by default. |
| `A4T_MT5_SPIKE_VERIFIED` | Asserts a human has proven the path in this deployment. Off by default; does **not** follow from `ENABLED`. |
| `A4T_MT5_VENDOR_TOKEN` | The vendor API token. **Not yet used.** |
| `A4T_MT5_VENDOR_BASE_URL` | Vendor endpoint, so it can be pointed at a fake in tests. |

Client MT5 credentials would live in the **vendor's** infrastructure, not
ours. If we ever hold them, they go through `user_store`'s encrypted fields
like every other credential, and that is a separate review.

---

## 10. What is deliberately not here

- No UI, no route, no navigation entry.
- No credential collection.
- No call to any real vendor API.
- No claim of MT5 support anywhere a client can see.

`tests/test_platform_provider_safety.py` enforces the last one: it fails if
the web source mentions MT5 at all, or if any platform module outside the
package imports a provider.
