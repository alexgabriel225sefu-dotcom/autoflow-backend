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
four states:

| State | Meaning | Can activate a rule or start automation |
|---|---|---|
| `none` | No record. **The default for every new sign-up** | No |
| `active` | Granted, and not past `expiresAt` | Yes |
| `expired` | Granted, and past `expiresAt` | No |
| `revoked` | Withdrawn deliberately | No |

The rule it enforces: *an unknown entitlement is not an entitlement.* A user
with no record is `none`, never "active until told otherwise".

The only automated grant path is the payment webhook, and checkout is
disabled. So during the beta every entitlement is granted by hand, and this
is how.

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

## 8. When this document stops being needed

When entitlement is derived rather than granted: a connected **demo** account
carries free demo access automatically, and a paid plan is what unlocks a
live account once live execution exists. At that point manual grants become
an exception path for support, not the normal way a client gets access.
