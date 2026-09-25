# Apex4Traders — live execution specification

What a live-execution milestone must contain before a single real order is
placed. **Nothing in this document is implemented, and this document does not
authorise implementing it.**

Live execution is a separate milestone with its own review. This exists so that
review has something to review, and so the current release's refusals are
understood as design rather than as unfinished work.

**Assessed against:** `d8f03196f` on `claude/apex4traders-platform-v1`.

---

## 0. Where the current release actually stands

Not "live trading is disabled". Stronger than that:

**`apex/platform/bridge.py` — the only module that can ask a broker to place an
order — is imported by nothing in production.** Its sole importer is its own
test. There is no sequence of calls from any request that arrives at
`bridge.submit`. The path is not gated; it is absent.

`tests/test_platform_live_invariants.py` proves this on the AST rather than by
grep, including the transitive import closure of `automation` and of the API,
so a module two hops away is caught as readily as a direct import. When
somebody wires the bridge up, that test fails. **That failure is the review
gate**, and it should not be "fixed" by relaxing the test.

Three further locks exist and each is tested with the other two disabled,
because the first time they were written, removing any one of them left every
test green:

| Lock | Where | What it decides |
|---|---|---|
| 1 | `ctrader_link.live_allowed()` | Environment: production **and** an explicit flag. Two conditions, not one. |
| 2 | `entitlement.capability()` | Refuses a live account under **both** entitlements. A paid plan unlocks nothing. |
| 3 | `automation._preflight()` | The resolved connection's own mode, checked again, and lock 2 invoked. |

And `entitlement.live_execution_enabled()` returns a literal `False` — no
environment read, no call, no name referenced at all. The invariant test
asserts that on the AST, so it cannot quietly become configurable.

## 1. What this milestone is not allowed to be

- **Not a flag flip.** If the work amounts to setting `LIVE_TRADING_ENABLED`,
  it has not been done. `/readyz` currently *fails* when that variable is set,
  precisely so a deployment cannot pretend the path exists.
- **Not a relaxation of the locks.** Each lock exists because the others can
  fail. Removing one because the others cover it is how all three end up gone.
- **Not shipped with the demo release.** It needs its own branch, its own
  review, and its own staged rollout.
- **Not first exercised on a client's account.** See §11.

## 2. Entitlement — what must be true of the client

Today `paid_live` is a name with nothing behind it, and that is deliberate
(`docs/BETA_CONFIGURATION.md`). Before it unlocks anything:

| Requirement | Why |
|---|---|
| A verified payment, granted by the signed webhook only | `billing.handle_event` is the only grant path. A browser must not be able to reach an entitlement — see `web/src/app/api/create-payment-intent/route.ts`. |
| The entitlement records **what was bought** | `licence.grant(plan=...)` already takes a plan. A plan string that does not correspond to a sold product puts a false fact in the closest thing this product has to a ledger. |
| Explicit, recorded, re-affirmable consent to live trading | Separate from the terms accepted at sign-up. A client who agreed to demo automation has not agreed to real money moving. |
| A per-client kill switch that outranks the entitlement | `licence.revoke()` already blocks everything including demo. It must also stop a running live loop, not only refuse the next start. |
| Consent that expires | A consent given once, a year ago, is not informed consent for a loop running today. |

**Open owner decisions that block this section entirely:** D1–D3, D5, D6 in
`docs/PAYMENT_AND_LICENCE_DECISIONS.md`, and L1–L4, L6–L8 in
`docs/LEGAL_LAUNCH_BLOCKERS.md`. No price is approved; no legal entity is
named. Until those exist there is nothing to sell and nobody to sell it.

## 3. Account-mode verification — the fact that must come from the broker

Today `account_mode()` reads the mode recorded at link time, which came from
cTrader's own account list (`live` flag). For demo that is sufficient: being
wrong means refusing a demo account, which costs nothing.

For live it is not sufficient. Requirements:

1. **Re-verify the mode against the broker at start, not at link.** A link
   record can be months old. `apex/bot.py`'s legacy path already does the
   equivalent — it asks the broker `environment()` rather than trusting stored
   state — and that is the pattern to follow.
2. **Re-verify on every reconnect and every token refresh.**
3. **Treat a mode the broker will not confirm as `unknown`, and refuse.**
   `unknown` must never fold into `live` *or* `demo`. It is already a third
   value in `entitlement.account_mode()`; keep it one.
4. **Refuse a mode change under a running loop.** If an account's mode differs
   from the one automation started on, stop and notify — do not adapt.
5. The mode must remain unwritable from a request body. Exactly one writer
   exists today (`ctrader_link.select_account`) and a test asserts it.

## 4. Ownership — already solved, must not regress

Ownership is the storage key, not a check after loading
(`store._k_current(owner_id, rule_id)`). A client asking for another client's
rule gets `NotFound`, because the key they can construct does not exist.

For live execution, extend the same principle: **the account id must be
derived from the caller's own link record, never accepted from the request.**
`ctrader_link.get_ctrader_connection` already resolves it this way, and a live
order must use that value and no other.

`store.OwnershipViolation` currently answers 500 — loud, never rendered as a
normal "not found". Keep that. A quiet ownership failure on a live account is
somebody else's money.

## 5. Risk gates — what must hold before an order is built

The legacy bot's `gates.authorize_order` is the model: one function, and every
origin goes through it. The platform's equivalent must enforce, per order:

