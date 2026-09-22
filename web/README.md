# Apex4Traders — web

The Apex4Traders client. Next.js 16 (App Router), React 19, TypeScript,
Tailwind v4, Supabase Auth.

It talks to the Python backend in `../apex-forex-bot` over `/api/v1`. It holds
no trading logic and no broker credentials: every decision about who you are,
what you own and whether an order may be placed is made server-side. The
cTrader access token never reaches this application.

## Environment

`.env*` is git-ignored in this project, so there is no committed example file.
Create `web/.env.local` with:

```
# Supabase Auth — the platform's identity provider.
# The ANON key is the public one and is safe in a browser.
# Never put SUPABASE_SERVICE_KEY here: it bypasses Row Level Security.
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon public key>

# Where the backend answers. Empty means the same origin.
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:3001
```

## Running locally

Backend (a second terminal), in demo/dev mode:

```bash
cd ../apex-forex-bot
export ALLOW_LOCAL_BACKEND_DEV=true APP_ENV=dev PRODUCT=forex PORT=3001
export TOKEN_ENCRYPTION_KEY=$(python3 -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export SUPABASE_URL=https://<project>.supabase.co SUPABASE_ANON_KEY=<anon key>
export CTRADER_REDIRECT_URI=http://localhost:3000/api/v1/ctrader/callback
python3 -c "from apex import bot; bot._start_dashboard_server(); input()"
```

Frontend:

```bash
npm install
npm run dev        # http://localhost:3000
```

## cTrader OAuth setup

1. In the cTrader Open API portal, create an application.
2. Set its redirect URI to the value of `CTRADER_REDIRECT_URI` above. It must
   match exactly — cTrader compares it byte for byte.
3. Put the application's credentials in the BACKEND environment as
   `CTRADER_CLIENT_ID` and `CTRADER_CLIENT_SECRET`. They never go in this
   project: the secret is used only to exchange the authorization code
   server-side.
4. Scope: `accounts` is enough to read balances and positions. `trading` is
   needed before orders can be placed.

The flow is three steps, and the third is why it is safe: **Connect** returns
an authorize URL, cTrader redirects back to the callback which parks the code
server-side and returns only a nonce, and **Finish** completes the link as the
signed-in user. That last step is what stops somebody starting a flow for
their own account and getting you to approve it.

## Tests

```bash
npm test
```

`src/test/e2e.test.ts` starts the **real** Python backend in a child process
and drives the real API client against it over a socket. Only Supabase is
stubbed, because the test has no Supabase project to reach. Everything else —
ownership, the licence store, the rule store, the journal, the cTrader link —
is the code that ships.

## What is not built

- Live trading. Automation runs on demo accounts only, and there is no branch
  that would start a live loop.
- A market data feed for previews. Preview evaluates candles you supply; it
  does not fetch them, and it never invents them.
