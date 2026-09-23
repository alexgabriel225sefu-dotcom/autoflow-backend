/**
 * The one way this app talks to the Apex4Traders backend.
 *
 * WHY THE RESULT IS A DISCRIMINATED UNION
 *
 * Every call returns either {ok: true, data} or {ok: false, status, code,
 * message}. TypeScript then refuses to let a component read `data` without
 * first proving the call succeeded, which is the whole point: the failure
 * this shape prevents is a screen that renders a confident empty state over a
 * request that actually returned 503. "No open positions" and "we could not
 * reach your broker" look identical if the error path is allowed to fall
 * through to the success path, and only one of them is safe to believe.
 *
 * The backend already answers in this spirit — reads carry {connected,
 * status} and omit their data key unless status is "ok" — so the client's job
 * is to preserve that distinction, never to smooth it over.
 */
import { createClient } from "./supabase/client";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";

export type ApiError = {
  ok: false;
  status: number;
  code: string;
  message: string;
  problems?: string[];
  licenceState?: string;
  capability?: string;
  /** Present on RATE_LIMITED, so a retry can wait rather than hammer. */
  retryAfterSec?: number;
};

export type ApiResult<T> = { ok: true; data: T } | ApiError;

/** Codes the UI branches on rather than matching against English text. */
export const CODES = {
  AUTH_REQUIRED: "AUTH_REQUIRED",
  AUTH_UNAVAILABLE: "AUTH_UNAVAILABLE",
  LICENCE_REQUIRED: "LICENCE_REQUIRED",
  NOT_FOUND: "NOT_FOUND",
  UNSUPPORTED: "UNSUPPORTED",
  RULE_INVALID: "RULE_INVALID",
  INSUFFICIENT_DATA: "INSUFFICIENT_DATA",
  RATE_LIMITED: "RATE_LIMITED",
  NETWORK: "NETWORK",
} as const;

function fail(status: number, code: string, message: string, extra = {}): ApiError {
  return { ok: false, status, code, message, ...extra };
}

/**
 * The Supabase access token for the current session, or null.
 *
 * Read fresh on every call rather than cached in a module variable: a token
 * that refreshed in another tab must be the one we send, and a stale one
 * would log the client out of a session that is perfectly alive.
 */
async function bearer(): Promise<string | null> {
  try {
    const { data } = await createClient().auth.getSession();
    return data.session?.access_token ?? null;
  } catch {
    return null;
  }
}

export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<ApiResult<T>> {
  const token = await bearer();
  if (!token) {
    return fail(401, CODES.AUTH_REQUIRED, "Sign in to continue.");
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/${path.replace(/^\//, "")}`, {
      method: init.method ?? "GET",
      signal: init.signal,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      cache: "no-store",
    });
  } catch (e) {
    // A network failure is NOT an empty result. Reported as its own code so
    // no screen can mistake it for "you have nothing".
    return fail(0, CODES.NETWORK, e instanceof Error ? e.message : "Network error");
  }

  let payload: Record<string, unknown> = {};
  try {
    payload = (await res.json()) as Record<string, unknown>;
  } catch {
    if (!res.ok) return fail(res.status, "BAD_RESPONSE", `Server error (${res.status}).`);
  }

  if (!res.ok || payload.ok === false) {
    const err = (payload.error ?? {}) as Record<string, unknown>;
    return fail(
      res.status,
      String(err.code ?? "ERROR"),
      String(err.message ?? `Request failed (${res.status}).`),
      {
        problems: Array.isArray(err.problems) ? (err.problems as string[]) : undefined,
        licenceState: err.licenceState as string | undefined,
        capability: err.capability as string | undefined,
        retryAfterSec: typeof err.retryAfterSec === "number" ? err.retryAfterSec : undefined,
      },
    );
  }
  return { ok: true, data: payload as T };
}

/* ── the shapes the backend actually returns ─────────────────────────── */

export type Licence = {
  state: "none" | "active" | "expired" | "revoked";
  expiresAt: number | null;
  plan: string | null;
};
export type Me = { user: { userId: string; email: string | null; emailVerified: boolean }; licence: Licence };

export type CtAccount = { ctid: number | string; mode: "demo" | "live"; label?: string };
export type CtraderStatus = {
  connected: boolean;
  accounts: CtAccount[];
  selected: { ctid: number | string; mode: "demo" | "live" } | null;
  liveAllowed: boolean;
  connectedAt?: number;
  expiresAt?: number | null;
};

/** Reads that can be "we could not ask". `status` is never assumed. */
export type ReadState = "ok" | "not_connected" | "reauth_required" | "unavailable";
export type PositionsRead = {
  connected: boolean;
  status: ReadState;
  accountId?: number | string;
  mode?: "demo" | "live";
  reason?: string;
  positions?: Position[];
};
export type OrdersRead = Omit<PositionsRead, "positions"> & { orders?: Order[] };
export type Position = {
  symbol: string; side: "BUY" | "SELL"; units: number;
  entryPrice: number | null; stopLoss: number | null; takeProfit: number | null;
  positionId: number | string;
};
export type Order = {
  orderId: number | string; symbol: string; side: "BUY" | "SELL"; units: number;
  orderType: string | null; status: string | null;
  limitPrice: number | null; stopPrice: number | null;
};

export type Candle = { open: number; high: number; low: number; close: number; time?: number };
export type CandlesRead = Omit<PositionsRead, "positions"> & {
  candles?: Candle[]; symbol?: string; timeframe?: string;
  count?: number; requested?: number;
};

export type RuleSummary = {
  ruleDocId: string; name: string; state: "draft" | "active" | "paused" | "archived";
  version: number; symbols: string[]; timeframe: string; updatedAt: number;
};
export type RuleDoc = RuleSummary & Record<string, unknown>;

export type ConditionParam = {
  type: string; default: unknown; choices: string[] | null;
  min: number | null; max: number | null; required: boolean;
};
export type ConditionSpec = { id: string; doc: string; params: Record<string, ConditionParam> };

export type ConditionResult = { id: string; passed: boolean | null; detail: string };
export type Decision = {
  verdict: "BUY" | "SELL" | "CLOSE" | "HOLD" | "REJECT";
  reason: string; conditions: ConditionResult[];
  executable: boolean; refusalCode: string | null; confidence: number | null;
};
export type PreviewResult = { decision: Decision; executable: false; wouldTrade: boolean };

export type JournalEntry = {
  entryId: string; kind: string; status: string | null; ts: number;
  symbol: string | null; accountId: string | null; ruleDocId: string | null;
  decision?: Decision; error?: string | null; correlationId: string;
};
export type JournalPage = {
  status: "ok"; entries: JournalEntry[]; total: number;
  limit: number; offset: number; hasMore: boolean;
};

export type Notification = {
  id: string; type: string; level: "info" | "warning" | "critical";
  title: string; body: string; ts: number; readAt: number | null;
};
export type NotificationPage = {
  status: "ok"; notifications: Notification[]; total: number;
  unread: number; hasMore: boolean;
};

export type AutomationState = {
  state: "stopped" | "running" | "paused";
  ruleDocId: string | null; mode: "demo" | null; startedAt: number | null;
};
