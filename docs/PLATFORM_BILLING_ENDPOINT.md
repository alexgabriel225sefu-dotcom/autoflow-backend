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
`{NEXT_PUBLIC_API_BASE_URL}/api/v1/billing/webhook`. The path is that
fixed path. The request does not choose the host. It copies the raw
body and the `Stripe-Signature` header and does not follow a redirect.
It forwards no cookie and no Authorization header. A missing signature
is refused with JSON 400 before the body is forwarded. A body or an
upstream response over 1 MiB is refused. The inbound body must finish
within 10 seconds, and the upstream call has its own 10 second deadline.
The configured origin must be a public https host when `NODE_ENV` is
`production`. A literal loopback, private, or link-local host is refused
in every environment, as is a URL with a username or password. Those
checks do not resolve DNS. A public hostname that points at a private
address is not detected. This is not a general SSRF guard. The host is
the operator's configured origin, and the path is fixed.
If `NEXT_PUBLIC_API_BASE_URL` is unset, or is the website's own origin,
the route answers JSON 503 and does not call itself. Other `/api/*`
paths on the website stay 404. This route does not turn checkout on.

The supported public URL, once that variable is the API origin, is:

`https://www.apex4traders.com/api/v1/billing/webhook`

The direct API URL above remains valid. Either can be the Stripe
destination. Both must reach the Python handler. A delivery has not
been made to either from this repository.

`POST` only. The handler is `apex.platform.billing.handle_event`, reached
from `apex.platform.api` when the route is `billing/webhook`. No session
cookie. The body is accepted only when the `Stripe-Signature` header
matches.

The approved endpoint, which has not been created from this repository,
lists exactly these events:

- `checkout.session.completed`
- `checkout.session.async_payment_succeeded`
- `charge.refunded`
- `charge.dispute.created`

It does not list `payment_intent.*`, `invoice.*`,
`customer.subscription.*`, `checkout.session.async_payment_failed`, or a
wildcard. A card payment arrives as `checkout.session.completed` with
`payment_status` `paid` and grants. A delayed method arrives first as
`checkout.session.completed` with `payment_status` `unpaid`, which does
not grant, and later as `checkout.session.async_payment_succeeded`. That
second event grants only when `payment_status` is `paid`. The two event
ids share one payment id. The worker that may grant holds a lease whose
value is its own token. After it acquires the lease it reads the durable
record again, and it reads whether that payment was already refunded.
Another worker can finish between the first look and the acquire. The
lease lasts 60 seconds so a dead worker does not block a replacement
forever. That duration is not what prevents a second grant. Publishing
the durable record and deleting the lease happen in one compare against
the token, so an expired worker cannot delete the replacement's lease.
A crash after the licence write and before that record can make the
replacement write the same active licence again. It does not grant if
the refund tombstone is already stored, so a revoked licence is not
turned back on. This is bounded recovery, not a promise that the licence
function runs only once. A store that cannot be read answers 500. `async_payment_failed`
is not subscribed. Because the unpaid session never granted, there is no
licence for that failure to withdraw.

The handler still contains older branches for `payment_intent.succeeded`,
`invoice.payment_succeeded`, `customer.subscription.deleted`, and
`invoice.payment_failed`. Those branches are not the approved
subscription. Do not add them to the endpoint.

A full `charge.refunded`, and `charge.dispute.created`, withdraw the
licence that was indexed for that payment. A partial refund does not.
A repeated event id is a duplicate.

## Same Stripe account, legacy checkouts

Adding this URL on the live account delivers the account's existing
events here too, including while platform checkout is off. A session whose
`metadata.product` or `metadata.sku` is set and is not `founder_lifetime`
is not the platform offer. It is acknowledged and not granted. The legacy
site sets `metadata.product` (for example `apex-forex`). This platform's
own Checkout Session does not set `metadata.product`; it sets
`metadata.a4tUserId`.

A `charge.refunded` or `charge.dispute.created` withdraws a licence only
when this handler indexed that payment at grant time, and only for the
account stored against that payment. `metadata.a4tUserId` on the charge
or the dispute does not choose the account. A named product or sku other
than `founder_lifetime` does not grant and does not revoke, even when
the object also carries `a4tUserId` and even when the payment id matches
one this handler granted. A repeated event id is a duplicate.

## Environment names

Values are not written here. The process reads:

| Name | Role |
|---|---|
| `A4T_STRIPE_WEBHOOK_SECRET` | The only secret to set on the platform API. It is the signing secret of the new endpoint |
| `STRIPE_WEBHOOK_SECRET` | Legacy process name. Leave it unset on the platform API. The handler reads it only when the platform name is unset. Do not copy it from the Telegram service |
| `NEXT_PUBLIC_API_BASE_URL` | API origin the website uses when it forwards the public webhook. Not a secret. The path is fixed |
| `A4T_CHECKOUT_ENABLED` | Must be on before a buyer can be sent to pay. Off leaves checkout at 503 |
| `A4T_AUTHENTICATED_CHECKOUT_ENABLED` | Second gate, also required |
| `STRIPE_SECRET_KEY` | Only to create a Checkout Session. Not required to verify a webhook |
| `A4T_STRIPE_PRICE_ID` | Price used when creating a session |
| `A4T_STRIPE_PAYMENT_LINK` | Alternative to creating a session |
| `A4T_PUBLIC_WEB_ORIGIN` | Where the buyer returns |

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

Create a separate endpoint. Do not edit `we_1TzH8rGpBbs5xtI5S0glUEVE`.
On the platform API, set one key, `A4T_STRIPE_WEBHOOK_SECRET`, to the
signing secret of that new endpoint. Do not set `STRIPE_WEBHOOK_SECRET`
on the platform API, and do not rotate or replace the secret the
Telegram service already uses. The handler answers 503 until
`A4T_STRIPE_WEBHOOK_SECRET` is set. If that name is unset, the handler
will read `STRIPE_WEBHOOK_SECRET`; leaving the legacy name unset on this
API is what keeps the two verifiers apart. No value is recorded here.

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
