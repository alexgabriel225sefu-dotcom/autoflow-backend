import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";

/**
 * Creates a payment intent. It cannot grant anything.
 *
 * WHAT CHANGED AND WHY
 *
 * This route used to take `amount` and `product` from the request body and
 * fall back to `29700` and `"apex-bot"` — the previous product's price and
 * SKU. Two problems: the amount was whatever the browser said, and the
 * fallback put a number on an invoice that nobody had approved for this
 * product.
 *
 * The owner-approved offer is a one-time Founder Lifetime unlock at 499 USD.
 * The environment may still override it for a reviewed deployment, but the
 * previous product fallback is gone. Checkout remains disabled unless
 * A4T_CHECKOUT_ENABLED=true, so these values do not enable payments by
 * themselves — see docs/PAYMENT_AND_LICENCE_DECISIONS.md.
 *
 * WHAT STILL CANNOT HAPPEN HERE
 *
 * A licence. Paying is not being entitled: the only path that grants is the
 * signed webhook in apex/platform/billing.py, which verifies the provider's
 * signature over the exact bytes it received. This route hands Stripe a
 * client secret and stops.
 *
 * WHAT IS NOT WIRED YET
 *
 * The platform user id. The webhook reads it from metadata **this server**
 * wrote, and this route has no verified session to write — it is a Next.js
 * route, not the authenticated platform API. Until checkout creation moves
 * behind the platform API with a verified Supabase token, this route refuses
 * rather than stamping an unverified id that the webhook would then trust.
 */

/**
 * The one sentence this route says when nothing is for sale.
 *
 * It states three things a caller needs and cannot get from a 503 alone:
 * that demo access is free, that nothing is being sold here, and that paying
 * is not how an entitlement is granted even when it is. The webhook grants by
 * reading a platform user id out of metadata a verified session wrote, and
 * this route has no verified session — so there is no code path from a
 * browser to an entitlement, in either configuration.
 */
export const CHECKOUT_DISABLED =
  "Checkout is not enabled in this release. Demo accounts are free and " +
  "require no payment. The paid unlock is planned as a one-time Founder " +
  "Lifetime purchase. Paying through this route is not how an entitlement " +
  "is granted; licences are granted by a verified payment webhook only, " +
  "never by this route.";

const APPROVED_PRICE_MINOR = "49900";
const APPROVED_CURRENCY = "usd";
const APPROVED_SKU = "founder_lifetime";

export const AUTHENTICATED_CHECKOUT_REQUIRED =
  "Checkout must be created by the authenticated platform API before it " +
  "can be enabled. This browser route cannot stamp a verified platform " +
  "user id onto the payment metadata.";

const MISSING = (what: string) =>
  NextResponse.json(
    {
      error: `${what} is not configured. This is an owner decision and has no ` +
        `default — see docs/PAYMENT_AND_LICENCE_DECISIONS.md.`,
    },
    { status: 503 },
  );

export async function POST(req: NextRequest) {
  // FIRST, before anything about configuration.
  //
  // This used to run after the Stripe key and the price were checked, so a
  // caller asking "can I buy this?" was told "STRIPE_SECRET_KEY is not
  // configured" — an answer about our deployment, to a question about the
  // product. The honest answer is that nothing is for sale, and it does not
  // depend on what else happens to be set.
  if (process.env.A4T_CHECKOUT_ENABLED !== "true") {
    return NextResponse.json(
      {
        error: CHECKOUT_DISABLED,
        checkoutEnabled: false,
      },
      { status: 503 },
    );
  }

  if (process.env.A4T_AUTHENTICATED_CHECKOUT_ENABLED !== "true") {
    return NextResponse.json(
      {
        error: AUTHENTICATED_CHECKOUT_REQUIRED,
        checkoutEnabled: false,
      },
      { status: 503 },
    );
  }

  const key = process.env.STRIPE_SECRET_KEY;
  const priceMinor = process.env.A4T_PRICE_MINOR ?? APPROVED_PRICE_MINOR;
  const currency = process.env.A4T_CURRENCY ?? APPROVED_CURRENCY;
  const sku = process.env.A4T_SKU ?? APPROVED_SKU;

  if (!key) return MISSING("STRIPE_SECRET_KEY");

  const amount = Number.parseInt(priceMinor, 10);
  if (!Number.isFinite(amount) || amount <= 0) {
    return MISSING("A4T_PRICE_MINOR (must be a positive integer in minor units)");
  }

  let email: unknown;
  let name: unknown;
  try {
    ({ email, name } = await req.json());
  } catch {
    return NextResponse.json({ error: "The body is not valid JSON." }, { status: 400 });
  }
  if (typeof email !== "string" || typeof name !== "string" || !email || !name) {
    return NextResponse.json({ error: "Missing required fields." }, { status: 400 });
  }

  try {
    const stripe = new Stripe(key, { apiVersion: "2026-05-27.dahlia" });
    const intent = await stripe.paymentIntents.create({
      // From the environment. Never from the request: an amount a browser
      // sends is an amount a browser chose.
      amount,
      currency,
      receipt_email: email,
      metadata: { name, email, product: sku },
      automatic_payment_methods: { enabled: true },
    });
    return NextResponse.json({ clientSecret: intent.client_secret });
  } catch (err) {
    // The provider's message is not returned: it can carry account details.
    const message = err instanceof Error ? err.message : String(err);
    console.error("PaymentIntent error:", message);
    return NextResponse.json({ error: "The payment provider refused." }, { status: 502 });
  }
}
