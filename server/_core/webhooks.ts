import { Request, Response } from 'express';
import { constructWebhookEvent, handleCheckoutSessionCompleted } from './stripe';
import { db } from '../db';
import { subscriptions } from '../../drizzle/schema';

export async function handleStripeWebhook(req: Request, res: Response) {
  const sig = req.headers['stripe-signature'] as string;

  try {
    const event = constructWebhookEvent(
      req.body,
      sig
    );

    // Test event detection
    if (event.id.startsWith('evt_test_')) {
      console.log('[Webhook] Test event detected, returning verification response');
      return res.json({ verified: true });
    }

    switch (event.type) {
      case 'checkout.session.completed': {
        const session = event.data.object as any;
        const { userId, tier, stripeCustomerId, stripeSubscriptionId } =
          await handleCheckoutSessionCompleted(session.id);

        // Save subscription to database
        await db.insert(subscriptions).values({
          userId,
          tier: tier as 'starter' | 'professional' | 'enterprise',
          stripeCustomerId,
          stripeSubscriptionId,
          stripePaymentIntentId: session.payment_intent,
          status: 'active',
          createdAt: new Date(),
          updatedAt: new Date(),
        });

        console.log(`[Webhook] Subscription created for user ${userId}`);
        break;
      }

      case 'customer.subscription.updated': {
        const subscription = event.data.object as any;
        // Update subscription status
        console.log(`[Webhook] Subscription updated: ${subscription.id}`);
        break;
      }

      case 'customer.subscription.deleted': {
        const subscription = event.data.object as any;
        // Mark subscription as cancelled
        console.log(`[Webhook] Subscription cancelled: ${subscription.id}`);
        break;
      }

      case 'invoice.paid': {
        const invoice = event.data.object as any;
        console.log(`[Webhook] Invoice paid: ${invoice.id}`);
        break;
      }

      default:
        console.log(`[Webhook] Unhandled event type: ${event.type}`);
    }

    res.json({ received: true });
  } catch (error) {
    console.error('[Webhook] Error:', error);
    res.status(400).send(`Webhook Error: ${(error as Error).message}`);
  }
}
