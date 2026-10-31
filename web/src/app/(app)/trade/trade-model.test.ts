import { describe, expect, it } from "vitest";
import type { CtraderStatus, Execution, MinLot, MinLotRead, StrategyPreset } from "@/lib/api";
import {
  EMPTY_CHOICE, minLotNotice, minLotPath, missingChoices, riskAmounts, ROW_LIMIT,
  startState, SYMBOLS, symbolView, tradeBody, type TradeChoice,
} from "./trade-model";

const STRAT: StrategyPreset = {
  id: "trend", label: "Trend follower", version: "1", family: "trend",
  what: "w", decides: "d", refuses: "r", source: "s",
};
type Body = {
  symbols: string[]; timeframe: string; strategy: string; automationLevel: string;
  sizing: unknown; name: string;
  limits: { maxDailyLossPercent: number | null; maxOpenPositions: number };
  entry: { conditions: unknown[] };
};
const READY: TradeChoice = {
  ...EMPTY_CHOICE, symbol: "EURUSD", strategy: STRAT, level: "approval",
  capitalAllocated: "1000", account: "demo",
};
const status = (over: Partial<CtraderStatus>): CtraderStatus => ({
  connected: true, accounts: [{ ctid: 7, mode: "demo" }],
  selected: { ctid: 7, mode: "demo" }, liveAllowed: false, ...over,
});
const exec = (over: Record<string, unknown>) =>
  ({ canAutomate: false, message: null, ...over }) as unknown as Execution;

describe("the instrument menu", () => {
  it("offers only what the engine trades: forex with a USD leg, and metals", () => {
    for (const s of SYMBOLS) {
      expect(s.id.length).toBe(6);
      expect(s.id.includes("USD") || s.group === "Metals").toBe(true);
    }
  });
  it("offers no index, because the engine has no calendars for one", () => {
    const ids = SYMBOLS.map((s) => s.id as string);
    for (const idx of ["US30", "NAS100", "SPX500", "GER40"]) {
      expect(ids).not.toContain(idx);
    }
  });
});

describe("riskAmounts", () => {
  it("is money from the typed size, to the cent", () => {
    expect(riskAmounts({ accountSize: "10000", riskPercent: "1", dailyLossPercent: "2" }))
      .toEqual({ perTrade: 100, perDay: 200 });
    expect(riskAmounts({ accountSize: "333.33", riskPercent: "0.25", dailyLossPercent: "" }))
      .toEqual({ perTrade: 0.83, perDay: null });
  });
  it("is null, never zero, when it cannot be worked out", () => {
    expect(riskAmounts({ accountSize: "", riskPercent: "1", dailyLossPercent: "2" }))
      .toEqual({ perTrade: null, perDay: null });
    expect(riskAmounts({ accountSize: "abc", riskPercent: "1", dailyLossPercent: "2" }).perTrade)
      .toBeNull();
    expect(riskAmounts({ accountSize: "-5", riskPercent: "1", dailyLossPercent: "2" }).perTrade)
      .toBeNull();
  });
});

describe("missingChoices", () => {
  it("asks for the choices nobody should make for the client, in order", () => {
    expect(missingChoices(EMPTY_CHOICE))
      .toEqual([
        "an instrument", "a strategy or a method of your own",
        "capital to allocate", "who acts on a setup",
      ]);
  });
  it("is empty only when everything is chosen", () => {
    expect(missingChoices(READY)).toEqual([]);
  });
  it("refuses a risk that is not a usable number", () => {
    for (const bad of ["", "0", "-1", "abc", "101"]) {
      expect(missingChoices({ ...READY, riskPercent: bad }), bad)
        .toContain("a risk per trade");
    }
  });
  it("requires a daily loss inside the platform ceiling", () => {
    expect(missingChoices({ ...READY, dailyLossPercent: "" }))
      .toContain("a valid daily loss limit");
    expect(missingChoices({ ...READY, dailyLossPercent: "0" }))
      .toContain("a valid daily loss limit");
    expect(missingChoices({ ...READY, dailyLossPercent: "5" }))
      .toContain("a valid daily loss limit");
    expect(missingChoices({ ...READY, dailyLossPercent: "2" })).toEqual([]);
  });
});

describe("tradeBody", () => {
  it("writes the choices over the builder's own defaults", () => {
    const b = tradeBody({ ...READY, symbol: "XAUUSD", timeframe: "4h",
      riskPercent: "0.5", dailyLossPercent: "3" }) as unknown as Body;
    expect(b.symbols).toEqual(["XAUUSD"]);
    expect(b.timeframe).toBe("4h");
    expect(b.strategy).toBe("trend");
    expect(b.automationLevel).toBe("approval");
    expect(b.sizing).toEqual({ mode: "risk_percent", riskPercent: 0.5, fixedVolume: null });
    expect(b.limits.maxDailyLossPercent).toBe(3);
    expect(b.limits.maxOpenPositions).toBe(1);
    expect(b.entry.conditions).toEqual([]);
    expect(b.name).toBe("Trend follower · XAUUSD");
  });
  it("sends an empty daily loss as null, so the account's own limit stays", () => {
    const b = tradeBody({ ...READY, dailyLossPercent: "" }) as unknown as Body;
    expect(b.limits.maxDailyLossPercent).toBeNull();
  });
  it("refuses to build without a strategy", () => {
    expect(() => tradeBody({ ...READY, strategy: null })).toThrow();
  });
});

