// server/_core/index.ts
import "dotenv/config";
import express2 from "express";
import { createServer } from "http";
import net from "net";
import { createExpressMiddleware } from "@trpc/server/adapters/express";

// shared/const.ts
var COOKIE_NAME = "app_session_id";
var ONE_YEAR_MS = 1e3 * 60 * 60 * 24 * 365;
var AXIOS_TIMEOUT_MS = 3e4;
var UNAUTHED_ERR_MSG = "Please login (10001)";
var NOT_ADMIN_ERR_MSG = "You do not have required permission (10002)";

// server/db.ts
import { eq, desc } from "drizzle-orm";
import { drizzle } from "drizzle-orm/mysql2";

// drizzle/schema.ts
import { int, mysqlEnum, mysqlTable, text, timestamp, varchar } from "drizzle-orm/mysql-core";
var users = mysqlTable("users", {
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
  lastSignedIn: timestamp("lastSignedIn").defaultNow().notNull()
});
var trades = mysqlTable("trades", {
  id: int("id").autoincrement().primaryKey(),
  userId: int("userId").notNull().references(() => users.id),
  symbol: varchar("symbol", { length: 20 }).notNull(),
  side: mysqlEnum("side", ["BUY", "SELL"]).notNull(),
  entryPrice: varchar("entryPrice", { length: 32 }).notNull(),
  exitPrice: varchar("exitPrice", { length: 32 }),
  quantity: varchar("quantity", { length: 32 }).notNull(),
  pnl: varchar("pnl", { length: 32 }),
  pnlPercent: varchar("pnlPercent", { length: 16 }),
  closeReason: varchar("closeReason", { length: 50 }),
  // TP, SL, AI_CLOSE, MANUAL
  openedAt: timestamp("openedAt").notNull(),
  closedAt: timestamp("closedAt"),
  confidence: int("confidence"),
  // AI confidence 0-100
  criteriaScore: int("criteriaScore"),
  // 0-5
  createdAt: timestamp("createdAt").defaultNow().notNull()
});
var alerts = mysqlTable("alerts", {
  id: int("id").autoincrement().primaryKey(),
  userId: int("userId").notNull().references(() => users.id),
  type: varchar("type", { length: 50 }).notNull(),
  // TRADE_OPEN, TRADE_CLOSE, STOP_HIT, DAILY_LIMIT, STRATEGY_STOP, SIGNAL_FILTERED
  title: text("title").notNull(),
  content: text("content").notNull(),
  tradeId: int("tradeId").references(() => trades.id),
  sentAt: timestamp("sentAt").notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull()
});
var dailySnapshots = mysqlTable("dailySnapshots", {
  id: int("id").autoincrement().primaryKey(),
  userId: int("userId").notNull().references(() => users.id),
  date: varchar("date", { length: 10 }).notNull(),
  // YYYY-MM-DD
  startBalance: varchar("startBalance", { length: 32 }).notNull(),
  endBalance: varchar("endBalance", { length: 32 }).notNull(),
  dailyPnL: varchar("dailyPnL", { length: 32 }).notNull(),
  dailyPnLPercent: varchar("dailyPnLPercent", { length: 16 }).notNull(),
  totalTrades: int("totalTrades").notNull().default(0),
  wins: int("wins").notNull().default(0),
  losses: int("losses").notNull().default(0),
  maxDrawdown: varchar("maxDrawdown", { length: 16 }),
  createdAt: timestamp("createdAt").defaultNow().notNull()
});
var botConfigs = mysqlTable("botConfigs", {
  id: int("id").autoincrement().primaryKey(),
  userId: int("userId").notNull().references(() => users.id).unique(),
  symbol: varchar("symbol", { length: 20 }).notNull().default("SOLUSDT"),
  timeframe: varchar("timeframe", { length: 10 }).notNull().default("5m"),
  riskPerTrade: varchar("riskPerTrade", { length: 16 }).notNull().default("0.02"),
  stopLossPct: varchar("stopLossPct", { length: 16 }).notNull().default("0.008"),
  takeProfitPct: varchar("takeProfitPct", { length: 16 }).notNull().default("0.016"),
  minConfidence: int("minConfidence").notNull().default(62),
  dailyLossLimit: varchar("dailyLossLimit", { length: 32 }),
  breakevenEnabled: int("breakevenEnabled").notNull().default(1),
  breakevenTrigger: varchar("breakevenTrigger", { length: 16 }).default("0.5"),
  partialTPEnabled: int("partialTPEnabled").notNull().default(1),
  partialTPPercent: varchar("partialTPPercent", { length: 16 }).default("0.5"),
  trailingStopEnabled: int("trailingStopEnabled").notNull().default(1),
  trailingStopDist: varchar("trailingStopDist", { length: 16 }).default("0.01"),
  paperTradingMode: int("paperTradingMode").notNull().default(0),
  paperBalance: varchar("paperBalance", { length: 32 }).default("10"),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull()
});
var paperTradingStates = mysqlTable("paperTradingStates", {
  id: int("id").autoincrement().primaryKey(),
  userId: int("userId").notNull().references(() => users.id).unique(),
  currentBalance: varchar("currentBalance", { length: 32 }).notNull(),
  startBalance: varchar("startBalance", { length: 32 }).notNull(),
  totalTrades: int("totalTrades").notNull().default(0),
  wins: int("wins").notNull().default(0),
  losses: int("losses").notNull().default(0),
  maxDrawdown: varchar("maxDrawdown", { length: 16 }),
  peakBalance: varchar("peakBalance", { length: 32 }),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull()
});
var subscriptions = mysqlTable("subscriptions", {
  id: int("id").autoincrement().primaryKey(),
  userId: int("userId").notNull().references(() => users.id).unique(),
  tier: mysqlEnum("tier", ["free", "starter", "professional", "enterprise"]).notNull().default("free"),
  stripeCustomerId: varchar("stripeCustomerId", { length: 255 }),
  stripeSubscriptionId: varchar("stripeSubscriptionId", { length: 255 }),
  stripePaymentIntentId: varchar("stripePaymentIntentId", { length: 255 }),
  status: mysqlEnum("status", ["active", "cancelled", "past_due", "expired"]).notNull().default("active"),
  currentPeriodStart: timestamp("currentPeriodStart"),
  currentPeriodEnd: timestamp("currentPeriodEnd"),
  cancelledAt: timestamp("cancelledAt"),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull()
});
var tools = mysqlTable("tools", {
  id: int("id").autoincrement().primaryKey(),
  name: varchar("name", { length: 100 }).notNull().unique(),
  slug: varchar("slug", { length: 100 }).notNull().unique(),
  description: text("description"),
  minTierRequired: mysqlEnum("minTierRequired", ["free", "starter", "professional", "enterprise"]).notNull().default("starter"),
  createdAt: timestamp("createdAt").defaultNow().notNull()
});
var toolUsage = mysqlTable("toolUsage", {
  id: int("id").autoincrement().primaryKey(),
  userId: int("userId").notNull().references(() => users.id),
  toolId: int("toolId").notNull().references(() => tools.id),
  usageCount: int("usageCount").notNull().default(0),
  monthlyLimit: int("monthlyLimit").notNull().default(0),
  // 0 = unlimited
  resetDate: timestamp("resetDate").notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull()
});
var affiliates = mysqlTable("affiliates", {
  id: int("id").autoincrement().primaryKey(),
  userId: int("userId").notNull().references(() => users.id).unique(),
  referralCode: varchar("referralCode", { length: 50 }).notNull().unique(),
  commissionRate: varchar("commissionRate", { length: 16 }).notNull().default("0.20"),
  // 20% default
  totalEarned: varchar("totalEarned", { length: 32 }).notNull().default("0"),
  totalReferrals: int("totalReferrals").notNull().default(0),
  status: mysqlEnum("status", ["active", "suspended", "inactive"]).notNull().default("active"),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull()
});
var referrals = mysqlTable("referrals", {
  id: int("id").autoincrement().primaryKey(),
  affiliateId: int("affiliateId").notNull().references(() => affiliates.id),
  customerId: int("customerId").notNull().references(() => users.id),
  tier: mysqlEnum("tier", ["starter", "professional", "enterprise"]).notNull(),
  commissionAmount: varchar("commissionAmount", { length: 32 }).notNull(),
  status: mysqlEnum("status", ["pending", "earned", "paid"]).notNull().default("pending"),
  paidAt: timestamp("paidAt"),
  createdAt: timestamp("createdAt").defaultNow().notNull()
});
var courses = mysqlTable("courses", {
  id: int("id").autoincrement().primaryKey(),
  title: varchar("title", { length: 255 }).notNull(),
  slug: varchar("slug", { length: 255 }).notNull().unique(),
  description: text("description"),
  minTierRequired: mysqlEnum("minTierRequired", ["free", "starter", "professional", "enterprise"]).notNull().default("starter"),
  videoUrl: varchar("videoUrl", { length: 500 }),
  duration: int("duration"),
  // in minutes
  order: int("order").notNull().default(0),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull()
});
var courseProgress = mysqlTable("courseProgress", {
  id: int("id").autoincrement().primaryKey(),
  userId: int("userId").notNull().references(() => users.id),
  courseId: int("courseId").notNull().references(() => courses.id),
  completed: int("completed").notNull().default(0),
  completedAt: timestamp("completedAt"),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull()
});
var communityPosts = mysqlTable("communityPosts", {
  id: int("id").autoincrement().primaryKey(),
  userId: int("userId").notNull().references(() => users.id),
  title: varchar("title", { length: 255 }).notNull(),
  content: text("content").notNull(),
  category: varchar("category", { length: 50 }).notNull(),
  // general, wins, questions, resources
  likes: int("likes").notNull().default(0),
  replies: int("replies").notNull().default(0),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull()
});
var communityReplies = mysqlTable("communityReplies", {
  id: int("id").autoincrement().primaryKey(),
  postId: int("postId").notNull().references(() => communityPosts.id),
  userId: int("userId").notNull().references(() => users.id),
  content: text("content").notNull(),
  likes: int("likes").notNull().default(0),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull()
});

