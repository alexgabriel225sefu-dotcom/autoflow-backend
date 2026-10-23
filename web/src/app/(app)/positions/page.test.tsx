import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const reads: { path: string | null; interval: number }[] = [];
let dealsFailure = false;

vi.mock("@/lib/api", () => ({
  api: vi.fn(async () => ({ ok: true, data: { status: "FILLED", sentence: "Position closed." } })),
}));

vi.mock("@/lib/use-api", () => ({
  useRead: (path: string | null, interval = 0) => {
    reads.push({ path, interval });
    if (path === "positions") return {
      result: { ok: true, data: {
        connected: true, status: "ok", accountId: 501, mode: "demo",
        positions: [{
          symbol: "EURUSD", side: "BUY", units: 1000, entryPrice: 1.1,
          currentPrice: 1.101, stopLoss: null, takeProfit: null,
          pnlPips: null, pnlAccount: null, pnlIsEstimate: true,
          quoteStale: true, quoteAgeSec: 42, hasStop: false,
          stopDistancePips: null, targetDistancePips: null,
          openTime: null, positionId: 7,
          warning: "UNPROTECTED: no stop-loss is attached",
        }],
      } }, loading: false, lastSync: Date.now(), reload: vi.fn(),
    };
    return dealsFailure ? {
      result: { ok: false, status: 503, code: "DEALS_UNAVAILABLE", message: "the broker did not return deal history" },
      loading: false, lastSync: Date.now(), reload: vi.fn(),
    } : {
      result: { ok: true, data: { connected: true, status: "ok", deals: [] } },
      loading: false, lastSync: Date.now(), reload: vi.fn(),
    };
  },
  whenSynced: () => "just now",
}));

import PositionsPage from "./page";

describe("positions read", () => {
  it("shows stale and unprotected values without offering a close action", () => {
    reads.length = 0;
    dealsFailure = false;
    render(<PositionsPage />);
    expect(screen.getAllByText("stale").length).toBeGreaterThan(0);
    expect(screen.getAllByText("None").length).toBeGreaterThan(0);
    expect(screen.getAllByText("UNPROTECTED: no stop-loss is attached").length).toBeGreaterThan(0);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText(/1 positions · 1 positions without a current price/)).toBeDefined();
    expect(screen.queryByRole("button", { name: /Close position/i })).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "View details" })[0]);
    expect(screen.getByRole("button", { name: "Close position" })).toBeDefined();
    expect(reads.some((r) => r.path === "positions" && r.interval === 5_000)).toBe(true);
    expect(reads.some((r) => r.path === "accounts/501/deals?days=7" && r.interval === 60_000)).toBe(true);
  });

  it("View details opens the detail ABOVE the table, with focus on it", () => {
    dealsFailure = false;
    render(<PositionsPage />);
    expect(screen.queryByRole("region", { name: /Position 7/ })).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "View details" })[0]);
    const detail = screen.getByRole("region", { name: /Position 7/ });
    const table = document.querySelector("table, .records");
    expect(table).not.toBeNull();
    // DOCUMENT_POSITION_FOLLOWING (4): the table comes after the detail.
    expect(detail.compareDocumentPosition(table!) & 4).toBe(4);
    expect(document.activeElement?.textContent).toContain("Position 7");
  });

  it("Back closes the detail", () => {
    dealsFailure = false;
    render(<PositionsPage />);
    fireEvent.click(screen.getAllByRole("button", { name: "View details" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.queryByRole("region", { name: /Position 7/ })).toBeNull();
  });

  it("shows a broker error when closed trades cannot be read", () => {
    dealsFailure = true;
    render(<PositionsPage />);
    expect(screen.getByText("DEALS_UNAVAILABLE")).toBeDefined();
    expect(screen.getByText("the broker did not return deal history")).toBeDefined();
    dealsFailure = false;
  });
});
