# Live gate drill

`docs/LIVE_EXECUTION_SPECIFICATION.md` §12 asks for "entitlement, consent and the
global stop exercised in a drill, not only in tests". This is the drill, in two
halves. Neither half places a real order.

## Half 1: the code, with a fake broker (done by a script)

```
cd apex-forex-bot && python3 scripts/live_gate_drill.py
```

It plays the real gate code in a throwaway process with a fake store and a fake
broker, and narrates each step: the release switch closed, then everything
open and an order allowed, then one lever at a time (global stop, live-only
stop, one instrument, one client, the environment switch, the licence, a
withdrawn approval, a demo account on the live path, the pilot's account,
instrument and size cap), putting each back and seeing the order allowed again.

It refuses to start if it can see production settings (`REDIS_URL`, Upstash,
Supabase service key, Stripe key, `A4T_LIVE_EXECUTION`,
`APEX_ALLOW_LIVE_ACCOUNTS`, or `APP_ENV=production`). It opens the release switch
only inside its own process. Exit 0 means every step behaved as written.

Last run: 2026-11-03, all steps passed.

## Half 2: the real deployment (the owner, in a shell on the service)

Live is closed on production, so this half exercises the stop and reads the
state. It does not open anything.

1. `python3 scripts/emergency_stop.py status` — expect "running — nothing is
   halted", and `GET /readyz` reports `live_trading` as closed.
2. `python3 scripts/emergency_stop.py halt --scope live --reason "drill" --by <you>`
   — `status` now names the stored switch. The demo automation keeps running
   (a live-only halt must not stop demo): confirm the next `[UserLoop:…] tick`
   line in the logs.
3. `python3 scripts/emergency_stop.py release --by <you>` — `status` is running
   again.
4. Only if a staging deployment exists: set `A4T_EMERGENCY_HALT=all` there,
   confirm it stops, remove it. Never on production during the drill.
5. Licence: with a test account, confirm that removing and re-granting a licence
   changes what `/live` shows for it, and that an id on `A4T_OPERATOR_USER_IDS`
   shows an active licence with no expiry.

Record each step, the date and your name here or in the PR that updates it:

| Step | Date | By | Result |
|---|---|---|---|
| 1 status | | | |
| 2 halt live, demo keeps ticking | | | |
| 3 release | | | |
| 4 environment switch (staging) | | | |
| 5 licence and operator list | | | |

## What this does not prove

Neither half talks to a real live broker account. That is the first real order,
on the operator's own account at the smallest size (spec §11, step 2). The restore
drill (`scripts/dr_drill.py`, X8) was closed on 2026-10-05; repeat it once before
that first order, because the ledger then becomes the record of real money.