| Gate | Note |
|---|---|
| A stop exists | `ruledoc` already refuses activation without one: "a rule without a stop has no defined risk". |
| Risk per trade, as a percentage of *live* balance | Read from the broker at decision time, never cached. The legacy bot caps initial live risk explicitly (`_LIVE_INITIAL_RISK_CAP`); the platform needs the same idea. |
| Maximum open positions | `limits.maxOpenPositions` is already in the RuleDoc and already validated. |
| Maximum daily loss, and maximum drawdown | Recorded in the RuleDoc today and **not enforced by any engine consumer** — labelled as such at the input. For live they must become enforced, and the label removed only when that is true. |
| Maximum daily trades | Same: recorded, not enforced. See also the `5/4` off-by-one observed in the legacy bot's counter — a cap that counts wrong is not a cap. |
| Exposure per instrument and correlated exposure | Not modelled at all today. |
| Spread and slippage ceilings | `execution.py` already refuses a *required* constraint it cannot honour rather than dropping it. That behaviour is correct and must be preserved: `SUPPORTED_CONSTRAINTS` is empty today, so a rule asking for one is refused, not silently downgraded. |
| News and session filters | Present in the legacy bot, absent from the platform. |
| An order type the connector can actually honour | `bridge.SUPPORTED_ORDER_TYPES` is `{MARKET}`. A rule asking for LIMIT or STOP must be refused at activation, not at execution. |

**Every gate must fail closed**, and every refusal must be journalled with its
own code. A refusal nobody can read is a refusal nobody can debug.

## 6. Idempotency and the ledger

The failure being prevented: a duplicate order because a retry, a redeploy or
two instances raced.

- `ledger.claim` / `ledger.record` already exist and `user_store.claim`
  (`SET NX`) is the correct primitive.
- **The claim must be taken before the broker call and released only on a
  confirmed outcome.** A claim released on an exception whose result is unknown
  turns one uncertain order into two.
- A claim key must be derived from the decision, not from a timestamp:
  `thesis.setupKey` in the legacy bot is the right shape
  (`SYMBOL:SIDE:strategy:bar`).
- **A shared backend becomes mandatory, not recommended.** Today `/readyz`
  fails in production without one; for live, the process must refuse to start.

## 7. Audit trail

Non-negotiable, and stricter than the journal:

- Every live order: who, when, which rule version, which decision id, the full
  request, the broker's reply, and the resulting position id.
- Every refusal, with its gate and its code.
- Every entitlement and consent change, with the actor.
- Every mode verification and its answer.
- **Append-only.** A record the application can rewrite is not an audit trail.
- **Redacted on the way out.** `apex/redact.py` masks tokens and now Fernet
  values; the audit must never contain a credential in the first place.

An active `RuleDoc` is already frozen and versioned, so an audit entry can
name the exact terms that were traded. Keep that.

## 8. Emergency stop

Three levels, all of which must exist:

1. **Per client.** `automation.stop` exists and is idempotent. It must also
   flatten or explicitly decline to flatten, and say which.
2. **Per instrument.** Not built.
3. **Global.** One switch that halts every live loop for every client, does not
   depend on the shared backend being reachable, and does not require a deploy.
   Not built.

Plus: **halt on the platform's own uncertainty.** If a read fails, if the mode
cannot be confirmed, if the ledger cannot answer — stop, do not continue on
stale state. The current release already refuses rather than guesses; live must
refuse and *also* wind down.

## 9. Rate limits

Counters are shared (`INCR` with a TTL) and the per-process fallback is
reported by `/readyz`. For live:

- Broker-facing limits are the binding ones. cTrader allows five historical
  requests per second **per connection**, shared across every client on it.
  Order throughput has its own limits and they are not the same numbers.
- The fallback must **refuse**, not degrade. An order-placing path that
  rate-limits in one process is not rate-limited.
- A per-client order-rate cap, separate from the API rate limit. A loop
  placing orders as fast as the API allows is the failure mode.

## 10. Rollback

- `TOKEN_ENCRYPTION_KEY` must not be rolled back — tokens encrypted under a
  new key cannot be read under the old one. Already in the runbook.
- Application rollback must not change how an in-flight order is interpreted.
  Frozen rule versions make this tractable; the ledger must make it safe.
- **A rollback must be able to leave live execution off** without rolling back
  anything else. That means the switch in §8.3 lives outside the application
  release.

## 11. Staged rollout, in order

1. Demo only, for as long as it takes to close blocker **X1**
   (`docs/CTRADER_DEMO_SMOKE_TEST.md`) — nothing has run against a real broker
   yet, demo or otherwise.
2. Live execution behind the locks, on the **operator's own** live account,
   with the smallest size the broker permits.
3. One consenting external client, at capped size, watched.
4. Wider, with the global switch in place and monitoring provisioned (**X7**).

**Step 2 must not be skipped.** A platform whose first live order is a client's
is a platform testing on somebody else's money.

## 12. Definition of done for the milestone

- [ ] Every item in §§2–10 implemented, each with tests.
- [ ] `tests/test_platform_live_invariants.py` **rewritten, not deleted** — the
      invariants change from "unreachable" to "reachable only through the
      gates", and that file is where the new shape is asserted.
- [ ] The three locks still three, each still tested with the others disabled.
- [ ] Entitlement, consent and the global stop exercised in a drill, not only
      in tests.
- [ ] A restore exercised once (**X8**), because the ledger is now the record
      of real money.
- [ ] Owner sign-off on pricing (D1–D3, D5, D6) and legal (L1–L4, L6–L8).
- [ ] A separate security review of this specification's implementation.

Until all of those are true, `entitlement.live_execution_enabled()` returns
`False`, and the correct answer to "can we turn it on?" is no.
