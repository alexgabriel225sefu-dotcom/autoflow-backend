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
});

export type AppRouter = typeof appRouter;
