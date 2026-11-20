# Waitlist email delivery

The landing page asks for one honest conversion before checkout exists: an email
address for early access. The address is stored encrypted first; email delivery
is best-effort and never turns a successful sign-up into a browser error.

## Provider choice

Provider: Resend transactional email over HTTPS.

Why this provider for launch:

- It needs no SDK in this repository. The backend sends one JSON `POST` to
  `https://api.resend.com/emails`.
- The free tier is enough for the first ad tests: 3,000 emails/month and
  100 emails/day at $0/month.
- At 100 waitlist addresses, the cost is $0.
- At 1,000 waitlist addresses, the cost is $0 if the launch send is spread
  across the free daily limit. A same-day blast above the daily free limit is
  not part of the low-budget launch plan.

Do not add tracking pixels, click tracking links, newsletter lists, or shared
marketing audiences. The form says no newsletter, no sharing, no tracking; that
is the product contract.

## Environment

| Variable | Required | Meaning |
|---|---|---|
| `RESEND_API_KEY` | only for waitlist email delivery | Server-side provider API key. Never log it and never expose it to the browser. |
| `A4T_WAITLIST_FROM_EMAIL` | only for waitlist email delivery | Verified Resend sender, for example `Apex4Traders <waitlist@example.com>`. |
| `A4T_WAITLIST_REPLY_TO` | optional | Reply-to mailbox, if the owner wants replies somewhere else. |

If none of these are configured, sign-ups still succeed and `/readyz` reports
`waitlist_email: skipped`. If only some are configured, `/readyz` reports
`waitlist_email: fail` and names the missing variables.

## Runtime contract

- First join only sends. A repeat sign-up returns `already` and does not send.
- The stored address remains encrypted.
- The browser response still carries no address and no delivery status.
- Provider errors are stored as a safe status such as `HTTP_400` or
  `TimeoutError`; the address is not copied into the error.
- `scripts/waitlist_export.py` is the operator view. It shows whether each
  address was `sent`, `failed`, `not_configured`, or `unknown`.

The placeholder email body is intentionally plain. Final launch email copy is
pending owner approval and must keep the same compliance rules as the landing
page: no profit promise, no financial advice, demo-first, live trading not
enabled.
