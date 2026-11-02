# Live launch checklist

The owner follows these steps in order before any real-money order can be
placed. This repository does not set the variables below and does not publish
the drafts. Legal drafts and the Stripe purchase path land in the sibling
changes (pull requests 38 and 39). This change is the request and approval
flow, and this list.

1. Register the company. Do not invent a legal entity, a registration number,
   or an address in the product.

2. Have a lawyer review the draft Legal terms, Refund policy and Tax notice
   at version `2026-10-24`. While they are unpublished, `/terms`, `/refunds`
   and `/tax` show `DRAFT - requires legal review`.

3. Replace the five placeholders `{{COMPANY_NAME}}`, `{{REGISTRATION_NUMBER}}`,
   `{{ADDRESS}}`, `{{JURISDICTION}}` and `{{VAT}}`. Leave the pages unpublished
   while any placeholder remains.

4. Publish only after that review. Set `A4T_LEGAL_PUBLISH` to exactly
   `2026-10-24`. The values `true`, `1`, `yes` and `on` do not publish. An
   operator whose id is listed in `A4T_OPERATOR_USER_IDS` then sends
   `POST /api/v1/live/terms/publish-current`. The request body cannot choose
   a different version.

5. Connect Stripe by name. No secret value belongs in the repository.
   Either set `A4T_STRIPE_PAYMENT_LINK` to the Payment Link (a public example
   is `https://buy.stripe.com/bJe9AT0EF2gD99Bcii2Ji02`; that URL is not a code
   default), or set `STRIPE_SECRET_KEY`, `A4T_STRIPE_PRICE_ID` and
   `A4T_PUBLIC_WEB_ORIGIN` so the server can create a Checkout Session. Also
   set `A4T_STRIPE_WEBHOOK_SECRET` or `STRIPE_WEBHOOK_SECRET`. Point the
   webhook at `/api/v1/billing/webhook` for `checkout.session.completed` and
   for refunds. A paid session whose amount is `49700` USD minor units, with
   `client_reference_id` set to the signed-in user id, records the founder
   lifetime licence. A repeated delivery of the same event does not record it
   twice.

6. Only after the provider is connected, set `A4T_CHECKOUT_ENABLED` and
   `A4T_AUTHENTICATED_CHECKOUT_ENABLED`. Until both are on, the buy button
   stays **Not on sale yet**. Publishing the terms is required before a live
   order, and it is not required before a purchase.

7. Set `A4T_OPERATOR_USER_IDS` to the accounts that may approve a live
   connection request. The client accepts the current published versions,
   requests a connection, and reads the result on `/live` and under
   Notifications. A rejection includes the scrubbed reason and the client
   may request again. Approval records the decision. It does not select a
   broker account and it does not place an order.

8. Last, and only after the steps above: the live switches.
   `A4T_LIVE_EXECUTION` must be exactly `enabled-i-accept-real-money-risk`.
   A value of `true` does not open that switch. `APEX_ALLOW_LIVE_ACCOUNTS`
   must be on, and `APP_ENV` must be `production`. These are owner-only and
   stay unset until then. Live orders stay refused while the switches are
   off, even when the terms, the licence and an approval are all on file.
