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

/**
 * AICashSystem Subscriptions — tracks user tier and payment status
 */
export const subscriptions = mysqlTable('subscriptions', {
  id: int('id').autoincrement().primaryKey(),
  userId: int('userId').notNull().references(() => users.id).unique(),
  tier: mysqlEnum('tier', ['free', 'starter', 'professional', 'enterprise']).notNull().default('free'),
  stripeCustomerId: varchar('stripeCustomerId', { length: 255 }),
  stripeSubscriptionId: varchar('stripeSubscriptionId', { length: 255 }),
  stripePaymentIntentId: varchar('stripePaymentIntentId', { length: 255 }),
  status: mysqlEnum('status', ['active', 'cancelled', 'past_due', 'expired']).notNull().default('active'),
  currentPeriodStart: timestamp('currentPeriodStart'),
  currentPeriodEnd: timestamp('currentPeriodEnd'),
  cancelledAt: timestamp('cancelledAt'),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
  updatedAt: timestamp('updatedAt').defaultNow().onUpdateNow().notNull(),
});

export type Subscription = typeof subscriptions.$inferSelect;
export type InsertSubscription = typeof subscriptions.$inferInsert;

/**
 * AICashSystem Tools — defines available tools and their limits
 */
export const tools = mysqlTable('tools', {
  id: int('id').autoincrement().primaryKey(),
  name: varchar('name', { length: 100 }).notNull().unique(),
  slug: varchar('slug', { length: 100 }).notNull().unique(),
  description: text('description'),
  minTierRequired: mysqlEnum('minTierRequired', ['free', 'starter', 'professional', 'enterprise']).notNull().default('starter'),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
});

export type Tool = typeof tools.$inferSelect;
export type InsertTool = typeof tools.$inferInsert;

/**
 * AICashSystem Usage Tracking — tracks tool usage per user
 */
export const toolUsage = mysqlTable('toolUsage', {
  id: int('id').autoincrement().primaryKey(),
  userId: int('userId').notNull().references(() => users.id),
  toolId: int('toolId').notNull().references(() => tools.id),
  usageCount: int('usageCount').notNull().default(0),
  monthlyLimit: int('monthlyLimit').notNull().default(0), // 0 = unlimited
  resetDate: timestamp('resetDate').notNull(),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
  updatedAt: timestamp('updatedAt').defaultNow().onUpdateNow().notNull(),
});

export type ToolUsage = typeof toolUsage.$inferSelect;
export type InsertToolUsage = typeof toolUsage.$inferInsert;

/**
 * AICashSystem Affiliates — tracks affiliate program participation
 */
export const affiliates = mysqlTable('affiliates', {
  id: int('id').autoincrement().primaryKey(),
  userId: int('userId').notNull().references(() => users.id).unique(),
  referralCode: varchar('referralCode', { length: 50 }).notNull().unique(),
  commissionRate: varchar('commissionRate', { length: 16 }).notNull().default('0.20'), // 20% default
  totalEarned: varchar('totalEarned', { length: 32 }).notNull().default('0'),
  totalReferrals: int('totalReferrals').notNull().default(0),
  status: mysqlEnum('status', ['active', 'suspended', 'inactive']).notNull().default('active'),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
  updatedAt: timestamp('updatedAt').defaultNow().onUpdateNow().notNull(),
});

export type Affiliate = typeof affiliates.$inferSelect;
export type InsertAffiliate = typeof affiliates.$inferInsert;

/**
 * AICashSystem Referrals — tracks affiliate referrals and commissions
 */
export const referrals = mysqlTable('referrals', {
  id: int('id').autoincrement().primaryKey(),
  affiliateId: int('affiliateId').notNull().references(() => affiliates.id),
  customerId: int('customerId').notNull().references(() => users.id),
  tier: mysqlEnum('tier', ['starter', 'professional', 'enterprise']).notNull(),
  commissionAmount: varchar('commissionAmount', { length: 32 }).notNull(),
  status: mysqlEnum('status', ['pending', 'earned', 'paid']).notNull().default('pending'),
  paidAt: timestamp('paidAt'),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
});

export type Referral = typeof referrals.$inferSelect;
export type InsertReferral = typeof referrals.$inferInsert;

/**
 * AICashSystem Courses — educational content modules
 */
export const courses = mysqlTable('courses', {
  id: int('id').autoincrement().primaryKey(),
  title: varchar('title', { length: 255 }).notNull(),
  slug: varchar('slug', { length: 255 }).notNull().unique(),
  description: text('description'),
  minTierRequired: mysqlEnum('minTierRequired', ['free', 'starter', 'professional', 'enterprise']).notNull().default('starter'),
  videoUrl: varchar('videoUrl', { length: 500 }),
  duration: int('duration'), // in minutes
  order: int('order').notNull().default(0),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
  updatedAt: timestamp('updatedAt').defaultNow().onUpdateNow().notNull(),
});

export type Course = typeof courses.$inferSelect;
export type InsertCourse = typeof courses.$inferInsert;

/**
 * AICashSystem Course Progress — tracks user progress through courses
 */
export const courseProgress = mysqlTable('courseProgress', {
  id: int('id').autoincrement().primaryKey(),
  userId: int('userId').notNull().references(() => users.id),
  courseId: int('courseId').notNull().references(() => courses.id),
  completed: int('completed').notNull().default(0),
  completedAt: timestamp('completedAt'),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
  updatedAt: timestamp('updatedAt').defaultNow().onUpdateNow().notNull(),
});

export type CourseProgress = typeof courseProgress.$inferSelect;
export type InsertCourseProgress = typeof courseProgress.$inferInsert;

/**
 * AICashSystem Community Posts — user-generated content in community
 */
export const communityPosts = mysqlTable('communityPosts', {
  id: int('id').autoincrement().primaryKey(),
  userId: int('userId').notNull().references(() => users.id),
  title: varchar('title', { length: 255 }).notNull(),
  content: text('content').notNull(),
  category: varchar('category', { length: 50 }).notNull(), // general, wins, questions, resources
  likes: int('likes').notNull().default(0),
  replies: int('replies').notNull().default(0),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
  updatedAt: timestamp('updatedAt').defaultNow().onUpdateNow().notNull(),
});

export type CommunityPost = typeof communityPosts.$inferSelect;
export type InsertCommunityPost = typeof communityPosts.$inferInsert;

/**
 * AICashSystem Community Replies — replies to community posts
 */
export const communityReplies = mysqlTable('communityReplies', {
  id: int('id').autoincrement().primaryKey(),
  postId: int('postId').notNull().references(() => communityPosts.id),
  userId: int('userId').notNull().references(() => users.id),
  content: text('content').notNull(),
  likes: int('likes').notNull().default(0),
  createdAt: timestamp('createdAt').defaultNow().notNull(),
  updatedAt: timestamp('updatedAt').defaultNow().onUpdateNow().notNull(),
});

export type CommunityReply = typeof communityReplies.$inferSelect;
export type InsertCommunityReply = typeof communityReplies.$inferInsert;
