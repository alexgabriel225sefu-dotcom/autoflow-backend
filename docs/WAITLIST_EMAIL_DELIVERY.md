# Waitlist email delivery

The landing page asks for one honest conversion before checkout exists: an email
address for early access. The address is stored encrypted first; email delivery
is best-effort and never turns a successful sign-up into a browser error.

## Provider choice

Provider: Resend or Brevo transactional email over HTTPS. Brevo is used when
`BREVO_API_KEY` is set (also when `RESEND_API_KEY` is set), otherwise Resend.
Both are a single JSON `POST`, with no SDK.

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
| `BREVO_API_KEY` | one of the two keys | Brevo API key (`api-key` header, `POST https://api.brevo.com/v3/smtp/email`). Takes precedence over Resend. Never log it and never expose it to the browser. |
| `RESEND_API_KEY` | one of the two keys | Resend API key. Used only when `BREVO_API_KEY` is not set. |
| `A4T_WAITLIST_FROM_EMAIL` | only for waitlist email delivery | Verified sender at the provider, for example `Apex4Traders <waitlist@example.com>`. With Brevo the sender's domain must be authenticated in Brevo (apex4traders.com is). |
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

## Announcing that early access is open

Operator tool: `apex-forex-bot/scripts/waitlist_announce.py`. It sends the one
email the form promised, to the people who have not had it. Run it on the
service (it needs `TOKEN_ENCRYPTION_KEY`, `RESEND_API_KEY` and
`A4T_WAITLIST_FROM_EMAIL`). It ships **no copy**: the owner writes the message
in a text file, and the owner approves it first.

1. **Dry run (the default).** Prints how many would go, masked samples and the
   exact phrase a real send needs. Changes nothing.
2. **Test send.** `--test-to you@example.com --send` sends one real copy to one
   address, marked `[TEST]`, and touches nothing on the list.
3. **Send in daily batches.** (add `--text-only` for no logo) `--limit 100 --send --confirm "SEND <campaign> TO <n>"`.
   The phrase names the campaign and the exact number about to go; if the list
   changed since the dry run it no longer matches. 100 a day stays inside the
   provider's free daily limit.

What it refuses, by design:

- **A second email.** Re-running a campaign only reaches people who have not
  had it. An uncertain outcome (timeout, 5xx, a crash mid-send) is **held**, not
  retried: check the provider's log, then pass `--retry-unknown`. A refused one
  (4xx, nothing went out) comes back with `--retry-failed`.
- **A removed address.** Each address is re-read just before its turn.
- **Copy that promises an outcome** (guarantees, returns, percentages). Override
  with `--allow-copy-flags` only after reading it.
- **No way off the list.** `--remove-contact` (or `A4T_WAITLIST_REMOVE_CONTACT`)
  is required and is added to every message, with a `List-Unsubscribe` header
  when it is an address.
- **Two runs at once.** A lease per campaign; on a deployment with no shared
  backend it asks you to confirm nothing else is running (`--no-lock`).
- **A provider that is down.** Three failures in a row stop the run.

- **A broken logo.** The message is a text part plus an HTML part with the logo
  (`web/public/email/logo.png`, served at
  `https://www.apex4traders.com/email/logo.png`). The tool checks that URL
  answers with an image before a real send; deploy the site first, or use
  `--text-only`.

The HTML is byte-identical for every recipient, has one image (the logo, no
query string, no token) and links only to URLs the owner wrote, unchanged. The
Privacy page says the email shows the logo and that loading it appears in
ordinary request logs; those logs are not used to find out who opened it. If
that changes (anything per recipient in the image or links), the Privacy page
and the form's promise change first.

Output is counts and masked addresses only. `--status` shows progress.

Keep **open and click tracking OFF** for the sending domain in the provider's
settings: the form promises no tracking, and that setting lives there, not here.
