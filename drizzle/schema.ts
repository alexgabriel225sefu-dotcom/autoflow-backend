import { int, mysqlEnum, mysqlTable, text, timestamp, varchar } from "drizzle-orm/mysql-core";

/**
 * Core user table backing auth flow.
 * Extend this file with additional tables as your product grows.
 * Columns use camelCase to match both database fields and generated types.
 */
export const users = mysqlTable("users", {
  /**
   * Surrogate primary key. Auto-incremented numeric value managed by the database.
   * Use this for relations between tables.
   */
  id: int("id").autoincrement().primaryKey(),
  /** Manus OAuth identifier (openId) returned from the OAuth callback. Unique per user. */
  openId: varchar("openId", { length: 64 }).notNull().unique(),
  name: text("name"),
  email: varchar("email", { length: 320 }),
  loginMethod: varchar("loginMethod", { length: 64 }),
  role: mysqlEnum("role", ["user", "admin"]).default("user").notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  lastSignedIn: timestamp("lastSignedIn").defaultNow().notNull(),
});

export type User = typeof users.$inferSelect;
export type InsertUser = typeof users.$inferInsert;

/**
 * Trade history table — persists all executed trades
 */
export const trades = mysqlTable('trades', {
  id: int('id').autoincrement().primaryKey(),
  userId: int('userId').notNull().references(() => users.id),
  symbol: varchar('symbol', { length: 20 }).notNull(),
  side: mysqlEnum('side', ['BUY', 'SELL']).notNull(),
  entryPrice: varchar('entryPrice', { length: 32 }).notNull(),
  exitPrice: varchar('exitPrice', { length: 32 }),
  quantity: varchar('quantity', { length: 32 }).notNull(),
  pnl: varchar('pnl', { length: 32 }),
  pnlPercent: varchar('pnlPercent', { length: 16 }),
  closeReason: varchar('closeReason', { length: 50 }), // TP, SL, AI_CLOSE, MANUAL
  openedAt: timestamp('openedAt').notNull(),
  closedAt: timestamp('closedAt'),
  confidence: int('confidence'), // AI confidence 0-100
  criteriaScore: int('criteriaScore'), // 0-5
  createdAt: timestamp('createdAt').defaultNow().notNull(),
});

export type Trade = typeof trades.$inferSelect;
export type InsertTrade = typeof trades.$inferInsert;

/**
 * Telegram alerts log — persists all bot alerts sent to user
 */
export const alerts = mysqlTable('alerts', {
  id: int('id').autoincrement().primaryKey(),
  userId: int('userId').notNull().references(() => users.id),
  type: varchar('type', { length: 50 }).notNull(), // TRADE_OPEN, TRADE_CLOSE, STOP_HIT, DAILY_LIMIT, STRATEGY_STOP, SIGNAL_FILTERED
  title: text('title').notNull(),
  content: text('content').notNull(),
  tradeId: int('tradeId').references(() => trades.id),
  sentAt: timestamp('sentAt').notNull(),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
});

export type Alert = typeof alerts.$inferSelect;
export type InsertAlert = typeof alerts.$inferInsert;

/**
 * Daily PnL snapshots — tracks daily performance
 */
export const dailySnapshots = mysqlTable('dailySnapshots', {
  id: int('id').autoincrement().primaryKey(),
  userId: int('userId').notNull().references(() => users.id),
  date: varchar('date', { length: 10 }).notNull(), // YYYY-MM-DD
  startBalance: varchar('startBalance', { length: 32 }).notNull(),
  endBalance: varchar('endBalance', { length: 32 }).notNull(),
  dailyPnL: varchar('dailyPnL', { length: 32 }).notNull(),
  dailyPnLPercent: varchar('dailyPnLPercent', { length: 16 }).notNull(),
  totalTrades: int('totalTrades').notNull().default(0),
  wins: int('wins').notNull().default(0),
  losses: int('losses').notNull().default(0),
  maxDrawdown: varchar('maxDrawdown', { length: 16 }),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
});

export type DailySnapshot = typeof dailySnapshots.$inferSelect;
export type InsertDailySnapshot = typeof dailySnapshots.$inferInsert;

/**
 * Bot configuration — persists user-configurable bot parameters
 */
export const botConfigs = mysqlTable('botConfigs', {
  id: int('id').autoincrement().primaryKey(),
  userId: int('userId').notNull().references(() => users.id).unique(),
  symbol: varchar('symbol', { length: 20 }).notNull().default('SOLUSDT'),
  timeframe: varchar('timeframe', { length: 10 }).notNull().default('5m'),
  riskPerTrade: varchar('riskPerTrade', { length: 16 }).notNull().default('0.02'),
  stopLossPct: varchar('stopLossPct', { length: 16 }).notNull().default('0.008'),
  takeProfitPct: varchar('takeProfitPct', { length: 16 }).notNull().default('0.016'),
  minConfidence: int('minConfidence').notNull().default(62),
  dailyLossLimit: varchar('dailyLossLimit', { length: 32 }),
  breakevenEnabled: int('breakevenEnabled').notNull().default(1),
  breakevenTrigger: varchar('breakevenTrigger', { length: 16 }).default('0.5'),
  partialTPEnabled: int('partialTPEnabled').notNull().default(1),
  partialTPPercent: varchar('partialTPPercent', { length: 16 }).default('0.5'),
  trailingStopEnabled: int('trailingStopEnabled').notNull().default(1),
  trailingStopDist: varchar('trailingStopDist', { length: 16 }).default('0.01'),
  paperTradingMode: int('paperTradingMode').notNull().default(0),
  paperBalance: varchar('paperBalance', { length: 32 }).default('10'),
  updatedAt: timestamp('updatedAt').defaultNow().onUpdateNow().notNull(),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
});

export type BotConfig = typeof botConfigs.$inferSelect;
export type InsertBotConfig = typeof botConfigs.$inferInsert;

/**
 * Paper trading state — tracks simulated trading session
 */
export const paperTradingStates = mysqlTable('paperTradingStates', {
  id: int('id').autoincrement().primaryKey(),
  userId: int('userId').notNull().references(() => users.id).unique(),
  currentBalance: varchar('currentBalance', { length: 32 }).notNull(),
  startBalance: varchar('startBalance', { length: 32 }).notNull(),
  totalTrades: int('totalTrades').notNull().default(0),
  wins: int('wins').notNull().default(0),
  losses: int('losses').notNull().default(0),
  maxDrawdown: varchar('maxDrawdown', { length: 16 }),
  peakBalance: varchar('peakBalance', { length: 32 }),
  updatedAt: timestamp('updatedAt').defaultNow().onUpdateNow().notNull(),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
});

export type PaperTradingState = typeof paperTradingStates.$inferSelect;
export type InsertPaperTradingState = typeof paperTradingStates.$inferInsert;