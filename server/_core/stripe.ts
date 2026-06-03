import Stripe from 'stripe';
import { ENV } from './env';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY || '', {
  apiVersion: '2026-05-27.dahlia',
});

export async function createCheckoutSession(
  userId: number,
  email: string,
  tier: 'starter' | 'professional' | 'enterprise',
  origin: string
) {
  const prices = {
    starter: 'price_starter_297', // One-time
    professional: 'price_professional_97', // Monthly
    enterprise: 'price_enterprise_997', // Monthly
  };

  const session = await stripe.checkout.sessions.create({
    payment_method_types: ['card'],
    line_items: [
      {
        price: prices[tier],
        quantity: 1,
      },
    ],
    mode: tier === 'starter' ? 'payment' : 'subscription',
    customer_email: email,
    client_reference_id: userId.toString(),
    metadata: {
      userId: userId.toString(),
      tier,
    },
    success_url: `${origin}/checkout/success?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${origin}/checkout/cancel`,
  });

  return session;
}

export async function handleCheckoutSessionCompleted(sessionId: string) {
  const session = await stripe.checkout.sessions.retrieve(sessionId);

  if (!session.client_reference_id) {
    throw new Error('No user ID in session');
  }

  const userId = parseInt(session.client_reference_id);
  const tier = (session.metadata?.tier || 'starter') as any;
  const stripeCustomerId = session.customer as string;
  const stripeSubscriptionId = session.subscription as string;
  const stripePaymentIntentId = session.payment_intent as string;

  return {
    userId,
    tier,
    stripeCustomerId,
    stripeSubscriptionId,
    stripePaymentIntentId,
  };
}

export async function getCustomerSubscriptions(customerId: string) {
  const subscriptions = await stripe.subscriptions.list({
    customer: customerId,
    limit: 10,
  });

  return subscriptions.data;
}

export async function cancelSubscription(subscriptionId: string) {
  const subscription = await stripe.subscriptions.cancel(subscriptionId);
  return subscription;
}

export async function constructWebhookEvent(body: string, signature: string) {
  return stripe.webhooks.constructEvent(
    body,
    signature,
    process.env.STRIPE_WEBHOOK_SECRET || ''
  );
}
