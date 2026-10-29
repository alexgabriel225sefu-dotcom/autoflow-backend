# Stripe test-mode sandbox runbook

Goal: prove, with **Stripe test mode only**, that a payment becomes exactly one
licence, and that unpaid, duplicate, wrong-user, refunded and disputed events
do the right thing. No real money, no production keys, no checkout gate
flipped on a public deployment.

Source of truth for the figures below: `billing.APPROVED_PRICE_MINOR = 49700`
(497.00 USD), currency `usd`, SKU/plan `founder_lifetime`, one-time. Do not
type another price anywhere; `billing.offer_drift()` fails readiness on it.

Companion code: `apex/platform/billing.py` (webhook),
`apex/platform/stripe_checkout.py` (session / Payment Link creation),
`apex-forex-bot/scripts/stripe_webhook_replay.py` (signed local replay),
`apex-forex-bot/tests/test_stripe_webhook_replay.py` (proves the replay signs
what the verifier accepts).

---

## Part A. Local replay (no Stripe account needed, agent or owner)

Proves the server's reaction to each event shape. Uses a throwaway secret.

```bash
cd apex-forex-bot
export STRIPE_WEBHOOK_TEST_SECRET=whsec_local_replay_only   # any whsec_ value
# terminal 1: a LOCAL server on a dev/test store (never production data)
APP_ENV=dev ALLOW_PLAINTEXT_DEV_STORAGE=true ALLOW_LOCAL_BACKEND_DEV=true \
  TOKEN_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())") \
  A4T_STRIPE_WEBHOOK_SECRET=$STRIPE_WEBHOOK_TEST_SECRET PORT=8080 \
  python -u platform_server.py
# terminal 2
python scripts/stripe_webhook_replay.py            # default http://127.0.0.1:8080/api/v1/billing/webhook
```

The script refuses non-loopback URLs, refuses a secret that is not `whsec_...`,
never prints the secret, and exits non-zero on any FAIL. Twelve scenarios and
the expected reply of each:

| # | Scenario | Expected |
|---|---|---|
| 1 | Tampered signature | 400 `BAD_SIGNATURE` |
| 2 | Valid signature, timestamp 1 h old (captured-body replay) | 400 `BAD_SIGNATURE` |
| 3 | `checkout.session.completed`, `paid`, 49700 usd, user A | 200 `handled`, `outcome: granted` |
| 4 | Same event id delivered again | 200 `duplicate: true` |
| 5 | `payment_status: unpaid` | 200 `handled: false` (payment not completed) |
| 6 | Paid but 100 minor units (discounted / other product) | 200 `handled: false` (does not match the approved offer) |
| 7 | Paid, but metadata carries only an e-mail, no platform user id | 200 `handled: false` (no platform user) |
| 8 | `charge.refunded`, full, matched through the PaymentIntent | 200 `outcome: revoked` |
| 9 | Second paid purchase, user D | 200 `granted` |
| 10 | `charge.refunded`, partial (10.00 of 497.00) | 200 `handled: false` (licence stays) |
| 11 | `charge.dispute.created` | 200 `outcome: revoked` |
| 12 | `customer.created` (not acted on) | 200 `handled: false` |

"Wrong-user metadata" is scenario 7: the server takes the user id only from
`metadata.a4tUserId` / `client_reference_id`, never from an e-mail. A case the
replay deliberately does **not** auto-judge: metadata naming user B while
`client_reference_id` names user A. `billing._user_id_of` currently prefers the
metadata value; since both are written by the server at checkout, a real
mismatch should be impossible. If you ever see one in the dashboard, stop and
investigate; do not "fix" it by hand.

What the replay cannot show is what is in the licence store. The automated test
(`tests/test_stripe_webhook_replay.py`) asserts that for an in-process server;
against a server you started yourself, check with
`python -c "from apex.platform import licence as L; print(L.status_for('<id>'))"`
in the same environment.

---

## Part B. Real Stripe test mode (owner only)

An agent must not do these: they need the owner's Stripe login and a browser.
Use a **test-mode** sandbox deployment (a separate Render service or a local
server behind the Stripe CLI), never the production service.

### B0. Preconditions
1. Stripe dashboard: toggle **Test mode** on (top right). Everything below is
   created in test mode and has no relation to the live product.
