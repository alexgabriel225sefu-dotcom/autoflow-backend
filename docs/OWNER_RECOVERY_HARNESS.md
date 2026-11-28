# Application recovery harness

This is a check of the process's own restart answers. It is not a measure
of Render, Supabase, Redis, or Stripe recovery time, and it is not a
backup test. Connectors in this repository do not name a backup plan, a
point-in-time restore, or a Redis resource. Those facts stay unknown
until the owner reads them in the provider consoles. Do not put connection
strings in this file.

No production data is loaded. No broker order is sent. No email is sent.
No new database is created by the steps below.

## What a laptop can show

`apex-forex-bot/tests/test_platform_recovery_harness.py` uses a temporary
directory as the local store:

- A restart that did not get an answer from the broker keeps the position
  tracked. It does not call it closed.
- A broker answer that the position is still open adopts it.
- A broker answer that it is flat records it closed.
- A second identical order claim in the same process is a duplicate.
- A rule written for one user is not returned for another user id.
- A revoked licence is not active.

That store is the same process and the same local files. The harness
does not start a subprocess, Postgres, Redis, or a load test. It does
not prove that two deployed instances share a claim. Production order
idempotency still depends on the shared store the service was given.
This harness does not identify which provider that is, and it is not a
backup or a provider recovery result.

`apex-forex-bot/tests/test_platform_tenant_http.py` is the HTTP form of
the tenant check: two synthetic users, the real platform server on
localhost, identity stubbed, no outbound account. Bob does not receive
Alice's rule, journal entry, or pending approval.

## What the owner can run later, still without production

On a machine that is not production, with outbound calls to the broker,
Stripe, and Supabase blocked or stubbed:

```bash
cd apex-forex-bot
python3 tests/test_platform_recovery_harness.py
python3 tests/test_platform_tenant_http.py
python3 tests/test_platform_foreign_checkout.py
python3 tests/test_leverage_unknown.py
```

Do not point these at a live database URL. Do not create a broker account
or a mailbox for them.

A full demo order on a real cTrader demo account is a separate owner
session. It is described in `docs/CTRADER_DEMO_SMOKE_TEST.md`. This
harness does not perform it.

## Leverage freshness

A successful leverage reading is kept for 60 seconds for that account,
environment, and token, then the broker must confirm it. If the refresh
fails, the old number is not used and the order is not sized. An entry
left with no expiry is not treated as still true. Unknown readings are
also kept for 60 seconds so a tight loop does not ask on every tick.
