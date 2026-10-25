import type {
  CtraderStatus, Execution, RuleDoc, StrategyPreset,
} from "@/lib/api";
import { BLANK, toDoc } from "@/components/app/rule-form";
import { presetRuleBody } from "../rules/new/strategy/catalog";

/**
 * The decisions behind the Trade page, kept out of the component so they can
 * be tested without a DOM, a session or an API.
 *
 * THE PRODUCT IN ONE SENTENCE
 *
 * A client does not write rules. They pick an instrument, pick one of the
 * engine's own strategies, say how much they are willing to risk, and start.
 * Everything below is the arithmetic and the bookkeeping of that, and none of
 * it invents a fact: the strategies and what they refuse come from the server,
 * the account and the live gate come from the server, and the money figures
 * are labelled as an estimate from a number the client typed.
 */

/**
 * What this platform trades: forex with a USD leg, and metals. The same
 * allowlist the server enforces (`forex.is_tradeable`), written out as a menu.
 *
 * INDICES ARE NOT HERE ON PURPOSE. They need per-exchange trading calendars the
 * engine does not have, and offering one would be a choice the server then
 * refuses far from where the client made it. If the engine gains them, this
 * list is the one place that needs to change.
 */
export const SYMBOLS = [
  { id: "EURUSD", label: "EUR/USD", group: "Forex" },
  { id: "GBPUSD", label: "GBP/USD", group: "Forex" },
  { id: "USDJPY", label: "USD/JPY", group: "Forex" },
  { id: "USDCHF", label: "USD/CHF", group: "Forex" },
  { id: "AUDUSD", label: "AUD/USD", group: "Forex" },
  { id: "USDCAD", label: "USD/CAD", group: "Forex" },
  { id: "NZDUSD", label: "NZD/USD", group: "Forex" },
  { id: "XAUUSD", label: "Gold", group: "Metals" },
  { id: "XAGUSD", label: "Silver", group: "Metals" },
] as const;

export const TIMEFRAME_CHOICES = ["15m", "1h", "4h", "1d"] as const;

/** Risk per trade, as quick picks. Anything else is typed. */
export const RISK_PICKS = ["0.25", "0.5", "1"] as const;

/** The platform's own ceilings, shown so a choice above them is not a surprise.
 *  The server is what enforces them; these only explain. */
export const LIVE_RISK_CAP = 1;
export const DAILY_LOSS_CEILING = 4;

export type TradeChoice = {
  symbol: string;
  timeframe: string;
  strategy: StrategyPreset | null;
  /** Percent of balance risked on one trade, as typed. */
  riskPercent: string;
  /** Percent of the day's opening balance at which the day stops. */
  dailyLossPercent: string;
  /** signals | approval | full, or "" while nothing is chosen. */
  level: string;
  /** Optional, typed by the client, used ONLY for the estimate. */
  accountSize: string;
};

export const EMPTY_CHOICE: TradeChoice = {
  symbol: "", timeframe: "1h", strategy: null,
  riskPercent: "1", dailyLossPercent: "2", level: "", accountSize: "",
};

const num = (v: string): number | null => {
  const t = (v ?? "").trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};

/** Round to cents. Money is shown to the cent and never beyond. */
const cents = (n: number) => Math.round(n * 100) / 100;

/**
 * What the choices could cost, in money.
 *
 * AN ESTIMATE FROM WHAT THE CLIENT TYPED. The platform does not hand the
 * browser the broker balance, so there is no real balance to multiply. The
 * figure is "the most one trade is sized to lose" and "the day's stop", both
 * of which are limits, never a forecast of anything. Null when the size or the
 * percentage is not a usable number, so the screen shows a dash and not zero.
 */
export function riskAmounts(c: Pick<TradeChoice,
  "accountSize" | "riskPercent" | "dailyLossPercent">) {
  const size = num(c.accountSize);
  const risk = num(c.riskPercent);
  const day = num(c.dailyLossPercent);
  const ok = size !== null && size > 0;
  return {
    perTrade: ok && risk !== null && risk > 0 ? cents(size * risk / 100) : null,
    perDay: ok && day !== null && day > 0 ? cents(size * day / 100) : null,
  };
}

/** What is still to choose, in the order the page asks for it. Empty = ready. */
export function missingChoices(c: TradeChoice): string[] {
  const out: string[] = [];
  if (!c.symbol) out.push("an instrument");
  if (!c.strategy) out.push("a strategy");
  const risk = num(c.riskPercent);
  if (risk === null || risk <= 0 || risk > 100) out.push("a risk per trade");
  const day = num(c.dailyLossPercent);
  if (c.dailyLossPercent.trim() !== "" && (day === null || day <= 0 || day > 100)) {
    out.push("a valid daily loss limit");
  }
  if (!c.level) out.push("who acts on a setup");
  return out;
}

/**
 * The document the server is sent. Starts from the rule builder's own BLANK
 * so a field this page does not ask about is the same default the builder
 * would have written, and then writes the choices over it. The strategy
 * decides entries and exits, so the conditions are emptied (`presetRuleBody`).
 */
export function tradeBody(c: TradeChoice): Partial<RuleDoc> {
  if (!c.strategy) throw new Error("a strategy is required");
  const draft = {
    ...BLANK,
    name: `${c.strategy.label} · ${c.symbol}`,
    symbols: c.symbol,
    timeframe: c.timeframe,
    automationLevel: c.level,
    sizingMode: "risk_percent",
    riskPercent: c.riskPercent.trim(),
    maxDailyLossPercent: c.dailyLossPercent.trim(),
  };
  return presetRuleBody(toDoc(draft), c.strategy.id);
}

export type StartState =
  | { kind: "connect"; label: string; reason: string }
  | { kind: "choose_account"; label: string; reason: string }
  | { kind: "demo"; label: string; reason: null; accountId: string }
  | { kind: "live"; label: string; reason: null; accountId: string }
  | { kind: "live_closed"; label: string; reason: string; href: string };

/**
 * What the Start button is allowed to be, from the server's answers alone.
 *
 * Demo starts. Live starts only when the SERVER says this client can automate
 * on it; otherwise the button becomes the next step towards live (request
 * access, or waiting for approval) and starts nothing. The browser never
 * decides that a live account is usable.
 */
export function startState(input: {
  status: CtraderStatus | null;
  execution: Execution | null;
}): StartState {
  const { status, execution } = input;
  if (!status || !status.connected || status.accounts.length === 0) {
    return { kind: "connect", label: "Connect cTrader",
             reason: "Connect a cTrader account to run a strategy on it." };
  }
  const sel = status.selected;
  if (!sel) {
    return { kind: "choose_account", label: "Choose an account",
             reason: "Pick the account this should run on." };
  }
  const id = String(sel.ctid);
  if (sel.mode === "demo") {
    return { kind: "demo", label: "Start on demo", reason: null, accountId: id };
  }
  if (execution?.canAutomate) {
    return { kind: "live", label: "Start on live", reason: null, accountId: id };
  }
  const req = execution?.liveGate?.request?.status;
  if (req === "pending") {
    return { kind: "live_closed", label: "Awaiting approval", href: "/live",
             reason: "Your request for live access is waiting for approval." };
  }
  if (execution?.liveGate?.status === "unknown") {
    return { kind: "live_closed", label: "Live status unknown", href: "/live",
             reason: execution.liveGate.summary
               || "The live status could not be read, so nothing starts." };
  }
  return { kind: "live_closed", label: "Request live access", href: "/live",
           reason: execution?.liveGate?.summary
             || execution?.message
             || "Live access is not open on this account yet." };
}
