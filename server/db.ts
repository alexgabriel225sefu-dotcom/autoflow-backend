import { eq, desc } from "drizzle-orm";
import { drizzle } from "drizzle-orm/mysql2";
import { InsertUser, users, trades, alerts, botConfigs, dailySnapshots, paperTradingStates } from "../drizzle/schema";
import { ENV } from './_core/env';
import type { InsertTrade, InsertAlert, InsertBotConfig, InsertDailySnapshot, InsertPaperTradingState } from '../drizzle/schema';

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


