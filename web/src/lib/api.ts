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
  /**
   * A keyed reference to one broker-link attempt, safe to display and to
   * quote. It identifies the attempt in the server logs and reveals neither
   * the nonce it derives from nor who made it — which is the point: the
   * alternative was asking people to photograph a screen that has their
   * session on it.
   */
  diagnosticId?: string;
  /**
   * Where to open a broker account under the referral programme, present ONLY
   * on an ACCOUNT_LIMIT refusal — the moment a client has just tried to add
   * another real-money account and is the one client actually asking.
   *
   * The url and the disclosure arrive TOGETHER and must be rendered together.
   * The server has no accessor that returns the url alone, for the same
   * reason: the arrangement pays the operator from the volume the client
   * trades, and a link shown without saying so is the version both a client
   * and a regulator object to.
   */
  brokerSignup?: { url: string; disclosure: string };
};

export type ApiResult<T> = { ok: true; data: T } | ApiError;

/** Codes the UI branches on rather than matching against English text. */
export const CODES = {
  AUTH_REQUIRED: "AUTH_REQUIRED",
  AUTH_UNAVAILABLE: "AUTH_UNAVAILABLE",
  /** The platform could not reach its store. Never means "you have none". */
  STORE_UNAVAILABLE: "STORE_UNAVAILABLE",
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
 * Both halves or neither. A payload carrying a url and no disclosure is
 * dropped rather than rendered — the server does not produce one, so if it
 * ever arrives something is wrong, and showing a bare referral link is the
 * one outcome worth refusing.
 */
function isBrokerSignup(v: unknown): v is { url: string; disclosure: string } {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  return typeof o.url === "string" && o.url.startsWith("https://")
    && typeof o.disclosure === "string" && o.disclosure.length > 0;
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

/**
 * A GET that carries no session, for the routes that need none.
 *
 * There are three of those on the API and only one a browser reads:
 * billing/offer, which a visitor on the pricing page has no session for. It
 * goes through the same response handling as `api`, so a failure arrives as
 * the same ApiError and no screen has to invent a second way to be unsure.
 *
 * Deliberately GET-only and deliberately separate, so "no token" stays a
 * decision made per call site rather than a fallback inside `api` that an
 * authenticated route could reach by accident.
 */
export async function publicApi<T>(
  path: string,
  init: { signal?: AbortSignal } = {},
): Promise<ApiResult<T>> {
  return request<T>(path, { signal: init.signal }, null);
}

export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<ApiResult<T>> {
  const token = await bearer();
  if (!token) {
    return fail(401, CODES.AUTH_REQUIRED, "Sign in to continue.");
  }
  return request<T>(path, init, token);
}

async function request<T>(
  path: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal },
  token: string | null,
): Promise<ApiResult<T>> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/${path.replace(/^\//, "")}`, {
      method: init.method ?? "GET",
      signal: init.signal,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
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
        diagnosticId: typeof err.diagnosticId === "string" ? err.diagnosticId : undefined,
        brokerSignup: isBrokerSignup(err.brokerSignup) ? err.brokerSignup : undefined,
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
/**
 * What this release charges for, for pages with no session to ask.
 *
 * A signed-in client gets this from the server, in `me.execution.planNotice`
 * — that is the copy of record. The landing and sign-up pages have no session
 * and cannot ask, so they use this constant, and content.test.ts pins it to
 * the Python that produces the other one. Two places is one more than ideal;
 * a visitor not being told whether signing up costs money is worse.
 */
export const PLAN_NOTICE =
  "Demo accounts are free for a 14-day trial. Real-money account access is " +
  "a paid plan, and live execution is not enabled in this release.";

/**
 * What the SERVER says this client may do. Not derived here.
 *
 * Reading a licence state and an account mode and combining them into a
 * verdict is a decision, and it is made once, in
 * apex/platform/entitlement.py. A second copy of that decision in the browser
 * would be a copy that can disagree — and the disagreement people notice is
 * the one where the UI offers a control the server then refuses.
 */
export type Execution = {
  accountMode: "demo" | "live" | "unknown";
  entitlement: "free_demo" | "paid_live";
  licenceState: Licence["state"];
  /** False in this release, from the server, every time. */
  liveExecutionEnabled: boolean;
  planNotice: string;
  canAutomate: boolean;
  /**
   * Whether this client may freeze a rule version. NOT the same permission as
   * canAutomate, and not derivable from the licence state by a component:
   * activation records terms, it does not trade, and the free tier is allowed
   * it. The rule page decided this for itself once and dead-ended every free
   * demo client — they could build a rule and never activate it.
   */
  canActivate: boolean;
  /** Why not, when canActivate is false. The server's words. */
  activationRefusal: string | null;
  /**
   * The plan on file: the free trial, the paid one, or none. The server
   * decides what these mean — `entitlement` is the answer to "has this client
   * paid for live", and it is NOT derivable from `plan` by a component.
   */
  plan: string;
  onTrial: boolean;
  /** Days remaining on the free trial, rounded up, or null when not on one. */
  trialDaysLeft: number | null;
  trialExpiresAt: number | null;
  /**
   * How many distinct real-money accounts this client may trade here. Demo
   * accounts are not limited. More than one requires their broker account to
   * be confirmed under the referral programme, which only the operator can
   * record — so a component must never offer to raise this itself.
   */
  accountAllowance: number;
  reason:
    | null
    | "NOT_CONNECTED"
    | "REAUTH_REQUIRED"
    | "LIVE_NOT_AVAILABLE"
    | "LICENCE_REVOKED"
    /** The free trial ran out. Different next step from NO_LICENCE. */
    | "TRIAL_EXPIRED"
    /** No trial on file at all — never started, or cleared. */
    | "NO_LICENCE"
    /**
     * Live IS open on this deployment, and this client's plan does not cover
     * it. Deliberately distinct from LIVE_NOT_AVAILABLE, which means nobody
     * can trade live here yet: the two have different next steps, and telling
     * a paying client the wrong one is a lie about what they bought.
     */
    | "LIVE_NOT_ENTITLED";
  message: string;
  /**
   * "LIVE" is real money. It is its own word rather than the ABSENCE of
   * "LIVE BLOCKED" — a client must never have to infer that they are trading
   * real money from a badge that stopped appearing.
   */
  badge: "DEMO" | "LIVE" | "LIVE BLOCKED" | "NOT CONNECTED" | "REAUTH REQUIRED";
};

export type Me = {
  user: { userId: string; email: string | null; emailVerified: boolean };
  licence: Licence;
  execution: Execution;
};

export type CtAccount = { ctid: number | string; mode: "demo" | "live"; label?: string };
export type CtraderStatus = {
  connected: boolean;
  accounts: CtAccount[];
  selected: { ctid: number | string; mode: "demo" | "live" } | null;
  liveAllowed: boolean;
  connectedAt?: number;
  expiresAt?: number | null;
  /**
   * How many real-money accounts this client may trade here, and where more
   * come from. Carried on the ACCOUNTS read only — that is the screen where
   * "how do I add another" is a question somebody is actually asking.
   *
   * `signup` arrives with its disclosure and never without it: the server has
   * no accessor returning the url alone, because the arrangement pays the
   * operator from the volume the client trades and a link shown without
   * saying so is the version both a client and a regulator object to.
   */
  accountPlan?: {
    realMoneyAllowance: number;
    realMoneyUsed: number;
    demoUnlimited: boolean;
    confirmed: boolean;
    signup: { url: string; disclosure: string } | null;
  };
};

/**
 * The offer, as the SERVER states it. Never assembled in the browser.
 *
 * `priceMinor` is in the currency's minor unit, which is what the payment
 * provider works in and therefore what billing.py keeps. Formatting happens
 * at the edge, in one place, so no screen rounds it differently.
 *
 * `checkoutEnabled` is both of the server's checkout gates, already combined.
 * A component must not decide this: payments are off in this release, and a
 * button that offers to take money when the server will refuse is the
 * dangerous direction to be wrong in.
 */
export type PublicOffer = {
  sku: string;
  plan: string;
  purchaseMode: string;
  priceMinor: number;
  currency: string;
  periodDays: number | null;
  checkoutEnabled: boolean;
};

/** What the waitlist route answers. It never returns the address. */
export type WaitlistResult = {
  status: "added" | "already";
  /** Present on a repeat call: whether it filled in a blank. */
  answered?: boolean;
};

/**
 * Ask to be told when access opens.
 *
 * POSTs without a session, because a visitor has none. Returns the same
 * ApiResult shape as everything else, so the form has one way to be unsure.
 */
export async function joinWaitlist(
  email: string,
  source: "landing" | "pricing" | "direct",
  answers?: { platform?: string; broker?: string },
): Promise<ApiResult<WaitlistResult>> {
  return request<WaitlistResult>(
    "waitlist",
    { method: "POST", body: { email, source, ...(answers ?? {}) } },
    null);
}

/** `priceMinor` + `currency` as the reader's locale would write them. */
export function formatOfferPrice(offer: PublicOffer, locale?: string): string {
  const code = (offer.currency || "usd").toUpperCase();
  const major = (offer.priceMinor ?? 0) / 100;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: code,
      // A whole-number price should not read as "$499.00" on a pricing card,
      // and a price with cents must not be silently rounded away.
      minimumFractionDigits: Number.isInteger(major) ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(major);
  } catch {
    // An unknown currency code must not take the page down with it.
    return `${major} ${code}`;
  }
}

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
export type DealsRead = Omit<PositionsRead, "positions"> & { deals?: ClosedTrade[] };
export type Position = {
  symbol: string; side: "BUY" | "SELL"; units: number;
  entryPrice: number | null; stopLoss: number | null; takeProfit: number | null;
  positionId: number | string;
  currentPrice?: number | null; quoteAgeSec?: number | null; quoteStale?: boolean;
  pnlPips?: number | null; pnlAccount?: number | null; pnlIsEstimate?: boolean;
  stopDistancePips?: number | null; targetDistancePips?: number | null;
  hasStop?: boolean; warning?: string; openTime?: number | null;
};
export type ClosePositionRead = {
  close: { status: "FILLED" | "PARTIAL" | "ALREADY_CLOSED"; sentence: string;
    remainingVolume?: number | null; positionId?: number | string };
  sentence: string;
};
export type ClosedTrade = {
  symbol: string | null; side: "BUY" | "SELL" | null; units: number | null;
  entry: number | null; exit: number | null; net: number | null;
  closedAt: number | null; positionId?: number | string;
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

/**
 * One of the engine's ready-made strategies, as the server describes it.
 *
 * `refuses` is the field that matters most on the screen, and it is a field
 * rather than a sentence folded into `what` for that reason: the useful half
 * of a trading strategy is the market it declines to trade, and five of
 * these decline nothing beyond "the setup is not there". A client has to be
 * able to read that before choosing.
 *
 * `label` and `version` are the strategy class's own, read from the engine's
 * registry. Nothing in this project keeps its own name for a strategy — a
 * second copy would drift the first time one is renamed.
 */
export type StrategyPreset = {
  id: string;
  label: string;
  version: string;
  family: string;
  what: string;
  decides: string;
  refuses: string;
  /** Where the description was read from, so a claim can be checked. */
  source: string;
};

/** A strategy the engine registers and this platform does not offer. */
export type WithheldStrategy = {
  id: string;
  label: string;
  reason: string;
  kind: "rule_builder" | "high_risk" | string;
};

export type StrategyCatalogue = {
  strategies: StrategyPreset[];
  withheld: WithheldStrategy[];
  /** The rule-builder strategy id, so no component writes the string itself. */
  ruleBuilderId: string;
  /** The RuleDoc field a chosen preset is written to. */
  presetField: string;
  /**
   * Registered strategies this release has no description for. Absent when
   * there are none, which is the normal case — a key that is always present
   * and almost always empty is a key the UI learns to ignore.
   */
  unclassified?: string[];
};

export type ConditionParam = {
  type: string; default: unknown; choices: string[] | null;
  min: number | null; max: number | null; required: boolean;
};
export type ConditionSpec = {
  id: string;
  doc: string;
  params: Record<string, ConditionParam>;
  /**
   * Whether this condition, with its own defaults, points at a SIDE.
   *
   * Six of the twelve do. The rest are filters — volatility, session,
   * weekday, spread, position count — which say WHEN to trade and never
   * which way. A rule whose `sides` is BOTH is refused with
   * DIRECTION_AMBIGUOUS unless a satisfied condition implies one, which is
   * why the builder opens with a directional condition rather than the
   * alphabetically first.
   *
   * Computed by the server, never re-derived here: a list of directional ids
   * in the browser would be a second copy of that fact, drifting the first
   * time a condition is added.
   */
  impliesDirection?: boolean;
};

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
  /** The market reading the entry was made against. A `signal` entry carries
   *  the price the setup qualified at, which is the one number a client needs
   *  to act on it themselves — at that level nothing else will. */
  snapshot?: { symbol?: string | null; price?: number | null } | null;
};
export type JournalPage = {
  status: "ok"; entries: JournalEntry[]; total: number;
  limit: number; offset: number; hasMore: boolean;
};

export type Notification = {
  id: string; type: string; level: "info" | "warning" | "critical";
  title: string; body: string; ts: number; readAt: number | null;
  /** Where to go to act on it, when there is somewhere. A signal points at
   *  the journal, which keeps the setup after this list has rotated past it. */
  link?: string | null;
};
export type NotificationPage = {
  status: "ok"; notifications: Notification[]; total: number;
  unread: number; hasMore: boolean;
};

/**
 * A setup the engine proposed and will NOT place until the client answers.
 *
 * Every optional field here is optional because the server refuses to invent
 * it. `price` and `reasoning` come from the engine's alert, which is a
 * separate write from the proposal itself, so they can genuinely be unknown —
 * `detailKnown` says which case this is, and the card shows "not recorded"
 * rather than an empty space that reads as nothing to say.
 *
 * `actionable` and `refusal` are the SERVER's verdict on whether approving
 * would be accepted. The browser disables a button from them rather than
 * deciding for itself what the rules are: a second copy of that decision
 * would be the one that let a client press Approve on a setup the backend
 * then refused.
 */
export type PendingApproval = {
  symbol: string;
  side: "BUY" | "SELL";
  price: number | null;
  confidence: number | null;
  reasoning: string | null;
  keyFactors: string[];
  detailKnown: boolean;
  proposedAt: number;
  ageSec: number;
  expiresAt: number;
  expiresInSec: number;
  expired: boolean;
  actionable: boolean;
  refusal: string | null;
};
export type ApprovalRead = {
  /** "ok" means we read the account. "unknown" means we could not. */
  status: "ok" | "unknown";
  approval?: PendingApproval | null;
  /** A proposal is stored and could not be read. It can only be dismissed. */
  unreadable?: boolean;
  reason?: string;
};
export type ApprovalResult = {
  status: "ok";
  /** "placed" — the order went through. "unknown" — the broker never said. */
  outcome?: "placed" | "unknown";
  order?: {
    symbol: string; side: string; price: number | null;
    units: number | null; stopLoss: number | null; takeProfit: number | null;
  } | null;
  detail?: string;
  rejected?: boolean;
  alreadyGone?: boolean;
};

export type AutomationState = {
  state: "stopped" | "running" | "paused";
  ruleDocId: string | null; mode: "demo" | null; startedAt: number | null;
  /** WHAT "RUNNING" MEANS, which the state on its own does not say.
   *
   *  The engine has three levels and they differ by whether a setup becomes
   *  an order. The status strip showed the same RUNNING for all three, so a
   *  client at Signals Only read it as "it is trading for me".
   *
   *  The label and the verdict are the SERVER's, never assembled here: which
   *  levels place orders is a decision about money, and a second copy of it
   *  in the browser would be free to drift from the one the loop obeys.
   *  Null when nothing is running — there is no level to report. */
  level?: "signals" | "approval" | "full" | null;
  levelLabel?: string | null;
  levelBlurb?: string | null;
  levelExecutes?: boolean | null;
  /** WHETHER STOPPING ALSO CLOSED WHAT WAS OPEN, which it does not.
   *
   *  §8.1 of the live-execution specification requires a stop to flatten or
   *  explicitly DECLINE to flatten, and say which. The server has always
   *  answered correctly — `flattened: false`, `flattenDeclined: true`, and a
   *  sentence saying the position stays at the broker with its stop and
   *  target — and this type did not carry the fields, so the browser threw
   *  the whole answer away and said "Automation is now stopped".
   *
   *  That is the most expensive silence in the product. A client with a
   *  losing position presses Stop, reads "stopped", and closes the tab. The
   *  position is still open at their broker. The only place the truth
   *  appeared was a notification on a page they were never sent to.
   *
   *  The sentence is the SERVER's. What a stop does to real exposure is not
   *  a thing to keep a second copy of in a browser. */
  flattened?: boolean;
  flattenDeclined?: boolean;
  flattenReason?: string | null;
};
