import { publicProcedure, protectedProcedure, router } from '../_core/trpc';
import { z } from 'zod';
import { createCheckoutSession } from '../_core/stripe';
import { db } from '../db';

export const paymentsRouter = router({
  createCheckout: publicProcedure
    .input(
      z.object({
        tier: z.enum(['starter', 'professional', 'enterprise']),
        origin: z.string(),
      })
    )
    .mutation(async ({ input, ctx }) => {
      if (!ctx.user) {
        throw new Error('User not authenticated');
      }

      const session = await createCheckoutSession(
        ctx.user.id,
        ctx.user.email || 'user@example.com',
        input.tier,
        input.origin
      );

      return { url: session.url };
    }),

  getSubscription: protectedProcedure.query(async ({ ctx }) => {
    const subscription = await db.query.subscriptions.findFirst({
      where: (subs, { eq }) => eq(subs.userId, ctx.user.id),
    });

    return subscription || null;
  }),

  updateSubscriptionTier: protectedProcedure
    .input(z.object({ tier: z.enum(['starter', 'professional', 'enterprise']) }))
    .mutation(async ({ input, ctx }) => {
      await db
        .update(db.schema.subscriptions)
        .set({ tier: input.tier, updatedAt: new Date() })
        .where(db.eq(db.schema.subscriptions.userId, ctx.user.id));

      return { success: true };
    }),
});
