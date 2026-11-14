# Account data export and erasure, and the 2026-10-29 security fixes

## Endpoints (authenticated, fresh session, no trial started)

`GET /api/v1/account/export` (bucket `account_export`, 10/hour)

    200 {"ok": true, "exportedAt": "<ISO-8601 UTC>", "data": {
          "rules", "ruleVersions", "journal", "notifications", "approvals",
          "automation", "audit", "referral", "liveAccess", "billing", "other",
          "licence", "ctraderLink", "settings", "trades"}}

Only keys carrying the caller's Supabase user id as a whole key segment are
read. Every field whose name looks like a credential (`token`, `secret`,
`password`, `apiKey`, `…_key`, `nonce`, `signature`) and every stored
ciphertext (`enc:…`) is removed. cTrader link data is
`ctrader_link.public_status`, which never carries tokens.

`DELETE /api/v1/account`, body `{"confirm": "DELETE"}` (bucket
`account_delete`, 5/hour per session and per person, fails closed)

    200 {"ok": true, "deleted": {"<category>": <count>, ...},
         "authUserDeleted": <bool>, "note": "<sentence>"}

Categories always present: `rules journal notifications licence ctraderLink
settings trades automation caches`; others (`billing approvals audit referral
liveAccess other`) appear when something was removed. Counts are keys removed.

Order: automation is stopped through `automation.stop` (a failed stop answers
503 `AUTOMATION_STOP_FAILED` and erases nothing); then every owned key is
deleted, plus `billing:ref:*` entries whose value names the user and the
engine's active-user set membership; then the Supabase auth user is deleted
via `DELETE /auth/v1/admin/users/<id>` when `SUPABASE_SERVICE_ROLE_KEY` is set.
Without it `authUserDeleted` is `false` and `note` says support must remove
the sign-in account. Idempotent: a repeat answers 200 with zero counts.

Errors: 400 `CONFIRMATION_REQUIRED`, 401, 429 `RATE_LIMITED`, 503
`AUTOMATION_STOP_FAILED` / `STORE_UNAVAILABLE` / `RATE_LIMIT_UNAVAILABLE`.

Not done by erasure: cTrader app access is not revoked at cTrader (no revoke
call is used; the note says so), open broker positions are not closed, and the
operator's live-access review queue is not edited. The web app should sign
the user out after a successful erasure: if the auth user still exists, the
next authenticated request starts a fresh empty account.

Tested: the Redis path (`SCAN <ns>:*<uid>*`, `DEL`, the active-user set) in
`tests/test_account_erasure_redis.py`, which runs the real `user_store`
functions against an in-memory stand-in for the redis-py client, with a paged
SCAN. It shows a user's keys of every kind are erased, another user's are not
(including an id that contains the caller's id), an unreachable store raises
instead of answering "deleted", and a second erasure reports zeros. The same
file fails when a new key kind is written under `a4t:` that is neither mapped
to a category in `account_data` nor exempted there with a reason.

Not erased, and a decision for the owner: `billing:review:<stripe event>`
records hold `claimedUserId` in their value and are keyed by the event, so a
scan on the user id does not find them. They are payment records held for
manual review, and keeping or deleting them is a legal retention question.

Unverified: the real Upstash/Redis service (the stand-in is not a server), and
the Supabase admin call, which is tested with an injected transport, not
against Supabase.

## Other fixes in the same audit

| Finding | Change |
|---|---|
| Token flood | `addr_verify` per-address budget (120/min, `RL_A4T_ADDR_VERIFY_PER_MIN`) spent only on Supabase cache misses; rejected tokens cached 30 s (`identity.NEG_CACHE_TTL_S`), also for fresh routes; outages never cached. |
| Limiter fails open | Mutating routes fail closed (503 `RATE_LIMIT_UNAVAILABLE`); reads, `emergency/stop` and `billing/webhook` stay lenient. |
| Resume bypass | `rules/{id}/resume` requires ownership, a confirmed e-mail, `entitlement.require_activation` and a fresh session. |
| Rule cap | `A4T_MAX_RULES_PER_USER` (default 50), archived rules included; 409 `RULE_LIMIT_REACHED`. |
| Stripe `v1` | Every `v1` in `Stripe-Signature` is compared; exactly one `t`. |
| Payment Link id | See `PAYMENT_AND_LICENCE_DECISIONS.md`. |
| RLS | `sql/003_rls_server_tables.sql` (not applied). |
| Key rotation | `TOKEN_ENCRYPTION_OLD_KEYS`: comma-separated retired Fernet keys, decrypt only (MultiFernet). Existing ciphertext is not re-encrypted until rewritten. Rotating `TOKEN_ENCRYPTION_KEY` also changes keys derived from it (OAuth state, link log, waitlist digests). An invalid old key refuses startup. |