// server/_core/env.ts
var ENV = {
  appId: process.env.VITE_APP_ID ?? "",
  cookieSecret: process.env.JWT_SECRET ?? "",
  databaseUrl: process.env.DATABASE_URL ?? "",
  oAuthServerUrl: process.env.OAUTH_SERVER_URL ?? "",
  ownerOpenId: process.env.OWNER_OPEN_ID ?? "",
  isProduction: process.env.NODE_ENV === "production",
  forgeApiUrl: process.env.BUILT_IN_FORGE_API_URL ?? "",
  forgeApiKey: process.env.BUILT_IN_FORGE_API_KEY ?? ""
};

// server/db.ts
var _db = null;
async function getDb() {
  if (!_db && process.env.DATABASE_URL) {
    try {
      _db = drizzle(process.env.DATABASE_URL);
    } catch (error) {
      console.warn("[Database] Failed to connect:", error);
      _db = null;
    }
  }
  return _db;
}
async function upsertUser(user) {
  if (!user.openId) {
    throw new Error("User openId is required for upsert");
  }
  const db = await getDb();
  if (!db) {
    console.warn("[Database] Cannot upsert user: database not available");
    return;
  }
  try {
    const values = {
      openId: user.openId
    };
    const updateSet = {};
    const textFields = ["name", "email", "loginMethod"];
    const assignNullable = (field) => {
      const value = user[field];
      if (value === void 0) return;
      const normalized = value ?? null;
      values[field] = normalized;
      updateSet[field] = normalized;
    };
    textFields.forEach(assignNullable);
    if (user.lastSignedIn !== void 0) {
      values.lastSignedIn = user.lastSignedIn;
      updateSet.lastSignedIn = user.lastSignedIn;
    }
    if (user.role !== void 0) {
      values.role = user.role;
      updateSet.role = user.role;
    } else if (user.openId === ENV.ownerOpenId) {
      values.role = "admin";
      updateSet.role = "admin";
    }
    if (!values.lastSignedIn) {
      values.lastSignedIn = /* @__PURE__ */ new Date();
    }
    if (Object.keys(updateSet).length === 0) {
      updateSet.lastSignedIn = /* @__PURE__ */ new Date();
    }
    await db.insert(users).values(values).onDuplicateKeyUpdate({
      set: updateSet
    });
  } catch (error) {
    console.error("[Database] Failed to upsert user:", error);
    throw error;
  }
}
async function getUserByOpenId(openId) {
  const db = await getDb();
  if (!db) {
    console.warn("[Database] Cannot get user: database not available");
    return void 0;
  }
  const result = await db.select().from(users).where(eq(users.openId, openId)).limit(1);
  return result.length > 0 ? result[0] : void 0;
}
async function createTrade(userId, trade) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.insert(trades).values({
    ...trade,
    userId
  });
  return result;
}
async function getTradeHistory(userId, limit = 50) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.select().from(trades).where(eq(trades.userId, userId)).orderBy(desc(trades.openedAt)).limit(limit);
  return result;
}
async function updateTrade(tradeId, updates) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.update(trades).set(updates).where(eq(trades.id, tradeId));
}
async function createAlert(userId, alert) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.insert(alerts).values({
    ...alert,
    userId
  });
  return result;
}
async function getAlertHistory(userId, limit = 20) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.select().from(alerts).where(eq(alerts.userId, userId)).orderBy(desc(alerts.sentAt)).limit(limit);
  return result;
}
async function getBotConfig(userId) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.select().from(botConfigs).where(eq(botConfigs.userId, userId)).limit(1);
  return result.length > 0 ? result[0] : null;
}
async function upsertBotConfig(userId, config) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const existing = await getBotConfig(userId);
  if (existing) {
    await db.update(botConfigs).set(config).where(eq(botConfigs.userId, userId));
  } else {
    await db.insert(botConfigs).values({
      userId,
      ...config
    });
  }
}
async function createDailySnapshot(userId, snapshot) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.insert(dailySnapshots).values({
    ...snapshot,
    userId
  });
  return result;
}
async function getDailySnapshots(userId, days = 30) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.select().from(dailySnapshots).where(eq(dailySnapshots.userId, userId)).orderBy(desc(dailySnapshots.date)).limit(days);
  return result;
}
async function getPaperTradingState(userId) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.select().from(paperTradingStates).where(eq(paperTradingStates.userId, userId)).limit(1);
  return result.length > 0 ? result[0] : null;
}
async function upsertPaperTradingState(userId, state) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const existing = await getPaperTradingState(userId);
  if (existing) {
    await db.update(paperTradingStates).set(state).where(eq(paperTradingStates.userId, userId));
  } else {
    await db.insert(paperTradingStates).values({
      userId,
      ...state
    });
  }
}
async function getSubscription(userId) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.select().from(subscriptions).where(eq(subscriptions.userId, userId)).limit(1);
  return result.length > 0 ? result[0] : null;
}
async function upsertSubscription(userId, sub) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const existing = await getSubscription(userId);
  if (existing) {
    await db.update(subscriptions).set(sub).where(eq(subscriptions.userId, userId));
  } else {
    await db.insert(subscriptions).values({
      userId,
      ...sub
    });
  }
}
async function getAllTools() {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  return await db.select().from(tools);
}
async function getToolBySlug(slug) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.select().from(tools).where(eq(tools.slug, slug)).limit(1);
  return result.length > 0 ? result[0] : null;
}
async function getToolUsage(userId, toolId) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.select().from(toolUsage).where(eq(toolUsage.userId, userId) && eq(toolUsage.toolId, toolId)).limit(1);
  return result.length > 0 ? result[0] : null;
}
async function incrementToolUsage(userId, toolId) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const existing = await getToolUsage(userId, toolId);
  if (existing) {
    await db.update(toolUsage).set({ usageCount: existing.usageCount + 1 }).where(eq(toolUsage.id, existing.id));
  } else {
    await db.insert(toolUsage).values({
      userId,
      toolId,
      usageCount: 1,
      resetDate: /* @__PURE__ */ new Date()
    });
  }
}
async function getAffiliateByUserId(userId) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.select().from(affiliates).where(eq(affiliates.userId, userId)).limit(1);
  return result.length > 0 ? result[0] : null;
}
async function getReferralsByAffiliate(affiliateId) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  return await db.select().from(referrals).where(eq(referrals.affiliateId, affiliateId)).orderBy(desc(referrals.createdAt));
}
async function getAllCourses() {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  return await db.select().from(courses).orderBy(courses.order);
}
async function getCourseBySlug(slug) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.select().from(courses).where(eq(courses.slug, slug)).limit(1);
  return result.length > 0 ? result[0] : null;
}
async function getCourseProgress(userId, courseId) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.select().from(courseProgress).where(eq(courseProgress.userId, userId) && eq(courseProgress.courseId, courseId)).limit(1);
  return result.length > 0 ? result[0] : null;
}
async function markCourseComplete(userId, courseId) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const existing = await getCourseProgress(userId, courseId);
  if (existing) {
    await db.update(courseProgress).set({ completed: 1, completedAt: /* @__PURE__ */ new Date() }).where(eq(courseProgress.id, existing.id));
  } else {
    await db.insert(courseProgress).values({
      userId,
      courseId,
      completed: 1,
      completedAt: /* @__PURE__ */ new Date()
    });
  }
}
async function createCommunityPost(userId, post) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  return await db.insert(communityPosts).values({
    ...post,
    userId
  });
}
async function getCommunityPosts(limit = 20) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  return await db.select().from(communityPosts).orderBy(desc(communityPosts.createdAt)).limit(limit);
}
async function createCommunityReply(postId, userId, content) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  return await db.insert(communityReplies).values({
    postId,
    userId,
    content
  });
}
async function getCommunityReplies(postId) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  return await db.select().from(communityReplies).where(eq(communityReplies.postId, postId)).orderBy(desc(communityReplies.createdAt));
}

