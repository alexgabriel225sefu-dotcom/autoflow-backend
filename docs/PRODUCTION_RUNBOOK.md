# Apex4Traders — production runbook

Operating the platform. Everything here is checkable against the code; where
something is not yet provisioned it says so rather than describing a system
that does not exist.

**Live trading is not part of this deployment.** No procedure below enables
it, and none should be read as a step towards it.

For a private beta specifically, read `docs/BETA_CONFIGURATION.md` alongside
this. Granting or withdrawing a client's entitlement by hand is
`docs/MANUAL_LICENCE_OPERATIONS.md`.

---

## 1. Required environment

### Backend (`apex-forex-bot`)

| Variable | Required | What it does |
|---|---|---|
| `TOKEN_ENCRYPTION_KEY` | **yes** | Fernet key for broker tokens at rest. Startup is refused without it. |
| `REDIS_URL` *or* `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` | **yes** | Shared backend. Without it, ownership, entitlement and order idempotency become per-container. |
| `SUPABASE_URL` | **yes** | Token verification endpoint. |
| `SUPABASE_ANON_KEY` | **yes** | The public key. **Never** `SUPABASE_SERVICE_KEY` — it bypasses row-level security. |
| `CTRADER_CLIENT_ID` | yes, for OAuth | cTrader Open API application. |
| `CTRADER_CLIENT_SECRET` | yes, for OAuth | Server-side only. Never reaches the browser. |
| `CTRADER_REDIRECT_URI` | yes, for OAuth | Must match the portal byte for byte. |
| `PRODUCT` | yes | `forex`. Namespaces every stored key. |
| `APP_ENV` | yes | `production`. |
| `PAPER_TRADING`, `CTRADER_ENV`, `BROKER` | — | **Do not change these as part of an operational task.** |
| `A4T_STRIPE_WEBHOOK_SECRET` | only with billing | Unset means the webhook answers 503. |
| `A4T_PLAN`, `A4T_PURCHASE_MODE`, `A4T_LICENCE_DAYS` | optional | Defaults describe the one-time `founder_lifetime` offer. Leave `A4T_LICENCE_DAYS` unset for no expiry. |
| `RL_A4T_*_PER_MIN` | optional | Rate limits, below. |
| `RATE_LIMIT_STORE` | optional | `auto` (default) uses the shared backend. `memory` forces the per-process limiter, which is a development choice and makes `/readyz` refuse in production. |

**Must NOT be set in production:**

```
ALLOW_LOCAL_BACKEND_DEV     # makes a per-container store acceptable
ALLOW_PLAINTEXT_DEV_STORAGE # stores broker tokens unencrypted
APP_ENV=dev
```

The store refuses to start if the first two are needed and `APP_ENV` is not
`dev`. That refusal is the safety net, not the plan.

### Web (`web`)

| Variable | Required | What it does |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | **yes** | Public. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | **yes** | Public by design. Never the service key. |
| `NEXT_PUBLIC_API_BASE_URL` | yes | Empty means same origin. |
| `STRIPE_SECRET_KEY` | only with billing | Server-side only; never prefixed `NEXT_PUBLIC_`. |
| `A4T_PRICE_MINOR`, `A4T_CURRENCY`, `A4T_SKU` | only with billing | Defaults are `49900`, `usd`, `founder_lifetime`. Checkout still needs both gates below. |
| `A4T_CHECKOUT_ENABLED`, `A4T_AUTHENTICATED_CHECKOUT_ENABLED` | only with billing | Both must stay off until paid checkout is reviewed and created from authenticated platform API. |
| `A4T_CHECKOUT_ENABLED` | only with billing | Must be `true`. Currently off. |

A variable prefixed `NEXT_PUBLIC_` is compiled into the browser bundle. Anything
secret must not carry that prefix.

---

## 2. Rate limits

`apex/platform/ratelimit.py`. Applied before authentication, so a flood costs
no Supabase round trips.

| Bucket | Routes | Default | Override |
|---|---|---|---|
| `candles` | `accounts/{ctid}/candles` | 30/min | `RL_A4T_CANDLES_PER_MIN` |
| `preview` | `rules/{id}/preview` | 20/min | `RL_A4T_PREVIEW_PER_MIN` |
| `oauth` | non-GET `ctrader/*` | 10/min | `RL_A4T_OAUTH_PER_MIN` |
| `activate` | `rules/{id}/activate` | 10/min | `RL_A4T_ACTIVATE_PER_MIN` |
| `control` | non-GET `automation/*` | 20/min | `RL_A4T_CONTROL_PER_MIN` |
| `webhook` | `billing/webhook` | 120/min | `RL_A4T_WEBHOOK_PER_MIN` |
| `default` | everything else, including all polls | 240/min | `RL_A4T_DEFAULT_PER_MIN` |

