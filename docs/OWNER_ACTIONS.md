# Owner actions

What only the owner can do, in the order that unblocks the most. Each item says
where to click or which variable to set, and where the detail lives. Names of
variables only; set values in the host's secret store (Render), never in the
repo or in chat.

Status as of 2026-10-29. "Unverified" means I could not confirm it from the
code or from the deployment.

Owner decision on record: start **without a company, VAT number or lawyer**
until the first revenue. Section C therefore comes last and nothing in A or B
depends on it. No legal text has been drafted and no checkout gate has been
flipped.

---

## A. Do now (days)

### 1. Decide what happens when the free trial ends  (urgent: 2026-10-31)
The app banner "Demo automation is free on this account until 31 Oct 2026" is
that account's own trial end: account creation + 14 days
(`plans.start_trial`, `licence.expiresAt`). It is not a global date. At that
instant demo automation **stops** for that account: running loops are stopped
by the watchdog within about 3 minutes and new starts are refused with
`TRIAL_EXPIRED`. Nothing is deleted, nothing converts to a paid plan, and
signing in again does not extend it. Proof:
`apex-forex-bot/tests/test_platform_trial_expiry.py`.

Choose one:
- **Let it lapse** (current behaviour). Clients see: "the 14-day free demo trial
  for this account has ended, so demo automation is paused. Your rules and
  settings are kept - contact support to continue".
- **Extend named accounts by hand** with the existing mechanism,
  `licence.grant("<supabase-user-id>", plan="demo_trial",
  expires_at=<unix seconds>)` run on the backend host in the deployment's
  environment. Steps and cautions: `docs/MANUAL_LICENCE_OPERATIONS.md` section 5.
  Find the user id in Supabase -> Authentication -> Users. Nothing in the code
  extends a trial on its own.
- **Change the default length for future sign-ups** (`plans.TRIAL_DAYS`): a
  code change that does not touch existing trials. Ask engineering.

Whichever you pick, a support address (item 6) should exist before 31 Oct
because the message tells clients to contact support.

### 2. Stripe dashboard, test mode (sandbox pass)
Follow `docs/STRIPE_SANDBOX_RUNBOOK.md` Part B: toggle Test mode, create the
497.00 USD one-time product, copy the test Price id and `sk_test_` key, add the
webhook endpoint (`/api/v1/billing/webhook`, events `checkout.session.completed`,
`charge.refunded`, `charge.dispute.created`), then run its eleven checks.
Variables (sandbox service only): `STRIPE_SECRET_KEY`, `A4T_STRIPE_PRICE_ID`,
`A4T_PUBLIC_WEB_ORIGIN`, `A4T_STRIPE_WEBHOOK_SECRET`. Production keeps both
`A4T_CHECKOUT_ENABLED` and `A4T_AUTHENTICATED_CHECKOUT_ENABLED` unset.
Before this, anyone can run Part A (local signed replay) without Stripe:
`python apex-forex-bot/scripts/stripe_webhook_replay.py`.

### 3. Supabase: sign-in providers and redirect URLs
Supabase dashboard -> Authentication -> URL Configuration: add
`https://apex4traders-web.onrender.com/auth/callback` (and
`http://localhost:3000/auth/callback` for local work). Authentication ->
Providers: enable **Google** (client id and secret from Google Cloud Console;
add Supabase's callback URL to the Google client) and **Apple** (Services ID,
key). Steps in `docs/SUPABASE_OAUTH_SETUP.md`. Test with a new and an
existing account. Until enabled the buttons show Supabase's error.

### 4. Supabase: run the RLS migration
A row-level-security migration is being prepared by the security work stream.
**Unverified:** its file name and whether it is merged; it is not on this
branch (`sql/` here has only `001_licences_and_bot_configs.sql`,
`002_trade_events.sql`, `affiliates-schema.sql`). When it lands: Supabase ->
SQL Editor -> paste and run it once on the production project, then confirm
the app still signs in and loads. Never put the service key in the web app
(`docs/PRODUCTION_RUNBOOK.md`, `SUPABASE_ANON_KEY` row).

