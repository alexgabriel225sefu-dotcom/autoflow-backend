import type {
  BrokerSymbol, CtraderStatus, Execution, MinLotRead, RuleDoc, StrategyPreset,
  SymbolsRead,
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

/** The class names a client reads. A class not named here is shown under the
 *  server's own id, capitalised, so the list never hides one it has not heard of. */
export const CLASS_LABELS: Record<string, string> = {
  forex: "Forex", metal: "Metals", forex_cross: "Forex crosses",
  index: "Indices", stock: "Stocks", other: "Other",
};

/** How many rows are drawn at once. A broker lists hundreds or thousands. */
export const ROW_LIMIT = 80;

export type SymbolView = {
  /** Where the list came from: the broker's own, or the engine's fallback. */
  source: "broker" | "engine";
  rows: BrokerSymbol[];
  /** Matches before the row limit, so "showing 80 of 412" can be said. */
  matches: number;
  /** Everything the broker lists, and how much of it the engine cannot trade yet. */
  total: number;
  unsupported: number;
  classes: { id: string; label: string; count: number }[];
};

/**
 * The instrument list the Market block draws.
 *
 * The broker's own list when it was read, with every entry shown (the ones the
 * engine cannot trade yet are marked, not hidden). When the read did not
 * succeed the fallback is the engine's own allowlist and the page says so: an
 * empty menu would read as "your broker offers nothing".
 *
 * With no search and "show all" off, only what can be traded is listed, so a
 * client is not scrolling a thousand disabled stocks to find EUR/USD. A search
 * always looks across everything, because "AAPL" typed in should find AAPL and
 * say why it is not available yet.
 */
export function symbolView(
  read: SymbolsRead | null, query: string, cls: string, showAll: boolean,
): SymbolView {
  const fromBroker = !!read && read.status === "ok" && Array.isArray(read.symbols);
  const all: BrokerSymbol[] = fromBroker
    ? (read!.symbols as BrokerSymbol[])
    : SYMBOLS.map((s) => ({
        id: s.id, class: s.group === "Metals" ? "metal" : "forex",
        tradeable: true, reason: null,
      }));
  const q = query.trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
  const counts = new Map<string, number>();
  for (const s of all) counts.set(s.class, (counts.get(s.class) ?? 0) + 1);
  const matching = all.filter((s) =>
    (cls === "all" || s.class === cls)
    && (q === "" || s.id.includes(q))
    && (showAll || q !== "" || s.tradeable));
  return {
    source: fromBroker ? "broker" : "engine",
    rows: matching.slice(0, ROW_LIMIT),
    matches: matching.length,
    total: all.length,
    unsupported: all.filter((s) => !s.tradeable).length,
    classes: [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([id, count]) => ({ id, label: CLASS_LABELS[id] ?? id.charAt(0).toUpperCase() + id.slice(1), count })),
  };
}

/** A method the client built from conditions, loaded from their own rule. */
export type CustomMethod = {
  ruleDocId: string;
  name: string;
  entry: unknown;
  exit: unknown;
  sides: string;
};

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
  /** One of the engine's ready-made strategies, or null. */
  strategy: StrategyPreset | null;
  /** The client's own method (entry and exit conditions), or null. Exactly
   *  one of `strategy` and `custom` is set once a method is chosen. */
  custom: CustomMethod | null;
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
  symbol: "", timeframe: "1h", strategy: null, custom: null,
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

/**
 * The read that asks whether the broker's minimum order size would risk more
 * than the chosen percentage. Null until there is something to ask: an
 * instrument, a timeframe and a risk that is a usable number.
 */
export function minLotPath(c: Pick<TradeChoice, "symbol" | "timeframe" | "riskPercent">): string | null {
  const risk = num(c.riskPercent);
  if (!c.symbol || !c.timeframe || risk === null || risk <= 0 || risk > 100) return null;
  const q = new URLSearchParams({
    symbol: c.symbol, timeframe: c.timeframe, riskPercent: String(risk),
  });
  return `trade/min-lot?${q.toString()}`;
}

const usd = (n: number) => `$${n.toFixed(2)}`;

/**
 * The warning shown under Risk, or null when there is nothing to warn about.
 *
 * It is shown only when the server says the minimum size exceeds the chosen
 * risk, and it says so as an estimate. A read that did not answer produces a
 * quiet "could not check" and never a reassurance: silence would read as
 * "this is fine", which is a claim nobody made.
 */
export function minLotNotice(
  r: MinLotRead | null | undefined,
  asked?: Pick<TradeChoice, "symbol" | "timeframe" | "riskPercent">,
): { tone: "warn" | "muted"; text: string } | null {
  if (!r) return null;
  if (r.status === "unavailable") {
    return { tone: "muted", text: "Could not check the broker's minimum size right now." };
  }
  const m = r.minLot;
  if (r.status !== "ok" || !m || !m.exceeds) return null;
  // An answer for a different instrument, timeframe or risk than is chosen now
  // is a stale one: the choice changed while it was on its way. Showing it
  // would warn about something the client is no longer looking at.
  if (asked) {
    const want = num(asked.riskPercent);
    // The server rounds the percentage to two places.
    if (m.symbol !== asked.symbol || m.timeframe !== asked.timeframe
        || want === null || Math.abs(m.targetPct - want) > 0.006) return null;
  }
  return {
    tone: "warn",
    text:
      `The broker's smallest order for ${m.symbol} is ${m.minUnits} ${m.unitLabel}. ` +
      `With a typical stop (${m.basis}) that risks about ${usd(m.riskUsd)} ` +
      `(${m.riskPct}% of the account), more than the ${usd(m.targetUsd)} ` +
      `(${m.targetPct}%) you chose. An estimate: a rule with its own stop will differ. ` +
      `The trade is still sized at the minimum, and the day's loss limit counts what is left.`,
  };
}

/** What is still to choose, in the order the page asks for it. Empty = ready. */
export function missingChoices(c: TradeChoice): string[] {
  const out: string[] = [];
  if (!c.symbol) out.push("an instrument");
  if (!c.strategy && !c.custom) out.push("a strategy or a method of your own");
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
  if (!c.strategy && !c.custom) throw new Error("a strategy or method is required");
  const draft = {
    ...BLANK,
    name: `${c.strategy ? c.strategy.label : c.custom!.name} · ${c.symbol}`,
    symbols: c.symbol,
    timeframe: c.timeframe,
    automationLevel: c.level,
    sizingMode: "risk_percent",
    riskPercent: c.riskPercent.trim(),
    maxDailyLossPercent: c.dailyLossPercent.trim(),
  };
  if (c.strategy) return presetRuleBody(toDoc(draft), c.strategy.id);
  // The client's own method: its entry and exit conditions and the sides it
  // trades, written over the shared terms. No `strategy` field, so the rule
  // runs from the conditions exactly as the builder's own rules do.
  const m = c.custom!;
  return {
    ...toDoc(draft),
    sides: m.sides,
    entry: m.entry,
    exit: m.exit,
  } as Partial<RuleDoc>;
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
