# ADR: Checkout creation stays behind the authenticated platform API

Status: accepted
Date: 2026-10-03

## Context

Apex4Traders is not taking payments in the current release. Demo accounts are free. A paid live unlock may be introduced later as a reviewed, one-time founder purchase, but live execution and checkout remain disabled until the owner explicitly enables them after review.

The legacy browser route at `web/src/app/api/create-payment-intent/route.ts` could create a Stripe PaymentIntent when deployment flags were set. That route does not verify a platform session. The payment webhook grants access only from provider-signed events that carry a platform user id written by our server, so checkout creation must be coupled to a verified platform identity before any payment can be trusted.

The platform API already exposes `POST /api/v1/billing/checkout`. It requires a fresh authenticated session and currently returns `CHECKOUT_NOT_ENABLED` while checkout is disabled, then `CHECKOUT_NOT_IMPLEMENTED` even if both checkout gates are turned on.

## Decision

The browser checkout route is a fail-closed compatibility endpoint. It imports no Stripe SDK, reads no Stripe secret, creates no PaymentIntent, and always returns a disabled response.

When checkout is ready to be reviewed, creation must be implemented only in `POST /api/v1/billing/checkout` after a fresh verified session has identified the platform user. The browser may call that authenticated API, but it must not create payment provider objects directly.

## Consequences

- No unauthenticated browser request can create a PaymentIntent.
- Feature flags cannot accidentally turn the old browser route into a charge path.
- The only future checkout creation point is the authenticated platform API, where the server can write trusted metadata for the signed webhook.
- This does not enable checkout, payments, live trading, subscriptions, or entitlements.