### 5. Supabase service-role key for account deletion
Account deletion needs the server to call Supabase's admin API. Set
`SUPABASE_SERVICE_KEY` on the **API service only** (the Render API service ->
Environment); Supabase -> Project Settings -> API -> `service_role`. Server
side only, never `NEXT_PUBLIC_*`, never in the web service. **Unverified:**
the deletion endpoint's exact name; confirm in `docs/PRODUCTION_RUNBOOK.md`
once that change is merged.

### 6. Support mailbox
Create the address clients will be told to write to (any mailbox you read).
Put it where the product shows contact details; the legal pages still carry
`[TO BE CONFIRMED]` placeholders and are deliberately not filled (section C).
Optional reply-to for waitlist mail: `A4T_WAITLIST_REPLY_TO`.

### 7. E-mail sending: sender domain
- Waitlist mail: Resend dashboard -> Domains -> add and verify your sender
  domain (DNS records), create an API key. Set `RESEND_API_KEY` and
  `A4T_WAITLIST_FROM_EMAIL`. `/readyz` `waitlist_email` must read `ok`, not
  `skipped` or `fail`. Detail: `docs/WAITLIST_EMAIL_DELIVERY.md`.
- Sign-up confirmation mail (Supabase): Supabase -> Authentication -> SMTP
  Settings -> enable custom SMTP (Resend's SMTP works) with the same verified
  domain, because Supabase's built-in sender is rate-limited. **Unverified:**
  whether a sign-up confirmation has ever been completed end to end
  (`docs/RELEASE_READINESS.md`, X1).

### 8. UptimeRobot
uptimerobot.com -> Add New Monitor -> HTTP(s), interval 5 min, three monitors:
`https://apex4traders-api.onrender.com/healthz`,
`https://apex4traders-api.onrender.com/readyz`,
`https://apex4traders-web.onrender.com/`. Set an alert contact you read.
Detail: `docs/PRODUCTION_RUNBOOK.md` (monitoring section). Unverified: that
none exists today.

---

## B. Before taking the first payment

### 9. Production Stripe
After item 2 passes: Stripe -> activate the live account, create the live
product (same 497.00 USD) and the live webhook endpoint, then on the
**production API service** set the live equivalents of the sandbox variables
and, as the last step, `A4T_CHECKOUT_ENABLED` and
`A4T_AUTHENTICATED_CHECKOUT_ENABLED`. These two are the switch; nothing else
is. Confirm `GET /api/v1/billing/offer` shows 49700 usd and `/readyz` has no
offer drift. Do this only when you accept that, per your decision, there is no
company, VAT or published refund policy yet (item 10).

### 10. Know what you are choosing without a company
Stripe will ask who the seller is; selling as an individual is possible but
tax and consumer-law exposure is yours. This is stated plainly, not decided
for you. The list of what is missing is `docs/LEGAL_LAUNCH_BLOCKERS.md`.

---

## C. Later, after first revenue (deferred by owner decision)

Nothing here is drafted or filled in. In order:
1. Company / legal entity, then update the Stripe account to it.
2. VAT registration and the tax-display choice (D5 in
   `docs/PAYMENT_AND_LICENCE_DECISIONS.md`; L5 in
   `docs/LEGAL_LAUNCH_BLOCKERS.md`).
3. A lawyer: Terms of Service, Privacy Policy, risk disclosure, refund policy
   (L1 to L8 in `docs/LEGAL_LAUNCH_BLOCKERS.md`). Then an operator records the
   published versions (`A4T_LEGAL_PUBLISH`, `/live/review`) so the live gate
   can see them.
4. Only then consider live execution: a separate reviewed milestone
   (`docs/LIVE_EXECUTION_SPECIFICATION.md`, `docs/LIVE_LAUNCH_CHECKLIST.md`).
   `A4T_LIVE_EXECUTION` stays closed until that review.
