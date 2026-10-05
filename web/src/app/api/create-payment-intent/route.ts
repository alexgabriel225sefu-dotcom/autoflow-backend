import { NextResponse } from "next/server";

/**
 * Legacy checkout creation endpoint.
 *
 * Payments are intentionally unavailable in this release. Checkout creation
 * must happen behind the authenticated platform API before it can be reviewed
 * for production, because the payment webhook grants access only from provider
 * events that carry a platform user id written by a verified session. This
 * Next.js route has no verified platform session, so it must never create a
 * PaymentIntent.
 */
export const CHECKOUT_DISABLED =
  "Checkout is not enabled in this release. Demo accounts are free and " +
  "require no payment. Paid access must be created by the authenticated " +
  "platform API after review; this browser route cannot create payments.";

export async function POST() {
  return NextResponse.json(
    {
      error: CHECKOUT_DISABLED,
      checkoutEnabled: false,
    },
    { status: 503 },
  );
}