Keyed per authenticated user, falling back to the address. Refusals answer
`429` with `{"error": {"code": "RATE_LIMITED", "bucket", "retryAfterSec"}}`.

**Where the counter lives.** Each bucket is counted with `INCR` plus a TTL in
the shared backend, so every instance shares one window. The window is a floor
of the clock, which is what lets instances agree without coordinating.

This costs **one `INCR` per request** to `/api/v1/*`. That is the price of a
limit that is real across instances, and it is worth knowing before reading a
latency graph: if the backend is slow, every request is slow. The limiter
handles the backend being *down* — it falls back and `/readyz` says so — but
not the backend being slow, which shows up as latency rather than as an error.

If the shared backend cannot answer, the limiter falls back to a fixed window
held in **one process**: with N instances the effective limit becomes N times
the configured one. That fallback is a development convenience, not a
deployment posture — `/readyz` reports `rate_limit_store: fail` in production
whenever it is in force, and a deployment in that state should be fixed rather
than tuned around.

**`candles` is protection for the broker connection, not just the server.**
cTrader allows five historical requests per second **per connection**, shared
across every client on it.

---

## 3. Startup

1. Set the environment above.
2. Start the backend; it refuses to start on a missing encryption key or a
   missing shared backend, and the message says which.
3. Confirm `GET /readyz` answers **200** with `"status": "ok"`. A 503 lists
   every refusing check by name; fix those before going further.
4. Confirm `GET /api/v1/me` with a valid bearer token returns 200 and
   `GET /api/v1/conditions` lists the condition registry.
5. Deploy the web app with `npm run build`, then `npm run start`.
6. Confirm `/login` renders and a sign-in reaches `/dashboard`.

## 4. Health checks

Two unauthenticated endpoints, both JSON, neither carrying any secret, key,
token or environment-variable value.

### `GET /healthz` — liveness

Answers 200 while the process is running, and **touches no dependency**. That
is deliberate: a liveness probe that checks Redis turns a backend degradation
into every container restarting at once, which is how a degradation becomes an
outage.

```json
{"ok": true, "status": "ok", "uptimeSec": 4821.3}
```

Point the platform's restart probe at this one, and nothing else.

### `GET /readyz` — readiness

200 when every required dependency is right, **503** when one is not. Point
the deploy's traffic gate at this one.

```json
{"ok": false, "status": "fail", "environment": "production",
 "checkedAt": 1758648000, "failed": ["shared_store"],
 "checks": [{"name": "shared_store", "status": "fail",
             "message": "no shared backend: ownership, entitlement and order idempotency would be per-container"}]}
```

| Check | Fails when |
|---|---|
| `supabase` | `SUPABASE_URL` or `SUPABASE_ANON_KEY` is unset — the platform cannot tell who anyone is |
| `encryption` | `TOKEN_ENCRYPTION_KEY` is unset. In development, `degraded` with the explicit plaintext opt-in |
| `shared_store` | No shared backend in production, or one is configured and does not answer |
| `rate_limit_store` | Counters are per process in production |
| `ctrader_oauth` | Any of the three cTrader variables is unset — no client can connect an account |
| `billing` | Checkout is enabled and the price, currency, SKU or webhook secret is missing. `skipped` while checkout is off |
| `dev_flags` | A development-only flag is set in production |
| `live_trading` | `LIVE_TRADING_ENABLED` is set, against a release with no execution path for it |

`degraded` does not fail readiness: it is a development box saying so, and the
`environment` field says which kind of box answered. In production the same
conditions are failures.

The answer is computed at most once every few seconds and served from there,
so a probe loop cannot turn into load on Redis. `checkedAt` says when it was
computed; a readiness verdict can be up to five seconds old.

### `GET /api/v1/system/status` — authenticated diagnostics

The same checks, plus uptime and what this release can do
(`demoAutomation: true`, `liveTrading: false`, `checkoutEnabled`). It returns
no more secret material than `/readyz` does — being signed in is not a reason
to start returning keys.

### Interim checks that still apply

| Check | How | Healthy |
|---|---|---|
| Auth path | `GET /api/v1/me` | 200, or 401 `AUTH_REQUIRED` for a bad token — **not** 503 `AUTH_UNAVAILABLE`, which means Supabase is unreachable |
| Frontend up | `GET /` | 200 |

