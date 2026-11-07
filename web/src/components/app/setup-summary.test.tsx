import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SetupSummary, summaryTiles } from "./setup-summary";
import { EMPTY_CHOICE, type TradeChoice } from "@/app/(app)/trade/trade-model";

const choice: TradeChoice = {
  ...EMPTY_CHOICE, symbol: "EURUSD", timeframe: "M15", riskPercent: "0.5",
  dailyLossPercent: "2", account: "demo",
  custom: { ruleDocId: "r1", name: "My pullback", entry: {}, exit: {}, sides: "BOTH" } as TradeChoice["custom"],
};

describe("summaryTiles", () => {
  it("maps only what the page has", () => {
    const t = Object.fromEntries(summaryTiles(choice, { accountId: "123" }).map((x) => [x.key, x.value]));
    expect(t).toEqual({
      instrument: "EURUSD", timeframe: "M15", strategy: "My pullback (my method)",
      risk: "0.5%", dayStop: "2%", account: "#123", mode: "Demo",
    });
  });
  it("shows a dash for anything not chosen, never a made-up value", () => {
    const t = summaryTiles({ ...EMPTY_CHOICE, timeframe: "" }, {});
    for (const k of ["instrument", "timeframe", "strategy", "account", "mode"])
      expect(t.find((x) => x.key === k)?.value).toBe("—");
  });
  it("labels live as Live", () => {
    const t = summaryTiles({ ...choice, account: "live" }, { accountId: 9 });
    expect(t.find((x) => x.key === "mode")?.value).toBe("Live");
  });
});

describe("SetupSummary", () => {
  it("renders every tile and the start control it is given", () => {
    render(<SetupSummary choice={choice} accountId="123"><button>Start</button></SetupSummary>);
    for (const l of ["Instrument", "Timeframe", "Strategy", "Risk per trade",
      "Stop the day at", "Account", "Mode"]) expect(screen.getByText(l)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start" })).toBeTruthy();
  });
});