// server/_core/cookies.ts
function isSecureRequest(req) {
  if (req.protocol === "https") return true;
  const forwardedProto = req.headers["x-forwarded-proto"];
  if (!forwardedProto) return false;
  const protoList = Array.isArray(forwardedProto) ? forwardedProto : forwardedProto.split(",");
  return protoList.some((proto) => proto.trim().toLowerCase() === "https");
}
function getSessionCookieOptions(req) {
  return {
    httpOnly: true,
    path: "/",
    sameSite: "none",
    secure: isSecureRequest(req)
  };
}

// shared/_core/errors.ts
var HttpError = class extends Error {
  constructor(statusCode, message) {
    super(message);
    this.statusCode = statusCode;
    this.name = "HttpError";
  }
};
var ForbiddenError = (msg) => new HttpError(403, msg);

// server/_core/sdk.ts
import axios from "axios";
import { parse as parseCookieHeader } from "cookie";
import { SignJWT, jwtVerify } from "jose";
var isNonEmptyString = (value) => typeof value === "string" && value.length > 0;
var EXCHANGE_TOKEN_PATH = `/webdev.v1.WebDevAuthPublicService/ExchangeToken`;
var GET_USER_INFO_PATH = `/webdev.v1.WebDevAuthPublicService/GetUserInfo`;
var GET_USER_INFO_WITH_JWT_PATH = `/webdev.v1.WebDevAuthPublicService/GetUserInfoWithJwt`;
var OAuthService = class {
  constructor(client) {
    this.client = client;
    console.log("[OAuth] Initialized with baseURL:", ENV.oAuthServerUrl);
    if (!ENV.oAuthServerUrl) {
      console.error(
        "[OAuth] ERROR: OAUTH_SERVER_URL is not configured! Set OAUTH_SERVER_URL environment variable."
      );
    }
  }
  decodeState(state) {
    const redirectUri = atob(state);
    return redirectUri;
  }
  async getTokenByCode(code, state) {
    const payload = {
      clientId: ENV.appId,
      grantType: "authorization_code",
      code,
      redirectUri: this.decodeState(state)
    };
    const { data } = await this.client.post(
      EXCHANGE_TOKEN_PATH,
      payload
    );
    return data;
  }
  async getUserInfoByToken(token) {
    const { data } = await this.client.post(
      GET_USER_INFO_PATH,
      {
        accessToken: token.accessToken
      }
    );
    return data;
  }
};
var createOAuthHttpClient = () => axios.create({
  baseURL: ENV.oAuthServerUrl,
  timeout: AXIOS_TIMEOUT_MS
});
var SDKServer = class {
  client;
  oauthService;
  constructor(client = createOAuthHttpClient()) {
    this.client = client;
    this.oauthService = new OAuthService(this.client);
  }
  deriveLoginMethod(platforms, fallback) {
    if (fallback && fallback.length > 0) return fallback;
    if (!Array.isArray(platforms) || platforms.length === 0) return null;
    const set = new Set(
      platforms.filter((p) => typeof p === "string")
    );
    if (set.has("REGISTERED_PLATFORM_EMAIL")) return "email";
    if (set.has("REGISTERED_PLATFORM_GOOGLE")) return "google";
    if (set.has("REGISTERED_PLATFORM_APPLE")) return "apple";
    if (set.has("REGISTERED_PLATFORM_MICROSOFT") || set.has("REGISTERED_PLATFORM_AZURE"))
      return "microsoft";
    if (set.has("REGISTERED_PLATFORM_GITHUB")) return "github";
    const first = Array.from(set)[0];
    return first ? first.toLowerCase() : null;
  }
  /**
   * Exchange OAuth authorization code for access token
   * @example
   * const tokenResponse = await sdk.exchangeCodeForToken(code, state);
   */
  async exchangeCodeForToken(code, state) {
    return this.oauthService.getTokenByCode(code, state);
  }
  /**
   * Get user information using access token
   * @example
   * const userInfo = await sdk.getUserInfo(tokenResponse.accessToken);
   */
  async getUserInfo(accessToken) {
    const data = await this.oauthService.getUserInfoByToken({
      accessToken
    });
    const loginMethod = this.deriveLoginMethod(
      data?.platforms,
      data?.platform ?? data.platform ?? null
    );
    return {
      ...data,
      platform: loginMethod,
      loginMethod
    };
  }
  parseCookies(cookieHeader) {
    if (!cookieHeader) {
      return /* @__PURE__ */ new Map();
    }
    const parsed = parseCookieHeader(cookieHeader);
    return new Map(Object.entries(parsed));
  }
  getSessionSecret() {
    const secret = ENV.cookieSecret;
    return new TextEncoder().encode(secret);
  }
  /**
   * Create a session token for a Manus user openId
   * @example
   * const sessionToken = await sdk.createSessionToken(userInfo.openId);
   */
  async createSessionToken(openId, options = {}) {
    return this.signSession(
      {
        openId,
        appId: ENV.appId,
        name: options.name || ""
      },
      options
    );
  }
  async signSession(payload, options = {}) {
    const issuedAt = Date.now();
    const expiresInMs = options.expiresInMs ?? ONE_YEAR_MS;
    const expirationSeconds = Math.floor((issuedAt + expiresInMs) / 1e3);
    const secretKey = this.getSessionSecret();
    return new SignJWT({
      openId: payload.openId,
      appId: payload.appId,
      name: payload.name
    }).setProtectedHeader({ alg: "HS256", typ: "JWT" }).setExpirationTime(expirationSeconds).sign(secretKey);
  }
  async verifySession(cookieValue) {
    if (!cookieValue) {
      console.warn("[Auth] Missing session cookie");
      return null;
    }
    try {
      const secretKey = this.getSessionSecret();
      const { payload } = await jwtVerify(cookieValue, secretKey, {
        algorithms: ["HS256"]
      });
      const { openId, appId, name } = payload;
      if (!isNonEmptyString(openId) || !isNonEmptyString(appId) || !isNonEmptyString(name)) {
        console.warn("[Auth] Session payload missing required fields");
        return null;
      }
      return {
        openId,
        appId,
        name
      };
    } catch (error) {
      console.warn("[Auth] Session verification failed", String(error));
      return null;
    }
  }
  async getUserInfoWithJwt(jwtToken) {
    const payload = {
      jwtToken,
      projectId: ENV.appId
    };
    const { data } = await this.client.post(
      GET_USER_INFO_WITH_JWT_PATH,
      payload
    );
    const loginMethod = this.deriveLoginMethod(
      data?.platforms,
      data?.platform ?? data.platform ?? null
    );
    return {
      ...data,
      platform: loginMethod,
      loginMethod
    };
  }
  async authenticateRequest(req) {
    const cookies = this.parseCookies(req.headers.cookie);
    const sessionCookie = cookies.get(COOKIE_NAME);
    const session = await this.verifySession(sessionCookie);
    if (!session) {
      throw ForbiddenError("Invalid session cookie");
    }
    if (session.openId.startsWith(CRON_OPEN_ID_PREFIX)) {
      const userInfo = await this.getUserInfoWithJwt(sessionCookie ?? "");
      const taskUid = userInfo.taskUid ?? null;
      if (!taskUid) {
        throw ForbiddenError("Cron session missing task_uid");
      }
      return buildCronUser(userInfo);
    }
    const sessionUserId = session.openId;
    const signedInAt = /* @__PURE__ */ new Date();
    let user = await getUserByOpenId(sessionUserId);
    if (!user) {
      try {
        const userInfo = await this.getUserInfoWithJwt(sessionCookie ?? "");
        await upsertUser({
          openId: userInfo.openId,
          name: userInfo.name || null,
          email: userInfo.email ?? null,
          loginMethod: userInfo.loginMethod ?? userInfo.platform ?? null,
          lastSignedIn: signedInAt
        });
        user = await getUserByOpenId(userInfo.openId);
      } catch (error) {
        console.error("[Auth] Failed to sync user from OAuth:", error);
        throw ForbiddenError("Failed to sync user info");
      }
    }
    if (!user) {
      throw ForbiddenError("User not found");
    }
    await upsertUser({
      openId: user.openId,
      lastSignedIn: signedInAt
    });
    return user;
  }
};
var CRON_OPEN_ID_PREFIX = "cron_";
function buildCronUser(userInfo) {
  const now = /* @__PURE__ */ new Date();
  return {
    id: -1,
    openId: userInfo.openId,
    name: userInfo.name || "Manus Scheduled Task",
    email: null,
    loginMethod: null,
    role: "user",
    createdAt: now,
    updatedAt: now,
    lastSignedIn: now,
    taskUid: userInfo.taskUid ?? void 0,
    isCron: true
  };
}
var sdk = new SDKServer();

