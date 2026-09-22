# Apex4Traders Platform v1 — release candidate checklist

Staging only. **No merge, no public deploy, no live trading.**

Branch: `claude/apex4traders-platform-v1`.

---

## Live trading does not exist

Not "disabled", not "behind a flag" — **not implemented**. There is no branch
in `apex/platform/automation.py` that starts a live loop, and no configuration
that would create one. Three independent refusals stand in the way:

1. `ctrader_link.live_allowed()` requires `APP_ENV=production` **and** an
   explicit `APEX_ALLOW_LIVE_ACCOUNTS=true`. Either alone is not enough.
2. `select_account()` refuses to select a live account when that is false, and
   `get_ctrader_connection()` refuses to open one even for reading.
3. `automation._preflight()` refuses any account whose mode is not `demo`,
   with `LIVE_NOT_SUPPORTED`.

When live is built it will be deliberate work with its own review.

---

## What is implemented

| Area | State |
|---|---|
| Identity | Supabase Auth (email + password). Platform identity is `supabase_user_id`. |
| Sessions | Verified against Supabase per request, 60s cache; destructive calls bypass the cache. |
| Licence | Per-user store keyed by Supabase id. Unknown is **not** entitled. |
| cTrader link | OAuth with an authenticated completion step; tokens encrypted at rest. |
| Rules | RuleDoc CRUD, validation, activation (freezes a version), versioning. |
| Conditions | 12, all with published formulas and named parameters. |
| Evaluator | Pure. Three-valued logic: unknown is never folded into false. |
| Execution | Decision → ExecutionRequest → the existing `force_trade` gate. One path. |
| Reads | accounts, positions, orders, candles — all read-only. |
| Journal | 12 statuses, filter by account/symbol/period/RuleDoc/status, paged. |
| Notifications | In-platform centre, read/read-all, filter by type. |
| Preview | Read-only, on candles fetched from the connected account. |
| Automation | Demo only: start, pause, resume, stop. Idempotent, journalled. |
| Web client | Next.js 16, 17 pages, every screen backed by a real endpoint. |

### Endpoints

```
GET  /api/v1/me                          GET  /api/v1/conditions
GET  /api/v1/rules                       POST /api/v1/rules
GET  /api/v1/rules/{id}                  PUT  /api/v1/rules/{id}
POST /api/v1/rules/{id}/validate|activate|pause|resume|archive|version|preview
GET  /api/v1/rules/{id}/versions/{n}
POST /api/v1/ctrader/connect|complete|select|disconnect
GET  /api/v1/ctrader/status              GET  /api/v1/ctrader/callback  (no auth)
GET  /api/v1/accounts                    GET  /api/v1/accounts/{ctid}
GET  /api/v1/accounts/{ctid}/positions|orders|candles
GET  /api/v1/positions                   GET  /api/v1/orders
GET  /api/v1/journal                     GET  /api/v1/journal/{id}
GET  /api/v1/notifications               POST /api/v1/notifications/read-all
POST /api/v1/notifications/{id}/read
GET  /api/v1/automation                  POST /api/v1/automation/start|pause|resume|stop
```

`GET /api/v1/ctrader/callback` is the only unauthenticated route, and it has
to be: cTrader redirects a browser there, and a browser arriving from a
redirect carries no bearer token. It finishes nothing — it parks the
authorization code server-side and returns a nonce.

---

## What is NOT implemented

- **Live trading.** See above.
- **Email delivery from the platform.** Supabase sends confirmation and reset
  mail. There is no other outbound email.
- **Payments / licence purchase.** `licence.grant()` is called server-side;
  there is no checkout flow wired to it.
- **Closing or amending positions from the platform.** The read path is
  read-only by construction, and no endpoint closes a position.
- **Multi-account automation.** One running rule per client.
- **Backtesting.** Preview evaluates one snapshot, not a history.
- **WebSockets.** The dashboard polls, and stops polling on a hidden tab.

---

## Environment

### Backend (`apex-forex-bot`)

| Variable | Required | Notes |
|---|---|---|
| `SUPABASE_URL` | yes | Session verification. |
| `SUPABASE_ANON_KEY` | yes | The **public** anon key. Never the service key. |
| `TOKEN_ENCRYPTION_KEY` | yes | Fernet key. Encrypts broker tokens; the OAuth state key is derived from it. |
| `CTRADER_CLIENT_ID` / `CTRADER_CLIENT_SECRET` | yes | From the cTrader Open API portal. |
| `CTRADER_REDIRECT_URI` | yes | Must match the portal byte for byte. |
| `PRODUCT` | yes | Key namespace, e.g. `forex`. |
| `REDIS_URL` or Upstash pair | production | Without a shared backend, startup is refused unless `ALLOW_LOCAL_BACKEND_DEV=true` **and** `APP_ENV=dev`. |
| `APP_ENV` | yes | `dev` or `production`. |
| `APEX_ALLOW_LIVE_ACCOUNTS` | no | Leave unset. Live is not implemented. |
| `TELEGRAM_BOT_TOKEN` | **no** | Legacy only. The platform works without it. |

### Web (`web`)

Copy `web/env.example` to `web/.env.local`:

| Variable | Notes |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Same project as the backend. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Public anon key. |
| `NEXT_PUBLIC_API_BASE_URL` | Where the backend answers. |

`.gitignore` ignores `.env*` with no exceptions, so there is no filename
starting with `.env` under which real values could be committed by accident.

---

## Running locally

**Backend** (terminal 1):

