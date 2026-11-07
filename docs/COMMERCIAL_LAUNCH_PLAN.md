# Apex4Traders commercial launch plan

This document separates the work needed for a safe commercial launch from the
demo product that is already available.

## Current release status

- Demo accounts remain free.
- Live execution is unavailable. `entitlement.live_execution_enabled()` is a
  hard `False`, and the broker bridge is intentionally unreachable from the
  production request path.
- Checkout is OFF by configuration, not by missing code. `POST
  /api/v1/billing/checkout` requires a fresh authenticated session and then:
  `503 CHECKOUT_NOT_ENABLED` unless both `A4T_CHECKOUT_ENABLED` and
  `A4T_AUTHENTICATED_CHECKOUT_ENABLED` are set; `501 CHECKOUT_NOT_IMPLEMENTED`
  ("Not on sale yet") when the gates are on but Stripe is not configured; and
  only when `A4T_STRIPE_PAYMENT_LINK`, or `STRIPE_SECRET_KEY` +
  `A4T_STRIPE_PRICE_ID` + `A4T_PUBLIC_WEB_ORIGIN`, are set does
  `apex/platform/stripe_checkout.py` return a hosted URL (a Payment Link, or a
  newly created one-time Checkout Session). The session carries the platform
  user id in `client_reference_id` and `metadata.a4tUserId`, written by the
  server. The legacy browser route cannot create a payment object.
- The price is one figure: `billing.APPROVED_PRICE_MINOR = 49700` (497.00 USD).
  Any other number in a document is a transcription error; see
  `docs/PAYMENT_AND_LICENCE_DECISIONS.md` D1.
- No deployment flag or environment variable may be used to bypass either
  decision.

## Safe order of work

### 1. Sandbox checkout

The authenticated creation path exists (see "Current release status"); what
is missing is the test-mode exercise of it. Run it with Stripe test mode only,
following `docs/STRIPE_SANDBOX_RUNBOOK.md`. The server creates a one-time
Checkout Session for the approved Founder Lifetime product and writes the
authenticated platform user id into provider metadata. The browser receives
only the hosted checkout URL.

Fulfilment remains webhook-driven. The server verifies the raw signature,
requires `payment_status == "paid"`, and keeps event processing idempotent. A success-page redirect never grants a
licence. In code the webhook accepts `checkout.session.completed` (which must
be `paid`), `payment_intent.succeeded` and `invoice.payment_succeeded`;
`checkout.session.async_payment_succeeded` is NOT handled by `billing.py`
today, so a delayed-payment method would be acknowledged and ignored. Card
payments arrive as `completed` + `paid` and are unaffected.

The sandbox checklist is complete only after a real test-mode payment, webhook
delivery, duplicate delivery, unpaid session, wrong-user metadata, refund and
dispute have all been exercised. Production checkout stays off until tax,
refund, legal-entity and support details are recorded in the runbook.

### 2. Live execution readiness

Live execution needs a separate reviewed milestone. Before any real order, the
following must be implemented and tested:

- broker mode re-verification at start, reconnect and token refresh;
- explicit, expiring live consent and a per-client kill switch;
- shared idempotency claims and an append-only audit ledger;
- enforced stop, risk, exposure, drawdown and daily-trade limits;
- shared per-client order rate limits;
- instrument and global emergency stops;
- staged rollout on the owner's own account, then one consenting external
  account;
- independent security review and an exercised rollback.

Until every item is green, the correct product behaviour is a clear refusal to
trade a live account.

## Approved advertising copy for the current product

Use these messages for landing pages and small ad tests:

- “Connect your own cTrader account, test your rules on demo, and manage risk
  from one control panel.”
- “Build and preview your own trading workflow before you consider live use.”
- “Demo access is free. No outcome claims, signals, or investment advice.”
- “Live execution is planned for a separately reviewed release.”

Do not use outcome claims, passive income language, winning rates, automated
gains, or immediate live execution. Do not imply that Apex4Traders
manages client funds or gives personalised financial advice.

## Owner launch gates

The owner must provide the legal entity, support address, refund terms, tax
display decision, Stripe production account and webhook secret before a
production checkout can be enabled. These are operational prerequisites, not
deployment flags.
