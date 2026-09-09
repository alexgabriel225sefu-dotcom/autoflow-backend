# APEX — backup and restore

Operational procedure. The code is `apex/backup.py`; the automated round-trip
test is `tests/test_backup_restore.py`.

## Scope

### Backed up

| What | Where it lives | Why it cannot be rebuilt |
|---|---|---|
| Users | `{ns}:user:{id}` | settings, risk, automation level, live/paper |
| Licences | `license_key` on each record | proof of purchase |
| Access state | access store | who is entitled |
| Broker metadata | `ctrader_account_id`, `ctrader_env`, `ctrader_accounts` | which account is linked |
| Credentials | `ctrader_access_token`, `ctrader_refresh_token` | **stored and backed up encrypted** |
| Trading state | restart snapshot on the user record | what the loop reconciles against |
| Trade journal | `{ns}:trades:{id}` | the only record of what happened |
| Audit events | `{ns}:audit` | who did what through the control plane |

### Deliberately NOT backed up

These are runtime coordination. Restoring them is not merely useless, it is
harmful — the reason is given for each because "rebuildable" alone would not
explain why restoring is worse than skipping.

| What | Why restoring it is wrong |
|---|---|
| Ownership leases (`own:user:*`) | A restored lease claims a user for a container that no longer exists, and locks out the one that does. A recovery becomes an outage. |
| Command queue | Replaying operator commands from a backup re-runs them against a different world. |
| Replay markers (`cmdseen:*`) | Tied to command ids that no longer matter. |
| Heartbeats | Meaningless outside their moment. |
| Dash / worker cache | Rebuilt on the first tick. |
| Order idempotency claims | Bound to a 120s window that has long passed. |

## Encryption

Backups carry the `enc:` ciphertext **verbatim**. A backup file is therefore
not a credential dump, and `backup.verify()` refuses any snapshot in which a
credential field is not encrypted — a decrypted backup is treated as a defect,
not a convenience.

The consequence is operational and worth stating plainly:

> **Losing `TOKEN_ENCRYPTION_KEY` makes every backup useless for broker
> reconnection.** Restoring gets you users who look connected and cannot trade;
> each one has to re-link their account via `/ctrader`.

Store the key **separately from the backups**, in a password manager or a
secrets manager. A backup and its key in the same place is one compromise, not
two.

## Where backups go

Not prescribed by code — `dump` writes JSON to stdout, so the destination is
the operator's choice. Requirements for whatever you pick:

- **Off the platform holding the live data.** A backup in the same Upstash
  account as the source does not survive that account being lost.
- **Encrypted at rest** by the destination, in addition to the field-level
  encryption above.
- **Access-controlled.** The file contains licence keys and account ids.

## Frequency and retention

| | Value | Reasoning |
|---|---|---|
| Frequency | Daily, plus before any deploy that touches `user_store` | Settings change slowly; schema changes are the risk |
| Retention | 30 daily, 6 monthly | Long enough to notice corruption that was not obvious on the day |
| **RPO** | ≤ 24h (the backup interval) | Nothing is streamed. A restore loses at most one interval of settings changes and journal rows. Positions are NOT lost — they live at the broker and are rediscovered. |
| **RTO** | Minutes, dominated by broker reconnection | Writing keys back takes seconds. Then the loop must reach cTrader for each user and discover positions. |

RPO deserves one clarification: the thing a client would most miss is not in
the backup at all. **Open positions live at the broker.** A restore that loses
a day of settings still recovers every position, because the loop reads them
from cTrader on startup and the broker is authoritative.

## Taking a backup

```bash
cd apex-forex-bot
python -m apex.backup dump > apex-backup-$(date -u +%Y-%m-%d).json
python -m apex.backup verify < apex-backup-$(date -u +%Y-%m-%d).json
```

Always `verify`. A backup nobody has verified is a guess.

## Restoring

```bash
python -m apex.backup restore --dry-run < apex-backup-2026-08-15.json   # inspect
python -m apex.backup restore < apex-backup-2026-08-15.json             # commit
```

### Reading the result — this is the part that matters

`restore` returns an explicit verdict, not a log to interpret:

| `result` | Meaning | Exit code |
|---|---|---|
| `COMPLETE` | Every expected record restored and read back | 0 |
| `PARTIAL` | Some records did not restore. **This is not a successful restore.** | 1 |
| `FAILED` | The snapshot did not verify, or nothing restored | 1 |

The report carries `expected`, `restored` and `failed` counts per category, so
"how much of it worked" is a number rather than a judgement. Every user record
is **read back** after writing — a write that reported success and is not there
is the failure a restore cannot afford to discover later.

The CLI exits non-zero on anything but `COMPLETE`, so a script that ignores the
JSON still fails loudly. **Do not start the application on a PARTIAL restore.**
Investigate first: a half-restored deployment has clients whose entitlement and
broker links disagree with each other.

`restore` writes state only. Steps 3–10 below are the **normal startup path**;
this module deliberately does not short-circuit any of them.

1. Write users, access, journals, audit — done by `restore`
2. Do **not** write leases, queues or heartbeats — enforced by `restore`
3. Start the application → reconnects Redis
4. The loop reconnects each broker account
5. The loop discovers real positions and orders at the broker
6. Reconcile — **broker wins** over any local snapshot
7. Rebuild user loops from `active`
8. Verify licences — re-checked at the order gate, not only at startup
9. Acquire ownership leases **fresh**
10. Confirm safe state: `ops_system_health`, then `ops_broker_reconcile` per user

Step 10 is the one people skip. Use it: a restore that silently disagrees with
the broker is exactly the condition `ops_broker_reconcile` exists to name.

## Verifying a restore worked

```bash
python tests/test_backup_restore.py     # the automated round trip
```

Then, against the restored deployment:

- `ops_system_health` → workers running, brokers connected
- `ops_broker_reconcile` per user → `RECONCILED`, or a named mismatch
- `ops_user_health` for a known client → licence ACTIVE, lease ACTIVE

## Testing the procedure

The round trip is automated and runs in the suite: write state, dump, destroy,
restore, compare. It asserts the two properties that are easy to get backwards
— that the dump does **not** decrypt, and that the restore does **not** bring
back ownership leases.

Run a restore drill against a scratch environment on a schedule. The test
proves the code round-trips; only a drill proves the *procedure* does, and the
gap between those two is where disaster recovery usually fails.