```bash
cd apex-forex-bot
export APP_ENV=dev PRODUCT=forex PORT=3001
export ALLOW_LOCAL_BACKEND_DEV=true
export TOKEN_ENCRYPTION_KEY=$(python3 -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export SUPABASE_URL=https://<project>.supabase.co
export SUPABASE_ANON_KEY=<anon key>
export CTRADER_CLIENT_ID=<id> CTRADER_CLIENT_SECRET=<secret>
export CTRADER_REDIRECT_URI=http://localhost:3001/api/v1/ctrader/callback
python3 -c "from apex import bot; bot._start_dashboard_server(); input()"
```

**Frontend** (terminal 2):

```bash
cd web
npm install
npm run dev     # http://localhost:3000
```

---

## Manual test with a cTrader DEMO account

Do this on a demo account. Nothing below can place an order — automation is
demo-only and there is no live path — but demo is also where a misconfigured
rule costs nothing.

1. **Sign up** at `/signup`. Confirm the email from Supabase. Connecting a
   broker and activating a rule are both refused until you do.
2. **Licence.** `/license` will show *No licence*. Grant one server-side:
   `python3 -c "from apex.platform import licence; licence.grant('<supabase-user-id>', plan='pro')"`.
   The id is on `/settings`. Reload — it should read *Licensed*.
3. **Connect cTrader** at `/connect`. Step 1 opens cTrader in a new tab; sign
   in and approve. Step 2 finishes the link **in the app**. That second step
   runs as you, which is what stops someone else's flow binding your account.
4. **Choose an account** at `/accounts`. A live account shows *Live accounts
   are not available here* and has no Select button. Select the demo one.
5. **Check the reads.** `/positions` and `/orders` should show *No open
   positions* / *No pending orders* with the account and DEMO badge. If the
   broker cannot be reached you should see the real error, never an empty
   table.
6. **Build a rule** at `/rules/new`. Only conditions the engine implements
   appear. Save the draft.
7. **Validate** on the rule page. Fix anything listed; every problem is shown
   at once, not one at a time.
8. **Preview.** Pick the instrument, keep the rule's timeframe, *Fetch market
   data*, then *Preview*. The source line should name the account, the bar
   count and the time of the last bar. A HOLD or REJECT is labelled as not
   executable and no order is created.
9. **Activate** the rule. It freezes at version 1; editing it afterwards
   creates version 2 as a draft while version 1 keeps running.
10. **Start automation** (demo). Confirm the prompt. `/dashboard` should show
    *RUNNING* and DEMO. `/journal?status=automation_started` should have an
    entry; `/notifications` should have an unread alert.
11. **Pause, resume, stop.** Each asks for confirmation and shows the API's
    answer. Stopping twice is not an error.
12. **Disconnect** at `/accounts`. Every read should fall back to *No cTrader
    account is connected* — not to an empty table.

---

## Known risks

| Risk | Detail |
|---|---|
| **Session cache TTL** | A revoked Supabase session stays valid for up to 60s on read endpoints. Destructive calls re-verify, so the window applies to reads only. |
| **Local dev backend** | With `ALLOW_LOCAL_BACKEND_DEV=true` the store is per-process: ownership, entitlement and order idempotency do not coordinate between instances. Never set it on a deployed service. |
| **Journal index writes** | The per-user index is read-modify-write under a Redis claim. Without a shared backend there is no lock and a concurrent append could lose a line. Development only. |
| **Journal cap** | 5000 entries per client; older ones are dropped. |
| **cTrader rate limits** | 5 historical requests/second per connection. Candles go through the shared cache, but a busy account can still be throttled — that surfaces as `unavailable`, not as empty data. |
| **`get_candles` has no paper short-circuit** | Trendbars are public market data, so the connector fetches them for real even on a paper account. Correct, but it means a candles request needs a working broker connection. |
| **Preview is one snapshot** | It answers "what would this rule decide on these bars", not "how would it have performed". Do not read it as a backtest. |
| **No rate limiting on the platform API** | The existing server rate-limits its own older routes; `/api/v1/*` relies on Supabase auth and per-account broker limits. Worth adding before public exposure. |
| **Supabase availability** | If Supabase cannot be reached, every endpoint answers 503 `AUTH_UNAVAILABLE`. Clients are not signed out, but nothing works until it returns. |

---

## Telegram: legacy, and not part of Apex4Traders v1

Verified, not assumed:

- **`apex/platform/` imports nothing from Telegram.** Asserted across the whole
  package through the AST in `tests/test_platform_ctrader_link.py`, so the file
  that reintroduces it fails the suite.
- **`web/src` contains one mention**, in `src/test/backend_fixture.py`, which
  *removes* `TELEGRAM_BOT_TOKEN` from the environment before starting the
  backend. It is a negative assertion — proof the flow runs without a bot
  token — not a dependency.
- **The old Telegram code still exists and still works.** `apex/telegram.py`,
  `apex/ctrader_oauth.py` and the `chat_id`-keyed stores are untouched, because
  clients onboarded through Telegram have tokens stored there and deleting it
  would strand them.
- `apex/ctrader_oauth.py` carries a `DEPRECATED` header explaining why it could
  not be reused: it is keyed by `chat_id`, it signs OAuth state with the bot
  token, and it completes the account link inside the callback.

**None of it is part of the Apex4Traders v1 platform path.** A deployment with
no `TELEGRAM_BOT_TOKEN` set runs the platform completely.

---

## Verification

```bash
python3 apex-forex-bot/tests/run_all.py   # backend
cd web && npm test                        # frontend
cd web && npm run build                   # production build
```
