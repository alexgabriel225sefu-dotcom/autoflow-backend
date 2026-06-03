import { COOKIE_NAME } from "@shared/const";
import { getSessionCookieOptions } from "./_core/cookies";
import { systemRouter } from "./_core/systemRouter";
import { publicProcedure, router, protectedProcedure } from "./_core/trpc";
import { z } from "zod";
import * as db from "./db";
import { TRPCError } from "@trpc/server";

export const appRouter = router({
  system: systemRouter,
  auth: router({
    me: publicProcedure.query(opts => opts.ctx.user),
    logout: publicProcedure.mutation(({ ctx }) => {
      const cookieOptions = getSessionCookieOptions(ctx.req);
      ctx.res.clearCookie(COOKIE_NAME, { ...cookieOptions, maxAge: -1 });
      return {
        success: true,
      } as const;
    }),
  }),

  // ─── Trading Bot Routers ──────────────────────────────────
  trades: router({
    history: protectedProcedure
      .input(z.object({ limit: z.number().int().positive().default(50) }).optional())
      .query(async ({ ctx, input }) => {
        try {
          return await db.getTradeHistory(ctx.user.id, input?.limit || 50);
        } catch (err) {
          console.error('[tRPC] trades.history error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch trade history' });
        }
      }),
    create: protectedProcedure
      .input(z.object({
        symbol: z.string(),
        side: z.enum(['BUY', 'SELL']),
        entryPrice: z.string(),
        quantity: z.string(),
        confidence: z.number().optional(),
        criteriaScore: z.number().optional(),
      }))
      .mutation(async ({ ctx, input }) => {
        try {
          const tradeData: any = {
            symbol: input.symbol,
            side: input.side,
            entryPrice: input.entryPrice,
            quantity: input.quantity,
            openedAt: new Date(),
          };
          if (input.confidence !== undefined) tradeData.confidence = input.confidence;
          if (input.criteriaScore !== undefined) tradeData.criteriaScore = input.criteriaScore;
          return await db.createTrade(ctx.user.id, tradeData);
        } catch (err) {
          console.error('[tRPC] trades.create error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to create trade' });
        }
      }),
    close: protectedProcedure
      .input(z.object({
        tradeId: z.number(),
        exitPrice: z.string(),
        pnl: z.string(),
        pnlPercent: z.string(),
        closeReason: z.string(),
      }))
      .mutation(async ({ ctx, input }) => {
        try {
          await db.updateTrade(input.tradeId, {
            exitPrice: input.exitPrice,
            pnl: input.pnl,
            pnlPercent: input.pnlPercent,
            closeReason: input.closeReason,
            closedAt: new Date(),
          });
          return { success: true };
        } catch (err) {
          console.error('[tRPC] trades.close error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to close trade' });
        }
      }),
  }),

  alerts: router({
    history: protectedProcedure
      .input(z.object({ limit: z.number().int().positive().default(20) }).optional())
      .query(async ({ ctx, input }) => {
        try {
          return await db.getAlertHistory(ctx.user.id, input?.limit || 20);
        } catch (err) {
          console.error('[tRPC] alerts.history error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch alerts' });
        }
      }),
    create: protectedProcedure
      .input(z.object({
        type: z.string(),
        title: z.string(),
        content: z.string(),
        tradeId: z.number().optional(),
      }))
      .mutation(async ({ ctx, input }) => {
        try {
          const alertData: any = {
            type: input.type,
            title: input.title,
            content: input.content,
            sentAt: new Date(),
          };
          if (input.tradeId) alertData.tradeId = input.tradeId;
          return await db.createAlert(ctx.user.id, alertData);
        } catch (err) {
          console.error('[tRPC] alerts.create error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to create alert' });
        }
      }),
  }),

  config: router({
    get: protectedProcedure.query(async ({ ctx }) => {
      try {
        const config = await db.getBotConfig(ctx.user.id);
        return config || {
          symbol: 'SOLUSDT',
          timeframe: '5m',
          riskPerTrade: '0.02',
          stopLossPct: '0.008',
          takeProfitPct: '0.016',
          minConfidence: 62,
          breakevenEnabled: 1,
          partialTPEnabled: 1,
          trailingStopEnabled: 1,
          paperTradingMode: 0,
        };
      } catch (err) {
        console.error('[tRPC] config.get error:', err);
        throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch config' });
      }
    }),
    update: protectedProcedure
      .input(z.object({
        symbol: z.string().optional(),
        timeframe: z.string().optional(),
        riskPerTrade: z.string().optional(),
        stopLossPct: z.string().optional(),
        takeProfitPct: z.string().optional(),
        minConfidence: z.number().optional(),
        dailyLossLimit: z.string().optional(),
        breakevenEnabled: z.number().optional(),
        breakevenTrigger: z.string().optional(),
        partialTPEnabled: z.number().optional(),
        partialTPPercent: z.string().optional(),
        trailingStopEnabled: z.number().optional(),
        trailingStopDist: z.string().optional(),
        paperTradingMode: z.number().optional(),
        paperBalance: z.string().optional(),
      }))
      .mutation(async ({ ctx, input }) => {
        try {
          await db.upsertBotConfig(ctx.user.id, input);
          return { success: true };
        } catch (err) {
          console.error('[tRPC] config.update error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to update config' });
        }
      }),
  }),

  snapshots: router({
    daily: protectedProcedure
      .input(z.object({ days: z.number().int().positive().default(30) }).optional())
      .query(async ({ ctx, input }) => {
        try {
          return await db.getDailySnapshots(ctx.user.id, input?.days || 30);
        } catch (err) {
          console.error('[tRPC] snapshots.daily error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch daily snapshots' });
        }
      }),
    create: protectedProcedure
      .input(z.object({
        date: z.string(),
        startBalance: z.string(),
        endBalance: z.string(),
        dailyPnL: z.string(),
        dailyPnLPercent: z.string(),
        totalTrades: z.number(),
        wins: z.number(),
        losses: z.number(),
        maxDrawdown: z.string().optional(),
      }))
      .mutation(async ({ ctx, input }) => {
        try {
          const snapshotData: any = {
            date: input.date,
            startBalance: input.startBalance,
            endBalance: input.endBalance,
            dailyPnL: input.dailyPnL,
            dailyPnLPercent: input.dailyPnLPercent,
            totalTrades: input.totalTrades,
            wins: input.wins,
            losses: input.losses,
          };
          if (input.maxDrawdown) snapshotData.maxDrawdown = input.maxDrawdown;
          return await db.createDailySnapshot(ctx.user.id, snapshotData);
        } catch (err) {
          console.error('[tRPC] snapshots.create error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to create daily snapshot' });
        }
      }),
  }),

  paperTrading: router({
    state: protectedProcedure.query(async ({ ctx }) => {
      try {
        return await db.getPaperTradingState(ctx.user.id);
      } catch (err) {
        console.error('[tRPC] paperTrading.state error:', err);
        throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch paper trading state' });
      }
    }),
    update: protectedProcedure
      .input(z.object({
        currentBalance: z.string().optional(),
        startBalance: z.string().optional(),
        totalTrades: z.number().optional(),
        wins: z.number().optional(),
        losses: z.number().optional(),
        maxDrawdown: z.string().optional(),
        peakBalance: z.string().optional(),
      }))
      .mutation(async ({ ctx, input }) => {
        try {
          await db.upsertPaperTradingState(ctx.user.id, input);
          return { success: true };
        } catch (err) {
          console.error('[tRPC] paperTrading.update error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to update paper trading state' });
        }
      }),
  }),

  // ─── AICashSystem Subscription Routers ──────────────────────
  subscriptions: router({
    me: protectedProcedure.query(async ({ ctx }) => {
      try {
        return await db.getSubscription(ctx.user.id);
      } catch (err) {
        console.error('[tRPC] subscriptions.me error:', err);
        throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch subscription' });
      }
    }),
    update: protectedProcedure
      .input(z.object({
        tier: z.enum(['free', 'starter', 'professional', 'enterprise']).optional(),
        stripeCustomerId: z.string().optional(),
        stripeSubscriptionId: z.string().optional(),
        stripePaymentIntentId: z.string().optional(),
        status: z.enum(['active', 'cancelled', 'past_due', 'expired']).optional(),
      }))
      .mutation(async ({ ctx, input }) => {
        try {
          await db.upsertSubscription(ctx.user.id, input);
          return { success: true };
        } catch (err) {
          console.error('[tRPC] subscriptions.update error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to update subscription' });
        }
      }),
  }),

  // ─── AICashSystem Tools Routers ────────────────────────────
  tools: router({
    list: publicProcedure.query(async () => {
      try {
        return await db.getAllTools();
      } catch (err) {
        console.error('[tRPC] tools.list error:', err);
        throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch tools' });
      }
    }),
    getBySlug: publicProcedure
      .input(z.object({ slug: z.string() }))
      .query(async ({ input }) => {
        try {
          return await db.getToolBySlug(input.slug);
        } catch (err) {
          console.error('[tRPC] tools.getBySlug error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch tool' });
        }
      }),
    incrementUsage: protectedProcedure
      .input(z.object({ toolId: z.number() }))
      .mutation(async ({ ctx, input }) => {
        try {
          await db.incrementToolUsage(ctx.user.id, input.toolId);
          return { success: true };
        } catch (err) {
          console.error('[tRPC] tools.incrementUsage error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to increment tool usage' });
        }
      }),
  }),

  // ─── AICashSystem Courses Routers ──────────────────────────
  courses: router({
    list: protectedProcedure.query(async () => {
      try {
        return await db.getAllCourses();
      } catch (err) {
        console.error('[tRPC] courses.list error:', err);
        throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch courses' });
      }
    }),
    getBySlug: protectedProcedure
      .input(z.object({ slug: z.string() }))
      .query(async ({ input }) => {
        try {
          return await db.getCourseBySlug(input.slug);
        } catch (err) {
          console.error('[tRPC] courses.getBySlug error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch course' });
        }
      }),
    markComplete: protectedProcedure
      .input(z.object({ courseId: z.number() }))
      .mutation(async ({ ctx, input }) => {
        try {
          await db.markCourseComplete(ctx.user.id, input.courseId);
          return { success: true };
        } catch (err) {
          console.error('[tRPC] courses.markComplete error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to mark course complete' });
        }
      }),
  }),

  // ─── AICashSystem Affiliate Routers ────────────────────────
  affiliates: router({
    me: protectedProcedure.query(async ({ ctx }) => {
      try {
        return await db.getAffiliateByUserId(ctx.user.id);
      } catch (err) {
        console.error('[tRPC] affiliates.me error:', err);
        throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch affiliate info' });
      }
    }),
    getReferrals: protectedProcedure.query(async ({ ctx }) => {
      try {
        const affiliate = await db.getAffiliateByUserId(ctx.user.id);
        if (!affiliate) return [];
        return await db.getReferralsByAffiliate(affiliate.id);
      } catch (err) {
        console.error('[tRPC] affiliates.getReferrals error:', err);
        throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch referrals' });
      }
    }),
  }),

  // ─── AICashSystem Community Routers ────────────────────────
  community: router({
    posts: publicProcedure
      .input(z.object({ limit: z.number().int().positive().default(20) }).optional())
      .query(async ({ input }) => {
        try {
          return await db.getCommunityPosts(input?.limit || 20);
        } catch (err) {
          console.error('[tRPC] community.posts error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch community posts' });
        }
      }),
    createPost: protectedProcedure
      .input(z.object({
        title: z.string(),
        content: z.string(),
        category: z.string(),
      }))
      .mutation(async ({ ctx, input }) => {
        try {
          return await db.createCommunityPost(ctx.user.id, input);
        } catch (err) {
          console.error('[tRPC] community.createPost error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to create post' });
        }
      }),
    getReplies: publicProcedure
      .input(z.object({ postId: z.number() }))
      .query(async ({ input }) => {
        try {
          return await db.getCommunityReplies(input.postId);
        } catch (err) {
          console.error('[tRPC] community.getReplies error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to fetch replies' });
        }
      }),
    createReply: protectedProcedure
      .input(z.object({
        postId: z.number(),
        content: z.string(),
      }))
      .mutation(async ({ ctx, input }) => {
        try {
          return await db.createCommunityReply(input.postId, ctx.user.id, input.content);
        } catch (err) {
          console.error('[tRPC] community.createReply error:', err);
          throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Failed to create reply' });
        }
            }),
  }),
});

export type AppRouter = typeof appRouter;