`AUTH_UNAVAILABLE` is the signal worth alerting on: it means the platform
cannot tell who anyone is, and it refuses rather than guessing.

## 5. Deployment

1. Run both suites: `python3 apex-forex-bot/tests/run_all.py`, and in `web`:
   `npm test && npm run build && npm run lint`.
2. Deploy the backend first. The API is additive; the web app tolerates an
   older backend better than the reverse.
3. Watch for `AUTH_UNAVAILABLE` and for 5xx on `/api/v1/*`.
4. Deploy the web app.

**Automation during a deploy.** More than one instance can run briefly; this
has been observed. Ownership and order idempotency depend on the shared
backend being reachable — that is why it is required, not optional.

## 6. Rollback

1. Redeploy the previous revision of the component that changed.
2. **Do not roll back `TOKEN_ENCRYPTION_KEY`.** Tokens encrypted under a new
   key cannot be read under the old one; clients would have to reconnect.
3. An active `RuleDoc` is frozen and versioned, so a rollback of application
   code does not rewrite anyone's rule.

## 7. Migrations

There is no schema migration step: storage is keyed documents, not tables.
A change to a stored shape must be **read-compatible** with the old one, and
records are only rewritten by the path that owns them.

## 8. Key rotation

### `TOKEN_ENCRYPTION_KEY`
Rotating it makes every stored broker token unreadable. There is no
re-encryption path today. The procedure is therefore: announce it, rotate,
and have every client reconnect their cTrader account. Do not rotate casually.

### Supabase keys
The anon key is public and can be rotated by updating both the backend and
`NEXT_PUBLIC_SUPABASE_ANON_KEY`, then redeploying. Sessions survive.

### cTrader client secret
Rotate in the cTrader portal, update `CTRADER_CLIENT_SECRET`, redeploy.
Existing access tokens keep working until they expire; the refresh path uses
the new secret.

### Stripe webhook secret
Add the new endpoint secret, redeploy, then remove the old endpoint in Stripe.
Deliveries signed with a retired secret will fail verification — which is
correct, but means an overlap window is wanted.

## 9. OAuth configuration

1. Create an application in the cTrader Open API portal.
2. Set its redirect URI to exactly `CTRADER_REDIRECT_URI`. cTrader compares
   byte for byte; a trailing slash is a different URI.
3. Scope `accounts` is enough to read balances and positions; `trading` is
   needed before orders can be placed.
4. The callback parks the authorization code server-side and returns only a
   nonce. The link is completed by an authenticated call from the signed-in
   client — that is what stops somebody starting a flow for their own account
   and getting a client to approve it.

## 10. Monitoring and alerting

> **THE GITHUB WORKFLOW IS NOT THE FIRST LINE, BECAUSE IT DOES NOT RUN.**
>
> GitHub executes `schedule:` workflows **only from the default branch**. The
> default branch of this repository is `main`, and this work lives on
> `claude/apex4traders-platform-v1`, which the protocol forbids merging to
> `main`. So the hourly cron below does not fire — not "might not", does not.
> `workflow_dispatch` is the only trigger that works today.
>
> **The external uptime service is the first line and it is not set up yet.**
> Until the three URLs below are in UptimeRobot (free tier, see costs) with an
> alert contact the owner actually reads, nothing is watching production and a
> customer is the alert. The workflow remains valuable as the manual deep
> check: it parses `/readyz` per check and follows the stylesheet, neither of
> which an uptime service can do.

Second line, manual until the workflow sits on a default branch:
`.github/workflows/production-health.yml` runs the
read-only monitor in `apex-forex-bot/scripts/check_production_health.py` on an
hourly schedule and on manual dispatch. It performs only unauthenticated
`GET` requests against:

- `https://apex4traders-api.onrender.com/healthz`
- `https://apex4traders-api.onrender.com/readyz`
- `https://apex4traders-web.onrender.com/`

The workflow has `contents: read`, no secrets, no deploy credentials and no
service write path. Alert delivery is the GitHub Actions failure notification
for this repository. The owner must watch this repository or configure GitHub
Actions failure emails/mobile notifications; otherwise the monitor can fail
correctly and nobody will read it. GitHub scheduled workflows run from the
default branch, so if `claude/apex4traders-platform-v1` is not the repository's
default branch, either move this workflow to the default branch after review or
create the same checks in an external uptime service immediately.

