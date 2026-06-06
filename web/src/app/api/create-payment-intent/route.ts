import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import crypto from "crypto";

function getStripe() {
  if (!process.env.STRIPE_SECRET_KEY) throw new Error("STRIPE_SECRET_KEY not set");
  return new Stripe(process.env.STRIPE_SECRET_KEY, { apiVersion: "2026-05-27.dahlia" });
}

export async function POST(req: NextRequest) {
  try {
    const { amount, currency, email, name, product } = await req.json();

    if (!email || !name) {
      return NextResponse.json({ error: "Missing required fields." }, { status: 400 });
    }

    const pendingKey = crypto.randomBytes(16).toString("hex");
    const stripe = getStripe();

    const intent = await stripe.paymentIntents.create({
      amount: amount ?? 29700,
      currency: currency ?? "usd",
      receipt_email: email,
      metadata: { name, email, product: product ?? "apex-bot", pendingKey },
      automatic_payment_methods: { enabled: true },
    });

    return NextResponse.json({ clientSecret: intent.client_secret, pendingKey });
  } catch (err: any) {
    console.error("PaymentIntent error:", err.message);
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