// server/_core/oauth.ts
function getQueryParam(req, key) {
  const value = req.query[key];
  return typeof value === "string" ? value : void 0;
}
function registerOAuthRoutes(app) {
  app.get("/api/oauth/callback", async (req, res) => {
    const code = getQueryParam(req, "code");
    const state = getQueryParam(req, "state");
    if (!code || !state) {
      res.status(400).json({ error: "code and state are required" });
      return;
    }
    try {
      const tokenResponse = await sdk.exchangeCodeForToken(code, state);
      const userInfo = await sdk.getUserInfo(tokenResponse.accessToken);
      if (!userInfo.openId) {
        res.status(400).json({ error: "openId missing from user info" });
        return;
      }
      await upsertUser({
        openId: userInfo.openId,
        name: userInfo.name || null,
        email: userInfo.email ?? null,
        loginMethod: userInfo.loginMethod ?? userInfo.platform ?? null,
        lastSignedIn: /* @__PURE__ */ new Date()
      });
      const sessionToken = await sdk.createSessionToken(userInfo.openId, {
        name: userInfo.name || "",
        expiresInMs: ONE_YEAR_MS
      });
      const cookieOptions = getSessionCookieOptions(req);
      res.cookie(COOKIE_NAME, sessionToken, { ...cookieOptions, maxAge: ONE_YEAR_MS });
      res.redirect(302, "/");
    } catch (error) {
      console.error("[OAuth] Callback failed", error);
      res.status(500).json({ error: "OAuth callback failed" });
    }
  });
}