Cost at launch scale: the repository workflow is expected to run 24 times per
day and should use well under one minute per run. That is roughly 730 included
Actions minutes per month. Public repositories are free; private repositories
on GitHub Free include 2,000 Actions minutes per month. The required external
uptime-service fallback is UptimeRobot free tier: 50 monitors, 5-minute
interval, $0/month at this scale. Do not choose a paid monitor while the total
launch budget is 200-300 EUR unless the owner explicitly approves it.

What each alert means and what to do:

| Alert | Means | First action |
|---|---|---|
| `api_healthz` transport failure or non-200 | The API process is unreachable from outside Render, or Render returned an error before the app answered. Customers cannot rely on the API. | Open Render for `apex4traders-api`, check service status and recent deploy logs, then retry `/healthz`. If a deploy just happened and the previous revision worked, redeploy the previous revision. |
| `api_healthz` missing or wrong `release.commit` | The app answered, but the monitor cannot identify the running build, or `A4T_EXPECTED_API_COMMIT` does not match. The deploy may not have taken. | Compare the monitor's commit with the commit Render says is live. If they differ after the deploy has finished, redeploy the intended commit or roll back deliberately. |
| `api_readyz` transport failure | The API is not reachable enough to report dependency status. | Treat as an API outage first: check Render status/logs, then `/healthz`. |
| `api_readyz` failed check: `supabase` | Identity is unavailable or misconfigured. The platform cannot tell who anyone is and should refuse authenticated work. | Check `SUPABASE_URL` and `SUPABASE_ANON_KEY` on the API service, then test `GET /api/v1/me` with a valid token. Do not bypass auth. |
| `api_readyz` failed check: `encryption` | Broker-token encryption is missing. Tokens must not be stored without this in production. | Set/fix `TOKEN_ENCRYPTION_KEY` and redeploy. Do not rotate casually; rotation makes existing broker tokens unreadable. |
| `api_readyz` failed check: `shared_store` | Ownership, entitlement, order idempotency or counters would be per-container, or the shared backend is down. | Check Upstash/Redis environment and provider status. Do not start automation until the shared backend is healthy. |
| `api_readyz` failed check: `rate_limit_store` | Rate-limit counters are local to one process. With more than one instance, limits multiply by instance count. | Restore the shared rate-limit store configuration. |
| `api_readyz` failed check: `ctrader_oauth` | Clients cannot connect cTrader accounts. | Check `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET` and `CTRADER_REDIRECT_URI`, including exact redirect URI bytes in the cTrader portal. |
| `api_readyz` failed check: `billing` | Checkout was enabled without the required reviewed payment configuration. | Turn checkout back off unless this is a reviewed payment launch. Then fix webhook/config before re-enabling. |
| `api_readyz` failed check: `dev_flags` | A development-only flag is set in production. | Remove the flag and redeploy. |
| `api_readyz` failed check: `live_trading` | `LIVE_TRADING_ENABLED` is set even though this release has no reviewed live execution path. | Remove the flag immediately and redeploy. Do not add a live trading path during incident response. |
| `web_home` transport failure or non-200 | The customer-facing web app is unreachable. | Open Render for `apex4traders-web`, check deploy logs, then retry `/`. If API checks are green, this is isolated to the web service. |
| `web_css` the served stylesheet does not define `--a4t-accent` | The page answers 200 with all its copy and **no working stylesheet** — a build served a CSS chunk from a previous build, or an empty one. Every content check passes on this page; it is simply unreadable, and it is the page an advertisement pays to put in front of a stranger. **This has shipped twice.** | Redeploy the web service **with the build cache cleared** — see the note on `buildCommand` in `docs/deploy/render-apex4traders.yaml`. Then confirm by fetching the chunk the live HTML links and grepping it for `--a4t-accent`; the commit in `/healthz` does NOT settle this, because the server can be on the right commit and still serve the stale chunk. |
| `web_css` links no stylesheet at all / stylesheet 404s | The build did not emit a stylesheet, or the asset path the HTML references is not being served. | Same as above, and check the build log for an error that did not fail the build. |

`/readyz` alerts must name the failed check. Do not page on the sentence
"readyz is red" alone; page on `supabase`, `shared_store`, `ctrader_oauth`,
or the exact check that failed.

Still worth watching after the first-line monitor:

1. `AUTH_UNAVAILABLE` from `/api/v1/*` — identity provider unreachable.
2. Backend process restarts.
3. `429 RATE_LIMITED` by bucket — a spike on `candles` means a client is
   looping, or the limit is too tight for normal use.
4. `BILLING_FAILED` — a paid event that did not provision. These are the ones
   a person has to look at.
