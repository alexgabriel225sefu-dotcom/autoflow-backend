# Payment and licence — what exists, and what the owner still has to decide

This records what was found in the repository and what was built on top of it.
Every business value below is read from the environment with **no default**,
because a price or a refund policy chosen by whoever wrote the code is a
business decision taken by the wrong person.

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

The Next.js checkout route now reads price, currency and SKU from the
environment, refuses with 503 when any is unset, ignores any `amount` the
browser sends, and is gated behind `A4T_CHECKOUT_ENABLED=true`, which is off.

## 3. Why checkout is still switched off

The webhook trusts `metadata.a4tUserId` because **this server** writes it. The
Next.js route has no verified Supabase session to write there — it is a
framework route, not the authenticated platform API.

Stamping an unverified id would hand the webhook a value the browser chose,
and the webhook would then grant on it. So the route refuses instead. Enabling
paid checkout means moving checkout creation behind the platform API, where
`_authenticate` has already proved who the caller is.

That is a small piece of work and it is deliberately not done yet: it should
be done once the owner has decided the plan shape (D3), because a
subscription and a one-off purchase create different Stripe objects.

## 4. Environment variables

Backend (`apex-forex-bot`):

| Variable | Meaning | Default |
|---|---|---|
| `A4T_STRIPE_WEBHOOK_SECRET` | verifies webhook deliveries | **none** — unset means 503 |
| `A4T_PLAN` | the plan name recorded on a licence | `standard` |
| `A4T_LICENCE_DAYS` | how long a grant lasts | **none** — unset means no expiry |

Web (`web`):

| Variable | Meaning | Default |
|---|---|---|
| `STRIPE_SECRET_KEY` | server-side only, never `NEXT_PUBLIC_` | **none** |
| `A4T_PRICE_MINOR` | price in minor units | **none** |
| `A4T_CURRENCY` | ISO currency | **none** |
| `A4T_SKU` | product identifier | **none** |
| `A4T_CHECKOUT_ENABLED` | must be `true` for the route to answer | off |

## 5. What the owner must decide

None of these can be chosen here.

| # | Decision | Consequence of leaving it |
|---|---|---|
| **D1** | **Price and currency** | Checkout returns 503. Licences can still be granted manually for a private beta. |
| **D2** | **SKU** | Same. `"apex-bot"` names the previous product and is not reused. |
| **D3** | **Plan shape** — one-off, monthly, or trial-then-paid | Decides whether `A4T_LICENCE_DAYS` is set, whether renewal events must extend a licence, and which Stripe object checkout creates. Until it is decided, moving checkout behind the authenticated API is premature. |
| **D4** | **Refund policy** | The current Terms say "all sales are final once the source code has been delivered" — a sentence about a product that no longer exists. The webhook already revokes on refund; what a client is *entitled* to is not a code question. |
| **D5** | **Tax handling** | Whether Stripe Tax is enabled, and whether the price is tax-inclusive. Affects the amount, so it blocks D1. |
| **D6** | **Whether paid access is part of beta at all** | A private demo beta can run with checkout off and licences granted manually. That removes D1, D2, D3 and D5 from the beta gate entirely, and is the lower-risk path. |

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