// server/_core/storageProxy.ts
function registerStorageProxy(app) {
  app.get("/manus-storage/*", async (req, res) => {
    const key = req.params[0];
    if (!key) {
      res.status(400).send("Missing storage key");
      return;
    }
    if (!ENV.forgeApiUrl || !ENV.forgeApiKey) {
      res.status(500).send("Storage proxy not configured");
      return;
    }
    try {
      const forgeUrl = new URL(
        "v1/storage/presign/get",
        ENV.forgeApiUrl.replace(/\/+$/, "") + "/"
      );
      forgeUrl.searchParams.set("path", key);
      const forgeResp = await fetch(forgeUrl, {
        headers: { Authorization: `Bearer ${ENV.forgeApiKey}` }
      });
      if (!forgeResp.ok) {
        const body = await forgeResp.text().catch(() => "");
        console.error(`[StorageProxy] forge error: ${forgeResp.status} ${body}`);
        res.status(502).send("Storage backend error");
        return;
      }
      const { url } = await forgeResp.json();
      if (!url) {
        res.status(502).send("Empty signed URL from backend");
        return;
      }
      res.set("Cache-Control", "no-store");
      res.redirect(307, url);
    } catch (err) {
      console.error("[StorageProxy] failed:", err);
      res.status(502).send("Storage proxy error");
    }
  });
}

// server/_core/systemRouter.ts
import { z } from "zod";

// server/_core/notification.ts
import { TRPCError } from "@trpc/server";
var TITLE_MAX_LENGTH = 1200;
var CONTENT_MAX_LENGTH = 2e4;
var trimValue = (value) => value.trim();
var isNonEmptyString2 = (value) => typeof value === "string" && value.trim().length > 0;
var buildEndpointUrl = (baseUrl) => {
  const normalizedBase = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  return new URL(
    "webdevtoken.v1.WebDevService/SendNotification",
    normalizedBase
  ).toString();
};
var validatePayload = (input) => {
  if (!isNonEmptyString2(input.title)) {
    throw new TRPCError({
      code: "BAD_REQUEST",
      message: "Notification title is required."
    });
  }
  if (!isNonEmptyString2(input.content)) {
    throw new TRPCError({
      code: "BAD_REQUEST",
      message: "Notification content is required."
    });
  }
  const title = trimValue(input.title);
  const content = trimValue(input.content);
  if (title.length > TITLE_MAX_LENGTH) {
    throw new TRPCError({
      code: "BAD_REQUEST",
      message: `Notification title must be at most ${TITLE_MAX_LENGTH} characters.`
    });
  }
  if (content.length > CONTENT_MAX_LENGTH) {
    throw new TRPCError({
      code: "BAD_REQUEST",
      message: `Notification content must be at most ${CONTENT_MAX_LENGTH} characters.`
    });
  }
  return { title, content };
};
async function notifyOwner(payload) {
  const { title, content } = validatePayload(payload);
  if (!ENV.forgeApiUrl) {
    throw new TRPCError({
      code: "INTERNAL_SERVER_ERROR",
      message: "Notification service URL is not configured."
    });
  }
  if (!ENV.forgeApiKey) {
    throw new TRPCError({
      code: "INTERNAL_SERVER_ERROR",
      message: "Notification service API key is not configured."
    });
  }
  const endpoint = buildEndpointUrl(ENV.forgeApiUrl);
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        accept: "application/json",
        authorization: `Bearer ${ENV.forgeApiKey}`,
        "content-type": "application/json",
        "connect-protocol-version": "1"
      },
      body: JSON.stringify({ title, content })
    });
    if (!response.ok) {
      const detail = await response.text().catch(() => "");
      console.warn(
        `[Notification] Failed to notify owner (${response.status} ${response.statusText})${detail ? `: ${detail}` : ""}`
      );
      return false;
    }
    return true;
  } catch (error) {
    console.warn("[Notification] Error calling notification service:", error);
    return false;
  }
}

// server/_core/trpc.ts
import { initTRPC, TRPCError as TRPCError2 } from "@trpc/server";
import superjson from "superjson";
var t = initTRPC.context().create({
  transformer: superjson
});
var router = t.router;
var publicProcedure = t.procedure;
var requireUser = t.middleware(async (opts) => {
  const { ctx, next } = opts;
  if (!ctx.user) {
    throw new TRPCError2({ code: "UNAUTHORIZED", message: UNAUTHED_ERR_MSG });
  }
  return next({
    ctx: {
      ...ctx,
      user: ctx.user
    }
  });
});
var protectedProcedure = t.procedure.use(requireUser);
var adminProcedure = t.procedure.use(
  t.middleware(async (opts) => {
    const { ctx, next } = opts;
    if (!ctx.user || ctx.user.role !== "admin") {
      throw new TRPCError2({ code: "FORBIDDEN", message: NOT_ADMIN_ERR_MSG });
    }
    return next({
      ctx: {
        ...ctx,
        user: ctx.user
      }
    });
  })
);