5. `broker_error` entries in the journal.

## 11. Incident response

### The broker is unreachable
Reads answer `{connected, status: "unavailable", reason}` and the UI says
"Market data unavailable". Automation refuses to place orders it cannot
confirm. No action is needed to make it safe; it already is.

### A client reports automation did nothing
Read their journal. `hold` means the rule ran and chose not to act, `reject`
carries a refusal code. Both are recorded with their conditions.

### A client's tokens are suspected compromised
`POST /api/v1/ctrader/disconnect` as that client, or clear their connection
record. Tell them to revoke the application inside cTrader as well —
disconnecting removes our copy, it does not revoke their grant.

### Suspending a licence
`apex.platform.licence.revoke(user_id)`. Takes effect on the next
authenticated request; `require()` refuses anything that could produce an
order. To re-enable, `grant()` with the plan.

### Stopping everything for one client
`POST /api/v1/automation/stop` as that client. It is idempotent.

## 12. Backup and recovery

The state that matters lives in the shared backend: rule documents and their
versions, the journal, notifications, licences, and encrypted broker links.

There are **two** mechanisms, and they are not interchangeable.

- **The provider's snapshot** (Redis/Upstash). Covers the whole keyspace,
  because it is taken below the application. Recovery is to restore the
  snapshot; the application is stateless between requests. Rate-limit counters
  live in the same backend and expire on their own TTL, so a restore may
  reinstate a window that has already passed — it clears itself within one
  window and needs no action.
- **The application-level backup**, `python -m apex.backup dump|verify|restore`
  and `scripts/dr_drill.py`. Portable, readable, and restorable into a
  different deployment, which the provider snapshot is not.

**Until 2026-10-05 the application-level backup silently covered only half the
product.** `dump()` read `{ns}:user:*`, the engine journals, access and audit —
and never the `{ns}:a4t:` namespace, which is every rule, every frozen version,
every licence, every encrypted broker link and the whole early-access list. A
restore from such a file brought back clients with their settings intact and
nothing to run, and reported COMPLETE doing it. Worst of all it lost the frozen
versions, which is what the journal points at: the surviving entries would have
described terms that no longer existed.

That is fixed, and a snapshot taken by the older code now **fails `verify()`**
rather than restoring as if it were whole. If you are holding a dump file
written before that date, it is not a backup of this product.

- **Exercised:** the full drill — dump, verify, restore, content check — has
  been run end to end against a real Redis with rules, frozen versions,
  licences, broker links and waitlist entries, and passes. Locks and
  half-finished OAuth authorisations are deliberately excluded and were
  confirmed absent from the dump.
- **Run against this deployment on 2026-10-05, and it PASSED** — 24 of 24
  platform records restored, 0 failed; rules 1/1, frozen versions 1/1, broker
  links 1/1, journal entries 10/10, early-access 6/6, both indexes rebuilt as
  sets. This is the first time the application-level backup has been proven on
  this deployment's own data, and it closes gate X8.

  It took two attempts. The first run stopped on the second gate: `verify()`
  refused a perfectly good snapshot with "snapshot contains zero users". This
  service carries the platform and no engine user records at all — which is
  what it IS — and that check predated the platform. A snapshot is now refused
  for being empty everywhere, not for having no engine users.
- **Re-run it after any change to what the platform stores.** A new key shape
  that `dump()` does not know about is invisible until a drill looks for it,
  which is exactly how the `a4t:` namespace went missing for as long as it
  did. From the API service's shell, where the credentials live:

  ```
  cd ~/project/src/apex-forex-bot && python3 scripts/dr_drill.py
  ```

  Production is read-only throughout; the restore half writes into a temporary
  directory with the shared backend forced off. Exit code 0 means pass. It
  writes a snapshot to the system temp directory that holds licence keys —
  delete it afterwards.

- **Still unproven:** a restore **into** a live deployment, and broker
  reconnection after one. The drill proves the snapshot is complete and
  restorable into an isolated target. Reconnecting cTrader per user is the
  normal startup path and has not been exercised following a recovery.

## 13. Secret and log redaction

`apex/redact.py` scrubs tokens from log output, and `broker_read._scrub()`
removes them from error messages before they reach a client. The platform API
forwards only `Authorization` and `Stripe-Signature` from the transport, so a
cookie cannot ride in on a client request.

When pasting logs into an issue, check for `access_token`, `refresh_token`,
`whsec_`, `sk_live_` and anything Fernet-shaped (`gAAAAA…`).
