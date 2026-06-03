import { eq, desc } from "drizzle-orm";
import { drizzle } from "drizzle-orm/mysql2";
import { InsertUser, users, trades, alerts, botConfigs, dailySnapshots, paperTradingStates, subscriptions, tools, toolUsage, affiliates, referrals, courses, courseProgress, communityPosts, communityReplies } from "../drizzle/schema";
import { ENV } from './_core/env';
import type { InsertTrade, InsertAlert, InsertBotConfig, InsertDailySnapshot, InsertPaperTradingState, InsertSubscription, InsertTool, InsertToolUsage, InsertAffiliate, InsertReferral, InsertCourse, InsertCourseProgress, InsertCommunityPost, InsertCommunityReply } from '../drizzle/schema';

let _db: ReturnType<typeof drizzle> | null = null;

// Lazily create the drizzle instance so local tooling can run without a DB.
export async function getDb() {
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

export async function upsertUser(user: InsertUser): Promise<void> {
  if (!user.openId) {
    throw new Error("User openId is required for upsert");
  }

  const db = await getDb();
  if (!db) {
    console.warn("[Database] Cannot upsert user: database not available");
    return;
  }

  try {
    const values: InsertUser = {
      openId: user.openId,
    };
    const updateSet: Record<string, unknown> = {};

    const textFields = ["name", "email", "loginMethod"] as const;
    type TextField = (typeof textFields)[number];

    const assignNullable = (field: TextField) => {
      const value = user[field];
      if (value === undefined) return;
      const normalized = value ?? null;
      values[field] = normalized;
      updateSet[field] = normalized;
    };

    textFields.forEach(assignNullable);

    if (user.lastSignedIn !== undefined) {
      values.lastSignedIn = user.lastSignedIn;
      updateSet.lastSignedIn = user.lastSignedIn;
    }
    if (user.role !== undefined) {
      values.role = user.role;
      updateSet.role = user.role;
    } else if (user.openId === ENV.ownerOpenId) {
      values.role = 'admin';
      updateSet.role = 'admin';
    }

    if (!values.lastSignedIn) {
      values.lastSignedIn = new Date();
    }

    if (Object.keys(updateSet).length === 0) {
      updateSet.lastSignedIn = new Date();
    }

    await db.insert(users).values(values).onDuplicateKeyUpdate({
      set: updateSet,
    });
  } catch (error) {
    console.error("[Database] Failed to upsert user:", error);
    throw error;
  }
}

export async function getUserByOpenId(openId: string) {
  const db = await getDb();
  if (!db) {
    console.warn("[Database] Cannot get user: database not available");
    return undefined;
  }

  const result = await db.select().from(users).where(eq(users.openId, openId)).limit(1);

  return result.length > 0 ? result[0] : undefined;
}

// ─── Trade queries ──────────────────────────────────────────
export async function createTrade(userId: number, trade: InsertTrade) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db.insert(trades).values({
    ...trade,
    userId,
  });
  return result;
}

export async function getTradeHistory(userId: number, limit = 50) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db
    .select()
    .from(trades)
    .where(eq(trades.userId, userId))
    .orderBy(desc(trades.openedAt))
    .limit(limit);
  return result;
}

export async function updateTrade(tradeId: number, updates: Partial<InsertTrade>) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  await db.update(trades).set(updates).where(eq(trades.id, tradeId));
}

// ─── Alert queries ──────────────────────────────────────────
export async function createAlert(userId: number, alert: InsertAlert) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db.insert(alerts).values({
    ...alert,
    userId,
  });
  return result;
}

export async function getAlertHistory(userId: number, limit = 20) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db
    .select()
    .from(alerts)
    .where(eq(alerts.userId, userId))
    .orderBy(desc(alerts.sentAt))
    .limit(limit);
  return result;
}

// ─── Bot config queries ──────────────────────────────────────
export async function getBotConfig(userId: number) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db
    .select()
    .from(botConfigs)
    .where(eq(botConfigs.userId, userId))
    .limit(1);
  return result.length > 0 ? result[0] : null;
}

export async function upsertBotConfig(userId: number, config: Partial<InsertBotConfig>) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const existing = await getBotConfig(userId);
  if (existing) {
    await db.update(botConfigs).set(config).where(eq(botConfigs.userId, userId));
  } else {
    await db.insert(botConfigs).values({
      userId,
      ...config,
    } as InsertBotConfig);
  }
}

// ─── Daily snapshot queries ──────────────────────────────────
export async function getDailySnapshot(userId: number, date: string) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db
    .select()
    .from(dailySnapshots)
    .where(eq(dailySnapshots.userId, userId) && eq(dailySnapshots.date, date))
    .limit(1);
  return result.length > 0 ? result[0] : null;
}

export async function createDailySnapshot(userId: number, snapshot: InsertDailySnapshot) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db.insert(dailySnapshots).values({
    ...snapshot,
    userId,
  });
  return result;
}

export async function getDailySnapshots(userId: number, days = 30) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db
    .select()
    .from(dailySnapshots)
    .where(eq(dailySnapshots.userId, userId))
    .orderBy(desc(dailySnapshots.date))
    .limit(days);
  return result;
}

// ─── Paper trading state queries ────────────────────────────
export async function getPaperTradingState(userId: number) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db
    .select()
    .from(paperTradingStates)
    .where(eq(paperTradingStates.userId, userId))
    .limit(1);
  return result.length > 0 ? result[0] : null;
}

