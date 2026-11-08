# Platform billing endpoint

This records the handler that already exists. It does not create a Stripe
endpoint, set an environment variable, or send a payment.

## What is live today

The only live webhook on the Apex Stripe account is still:

`https://autoflow-backend-2.onrender.com/api/stripe/webhook`

Events on that endpoint: `checkout.session.completed`, `charge.refunded`,
`charge.dispute.created`. That URL is the legacy host. It is not this
platform's handler. No sandbox Stripe account is connected here. A real
delivery to the platform URL has not been made, and this file does not
claim one.

## Where the handler actually is

The Python handler is `POST /api/v1/billing/webhook` on the API service.
The host that serves it directly is:

`https://apex4traders-api.onrender.com/api/v1/billing/webhook`

`https://www.apex4traders.com` is the Next.js site, not that service.
Before the site route in `web/src/app/api/v1/billing/webhook/route.ts`,
`POST /api/v1/billing/webhook` on the website was the catch-all JSON 404
(`web/src/app/api/[...path]/route.ts`). Middleware does not send `/api/*`
to the login page, so this was not a homepage redirect. It was still not
the billing handler. Stripe must not be pointed at a 404.

That site route now forwards one POST to
`{NEXT_PUBLIC_API_BASE_URL}/api/v1/billing/webhook`. It copies the raw
body and the `Stripe-Signature` header and does not follow a redirect.
It forwards no cookie and no Authorization header. If
`NEXT_PUBLIC_API_BASE_URL` is unset, or is the website's own origin, the
route answers JSON 503 and does not call itself. Other `/api/*` paths
on the website stay 404. This route does not turn checkout on.

The supported public URL, once that variable is the API origin, is:

`https://www.apex4traders.com/api/v1/billing/webhook`

The direct API URL above remains valid. Either can be the Stripe
destination. Both must reach the Python handler. A delivery has not
been made to either from this repository.

`POST` only. The handler is `apex.platform.billing.handle_event`, reached
from `apex.platform.api` when the route is `billing/webhook`. No session
cookie. The body is accepted only when the `Stripe-Signature` header
matches.

Events that can grant a platform licence:

- `checkout.session.completed` with `payment_status` `paid`
- `payment_intent.succeeded` with `status` `succeeded`
- `invoice.payment_succeeded`

Events that can withdraw one:

- `charge.refunded` when the charge is fully refunded (a partial refund
  does not withdraw)
- `charge.dispute.created`
- `customer.subscription.deleted`
- `invoice.payment_failed`

A repeated event id is a duplicate and does not grant or revoke again.
Two threads in one process, when the shared claim cannot be asked, do not
both grant: the second is told to retry.

## Same Stripe account, legacy checkouts

Adding this URL on the live account delivers the account's existing
events here too, including while platform checkout is off. A session whose
`metadata.product` or `metadata.sku` is set and is not `founder_lifetime`
is not the platform offer. It is acknowledged and not granted. The legacy
site sets `metadata.product` (for example `apex-forex`). This platform's
own Checkout Session does not set `metadata.product`; it sets
`metadata.a4tUserId`.

A legacy refund is not matched to a platform licence unless this handler
previously indexed that payment. It does not withdraw a licence it did not
grant.

## Environment names

Values are not written here. The process reads:

| Name | Role |
|---|---|
| `A4T_STRIPE_WEBHOOK_SECRET` | Preferred signing secret for this handler |
| `STRIPE_WEBHOOK_SECRET` | Accepted if the preferred name is unset |
| `NEXT_PUBLIC_API_BASE_URL` | API origin the website uses when it forwards the public webhook. Not a secret |

## Do not edit the existing live endpoint

The only live endpoint is `we_1TzH8rGpBbs5xtI5S0glUEVE`, currently aimed
at the legacy host. The supported change for an existing endpoint is a
URL update. That operation has no secret parameter. It does not show the
signing secret, and it does not say whether the platform process has the
same secret. Equality is unknown. This repository does not read
environment values and does not change Stripe.

Moving that endpoint's URL would stop the legacy host from receiving
`checkout.session.completed`, `charge.refunded`, and
`charge.dispute.created`. Those events are what the legacy Telegram
fulfillment consumes. The platform handler is a different verifier and a
different licence store. Pointing the existing endpoint at it would break
the legacy consumer and would not prove signatures verify.

A separate endpoint is required. Its signing secret has to be set on the
API as `A4T_STRIPE_WEBHOOK_SECRET` (or `STRIPE_WEBHOOK_SECRET` if that
name is the one already used). That configuration step is indispensable:
without a secret the handler answers 503 and verifies nothing, and there
is no API operation here that copies the legacy secret. Do not rotate the
secret on `we_1TzH8rGpBbs5xtI5S0glUEVE`.

GET on both the website and the API returns 404. That was observed on
8 November 2026 at 07:12 Europe/Amsterdam: the website body is JSON
`No such API endpoint.` and the API body says there is no such endpoint.
Neither response is HTML and neither is a redirect. GET 404 is what a
POST-only route does. It is not evidence that POST is missing. POST on
the API is the handler. POST on the website is the explicit forwarder
in this change, and only when `NEXT_PUBLIC_API_BASE_URL` is the API
origin. Until that forwarder is deployed, the website POST is still the
catch-all JSON 404. Do not send Stripe there before that deploy and
before the new endpoint's secret is set on the API.
| `A4T_CHECKOUT_ENABLED` | Must be on before a buyer can be sent to pay. Off leaves checkout at 503 |
| `A4T_AUTHENTICATED_CHECKOUT_ENABLED` | Second gate, also required |
| `STRIPE_SECRET_KEY` | Only to create a Checkout Session. Not required to verify a webhook |
| `A4T_STRIPE_PRICE_ID` | Price used when creating a session |
| `A4T_STRIPE_PAYMENT_LINK` | Alternative to creating a session |
| `A4T_PUBLIC_WEB_ORIGIN` | Where the buyer returns |

Checkout flags do not have to be on for the webhook to verify a delivery.
They must stay off until the owner has finished the sandbox check below.
This repository does not set them.

Test-mode events are refused when `APP_ENV` is `production` or `prod`.
Outside production, test-mode events are accepted so a sandbox can be
exercised. Do not point the live endpoint at a non-production process.

## Sandbox check, when the owner is ready

Use a Stripe test key and a test endpoint, not the live URL above.

1. Set `A4T_STRIPE_WEBHOOK_SECRET` on a non-production process to the
   signing secret of a test-mode endpoint whose URL is that process's
   `/api/v1/billing/webhook`.
2. Leave `A4T_CHECKOUT_ENABLED` off for the first check. Deliver a signed
   fixture whose `metadata.product` is `apex-forex`. Expect HTTP 200,
   `handled: false`, and no licence.
3. Turn both checkout flags on only for the sandbox process. Create a
   Checkout Session as a signed-in test user. Pay with Stripe's test card.
4. Expect one `checkout.session.completed` with `payment_status=paid`,
   amount 49700 usd (plus tax if the price is tax-exclusive), and
   `metadata.a4tUserId` equal to that user. Expect `outcome: granted`.
5. Deliver the same event id again. Expect `duplicate: true` and still
   one licence.
6. Refund the test charge in full. Expect `outcome: revoked`.
7. A partial refund must leave the licence in place.
8. Open a test dispute. Expect the licence withdrawn.
9. Confirm a test-mode event is refused if that process is started with
   `APP_ENV=production`.

No secret value belongs in the repository, an issue, or a log.

Backup and restore of the Stripe account itself are not visible from this
repository. Do not treat this handler as a backup.