describe("startState", () => {
  it("connect first when there is no connection", () => {
    expect(startState({ status: null, execution: null }).kind).toBe("connect");
    expect(startState({ status: status({ connected: false }), execution: null }).kind)
      .toBe("connect");
    expect(startState({ status: status({ accounts: [] }), execution: null }).kind)
      .toBe("connect");
  });
  it("choose an account when none is selected", () => {
    expect(startState({ status: status({ selected: null }), execution: null }).kind)
      .toBe("choose_account");
  });
  it("a demo account starts", () => {
    const s = startState({ status: status({}), execution: exec({}) });
    expect(s).toMatchObject({ kind: "demo", label: "Start on demo", accountId: "7" });
  });
  const liveSel = status({ selected: { ctid: 9, mode: "live" } });
  it("a live account starts ONLY when the server says it can automate", () => {
    expect(startState({ status: liveSel, execution: exec({ canAutomate: true }) }).kind)
      .toBe("live");
    expect(startState({ status: liveSel, execution: exec({ canAutomate: false }) }).kind)
      .toBe("live_closed");
    expect(startState({ status: liveSel, execution: null }).kind).toBe("live_closed");
  });
  it("a closed live account says what the next step is", () => {
    expect(startState({ status: liveSel, execution: exec({
      liveGate: { request: { status: "pending" }, status: "closed", summary: "s" } }) }))
      .toMatchObject({ kind: "live_closed", label: "Awaiting approval", href: "/live" });
    expect(startState({ status: liveSel, execution: exec({
      liveGate: { request: { status: "none" }, status: "closed", summary: "Terms not accepted" } }) }))
      .toMatchObject({ label: "Request live access", reason: "Terms not accepted" });
  });
  it("an unreadable live status is shown as unknown, never as closed or open", () => {
    expect(startState({ status: liveSel, execution: exec({
      liveGate: { request: { status: "none" }, status: "unknown", summary: "" } }) }))
      .toMatchObject({ label: "Live status unknown" });
  });
});

describe("symbolView", () => {
  const read = (symbols: { id: string; class: string; tradeable: boolean }[]) => ({
    connected: true, status: "ok", accountId: 7, mode: "demo",
    symbols: symbols.map((s) => ({ ...s, reason: s.tradeable ? null : "why not" })),
  });
  const MIX = read([
    { id: "EURUSD", class: "forex", tradeable: true },
    { id: "XAUUSD", class: "metal", tradeable: true },
    { id: "GBPJPY", class: "forex_cross", tradeable: false },
    { id: "US30", class: "index", tradeable: false },
    { id: "AAPL", class: "stock", tradeable: false },
  ]);

  it("lists what can be traded first and hides nothing in the counts", () => {
    const v = symbolView(MIX, "", "all", false);
    expect(v.source).toBe("broker");
    expect(v.rows.map((r) => r.id)).toEqual(["EURUSD", "XAUUSD"]);
    expect(v.total).toBe(5);
    expect(v.unsupported).toBe(3);
  });
  it("shows the unsupported ones, with their reason, when asked", () => {
    const v = symbolView(MIX, "", "all", true);
    expect(v.rows.map((r) => r.id)).toEqual(["EURUSD", "XAUUSD", "GBPJPY", "US30", "AAPL"]);
    expect(v.rows.find((r) => r.id === "US30")).toMatchObject({ tradeable: false, reason: "why not" });
  });
  it("a search looks across everything, so AAPL is found and explained", () => {
    const v = symbolView(MIX, "aapl", "all", false);
    expect(v.rows.map((r) => r.id)).toEqual(["AAPL"]);
    expect(v.rows[0].tradeable).toBe(false);
  });
  it("a search ignores slashes and case", () => {
    expect(symbolView(MIX, "eur/usd", "all", false).rows.map((r) => r.id)).toEqual(["EURUSD"]);
  });
  it("filters by class and counts each class", () => {
    const v = symbolView(MIX, "", "metal", false);
    expect(v.rows.map((r) => r.id)).toEqual(["XAUUSD"]);
    expect(v.classes.find((k) => k.id === "forex_cross")).toMatchObject({ label: "Forex crosses", count: 1 });
  });
  it("caps what is drawn and says how many matched", () => {
    const many = read(Array.from({ length: ROW_LIMIT + 40 }, (_, i) => (
      { id: `SYM${i}`, class: "forex", tradeable: true })));
    const v = symbolView(many, "", "all", false);
    expect(v.rows.length).toBe(ROW_LIMIT);
    expect(v.matches).toBe(ROW_LIMIT + 40);
  });
  it("falls back to the engine's own list when the broker was not read, and says so", () => {
    for (const bad of [null, { connected: true, status: "unavailable" },
      { connected: false, status: "disconnected" }, { connected: true, status: "ok" }]) {
      const v = symbolView(bad as never, "", "all", false);
      expect(v.source).toBe("engine");
      expect(v.rows.length).toBe(SYMBOLS.length);
      expect(v.rows.every((r) => r.tradeable)).toBe(true);
    }
  });
});