// server/_core/systemRouter.ts
var systemRouter = router({
  health: publicProcedure.input(
    z.object({
      timestamp: z.number().min(0, "timestamp cannot be negative")
    })
  ).query(() => ({
    ok: true
  })),
  notifyOwner: adminProcedure.input(
    z.object({
      title: z.string().min(1, "title is required"),
      content: z.string().min(1, "content is required")
    })
  ).mutation(async ({ input }) => {
    const delivered = await notifyOwner(input);
    return {
      success: delivered
    };
  })
});

// server/routers.ts
import { z as z2 } from "zod";
import { TRPCError as TRPCError3 } from "@trpc/server";
var appRouter = router({
  system: systemRouter,
  auth: router({
    me: publicProcedure.query((opts) => opts.ctx.user),
    logout: publicProcedure.mutation(({ ctx }) => {
      const cookieOptions = getSessionCookieOptions(ctx.req);
      ctx.res.clearCookie(COOKIE_NAME, { ...cookieOptions, maxAge: -1 });
      return {
        success: true
      };
    })
  }),
  // ─── Trading Bot Routers ──────────────────────────────────
  trades: router({
    history: protectedProcedure.input(z2.object({ limit: z2.number().int().positive().default(50) }).optional()).query(async ({ ctx, input }) => {
      try {
        return await getTradeHistory(ctx.user.id, input?.limit || 50);
      } catch (err) {
        console.error("[tRPC] trades.history error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch trade history" });
      }
    }),
    create: protectedProcedure.input(z2.object({
      symbol: z2.string(),
      side: z2.enum(["BUY", "SELL"]),
      entryPrice: z2.string(),
      quantity: z2.string(),
      confidence: z2.number().optional(),
      criteriaScore: z2.number().optional()
    })).mutation(async ({ ctx, input }) => {
      try {
        const tradeData = {
          symbol: input.symbol,
          side: input.side,
          entryPrice: input.entryPrice,
          quantity: input.quantity,
          openedAt: /* @__PURE__ */ new Date()
        };
        if (input.confidence !== void 0) tradeData.confidence = input.confidence;
        if (input.criteriaScore !== void 0) tradeData.criteriaScore = input.criteriaScore;
        return await createTrade(ctx.user.id, tradeData);
      } catch (err) {
        console.error("[tRPC] trades.create error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to create trade" });
      }
    }),
    close: protectedProcedure.input(z2.object({
      tradeId: z2.number(),
      exitPrice: z2.string(),
      pnl: z2.string(),
      pnlPercent: z2.string(),
      closeReason: z2.string()
    })).mutation(async ({ ctx, input }) => {
      try {
        await updateTrade(input.tradeId, {
          exitPrice: input.exitPrice,
          pnl: input.pnl,
          pnlPercent: input.pnlPercent,
          closeReason: input.closeReason,
          closedAt: /* @__PURE__ */ new Date()
        });
        return { success: true };
      } catch (err) {
        console.error("[tRPC] trades.close error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to close trade" });
      }
    })
  }),
  alerts: router({
    history: protectedProcedure.input(z2.object({ limit: z2.number().int().positive().default(20) }).optional()).query(async ({ ctx, input }) => {
      try {
        return await getAlertHistory(ctx.user.id, input?.limit || 20);
      } catch (err) {
        console.error("[tRPC] alerts.history error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch alerts" });
      }
    }),
    create: protectedProcedure.input(z2.object({
      type: z2.string(),
      title: z2.string(),
      content: z2.string(),
      tradeId: z2.number().optional()
    })).mutation(async ({ ctx, input }) => {
      try {
        const alertData = {
          type: input.type,
          title: input.title,
          content: input.content,
          sentAt: /* @__PURE__ */ new Date()
        };
        if (input.tradeId) alertData.tradeId = input.tradeId;
        return await createAlert(ctx.user.id, alertData);
      } catch (err) {
        console.error("[tRPC] alerts.create error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to create alert" });
      }
    })
  }),
  config: router({
    get: protectedProcedure.query(async ({ ctx }) => {
      try {
        const config = await getBotConfig(ctx.user.id);
        return config || {
          symbol: "SOLUSDT",
          timeframe: "5m",
          riskPerTrade: "0.02",
          stopLossPct: "0.008",
          takeProfitPct: "0.016",
          minConfidence: 62,
          breakevenEnabled: 1,
          partialTPEnabled: 1,
          trailingStopEnabled: 1,
          paperTradingMode: 0
        };
      } catch (err) {
        console.error("[tRPC] config.get error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch config" });
      }
    }),
    update: protectedProcedure.input(z2.object({
      symbol: z2.string().optional(),
      timeframe: z2.string().optional(),
      riskPerTrade: z2.string().optional(),
      stopLossPct: z2.string().optional(),
      takeProfitPct: z2.string().optional(),
      minConfidence: z2.number().optional(),
      dailyLossLimit: z2.string().optional(),
      breakevenEnabled: z2.number().optional(),
      breakevenTrigger: z2.string().optional(),
      partialTPEnabled: z2.number().optional(),
      partialTPPercent: z2.string().optional(),
      trailingStopEnabled: z2.number().optional(),
      trailingStopDist: z2.string().optional(),
      paperTradingMode: z2.number().optional(),
      paperBalance: z2.string().optional()
    })).mutation(async ({ ctx, input }) => {
      try {
        await upsertBotConfig(ctx.user.id, input);
        return { success: true };
      } catch (err) {
        console.error("[tRPC] config.update error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to update config" });
      }
    })
  }),
  snapshots: router({
    daily: protectedProcedure.input(z2.object({ days: z2.number().int().positive().default(30) }).optional()).query(async ({ ctx, input }) => {
      try {
        return await getDailySnapshots(ctx.user.id, input?.days || 30);
      } catch (err) {
        console.error("[tRPC] snapshots.daily error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch daily snapshots" });
      }
    }),
    create: protectedProcedure.input(z2.object({
      date: z2.string(),
      startBalance: z2.string(),
      endBalance: z2.string(),
      dailyPnL: z2.string(),
      dailyPnLPercent: z2.string(),
      totalTrades: z2.number(),
      wins: z2.number(),
      losses: z2.number(),
      maxDrawdown: z2.string().optional()
    })).mutation(async ({ ctx, input }) => {
      try {
        const snapshotData = {
          date: input.date,
          startBalance: input.startBalance,
          endBalance: input.endBalance,
          dailyPnL: input.dailyPnL,
          dailyPnLPercent: input.dailyPnLPercent,
          totalTrades: input.totalTrades,
          wins: input.wins,
          losses: input.losses
        };
        if (input.maxDrawdown) snapshotData.maxDrawdown = input.maxDrawdown;
        return await createDailySnapshot(ctx.user.id, snapshotData);
      } catch (err) {
        console.error("[tRPC] snapshots.create error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to create daily snapshot" });
      }
    })
  }),
  paperTrading: router({
    state: protectedProcedure.query(async ({ ctx }) => {
      try {
        return await getPaperTradingState(ctx.user.id);
      } catch (err) {
        console.error("[tRPC] paperTrading.state error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch paper trading state" });
      }
    }),
    update: protectedProcedure.input(z2.object({
      currentBalance: z2.string().optional(),
      startBalance: z2.string().optional(),
      totalTrades: z2.number().optional(),
      wins: z2.number().optional(),
      losses: z2.number().optional(),
      maxDrawdown: z2.string().optional(),
      peakBalance: z2.string().optional()
    })).mutation(async ({ ctx, input }) => {
      try {
        await upsertPaperTradingState(ctx.user.id, input);
        return { success: true };
      } catch (err) {
        console.error("[tRPC] paperTrading.update error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to update paper trading state" });
      }
    })
  }),
  // ─── AICashSystem Subscription Routers ──────────────────────
  subscriptions: router({
    me: protectedProcedure.query(async ({ ctx }) => {
      try {
        return await getSubscription(ctx.user.id);
      } catch (err) {
        console.error("[tRPC] subscriptions.me error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch subscription" });
      }
    }),
    update: protectedProcedure.input(z2.object({
      tier: z2.enum(["free", "starter", "professional", "enterprise"]).optional(),
      stripeCustomerId: z2.string().optional(),
      stripeSubscriptionId: z2.string().optional(),
      stripePaymentIntentId: z2.string().optional(),
      status: z2.enum(["active", "cancelled", "past_due", "expired"]).optional()
    })).mutation(async ({ ctx, input }) => {
      try {
        await upsertSubscription(ctx.user.id, input);
        return { success: true };
      } catch (err) {
        console.error("[tRPC] subscriptions.update error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to update subscription" });
      }
    })
  }),
  // ─── AICashSystem Tools Routers ────────────────────────────
  tools: router({
    list: publicProcedure.query(async () => {
      try {
        return await getAllTools();
      } catch (err) {
        console.error("[tRPC] tools.list error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch tools" });
      }
    }),
    getBySlug: publicProcedure.input(z2.object({ slug: z2.string() })).query(async ({ input }) => {
      try {
        return await getToolBySlug(input.slug);
      } catch (err) {
        console.error("[tRPC] tools.getBySlug error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch tool" });
      }
    }),
    incrementUsage: protectedProcedure.input(z2.object({ toolId: z2.number() })).mutation(async ({ ctx, input }) => {
      try {
        await incrementToolUsage(ctx.user.id, input.toolId);
        return { success: true };
      } catch (err) {
        console.error("[tRPC] tools.incrementUsage error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to increment tool usage" });
      }
    })
  }),
  // ─── AICashSystem Courses Routers ──────────────────────────
  courses: router({
    list: protectedProcedure.query(async () => {
      try {
        return await getAllCourses();
      } catch (err) {
        console.error("[tRPC] courses.list error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch courses" });
      }
    }),
    getBySlug: protectedProcedure.input(z2.object({ slug: z2.string() })).query(async ({ input }) => {
      try {
        return await getCourseBySlug(input.slug);
      } catch (err) {
        console.error("[tRPC] courses.getBySlug error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch course" });
      }
    }),
    markComplete: protectedProcedure.input(z2.object({ courseId: z2.number() })).mutation(async ({ ctx, input }) => {
      try {
        await markCourseComplete(ctx.user.id, input.courseId);
        return { success: true };
      } catch (err) {
        console.error("[tRPC] courses.markComplete error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to mark course complete" });
      }
    })
  }),
  // ─── AICashSystem Affiliate Routers ────────────────────────
  affiliates: router({
    me: protectedProcedure.query(async ({ ctx }) => {
      try {
        return await getAffiliateByUserId(ctx.user.id);
      } catch (err) {
        console.error("[tRPC] affiliates.me error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch affiliate info" });
      }
    }),
    getReferrals: protectedProcedure.query(async ({ ctx }) => {
      try {
        const affiliate = await getAffiliateByUserId(ctx.user.id);
        if (!affiliate) return [];
        return await getReferralsByAffiliate(affiliate.id);
      } catch (err) {
        console.error("[tRPC] affiliates.getReferrals error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch referrals" });
      }
    })
  }),
  // ─── AICashSystem Community Routers ────────────────────────
  community: router({
    posts: publicProcedure.input(z2.object({ limit: z2.number().int().positive().default(20) }).optional()).query(async ({ input }) => {
      try {
        return await getCommunityPosts(input?.limit || 20);
      } catch (err) {
        console.error("[tRPC] community.posts error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch community posts" });
      }
    }),
    createPost: protectedProcedure.input(z2.object({
      title: z2.string(),
      content: z2.string(),
      category: z2.string()
    })).mutation(async ({ ctx, input }) => {
      try {
        return await createCommunityPost(ctx.user.id, input);
      } catch (err) {
        console.error("[tRPC] community.createPost error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to create post" });
      }
    }),
    getReplies: publicProcedure.input(z2.object({ postId: z2.number() })).query(async ({ input }) => {
      try {
        return await getCommunityReplies(input.postId);
      } catch (err) {
        console.error("[tRPC] community.getReplies error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to fetch replies" });
      }
    }),
    createReply: protectedProcedure.input(z2.object({
      postId: z2.number(),
      content: z2.string()
    })).mutation(async ({ ctx, input }) => {
      try {
        return await createCommunityReply(input.postId, ctx.user.id, input.content);
      } catch (err) {
        console.error("[tRPC] community.createReply error:", err);
        throw new TRPCError3({ code: "INTERNAL_SERVER_ERROR", message: "Failed to create reply" });
      }
    })
  })
});

