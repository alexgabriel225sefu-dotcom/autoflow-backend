# Apex4Traders — production runbook

Operating the platform. Everything here is checkable against the code; where
something is not yet provisioned it says so rather than describing a system
that does not exist.

**Live trading is not part of this deployment.** No procedure below enables
it, and none should be read as a step towards it.

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
| `A4T_PLAN`, `A4T_LICENCE_DAYS` | optional | See `docs/PAYMENT_AND_LICENCE_DECISIONS.md`. |
| `RL_A4T_*_PER_MIN` | optional | Rate limits, below. |

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
| `A4T_PRICE_MINOR`, `A4T_CURRENCY`, `A4T_SKU` | only with billing | No defaults. Unset means checkout answers 503. |
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

**Known limitation.** `RateLimiter` is a fixed window in one process. With N
instances the effective limit is N times the configured one. Set limits with
the instance count in mind, and treat a shared counter as the fix if that
becomes insufficient.

**`candles` is protection for the broker connection, not just the server.**
cTrader allows five historical requests per second **per connection**, shared
across every client on it.

---

## 3. Startup

1. Set the environment above.
2. Start the backend; it refuses to start on a missing encryption key or a
   missing shared backend, and the message says which.
3. Confirm `GET /api/v1/me` with a valid bearer token returns 200 and
   `GET /api/v1/conditions` lists the condition registry.
4. Deploy the web app with `npm run build`, then `npm run start`.
5. Confirm `/login` renders and a sign-in reaches `/dashboard`.

## 4. Health checks

There is no dedicated `/healthz` yet. Until there is:

| Check | How | Healthy |
|---|---|---|
| Backend up | `GET /api/v1/conditions` with a valid token | 200 with a non-empty registry |
| Auth path | `GET /api/v1/me` | 200, or 401 `AUTH_REQUIRED` for a bad token — **not** 503 `AUTH_UNAVAILABLE`, which means Supabase is unreachable |
| Shared store | backend starts at all | it refuses otherwise |
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

Not yet provisioned. What is worth watching, in priority order:

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

- **Backup:** the Redis/Upstash provider's own snapshot mechanism.
- **Recovery:** restore the snapshot; the application is stateless between
  requests apart from in-process rate-limit windows, which reset harmlessly.
- **Not yet done:** a restore has not been exercised against this deployment.
  Until it has, the backup is a plan and not a guarantee. This is listed as a
  production-launch gate in `docs/RELEASE_READINESS.md`.

## 13. Secret and log redaction

`apex/redact.py` scrubs tokens from log output, and `broker_read._scrub()`
removes them from error messages before they reach a client. The platform API
forwards only `Authorization` and `Stripe-Signature` from the transport, so a
cookie cannot ride in on a client request.

When pasting logs into an issue, check for `access_token`, `refresh_token`,
`whsec_`, `sk_live_` and anything Fernet-shaped (`gAAAAA…`).
