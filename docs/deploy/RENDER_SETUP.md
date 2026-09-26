# Apex4Traders — bringing the private demo beta online

The step-by-step for creating the two Render services by hand. The blueprint
beside this file, `render-apex4traders.yaml`, holds the same settings in Render's
own format; this document is the one to follow in the dashboard, and it explains
the parts a YAML file cannot.

Nothing here has been applied. No service has been created, nothing is deployed,
no branch has been merged. Payments and live trading stay off, and a section
below says which variables would turn them on so they can be recognised and
avoided.

## 0. Before touching Render

Four external things have to exist first. Each one is a `fail` in `/readyz` until
it does, by name, so the readiness endpoint doubles as the checklist.

| What | Why | What you end up with |
|---|---|---|
| Supabase project | identity — sign-up, sign-in, confirmation e-mail | project URL, anon key |
| A shared Redis | ownership, entitlement and order idempotency are per-container without it | either a `REDIS_URL`, or an Upstash REST URL + token |
| cTrader Open API application | clients cannot connect an account at all without one | client id, client secret |
| A Fernet encryption key | broker tokens at rest; the API refuses to start without it | one generated key |

The Fernet key, generated on your own machine — it never goes in the repository
and never in a chat message:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep a copy somewhere you control. **If it is lost, every stored broker token
becomes unreadable** and every client has to reconnect their account. If it is
ever rotated, the same is true.

The cTrader application is created once, at <https://openapi.ctrader.com/apps>.
Its redirect URI depends on a URL Render has not issued yet, so §3 comes back to
it.

## 1. The API service

Create it first: the web service needs its URL, and the cTrader redirect URI
needs its hostname.

New → Web Service → this repository.

