# Payment and licence — one-time founder access, checkout still gated

This records what was found in the repository and what was built on top of it.
The owner has now chosen the commercial shape: demo access stays free and the paid unlock is a one-time Founder Lifetime purchase at **499 USD**. Checkout still stays off until the authenticated checkout path, legal copy, refund policy and tax handling are reviewed.

---

## 1. What was there before

| | |
|---|---|
| Payment provider | Stripe (`stripe@^22`, already a dependency) |
| Checkout route | `web/src/app/api/create-payment-intent/route.ts` |
| Price | **`29700`** minor units, hardcoded as a fallback |
| Currency | `"usd"`, hardcoded as a fallback |
| SKU | **`"apex-bot"`**, hardcoded as a fallback |
| Amount source | the **request body** — `amount ?? 29700` |
| Webhook for the platform | **none** |
| How a licence was granted | **it was not** |

`apex/platform/licence.py::grant()` existed and had **no production caller**.
A buyer paid and the platform learned nothing about it.

There is also `apex/stripe_license.py`, a Telegram-era handler keyed by
`chat_id`. It verifies signatures and claims event ids, and those two
mechanisms were worth reusing. It is **not** wired to the platform licence
store, and deliberately so: that store is keyed by the Supabase user id, and
merging the two would be a migration, not an accident of a shared key.

## 2. What was built

`apex/platform/billing.py`, reachable at `POST /api/v1/billing/webhook`.

- **Signature first.** The raw bytes are verified with stdlib HMAC before the
  body is parsed, with a 300-second tolerance so a captured delivery cannot be
  replayed later. `hmac.compare_digest`, not `==`.
- **Idempotent.** An event id is claimed with `user_store.claim` — a
  cross-process `SET NX`, which is the only thing that is correct when more
  than one instance is running — falling back to a stored marker when there is
  no shared backend. A duplicate delivery answers 200 and grants nothing.
- **A failed delivery releases its claim.** Otherwise the claim says "handled"
  while no licence was written, every retry is refused as a duplicate, and a
  buyer who has paid is never provisioned.
- **Identity comes from our own metadata.** The user id is read from
  `metadata.a4tUserId` or `client_reference_id`, both written server-side at
  checkout. **Never** from `receipt_email` or `customer_email`: matching on an
  address would let anyone who knows a client's email buy them a licence.
- **Only completed payments grant.** `payment_status: "unpaid"` grants nothing.
- **Refund, dispute, subscription deletion and failed renewal revoke.**
- **Unconfigured answers 503, not 200.** A webhook that silently accepts
  everything while switched off is worse than one that is off, because the
  provider stops retrying and the operator never finds out.

The Next.js checkout route now carries the approved one-time offer values, ignores any `amount` the browser sends, and is gated behind both `A4T_CHECKOUT_ENABLED=true` and `A4T_AUTHENTICATED_CHECKOUT_ENABLED=true`. Both are off. The second gate exists because this route still cannot stamp a verified platform user id onto Stripe metadata.

## 3. Why checkout is still switched off

The webhook trusts `metadata.a4tUserId` because **this server** writes it. The
Next.js route has no verified Supabase session to write there — it is a
framework route, not the authenticated platform API.

Stamping an unverified id would hand the webhook a value the browser chose,
and the webhook would then grant on it. So the route refuses instead. Enabling
paid checkout means moving checkout creation behind the platform API, where
`_authenticate` has already proved who the caller is.

That is a small piece of work and it is deliberately not done yet. The owner has decided the plan shape: one-time purchase, not subscription. The remaining implementation task is to create checkout from the authenticated platform API so the webhook receives a server-written `a4tUserId`.

## 4. Environment variables

Backend (`apex-forex-bot`):

| Variable | Meaning | Default |
|---|---|---|
| `A4T_STRIPE_WEBHOOK_SECRET` | verifies webhook deliveries | **none** — unset means 503 |
| `A4T_PLAN` | the plan name recorded on a licence | `founder_lifetime` |
| `A4T_PURCHASE_MODE` | records the commercial shape | `one_time` |
| `A4T_LICENCE_DAYS` | how long a grant lasts | **none** — no expiry for the one-time founder unlock |

Web (`web`):

| Variable | Meaning | Default |
|---|---|---|
| `STRIPE_SECRET_KEY` | server-side only, never `NEXT_PUBLIC_` | **none** |
| `A4T_PRICE_MINOR` | price in minor units | `49700` |
| `A4T_CURRENCY` | ISO currency | `usd` |
| `A4T_SKU` | product identifier | `founder_lifetime` |
| `A4T_CHECKOUT_ENABLED` | first gate; must be `true` for the route to answer | off |
| `A4T_AUTHENTICATED_CHECKOUT_ENABLED` | second gate; must be `true` after checkout creation is moved behind verified platform auth | off |

## 5. Owner decisions