2. Developers -> API keys: copy the **test** secret key (`sk_test_...`).
3. Product catalogue -> Add product: "Apex4Traders Founder Lifetime",
   one-time price **497.00 USD**. Copy the Price id (`price_...`). It must equal
   `GET /api/v1/billing/offer` -> `priceMinor 49700` or scenario 6 style
   refusals will fire on your own payment.
4. Install the Stripe CLI and `stripe login` (test mode).

### B1. Sandbox environment (names only; set values in the host's secret store)
| Variable | Value |
|---|---|
| `STRIPE_SECRET_KEY` | the `sk_test_...` key |
| `A4T_STRIPE_PRICE_ID` | the test `price_...` |
| `A4T_PUBLIC_WEB_ORIGIN` | the sandbox web origin, `https://...` |
| `A4T_STRIPE_WEBHOOK_SECRET` | from B2 (`whsec_...`) |
| `A4T_CHECKOUT_ENABLED`, `A4T_AUTHENTICATED_CHECKOUT_ENABLED` | `true` **on the sandbox service only** |
| `APP_ENV` | leave non-production, or accept that `livemode:false` events are refused in production (`billing._livemode_ok`) |

Leave `A4T_PRICE_MINOR`, `A4T_CURRENCY`, `A4T_SKU`, `A4T_PLAN` unset.
Do not set any of this on the production service during the sandbox pass.

### B2. Webhook secret
Local server: `stripe listen --forward-to localhost:8080/api/v1/billing/webhook`
prints a `whsec_...`; use it as `A4T_STRIPE_WEBHOOK_SECRET` and restart.
Hosted sandbox: Developers -> Webhooks -> Add endpoint
`https://<sandbox-api>/api/v1/billing/webhook`, events:
`checkout.session.completed`, `charge.refunded`, `charge.dispute.created`;
reveal and copy the signing secret.

### B3. The checks (record result and date for each)
1. **Pay.** Sign in to the sandbox web app with a verified account, press
   buy. Expect redirect to Stripe Checkout (hosted). Pay with card
   `4242 4242 4242 4242`, any future expiry, any CVC. Expect: return to
   `/license`, webhook delivery 200 `granted`, `GET /api/v1/me` shows the
   licence `active`, plan `founder_lifetime`.
2. **Success page alone grants nothing.** Open the `/license` success URL for a
   session you did not pay: no licence.
3. **Duplicate delivery.** Dashboard -> Webhooks -> the delivery -> Resend
   (or `stripe events resend <evt_id>`). Expect 200 `duplicate: true`, still
   one licence.
4. **Unpaid.** Start checkout, abandon it. Expect no licence. For a failing
   card use `4000 0000 0000 0002` (declined): no `completed`/`paid` event.
5. **Wrong user.** With two test accounts A and B: pay as A. B must show no
   licence. (The id comes from server-written metadata, never the e-mail.)
6. **Wrong amount.** Create a second test price (e.g. 1.00 USD) via a Payment
   Link and pay it as A. Expect 200 `handled: false`, no licence, a
   `[Billing] REFUSED ... approved offer is 49700` log line.
7. **Partial refund.** Payments -> the payment -> Refund 10.00. Expect
   `charge.refunded` -> 200 `handled: false`, licence still active.
8. **Full refund.** Refund the remainder. Expect `outcome: revoked`, licence
   `revoked`, `GET /api/v1/me` reflects it.
9. **Dispute.** Pay again as A (test card `4000 0000 0000 0259` creates a
   dispute). Expect `charge.dispute.created` -> `outcome: revoked`.
10. **Bad signature.** Edit the signing secret in the host to a wrong value:
    deliveries fail 400 and Stripe shows them failing; restore it.
11. **Livemode guard.** Only if the sandbox runs with `APP_ENV=production`:
    a test-mode event must be acknowledged but not grant.

### B4. Known gap to decide before live mode
`billing.GRANTING` handles `checkout.session.completed`,
`payment_intent.succeeded` and `invoice.payment_succeeded`. It does **not**
handle `checkout.session.async_payment_succeeded`. Cards are unaffected;
a delayed bank-debit method would pay and never grant. Either keep Checkout to
card payments (default) or ask engineering to add the event.

### B5. Exit
Delete the sandbox webhook endpoint, rotate/discard the test keys if they were
pasted anywhere, and confirm the production service still has both checkout
gates unset. Going live is a separate owner decision (see
`docs/OWNER_ACTIONS.md`).
