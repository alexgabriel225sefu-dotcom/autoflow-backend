# Apex4Traders — manual licence operations

Granting, checking and withdrawing a client's entitlement by hand, for the
period before checkout exists.

**This does not enable live trading.** A licence controls whether a client may
activate a rule and start automation. It has no bearing on demo versus live:
`automation.start` refuses any account that is not demo regardless of what
licence the client holds.

---

## 1. Why this document exists

`apex/platform/licence.py` is keyed by the Supabase user id and has exactly
four states. What a licence *means* changed with the entitlement model in
`apex/platform/entitlement.py`: demo access is free for the 14-day trial
(itself an `active` licence), and any state other than `active` blocks demo
automation (see the table).

| State | Meaning | Blocks demo automation |
|---|---|---|
| `none` | No record. A verified sign-in normally starts a 14-day `demo_trial` automatically (`api._start_trial_if_new`); `none` is what remains if that write failed | **Yes** (`NO_LICENCE`) |
| `active` | Granted, and not past `expiresAt`. The free demo trial is an `active` licence with `plan: demo_trial` | No |
| `expired` | Granted, and past `expiresAt`. A trial that ran out lands here | **Yes** (`TRIAL_EXPIRED`) |
| `revoked` | Withdrawn deliberately | **Yes** (`LICENCE_REVOKED`) |

**Corrected 2026-10-29.** This table used to say `none` and `expired` did not
block demo automation. That was true of an earlier model and is wrong now:
`entitlement.capability()` and the engine gate `user_loop._entitled` both
require an `active` licence, and a running loop is stopped by the watchdog
sweep (every 180 s) once its licence is no longer active. Proof:
`apex-forex-bot/tests/test_platform_trial_expiry.py`. A client whose trial has
ended is brought back by `licence.grant(...)` (section 5), not by signing in
again; `plans.start_trial` never extends.

`paid_live` does **not** unlock live trading in this release. There is no
execution path behind it; `entitlement.capability()` refuses a live account
under both entitlements, and the tests assert all four combinations.

A new verified account receives its 14-day trial without any action. What
this document is for is **extending or restoring** access by hand (section 5)
and **withdrawing** a client's access, and putting it
back.

The only automated grant path is the payment webhook, and checkout is
disabled — so any `active` licence in the store today was written by hand.

## 2. Finding the user id

A licence is keyed by the **Supabase user id**, not by e-mail, not by a
Telegram chat id, and not by a cTrader account number.

- The client can read their own id from `GET /api/v1/me` (`user.userId`).
- An operator finds it in the Supabase dashboard under Authentication →
  Users.

Do not guess it, and do not derive it from an e-mail address. Granting a
licence to the wrong id gives a stranger automation and leaves the intended
client refused, and neither party will be able to tell you why.

## 3. Granting

A new account gets its trial automatically, so a fresh beta tester needs no
grant. Grant one to **extend** a trial that is ending or has ended, to
restore someone, or to record a paid-tier client. Extending is an owner
decision (see `docs/OWNER_ACTIONS.md`); this release sells nothing and a
`beta` grant unlocks no live trading.

Run on the backend host, in the deployment's environment (the same
`PRODUCT`, `DATA_DIR` and Redis configuration — a licence written against the
wrong namespace is written somewhere nobody reads):

```python
from apex.platform import licence

# Beta tester, free demo access, no expiry.
licence.grant("<supabase-user-id>", plan="beta")

# Time-boxed instead — expiresAt is a UNIX timestamp in seconds.
import time
licence.grant("<supabase-user-id>", plan="beta",
              expires_at=time.time() + 30 * 86400)
```

`plan` is a free string recorded on the entitlement; use `"beta"` for beta
testers so a later report can tell them apart from anything sold. Passing a
`plan` that implies a paid tier to somebody who has not paid puts a false
fact in the record — the entitlement store is the closest thing this product
has to a ledger of who is owed what.

### Verifying the grant

```python
licence.status_for("<supabase-user-id>")
# {'state': 'active', 'expiresAt': None, 'plan': 'beta', ...}
```

Or ask as the client: `GET /api/v1/me` returns `licence`. That is the same
value the UI renders, so it is the one worth trusting.

## 4. Withdrawing

```python
from apex.platform import licence
licence.revoke("<supabase-user-id>")
```

This is the lever that still does something. A withdrawal outranks the free
tier: `entitlement.capability()` refuses a revoked client on a demo account
as well, which is the whole reason it is checked separately from the
entitlement name.

Takes effect on the client's **next authenticated request**. It does not stop
automation that is already running — stop that explicitly:

```
POST /api/v1/automation/stop      # as that client
```

Revocation is recorded, not deleted: the record keeps `grantedAt` and adds
`revokedAt`. Do not remove the record instead of revoking it. Deleting
returns the client to `none`, which refuses the same way but loses the fact
that they once held a licence and that somebody withdrew it.

## 5. Renewing an expired licence

There is no separate renew call. Grant again:

```python
licence.grant("<supabase-user-id>", plan="beta",
              expires_at=time.time() + 30 * 86400)
```

`grant` replaces the record. A previously revoked client becomes active
again, which is correct and is also why revocation must be a deliberate act
by someone who knows they are reversing it.

## 6. What never to do

- **Never grant a licence from a request the client's own browser made.**
  `grant` is called by the activation path and by the payment webhook. A
  route that let a client grant themselves one would be the whole
  entitlement system, undone.
- **Never write the record directly through `store._write`.** Use `grant`
  and `revoke`; they are the only two writers, and a hand-written record can
  omit a field every reader assumes is there.
- **Never record a masked key, plan name or expiry that did not happen.**
  `masked_key` exists for a real payment reference. Filling it with something
  invented makes the entitlement store lie about how access was obtained.
- **Never use a licence to work around the demo-only restriction.** It cannot
  do that, and an attempt to make it able to is a change to the live-trading
  milestone, not an operational task.

## 7. The legacy Telegram entitlement is a different thing

`apex/stripe_license.py` is keyed by Telegram `chat_id` and belongs to the
older forex bot. It is deliberately a separate store. Granting there does
nothing for a platform user, and the two must not be merged without an
explicit migration, or one product's identifiers start silently entitling the
other's clients.

## 8. What is left for this document to do

Entitlement is now derived rather than granted: a client with no record is
`free_demo` and can use the product. What remains here is the support path —
withdrawing access and restoring it — and the bookkeeping of who is on a paid
tier once there is something to sell.

The next change to this document is the one that comes with live execution
actually existing, at which point `paid_live` starts unlocking something and
granting it becomes a decision with money attached.
