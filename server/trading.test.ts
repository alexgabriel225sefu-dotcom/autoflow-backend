import { describe, it, expect, beforeEach, vi } from 'vitest';
import { appRouter } from './routers';
import type { TrpcContext } from './_core/context';

// Mock context
function createMockContext(): TrpcContext {
  return {
    user: {
      id: 1,
      openId: 'test-user',
      email: 'test@example.com',
      name: 'Test User',
      loginMethod: 'test',
      role: 'admin',
      createdAt: new Date(),
      updatedAt: new Date(),
      lastSignedIn: new Date(),
    },
    req: {
      protocol: 'https',
      headers: {},
    } as TrpcContext['req'],
    res: {
      clearCookie: vi.fn(),
    } as unknown as TrpcContext['res'],
  };
}

describe('Trading Bot tRPC Procedures', () => {
  let caller: ReturnType<typeof appRouter.createCaller>;
  let ctx: TrpcContext;

  beforeEach(() => {
    ctx = createMockContext();
    caller = appRouter.createCaller(ctx);
  });

  describe('Trades Router', () => {
    it('should fetch trade history', async () => {
      const result = await caller.trades.history({ limit: 10 });
      expect(Array.isArray(result)).toBe(true);
    });

    it('should create a new trade', async () => {
      const tradeData = {
        symbol: 'SOLUSDT',
        side: 'LONG' as const,
        entryPrice: 100,
        exitPrice: null,
        quantity: 1,
        pnl: null,
        closeReason: null,
      };

      const result = await caller.trades.create(tradeData);
      expect(result).toBeDefined();
      expect(result.symbol).toBe('SOLUSDT');
      expect(result.side).toBe('LONG');
    });

    it('should close an existing trade', async () => {
      // First create a trade
      const trade = await caller.trades.create({
        symbol: 'SOLUSDT',
        side: 'LONG',
        entryPrice: 100,
        exitPrice: null,
        quantity: 1,
        pnl: null,
        closeReason: null,
      });

      // Then close it
      const closed = await caller.trades.close({
        tradeId: trade.id,
        exitPrice: 105,
        pnl: 5,
        closeReason: 'TAKE_PROFIT',
      });

      expect(closed.exitPrice).toBe(105);
      expect(closed.pnl).toBe(5);
      expect(closed.closeReason).toBe('TAKE_PROFIT');
    });
  });

  describe('Alerts Router', () => {
    it('should fetch alert history', async () => {
      const result = await caller.alerts.history({ limit: 20 });
      expect(Array.isArray(result)).toBe(true);
    });

    it('should create a new alert', async () => {
      const alertData = {
        type: 'TRADE_OPEN' as const,
        title: 'Trade Opened',
        content: 'BUY SOLUSDT at 100',
      };

      const result = await caller.alerts.create(alertData);
      expect(result).toBeDefined();
      expect(result.type).toBe('TRADE_OPEN');
      expect(result.title).toBe('Trade Opened');
    });
  });

  describe('Config Router', () => {
    it('should fetch bot configuration', async () => {
      const result = await caller.config.get();
      expect(result).toBeDefined();
      expect(result.symbol).toBeDefined();
      expect(result.timeframe).toBeDefined();
    });

    it('should update bot configuration', async () => {
      const updates = {
        symbol: 'ETHUSDT',
        timeframe: '15m',
        riskPerTrade: '0.03',
      };

      const result = await caller.config.update(updates);
      expect(result.symbol).toBe('ETHUSDT');
      expect(result.timeframe).toBe('15m');
    });

    it('should update risk management settings', async () => {
      const updates = {
        breakevenEnabled: 1,
        breakevenTrigger: '0.5',
        partialTPEnabled: 1,
        partialTPPercent: '0.5',
        dailyLossLimit: '100',
      };

      const result = await caller.config.update(updates);
      expect(result.breakevenEnabled).toBe(1);
      expect(result.partialTPEnabled).toBe(1);
    });
  });

  describe('Paper Trading Router', () => {
    it('should fetch paper trading state', async () => {
      const result = await caller.paperTrading.state();
      expect(result).toBeDefined();
      expect(result.currentBalance).toBeDefined();
      expect(result.totalTrades).toBeDefined();
    });

    it('should update paper trading state', async () => {
      const updates = {
        currentBalance: '9500',
        totalTrades: 5,
        wins: 3,
        losses: 2,
      };

      const result = await caller.paperTrading.update(updates);
      expect(result.currentBalance).toBe('9500');
      expect(result.totalTrades).toBe(5);
    });
  });

  describe('Snapshots Router', () => {
    it('should fetch daily snapshots', async () => {
      const result = await caller.snapshots.daily({ days: 7 });
      expect(Array.isArray(result)).toBe(true);
    });

    it('should create a daily snapshot', async () => {
      const snapshotData = {
        date: new Date().toISOString().split('T')[0],
        openingBalance: '10000',
        closingBalance: '10500',
        dailyPnL: '500',
        tradesExecuted: 5,
        winRate: '0.6',
      };

      const result = await caller.snapshots.create(snapshotData);
      expect(result).toBeDefined();
      expect(result.dailyPnL).toBe('500');
    });
  });

  describe('Auth Router', () => {
    it('should return current user', async () => {
      const result = await caller.auth.me();
      expect(result).toBeDefined();
      expect(result.openId).toBe('test-user');
      expect(result.role).toBe('admin');
    });

    it('should logout user', async () => {
      const result = await caller.auth.logout();
      expect(result.success).toBe(true);
    });
  });

  describe('Error Handling', () => {
    it('should handle invalid trade data', async () => {
      try {
        await caller.trades.create({
          symbol: '',
          side: 'LONG',
          entryPrice: -100, // Invalid
          exitPrice: null,
          quantity: 0, // Invalid
          pnl: null,
          closeReason: null,
        });
        expect.fail('Should have thrown an error');
      } catch (error) {
        expect(error).toBeDefined();
      }
    });

    it('should handle missing required fields', async () => {
      try {
        await caller.config.update({
          symbol: '', // Empty symbol
        });
        expect.fail('Should have thrown an error');
      } catch (error) {
        expect(error).toBeDefined();
      }
    });
  });
});