describe("a method of your own", () => {
  const CUSTOM = { ruleDocId: "m1", name: "My RSI dip",
    entry: { combine: "AND", conditions: [{ id: "rsi" }] },
    exit: { combine: "OR", conditions: [] }, sides: "BUY" };
  const MINE: TradeChoice = {
    ...EMPTY_CHOICE, symbol: "XAUUSD", level: "approval", custom: CUSTOM,
    capitalAllocated: "1000", account: "demo",
  };
  it("counts as a chosen method", () => {
    expect(missingChoices(MINE)).toEqual([]);
  });
  it("is built from the client's own conditions, with no strategy field", () => {
    const b = tradeBody(MINE) as unknown as Record<string, unknown>;
    expect(b.strategy).toBeUndefined();
    expect(b.entry).toEqual(CUSTOM.entry);
    expect(b.exit).toEqual(CUSTOM.exit);
    expect(b.sides).toBe("BUY");
    expect(b.name).toBe("My RSI dip · XAUUSD");
    expect(b.symbols).toEqual(["XAUUSD"]);
  });
});

describe("the broker's minimum size against the chosen risk", () => {
  const GOLD: TradeChoice = { ...EMPTY_CHOICE, symbol: "XAUUSD", timeframe: "1h", riskPercent: "1" };
  const lot = (over: Partial<MinLot> = {}): MinLot => ({
    symbol: "XAUUSD", timeframe: "1h", minUnits: 1, unitLabel: "oz", units: 1,
    stopDistance: 100, targetUsd: 38.17, targetPct: 1, riskUsd: 97.4, riskPct: 2.55,
    exceeds: true, basis: "2.5 x ATR(14) on the last bars", ...over,
  });
  const read = (over: Partial<MinLotRead> = {}): MinLotRead =>
    ({ connected: true, status: "ok", minLot: lot(), ...over });

  it("asks only once there is an instrument, a timeframe and a usable risk", () => {
    expect(minLotPath(GOLD)).toBe("trade/min-lot?symbol=XAUUSD&timeframe=1h&riskPercent=1");
    expect(minLotPath({ ...GOLD, symbol: "" })).toBeNull();
    expect(minLotPath({ ...GOLD, riskPercent: "" })).toBeNull();
    expect(minLotPath({ ...GOLD, riskPercent: "0" })).toBeNull();
    expect(minLotPath({ ...GOLD, riskPercent: "101" })).toBeNull();
    expect(minLotPath({ ...GOLD, riskPercent: "abc" })).toBeNull();
  });

  it("warns, naming the minimum, the risk it implies and the risk chosen", () => {
    const n = minLotNotice(read(), GOLD)!;
    expect(n.tone).toBe("warn");
    expect(n.text).toContain("1 oz");
    expect(n.text).toContain("$97.40");
    expect(n.text).toContain("2.55%");
    expect(n.text).toContain("$38.17");
    expect(n.text).toContain("(1%)");
  });

  it("says it is an estimate and names its basis", () => {
    const t = minLotNotice(read(), GOLD)!.text;
    expect(t).toMatch(/estimate/i);
    expect(t).toContain("2.5 x ATR");
  });

  it("is silent when the minimum fits inside the chosen risk", () => {
    expect(minLotNotice(read({ minLot: lot({ exceeds: false, riskUsd: 36, riskPct: 0.94 }) }), GOLD)).toBeNull();
  });

  it("never reassures when the broker could not be asked", () => {
    const n = minLotNotice({ connected: true, status: "unavailable", reason: "x" }, GOLD)!;
    expect(n.tone).toBe("muted");
    expect(n.text).toMatch(/could not check/i);
    expect(minLotNotice({ connected: false, status: "not_connected" } as MinLotRead, GOLD)).toBeNull();
    expect(minLotNotice(null, GOLD)).toBeNull();
  });

  it("drops an answer that belongs to a choice the client has since changed", () => {
    expect(minLotNotice(read(), { ...GOLD, symbol: "XAGUSD" })).toBeNull();
    expect(minLotNotice(read(), { ...GOLD, timeframe: "15m" })).toBeNull();
    expect(minLotNotice(read(), { ...GOLD, riskPercent: "2" })).toBeNull();
    expect(minLotNotice(read(), { ...GOLD, riskPercent: "1.0" })).not.toBeNull();
  });
});