| # | Decision | Current answer |
|---|---|---|
| **D1** | **Price and currency** | **497 USD**, represented as `49700` minor units and `usd`. Recorded here as 499 until this correction; the owner set it at 497, which is what `billing.APPROVED_PRICE_MINOR`, the live Payment Link and the sales page all carry. `billing.offer_drift()` fails readiness on any environment that says otherwise, so a deployment copying the old figure is refused rather than charging it. |
| **D2** | **SKU** | `founder_lifetime`. `"apex-bot"` names the previous product and is not reused. |
| **D3** | **Plan shape** | **One-time purchase**, not a subscription. `A4T_LICENCE_DAYS` stays unset for no expiry. |
| **D4** | **Refund policy** | Still open. The webhook already revokes on refund; what a client is entitled to must be decided before paid launch. |
| **D5** | **Tax handling** | Still open. Decide whether Stripe Tax is enabled and whether the shown price is tax-inclusive. |
| **D6** | **Whether paid access is part of beta at all** | Demo remains free. Paid Founder Lifetime unlock is planned, but checkout remains off until authenticated checkout, legal, refund and tax are ready. |

## 6. Dependencies outside the code

- **Webhook endpoint registration.** Stripe must be pointed at
  `https://<domain>/api/v1/billing/webhook`, and the signing secret from that
  endpoint put in `A4T_STRIPE_WEBHOOK_SECRET`. A secret from a different
  endpoint will verify nothing.
- **Which events are enabled.** The handler acts on
  `checkout.session.completed`, `payment_intent.succeeded`,
  `invoice.payment_succeeded`, `charge.refunded`, `charge.dispute.created`,
  `customer.subscription.deleted` and `invoice.payment_failed`. Anything else
  is acknowledged and ignored.
- **A shared Redis or Upstash backend.** Without one, `user_store.claim`
  cannot answer and idempotency falls back to a read-then-write, which is not
  atomic across instances. Two instances receiving the same retry could both
  grant. The grant is idempotent in effect — the same user, the same plan —
  so the damage is bounded, but the guarantee is weaker and this is the
  honest statement of it.

## 7. Tests

`apex-forex-bot/tests/test_platform_billing.py`, twelve groups. Each one is an
attempt to obtain a licence some way other than a signed, paid, non-duplicate
event: unsigned, wrongly signed, valid-mac-wrong-body, replayed beyond the
tolerance window, duplicated, unpaid, naming no platform user, naming a user
by email instead of by our metadata, and through five authenticated routes a
browser could call.

Two mutations were run against them: making the signature comparison return
`True` fails three checks, and removing the duplicate guard fails two.

## 8. Stripe Checkout and the existing Payment Link

The owner already has a Stripe account and an approved 497 USD product. The
platform can send a signed-in buyer there. It does not do so unless
`A4T_CHECKOUT_ENABLED` is on (and `A4T_AUTHENTICATED_CHECKOUT_ENABLED`, the
second gate the route already required). Both default off. Published legal
terms are required before live trading, not before this purchase.

Names only. No value below is set by the repository.

| Variable | Meaning |
|---|---|
| `A4T_CHECKOUT_ENABLED` | Purchase gate. Off unless explicitly set. The buy button stays "Not on sale yet" while this is off. |
| `A4T_AUTHENTICATED_CHECKOUT_ENABLED` | Second gate. The checkout route still requires a verified session either way. |
| `A4T_STRIPE_PAYMENT_LINK` | Stripe Payment Link URL, `https://buy.stripe.com/<id>`. The public example is `https://buy.stripe.com/bJe9AT0EF2gD99Bcii2Ji02`. It is not a default. |
| `STRIPE_SECRET_KEY` | Secret key for creating a Checkout Session. Server-side only. |
| `A4T_STRIPE_PRICE_ID` | Stripe Price id of the 497 USD product. The browser never sends an amount. |
| `A4T_PUBLIC_WEB_ORIGIN` | `https://<host>` of the web app. Success and cancel URLs are `{origin}/license`. |
| `A4T_STRIPE_WEBHOOK_SECRET` | Verifies webhook deliveries. Unset means the webhook answers 503. |
| `STRIPE_WEBHOOK_SECRET` | Accepted alias for the same signing secret. |

When the buy button is enabled, `POST /api/v1/billing/checkout` returns the
Payment Link with `client_reference_id` set to the signed-in user id and
`prefilled_email` set to that account's email. A user id in the request body
is ignored. If no Payment Link is configured, the same route creates a
Checkout Session instead (`mode=payment`, the configured price,
`client_reference_id` and `metadata.a4tUserId` set to the user id, success
and cancel on `/license`).

`checkout.session.completed` with `payment_status=paid`, amount `49700` and
currency `usd` records the `founder_lifetime` licence for `client_reference_id`
(or `metadata.a4tUserId`). The same event id does not grant twice. A Payment
Link purchase is that event, provided the link was opened with
`client_reference_id`. A different amount does not grant. The legacy browser
route `web/src/app/api/create-payment-intent` still creates nothing.