// server/_core/context.ts
async function createContext(opts) {
  let user = null;
  try {
    user = await sdk.authenticateRequest(opts.req);
  } catch (error) {
    user = null;
  }
  return {
    req: opts.req,
    res: opts.res,
    user
  };
}

// server/_core/vite.ts
import express from "express";
import fs2 from "fs";
import { nanoid } from "nanoid";
import path2 from "path";
import { createServer as createViteServer } from "vite";

// vite.config.ts
import { jsxLocPlugin } from "@builder.io/vite-plugin-jsx-loc";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";
import { vitePluginManusRuntime } from "vite-plugin-manus-runtime";
var PROJECT_ROOT = import.meta.dirname;
var LOG_DIR = path.join(PROJECT_ROOT, ".manus-logs");
var MAX_LOG_SIZE_BYTES = 1 * 1024 * 1024;
var TRIM_TARGET_BYTES = Math.floor(MAX_LOG_SIZE_BYTES * 0.6);
function ensureLogDir() {
  if (!fs.existsSync(LOG_DIR)) {
    fs.mkdirSync(LOG_DIR, { recursive: true });
  }
}
function trimLogFile(logPath, maxSize) {
  try {
    if (!fs.existsSync(logPath) || fs.statSync(logPath).size <= maxSize) {
      return;
    }
    const lines = fs.readFileSync(logPath, "utf-8").split("\n");
    const keptLines = [];
    let keptBytes = 0;
    const targetSize = TRIM_TARGET_BYTES;
    for (let i = lines.length - 1; i >= 0; i--) {
      const lineBytes = Buffer.byteLength(`${lines[i]}
`, "utf-8");
      if (keptBytes + lineBytes > targetSize) break;
      keptLines.unshift(lines[i]);
      keptBytes += lineBytes;
    }
    fs.writeFileSync(logPath, keptLines.join("\n"), "utf-8");
  } catch {
  }
}
function writeToLogFile(source, entries) {
  if (entries.length === 0) return;
  ensureLogDir();
  const logPath = path.join(LOG_DIR, `${source}.log`);
  const lines = entries.map((entry) => {
    const ts = (/* @__PURE__ */ new Date()).toISOString();
    return `[${ts}] ${JSON.stringify(entry)}`;
  });
  fs.appendFileSync(logPath, `${lines.join("\n")}
`, "utf-8");
  trimLogFile(logPath, MAX_LOG_SIZE_BYTES);
}
function vitePluginManusDebugCollector() {
  return {
    name: "manus-debug-collector",
    transformIndexHtml(html) {
      if (process.env.NODE_ENV === "production") {
        return html;
      }
      return {
        html,
        tags: [
          {
            tag: "script",
            attrs: {
              src: "/__manus__/debug-collector.js",
              defer: true
            },
            injectTo: "head"
          }
        ]
      };
    },
    configureServer(server) {
      server.middlewares.use("/__manus__/logs", (req, res, next) => {
        if (req.method !== "POST") {
          return next();
        }
        const handlePayload = (payload) => {
          if (payload.consoleLogs?.length > 0) {
            writeToLogFile("browserConsole", payload.consoleLogs);
          }
          if (payload.networkRequests?.length > 0) {
            writeToLogFile("networkRequests", payload.networkRequests);
          }
          if (payload.sessionEvents?.length > 0) {
            writeToLogFile("sessionReplay", payload.sessionEvents);
          }
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ success: true }));
        };
        const reqBody = req.body;
        if (reqBody && typeof reqBody === "object") {
          try {
            handlePayload(reqBody);
          } catch (e) {
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ success: false, error: String(e) }));
          }
          return;
        }
        let body = "";
        req.on("data", (chunk) => {
          body += chunk.toString();
        });
        req.on("end", () => {
          try {
            const payload = JSON.parse(body);
            handlePayload(payload);
          } catch (e) {
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ success: false, error: String(e) }));
          }
        });
      });
    }
  };
}
var plugins = [react(), tailwindcss(), jsxLocPlugin(), vitePluginManusRuntime(), vitePluginManusDebugCollector()];
var vite_config_default = defineConfig({
  plugins,
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "client", "src"),
      "@shared": path.resolve(import.meta.dirname, "shared"),
      "@assets": path.resolve(import.meta.dirname, "attached_assets")
    }
  },
  envDir: path.resolve(import.meta.dirname),
  root: path.resolve(import.meta.dirname, "client"),
  publicDir: path.resolve(import.meta.dirname, "client", "public"),
  build: {
    outDir: path.resolve(import.meta.dirname, "dist/public"),
    emptyOutDir: true
  },
  server: {
    host: true,
    allowedHosts: [
      ".manuspre.computer",
      ".manus.computer",
      ".manus-asia.computer",
      ".manuscomputer.ai",
      ".manusvm.computer",
      "localhost",
      "127.0.0.1"
    ],
    fs: {
      strict: true,
      deny: ["**/.*"]
    }
  }
});

