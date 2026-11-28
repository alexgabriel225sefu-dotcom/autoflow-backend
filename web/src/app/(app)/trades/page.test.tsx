import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const paths: string[] = [];
let answer: ApiResult<unknown> = { ok: false, status: 404, code: "NOT_FOUND", message: "x" } as ApiResult<unknown>;
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: vi.fn(async (p: string) => { paths.push(p); return answer; }) };
});
import TradesPage from "./page";

const trade = (id: string, symbol: string, net: number) => ({
  positionId: id, symbol, side: "BUY", units: 1000, openedAt: 1_760_000_000, closedAt: 1_760_003_600,
  durationS: 3600, entry: 1.1, exit: 1.101, net, gross: net, swap: 0, commission: 0,
  strategyId: null, strategy: null, slPips: null, tpPips: null, slPrice: null, tpPrice: null,
});
const ok = (trades = [trade("1", "EURUSD", 12.5), trade("2", "GBPUSD", -4)]) => ({
  ok: true, status: 200, data: {
    status: "ok", mode: "demo", accountMode: "demo", days: 30, currency: null, trades,
    summary: { trades: trades.length, net: 8.5, wins: 1, losses: 1 },
    daily: [], equity: [], excluded: { otherMode: 0, undated: 0, unusableForCurve: 0 },
    source: { closedTrades: "broker deal history", journalReadable: true, labelled: 0 }, note: "From the broker.",
  },
} as ApiResult<unknown>);

afterEach(() => { cleanup(); paths.length = 0; });

describe("TradesPage", () => {
  it("asks for 30 days of demo trades", async () => {
    answer = ok(); render(<TradesPage />);
    await waitFor(() => expect(paths[0]).toBe("trades?days=30&mode=demo"));
  });
  it("filters by result", async () => {
    answer = ok(); render(<TradesPage />);
    await waitFor(() => expect(screen.queryByRole("button", { name: /EURUSD/ })).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Losses" }));
    expect(screen.queryByRole("button", { name: /EURUSD/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /GBPUSD/ })).not.toBeNull();
  });
  it("opens a trade's detail", async () => {
    answer = ok(); render(<TradesPage />);
    await waitFor(() => expect(screen.queryByRole("button", { name: /EURUSD/ })).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /EURUSD/ }));
    expect(screen.queryByTestId("trade-detail")).not.toBeNull();
  });
  it("an unreadable broker is not shown as no trades", async () => {
    answer = { ok: true, status: 200, data: { status: "unavailable", reason: "broker down" } } as ApiResult<unknown>;
    render(<TradesPage />);
    await waitFor(() => expect(screen.queryByText("Closed trades could not be read")).not.toBeNull());
    expect(screen.queryByText(/No closed trades/)).toBeNull();
  });
  it("an empty period says so", async () => {
    answer = ok([]); render(<TradesPage />);
    await waitFor(() => expect(screen.queryByText(/No closed trades in this period/)).not.toBeNull());
  });
});