export async function upsertPaperTradingState(userId: number, state: Partial<InsertPaperTradingState>) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const existing = await getPaperTradingState(userId);
  if (existing) {
    await db.update(paperTradingStates).set(state).where(eq(paperTradingStates.userId, userId));
  } else {
    await db.insert(paperTradingStates).values({
      userId,
      ...state,
    } as InsertPaperTradingState);
  }
}

// ─── AICashSystem Subscription queries ──────────────────────
export async function getSubscription(userId: number) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db
    .select()
    .from(subscriptions)
    .where(eq(subscriptions.userId, userId))
    .limit(1);
  return result.length > 0 ? result[0] : null;
}

export async function upsertSubscription(userId: number, sub: Partial<InsertSubscription>) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const existing = await getSubscription(userId);
  if (existing) {
    await db.update(subscriptions).set(sub).where(eq(subscriptions.userId, userId));
  } else {
    await db.insert(subscriptions).values({
      userId,
      ...sub,
    } as InsertSubscription);
  }
}

// ─── AICashSystem Tool queries ──────────────────────────────
export async function getAllTools() {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  return await db.select().from(tools);
}

export async function getToolBySlug(slug: string) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db.select().from(tools).where(eq(tools.slug, slug)).limit(1);
  return result.length > 0 ? result[0] : null;
}

export async function createTool(tool: InsertTool) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  return await db.insert(tools).values(tool);
}

// ─── AICashSystem Tool Usage queries ────────────────────────
export async function getToolUsage(userId: number, toolId: number) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db
    .select()
    .from(toolUsage)
    .where(eq(toolUsage.userId, userId) && eq(toolUsage.toolId, toolId))
    .limit(1);
  return result.length > 0 ? result[0] : null;
}

export async function incrementToolUsage(userId: number, toolId: number) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const existing = await getToolUsage(userId, toolId);
  if (existing) {
    await db.update(toolUsage)
      .set({ usageCount: existing.usageCount + 1 })
      .where(eq(toolUsage.id, existing.id));
  } else {
    await db.insert(toolUsage).values({
      userId,
      toolId,
      usageCount: 1,
      resetDate: new Date(),
    } as InsertToolUsage);
  }
}

// ─── AICashSystem Affiliate queries ─────────────────────────
export async function getAffiliateByUserId(userId: number) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db
    .select()
    .from(affiliates)
    .where(eq(affiliates.userId, userId))
    .limit(1);
  return result.length > 0 ? result[0] : null;
}

export async function getAffiliateByCode(code: string) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db
    .select()
    .from(affiliates)
    .where(eq(affiliates.referralCode, code))
    .limit(1);
  return result.length > 0 ? result[0] : null;
}

export async function createAffiliate(userId: number, referralCode: string) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  return await db.insert(affiliates).values({
    userId,
    referralCode,
  } as InsertAffiliate);
}

// ─── AICashSystem Referral queries ─────────────────────────
export async function createReferral(affiliateId: number, customerId: number, tier: string, commissionAmount: string) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  return await db.insert(referrals).values({
    affiliateId,
    customerId,
    tier: tier as any,
    commissionAmount,
  } as InsertReferral);
}

export async function getReferralsByAffiliate(affiliateId: number) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  return await db
    .select()
    .from(referrals)
    .where(eq(referrals.affiliateId, affiliateId))
    .orderBy(desc(referrals.createdAt));
}

// ─── AICashSystem Course queries ────────────────────────────
export async function getAllCourses() {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  return await db.select().from(courses).orderBy(courses.order);
}

export async function getCourseBySlug(slug: string) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db.select().from(courses).where(eq(courses.slug, slug)).limit(1);
  return result.length > 0 ? result[0] : null;
}

export async function createCourse(course: InsertCourse) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  return await db.insert(courses).values(course);
}

// ─── AICashSystem Course Progress queries ──────────────────
export async function getCourseProgress(userId: number, courseId: number) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const result = await db
    .select()
    .from(courseProgress)
    .where(eq(courseProgress.userId, userId) && eq(courseProgress.courseId, courseId))
    .limit(1);
  return result.length > 0 ? result[0] : null;
}

export async function markCourseComplete(userId: number, courseId: number) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  const existing = await getCourseProgress(userId, courseId);
  if (existing) {
    await db.update(courseProgress)
      .set({ completed: 1, completedAt: new Date() })
      .where(eq(courseProgress.id, existing.id));
  } else {
    await db.insert(courseProgress).values({
      userId,
      courseId,
      completed: 1,
      completedAt: new Date(),
    } as InsertCourseProgress);
  }
}

// ─── AICashSystem Community queries ─────────────────────────
export async function createCommunityPost(userId: number, post: Omit<InsertCommunityPost, 'userId'>) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  return await db.insert(communityPosts).values({
    ...post,
    userId,
  } as InsertCommunityPost);
}

export async function getCommunityPosts(limit = 20) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  return await db
    .select()
    .from(communityPosts)
    .orderBy(desc(communityPosts.createdAt))
    .limit(limit);
}

export async function createCommunityReply(postId: number, userId: number, content: string) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  return await db.insert(communityReplies).values({
    postId,
    userId,
    content,
  } as InsertCommunityReply);
}

export async function getCommunityReplies(postId: number) {
  const db = await getDb();
  if (!db) throw new Error('Database not available');
  
  return await db
    .select()
    .from(communityReplies)
    .where(eq(communityReplies.postId, postId))
    .orderBy(desc(communityReplies.createdAt));
}