// server/_core/vite.ts
async function setupVite(app, server) {
  const serverOptions = {
    middlewareMode: true,
    hmr: { server },
    allowedHosts: true
  };
  const vite = await createViteServer({
    ...vite_config_default,
    configFile: false,
    server: serverOptions,
    appType: "custom"
  });
  app.use(vite.middlewares);
  app.use("*", async (req, res, next) => {
    const url = req.originalUrl;
    try {
      const clientTemplate = path2.resolve(
        import.meta.dirname,
        "../..",
        "client",
        "index.html"
      );
      let template = await fs2.promises.readFile(clientTemplate, "utf-8");
      template = template.replace(
        `src="/src/main.tsx"`,
        `src="/src/main.tsx?v=${nanoid()}"`
      );
      const page = await vite.transformIndexHtml(url, template);
      res.status(200).set({ "Content-Type": "text/html" }).end(page);
    } catch (e) {
      vite.ssrFixStacktrace(e);
      next(e);
    }
  });
}
function serveStatic(app) {
  const distPath = process.env.NODE_ENV === "development" ? path2.resolve(import.meta.dirname, "../..", "dist", "public") : path2.resolve(import.meta.dirname, "public");
  if (!fs2.existsSync(distPath)) {
    console.error(
      `Could not find the build directory: ${distPath}, make sure to build the client first`
    );
  }
  app.use(express.static(distPath));
  app.use("*", (_req, res) => {
    res.sendFile(path2.resolve(distPath, "index.html"));
  });
}

// server/_core/index.ts
function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.listen(port, () => {
      server.close(() => resolve(true));
    });
    server.on("error", () => resolve(false));
  });
}
async function findAvailablePort(startPort = 3e3) {
  for (let port = startPort; port < startPort + 20; port++) {
    if (await isPortAvailable(port)) {
      return port;
    }
  }
  throw new Error(`No available port found starting from ${startPort}`);
}
async function startServer() {
  const app = express2();
  const server = createServer(app);
  app.use(express2.json({ limit: "50mb" }));
  app.use(express2.urlencoded({ limit: "50mb", extended: true }));
  registerStorageProxy(app);
  registerOAuthRoutes(app);
  app.use(
    "/api/trpc",
    createExpressMiddleware({
      router: appRouter,
      createContext
    })
  );
  if (process.env.NODE_ENV === "development") {
    await setupVite(app, server);
  } else {
    serveStatic(app);
  }
  const preferredPort = parseInt(process.env.PORT || "3000");
  const port = await findAvailablePort(preferredPort);
  if (port !== preferredPort) {
    console.log(`Port ${preferredPort} is busy, using port ${port} instead`);
  }
  server.listen(port, () => {
    console.log(`Server running on http://localhost:${port}/`);
  });
}
startServer().catch(console.error);
