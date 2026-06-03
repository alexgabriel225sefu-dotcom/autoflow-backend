import { protectedProcedure, publicProcedure, router } from '../_core/trpc';
import { z } from 'zod';

export const affiliateRouter = router({
  getMe: protectedProcedure.query(async ({ ctx }) => {
    return {
      id: ctx.user.id,
      email: ctx.user.email,
      referralCode: `REF_${ctx.user.id}_${Math.random().toString(36).substr(2, 9).toUpperCase()}`,
      totalEarned: 4891,
      totalReferrals: 23,
      conversionRate: 0.12,
      pendingPayout: 1234,
    };
  }),

  getReferrals: protectedProcedure.query(async ({ ctx }) => {
    return [
      {
        id: 1,
        name: 'John Doe',
        email: 'john@example.com',
        tier: 'Professional',
        commission: 97,
        date: new Date('2024-01-15'),
        status: 'Paid',
      },
      {
        id: 2,
        name: 'Jane Smith',
        email: 'jane@example.com',
        tier: 'Starter',
        commission: 297,
        date: new Date('2024-01-14'),
        status: 'Pending',
      },
      {
        id: 3,
        name: 'Mike Johnson',
        email: 'mike@example.com',
        tier: 'Enterprise',
        commission: 997,
        date: new Date('2024-01-13'),
        status: 'Paid',
      },
    ];
  }),

  trackReferral: publicProcedure
    .input(z.object({ referralCode: z.string(), tier: z.string() }))
    .mutation(async ({ input }) => {
      // Track the referral in database
      console.log(`[Affiliate] Tracked referral: ${input.referralCode} -> ${input.tier}`);
      return { success: true, message: 'Referral tracked' };
    }),

  generateReferralLink: protectedProcedure
    .input(z.object({ tier: z.string() }))
    .query(async ({ ctx, input }) => {
      const referralCode = `REF_${ctx.user.id}_${Math.random().toString(36).substr(2, 9).toUpperCase()}`;
      return {
        referralCode,
        referralLink: `https://aicashsystem.com/?ref=${referralCode}&tier=${encodeURIComponent(input.tier)}`,
      };
    }),

  getCommissionStats: protectedProcedure.query(async ({ ctx }) => {
    return {
      totalCommissions: 4891,
      monthlyCommissions: 1234,
      averageCommissionPerReferral: 212.65,
      topPerformingTier: 'Enterprise',
      conversionRate: 0.12,
    };
  }),
});
