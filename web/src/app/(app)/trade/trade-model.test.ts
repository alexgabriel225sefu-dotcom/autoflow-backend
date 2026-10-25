import { describe, expect, it } from "vitest";
import type { CtraderStatus, Execution, StrategyPreset } from "@/lib/api";
import {
  EMPTY_CHOICE, missingChoices, riskAmounts, startState, SYMBOLS, tradeBody,
  type TradeChoice,
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
      .toEqual(["an instrument", "a strategy", "who acts on a setup"]);
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
  it("lets the daily loss be empty (the account's own applies) but not nonsense", () => {
    expect(missingChoices({ ...READY, dailyLossPercent: "" })).toEqual([]);
    expect(missingChoices({ ...READY, dailyLossPercent: "0" }))
      .toContain("a valid daily loss limit");
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
