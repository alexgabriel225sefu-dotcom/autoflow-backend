/**
 * The performance page formats the server's figures and invents none.
 *
 * What it must not do: show a missing number as 0, print an infinite profit
 * factor, present an unreadable journal as "no trades", or rank a group that
 * the server marked too thin to judge.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiResult, PerformanceRead } from "@/lib/api";

const paths: string[] = [];
let answer: ApiResult<unknown> = { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" } as ApiResult<unknown>;

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: vi.fn(async (path: string) => { paths.push(path); return answer; }) };
});

import PerformancePage from "./page";

const summary = (over: Record<string, unknown> = {}) => ({
  trades: 10, wins: 6, losses: 4, win_rate: 60, net: 123.45, profit_factor: 1.8,
  expectancy: 12.35, max_drawdown: 30, avg_win: 40, avg_loss: -28.5, best: 90, worst: -50,
  noLosses: false, r: null, ...over,
});
const group = (id: string, label: string, thin = false, over: Record<string, unknown> = {}) =>
  ({ ...summary({ trades: thin ? 2 : 8 }), id, label, thin, ...over });
const ok = (over: Partial<PerformanceRead> = {}) => ({
  ok: true, status: 200, data: {
    status: "ok", period: "all", mode: "demo", summary: summary(),
    byStrategy: [group("trend", "Trend Following"), group("breakout", "Breakout", true)],
    bySymbol: [group("EURUSD", "EURUSD")], minTrades: 3,
    excluded: { unknownMode: 0, otherMode: 0 }, journalTrades: 10,
    note: "Closed trades from your broker's deal history for the last 30 days.",
    source: { closedTrades: "broker deal history", windowDays: 30, journalReadable: true, attributed: 10, unattributed: 0 },
    ...over,
  },
} as ApiResult<unknown>);

afterEach(() => { cleanup(); paths.length = 0; });

describe("PerformancePage", () => {
  it("asks for the demo account, all time, to start with", async () => {
    answer = ok();
    render(<PerformancePage />);
    await waitFor(() => expect(paths.length).toBeGreaterThan(0));
    expect(paths[0]).toBe("performance?period=all&mode=demo");
  });

  it("choosing a period asks the server for that period", async () => {
    answer = ok();
    render(<PerformancePage />);
    await waitFor(() => expect(paths.length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "7 days" }));
    await waitFor(() => expect(paths).toContain("performance?period=week&mode=demo"));
  });

  it("shows the server's figures", async () => {
    answer = ok();
    render(<PerformancePage />);
    await waitFor(() => expect(screen.queryByText("6 of 10 (60%)")).not.toBeNull());
    expect(screen.queryByText("$123.45")).not.toBeNull();
    expect(screen.queryByText("1.8")).not.toBeNull();
  });

  it("a negative amount carries its sign", async () => {
    answer = ok({ summary: summary({ net: -12.5 }) as never });
    render(<PerformancePage />);
    await waitFor(() => expect(screen.queryByText("−$12.50")).not.toBeNull());
  });

  it("no losing trade is said in words, not as infinity", async () => {
    answer = ok({ summary: summary({ losses: 0, profit_factor: null, noLosses: true }) as never });
    render(<PerformancePage />);
    await waitFor(() => expect(screen.queryByText("no losing trades")).not.toBeNull());
    expect(document.body.textContent).not.toMatch(/Infinity|∞/);
  });

  it("a missing number is a dash, never a zero", async () => {
    answer = ok({ summary: summary({ expectancy: null, max_drawdown: null }) as never });
    render(<PerformancePage />);
    await waitFor(() => expect(screen.queryAllByText("—").length).toBeGreaterThanOrEqual(2));
  });

  it("zero trades says so and shows no tiles", async () => {
    answer = ok({ summary: summary({ trades: 0, wins: 0, losses: 0, win_rate: 0, net: 0 }) as never });
    render(<PerformancePage />);
    await waitFor(() => expect(screen.queryByText(/No closed trades in this period/)).not.toBeNull());
    expect(screen.queryByText("Winning trades")).toBeNull();
  });

  it("an unreadable journal is NOT shown as no trades", async () => {
    answer = { ok: true, status: 200, data: { status: "unavailable", reason: "the broker closed-trade history could not be read just now" } } as ApiResult<unknown>;
    render(<PerformancePage />);
    await waitFor(() => expect(screen.queryByText(/not a statement that there were no trades/)).not.toBeNull());
    expect(screen.queryByText(/No closed trades in this period/)).toBeNull();
  });

  it("a thin group is labelled and the reason given", async () => {
    answer = ok();
    render(<PerformancePage />);
    await waitFor(() => expect(screen.queryByText(/too few to judge/)).not.toBeNull());
    expect(screen.queryByText(/Fewer than 3 trades is not evidence/)).not.toBeNull();
  });

  it("says what was left out, and that it was not guessed", async () => {
    answer = ok({ excluded: { unknownMode: 4, otherMode: 2 } });
    render(<PerformancePage />);
    await waitFor(() => expect(screen.queryByText(/4 older trades with no recorded account type/)).not.toBeNull());
    expect(screen.queryByText(/2 trades from another account type/)).not.toBeNull();
  });

  it("says how many trades are unlabelled, and why", async () => {
    answer = ok({ source: { closedTrades: "broker deal history", windowDays: 30, journalReadable: true, attributed: 6, unattributed: 4 } });
    render(<PerformancePage />);
    await waitFor(() => expect(screen.queryByText(/4 of 10 trades are\s+unlabelled/)).not.toBeNull());
  });

  it("an unreadable journal is said, since it costs the strategy labels", async () => {
    answer = ok({ source: { closedTrades: "broker deal history", windowDays: 30, journalReadable: false, attributed: 0, unattributed: 10 } });
    render(<PerformancePage />);
    await waitFor(() => expect(screen.queryByText(/journal could not be read just now/)).not.toBeNull());
  });

  it("a broker that could not be read is an error, not 'no closed trades'", async () => {
    answer = { ok: true, status: 200, data: { status: "unavailable", reason: "cTrader did not answer", brokerStatus: "unavailable" } } as ApiResult<unknown>;
    render(<PerformancePage />);
    await waitFor(() => expect(screen.queryByText(/cTrader did not answer/)).not.toBeNull());
    expect(screen.queryByText(/No closed trades in this period/)).toBeNull();
  });

  it("a failed request is shown with its code", async () => {
    answer = { ok: false, status: 500, code: "INTERNAL_ERROR", message: "boom" } as ApiResult<unknown>;
    render(<PerformancePage />);
    await waitFor(() => expect(document.body.textContent).toMatch(/INTERNAL_ERROR|boom/));
  });
});