| Setting | Value |
|---|---|
| Name | `apex4traders-api` |
| Language / runtime | Python |
| Branch | `claude/apex4traders-platform-v1` |
| Root Directory | `apex-forex-bot` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python -u platform_server.py` |
| Health Check Path | `/healthz` |
| Auto-Deploy | **Off** |

Three of those are worth more than a glance.

**`python -u platform_server.py`, and never `main.py`.** `main.py` starts the
Telegram bot: polling, the per-user trading loops, the operator dashboard.
Pointing this service at it would start a *second* live trading bot beside the
one already running. `platform_server.py` serves `/healthz`, `/readyz` and
`/api/v1/*` and nothing else — it does not import the bot at all, which
`tests/test_platform_server.py` checks on the import graph.

**`/healthz`, and not `/readyz`.** Render restarts a container that fails its
health check. `/readyz` deliberately touches Supabase, Redis and the rest, so
using it here would turn one dependency wobble into every container restarting at
once — a degradation becomes an outage. `/healthz` answers from process state
alone. Use `/readyz` by hand, in a browser, when you want to know whether the
dependencies are healthy.

**Auto-Deploy off.** A push to this branch should not restart a service that
holds broker sessions without somebody choosing the moment.

### Environment variables — API service

Set the four config values, then the secrets. `A4T_ALLOWED_ORIGIN` cannot be
filled in until §2 has produced the web URL; leave it for now and come back.

Required, plain config — type these values exactly:

| Key | Value |
|---|---|
| `PRODUCT` | `forex` |
| `APP_ENV` | `production` |
| `PYTHONUNBUFFERED` | `1` |
| `RATE_LIMIT_STORE` | `auto` |

Required secrets — paste the values into the Render dashboard only:

| Key | Where it comes from |
|---|---|
| `TOKEN_ENCRYPTION_KEY` | the Fernet key generated in §0 |
| `SUPABASE_URL` | Supabase → Project Settings → API |
| `SUPABASE_ANON_KEY` | the same page — the **anon** key, never the service key |
| `CTRADER_CLIENT_ID` | the cTrader application |
| `CTRADER_CLIENT_SECRET` | the cTrader application |
| `CTRADER_REDIRECT_URI` | §3 — it contains this service's own hostname |
| `A4T_ALLOWED_ORIGIN` | §2 — the web service's URL |

And **one** shared-backend option, not both:

| Option | Keys |
|---|---|
| Render Key Value, or any Redis | `REDIS_URL` |
| Upstash | `UPSTASH_REDIS_REST_URL` **and** `UPSTASH_REDIS_REST_TOKEN` |

A single Upstash variable on its own is the one combination that half-configures
the store, and `/readyz` reports it as configured-but-unreachable rather than
missing, which is a more confusing message than either.

Optional, and only if you want them:

| Key | Effect if set |
|---|---|
| `ADMIN_CHAT_IDS` | privileged operator ids for the legacy bot's tooling. The platform API does not read it. |
| `CTRADER_SCOPE` | defaults to `trading`. `accounts` restricts the OAuth grant to reading the account list — a reasonable choice for a demo beta, since nothing in this release places an order anyway. |

## 2. The web service

New → Web Service → the same repository.

| Setting | Value |
|---|---|
| Name | `apex4traders-web` |
| Language / runtime | Node |
| Branch | `claude/apex4traders-platform-v1` |
| Root Directory | `web` |
| Build Command | `npm ci && npm run build` |
| Start Command | `npm run start` |
| Health Check Path | `/` |
| Auto-Deploy | **Off** |

`npm ci` and not `npm install`: the lockfile is the dependency set that was
reviewed and audited, and `install` may resolve something else.

### Environment variables — web service

| Key | Value |
|---|---|
| `NODE_ENV` | `production` |
| `NEXT_PUBLIC_SUPABASE_URL` | the same Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | the same anon key |
| `NEXT_PUBLIC_API_BASE_URL` | the API service's URL from §1, e.g. `https://apex4traders-api.onrender.com`, no trailing slash |

**Nothing secret belongs on this service.** Everything prefixed `NEXT_PUBLIC_`
is compiled into the JavaScript the browser downloads — that is what the prefix
means, and both values above are public by design. These must never appear here,
under any name:

- `TOKEN_ENCRYPTION_KEY`
- `CTRADER_CLIENT_SECRET`
- `SUPABASE_SERVICE_KEY` (or service-role key)
- `UPSTASH_REDIS_REST_TOKEN`
- `REDIS_URL`
- `STRIPE_SECRET_KEY`

The web client has no code path that needs any of them. A secret on this service
is one `NEXT_PUBLIC_` prefix away from being published to every visitor.

### Then go back to the API service

Set `A4T_ALLOWED_ORIGIN` to the web service's URL — scheme and host, no path, no
trailing slash:

```
https://apex4traders-web.onrender.com
```

This is required, not cosmetic. The browser calls `/api/v1/*` on a different
origin with an `Authorization` header, which makes it a non-simple request, so it
sends a CORS preflight first and refuses the real call unless the reply names the
origin. Without this variable the dashboard loads and then shows nothing but
network errors. The value is compared exactly and never reflected back from the
request — reflecting it would let any site on the internet make authenticated
calls with a visitor's token. If you attach a custom domain later, add it to the
same variable, comma-separated.

## 3. The cTrader redirect URI

Register exactly this in the cTrader application, substituting the API service's
own hostname:

```
https://<API-HOST>/api/v1/ctrader/callback
```

With the default Render hostname:

```
https://apex4traders-api.onrender.com/api/v1/ctrader/callback
```

Then set `CTRADER_REDIRECT_URI` on the **API** service to the same string, byte
for byte. Three things go wrong here more often than anything else in this
document:

- **It is the API host, not the web host.** The callback is an API route. Sending
  cTrader to the web service produces a 404 at the end of a successful login.
- **A trailing slash is a different URI.** cTrader compares the string.
- **`/api/v1/ctrader/callback`, not `/api/ctrader/callback`.** The second one is
  the *legacy Telegram bot's* callback. It exists, it will answer, and it will
  attach the account to the wrong product.

If you attach a custom domain to the API later, register the new URI in the
cTrader portal as well and update the variable; do not assume the old one keeps
working.

## 4. Should the cTrader client secret be rotated first?

**Yes. Rotate it before this goes online.** Recommended, not required.

A defect fixed in `03cb63dcb` put the application's `client_secret` into the
message of any exception raised by a failed token exchange. cTrader reads its
token parameters from the query string, so the URL — and therefore the secret —
appeared in `requests`' own error text, and a failed token refresh is exactly the
kind of event that gets logged. The code no longer allows it, and the redactor
now masks credential-bearing query parameters as a second line of defence.

What is *not* known is whether such a line was ever written to the legacy
service's logs and retained. Determining that means reading production logs
looking for a secret, which is not something to do casually. Rotating is cheaper
than establishing the answer: it is one button in the cTrader portal plus one
variable on one service, it invalidates anything that may have leaked, and the
only cost is that clients who had already connected an account reconnect it.
Since nobody is connected yet, right now that cost is zero — which is why this is
the moment to do it.

Rotate in the portal, then update `CTRADER_CLIENT_SECRET` on the API service.
Nothing else changes: the client id and the redirect URI stay the same.

## 5. First verification, in order

Do these in order. Each one tells you something the next one assumes.

**1 — the API is running.** `/healthz` touches no dependency, so it answers even
when everything else is misconfigured:

```bash
curl -s https://apex4traders-api.onrender.com/healthz
# {"ok": true, "status": "ok", "uptimeSec": ...}
```

A 200 means the process is up. Anything else, or no answer at all, is a start
failure — read the service's log tab; the start command logs unbuffered, so the
reason is in there.

**2 — the dependencies are configured.** `/readyz` names every check and lists
the failures:

```bash
curl -s https://apex4traders-api.onrender.com/readyz | python3 -m json.tool
```

Expect `503` until everything in §0 is set, and read the `failed` list: it names
the variables, e.g. `not configured: CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET`.
It returns no secret and no environment *value*, only names, so it is safe to
read and safe to paste. Work down the list until it answers `200` with
`"status": "ok"`.

Two checks deserve reading closely rather than just counting:

- `live_trading` must say `"enabled": false`. That is the expected and only
  supported state for this release.
- `dev_flags` must say `no development-only flags are set`. If it names one,
  remove it from the service; in production those flags mean a per-container
  store or unencrypted broker tokens.

**3 — the web app loads.** Open the web service's URL. The landing page, `/login`
and `/signup` must render for a signed-out visitor. If the page is blank, the
build succeeded but the runtime failed — check the log tab.

**4 — the two halves can talk.** This is the step that catches a wrong
`A4T_ALLOWED_ORIGIN` or `NEXT_PUBLIC_API_BASE_URL`, and it is the failure most
likely to be mistaken for "the app is broken". From your machine:

```bash
curl -s -i -X OPTIONS \
  https://apex4traders-api.onrender.com/api/v1/me \
  -H "Origin: https://apex4traders-web.onrender.com" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: authorization" | head -8
```

Expect `204` and a header reading
`Access-Control-Allow-Origin: https://apex4traders-web.onrender.com`. A `403`
means `A4T_ALLOWED_ORIGIN` does not match the web URL exactly — check the scheme
and for a trailing slash.

And the unauthenticated call, which should be refused *politely*:

```bash
curl -s -i https://apex4traders-api.onrender.com/api/v1/me \
  -H "Origin: https://apex4traders-web.onrender.com" | head -12
```

Expect `401` with a JSON body **and** the `Access-Control-Allow-Origin` header
present. The header on a refusal is what lets the browser read the 401 and show
"sign in" instead of a generic network error.

**5 — sign up, and check what the server says you may do.** Create an account
through the web UI, confirm the e-mail, sign in. Then, in the browser's developer
tools on the dashboard, find the `GET /api/v1/me` request. Its `execution` block
is the server's own answer about capability, and the UI renders that rather than
deciding for itself. It must report live execution disabled. The badge on screen
must read `NOT CONNECTED` before a broker account is linked, and `DEMO` after a
demo account is.

## 6. Running the cTrader TLS check

`scripts/check_ctrader_tls.py` opens a TLS connection to
`demo.ctraderapi.com:5035` and closes it before sending anything. It needs no
credential and no account. It exists because port 5035 is not HTTPS and is
blocked on a great many networks, and "the broker is down" and "this network
does not allow 5035" look identical from inside the application.

**Shortest path: your own laptop.** A home or office connection normally allows
outbound 5035; a corporate network often does not, and a mobile hotspot is a
good second try.

```bash
git clone -b claude/apex4traders-platform-v1 <this repository> apex4traders
cd apex4traders/apex-forex-bot
python3 scripts/check_ctrader_tls.py
```

No dependencies are needed — it uses only the standard library. Exit codes are
deliberately distinct:

| Exit | Meaning |
|---|---|
| `0` | the handshake succeeded and the certificate verified |
| `1` | TCP reached the broker but TLS failed — a real problem, report it |
| `2` | port 5035 is unreachable from this host — a *network* answer, not a TLS one. Try another network. |

**From Render instead.** The API service's Shell tab works, on a paid instance
type, and it is the more useful place to run it because it answers the question
that matters — whether the *deployment* can reach the broker, not whether your
laptop can:

```bash
cd /opt/render/project/src/apex-forex-bot
python3 scripts/check_ctrader_tls.py
```

Run it there as well as locally once the service exists. A pass on your laptop
and a failure on Render means the bot cannot trade from Render, which is worth
knowing before a client connects an account.

## 7. After the TLS check passes

Then, and only then, `docs/CTRADER_DEMO_SMOKE_TEST.md` against a real cTrader
demo account. The minimum path, with the detail in that document:

1. Sign up, confirm, sign in on the deployed web app.
2. Connect the demo account through OAuth. The callback URL in the browser's
   address bar must be the one registered in §3.
3. Select the demo account. If the cTrader login also holds a live account, the
   selection must refuse it — that refusal is part of the test, not an obstacle.
4. Confirm the badge reads `DEMO`, and that `GET /api/v1/me` agrees.
5. Confirm balance, positions and orders carry real data from the broker. An
   empty list is only acceptable when it is genuinely true of the account.
6. Then run the script, from the deployment's own environment:

```bash
export SMOKE_CONFIRM_DEMO_ONLY=yes
export SMOKE_USER_ID=<the Supabase user id>
python3 scripts/smoke_ctrader_demo.py
```

`TOKEN_ENCRYPTION_KEY` has to be present in that environment, because the stored
broker token is encrypted with it — which is why running this from the API
service's shell is easier than running it locally. The script is read-only: it
places no order, closes no position and amends nothing. It refuses to start
without the confirmation variable, without a user id, without the encryption key,
if live execution is reported as enabled, or if the selected account is not a
demo account — and each refusal names the variable it wants, exiting `2`.

Set these in the service environment or your shell. Never paste them into a chat
message, an issue, or a commit.

## 8. What must not be set, on either service

These exist and each one would turn something on that has not been reviewed.
Listed so they can be recognised, not so they can be tried.

| Variable | What setting it would do |
|---|---|
| `LIVE_TRADING_ENABLED` | intended to enable real-money execution. No execution path exists behind it in this release and `entitlement.live_execution_enabled()` returns a literal `False`, so it cannot actually enable anything — but `/readyz` fails if it is set, deliberately, because its presence means somebody is trying. |
| `APEX_ALLOW_LIVE_ACCOUNTS` | would allow a real-money account to be selected. |
| `A4T_CHECKOUT_ENABLED` | would open checkout. There is no approved price, currency, SKU, legal entity or refund policy yet. |
| `A4T_STRIPE_WEBHOOK_SECRET` | only meaningful with checkout on; the webhook answers 503 while it is off. |
| `ALLOW_LOCAL_BACKEND_DEV` | makes a per-container store acceptable. In production that silently breaks ownership, entitlement and order idempotency. `/readyz` fails if it is set. |
| `ALLOW_PLAINTEXT_DEV_STORAGE` | stores broker tokens **unencrypted**. `/readyz` fails if it is set. |
| `CTRADER_ALLOW_STATELESS_CALLBACK` | accepts an unsigned OAuth callback, which cannot be attributed to a client — it can bind one person's broker account to another person's login. Startup is refused when this is on in production. |
| `DASHBOARD_TOKEN` | the legacy bot's operator dashboard. `platform_server.py` does not serve it, so the variable does nothing here; it belongs to the other service. |

## 9. What this deployment is and is not

It is a private demo beta on a real URL: sign-up, sign-in, connecting a cTrader
**demo** account, reading balance, positions, orders and candles, building rules
and previewing them against real bars.

It is not live trading — three independent locks refuse it and none of them is a
configuration flag. It is not a paid product; checkout is off and the billing
check is skipped rather than passed. It is not a public launch: the pricing,
legal entity, contact address, refund policy and data-region decisions are all
still open, and `docs/RELEASE_READINESS.md` lists them by identifier.

Until the smoke test in §7 has actually passed against a real demo account, the
honest status of the broker integration is untested. That is the one remaining
blocker, and it is the reason this document ends there rather than with a launch.
