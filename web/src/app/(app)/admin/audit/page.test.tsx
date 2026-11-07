/**
 * The audit page reads. It does not trade.
 *
 * A session the server refuses with 403 NOT_OPERATOR sees "Operators only"
 * and no account controls. A session the server accepts sees the connected
 * accounts and the deal columns the operator asked for, fetched with the
 * same api() client as the rest of the app.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const api = vi.fn();

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: (...args: unknown[]) => api(...args) };
});

import AuditPage from "./page";

const NOT_OPERATOR: ApiResult<never> = {
  ok: false,
  status: 403,
  code: "NOT_OPERATOR",
  message: "this action is limited to an operator",
};

const ACCOUNT = {
  ctidTraderAccountId: 424242,
  login: 9001,
  environment: "demo",
  broker: "Pepperstone",
  platformUserId: "user-1",
  selected: true,
  status: "ok",
};

function ok<T>(data: T): ApiResult<T> {
  return { ok: true, data };
}

function detail(path: string): ApiResult<unknown> {
  if (path === "admin/audit/accounts/424242") {
    return ok({
      account: {
        balance: 1000, leverage: 500, broker: "Pepperstone", login: 9001,
        equity: 1000, equityKnown: true, unrealizedPnl: 0, openPositions: 0,
        environment: "demo",
      },
    });
  }
  if (path === "admin/audit/accounts/424242/open") {
    return ok({ positions: [], pendingOrders: [] });
  }
  if (path.startsWith("admin/audit/accounts/424242/deals")) {
    return ok({
      timezone: "Europe/Amsterdam",
      from: "2026-10-18T13:00:00+01:00",
      to: "2026-11-01T12:00:00+01:00",
      truncated: false,
      deals: [{
        dealId: 2,
        time: "2026-01-15T13:00:00+01:00",
        symbol: "EURUSD",
        side: "BUY",
        lots: 1,
        executionPrice: 1.12,
        close: { net: 22 },
        placedByPlatform: true,
        entry_sl_set: true,
        entry_tp_set: false,
      }],
    });
  }
  if (path.startsWith("admin/audit/accounts/424242/orders")) {
    return ok({
      orders: [{
        orderId: 10, time: "2026-01-15T13:00:00+01:00", symbol: "EURUSD",
        side: "BUY", lots: 1, price: 1.1, stopLoss: null, takeProfit: null,
        placedByPlatform: false,
      }],
    });
  }
  return { ok: false, status: 404, code: "NOT_FOUND", message: path };
}

describe("admin audit page", () => {
  it("says Operators only and hides the account list on 403", async () => {
    api.mockResolvedValue(NOT_OPERATOR);
    render(<AuditPage />);
    expect((await screen.findByText("Operators only")).textContent).toMatch(/Operators only/);
    expect(screen.queryByRole("button", { name: "#424242" })).toBeNull();
    expect(screen.queryByRole("button", { name: /close|buy|sell|approve|place/i })).toBeNull();
    expect(api).toHaveBeenCalledWith("admin/audit/accounts");
    for (const call of api.mock.calls) {
      expect((call[1] as { method?: string } | undefined)?.method ?? "GET").toBe("GET");
    }
  });

  it("renders the deal columns from a GET of the default 14-day range", async () => {
    api.mockImplementation(async (path: string) => {
      if (path === "admin/audit/accounts") return ok({ accounts: [ACCOUNT] });
      return detail(path);
    });
    render(<AuditPage />);
    expect((await screen.findAllByText("EURUSD")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Pepperstone").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Platform").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Yes").length).toBeGreaterThan(0);
    expect(screen.getAllByText("No").length).toBeGreaterThan(0);
    expect(screen.getAllByText("22").length).toBeGreaterThan(0);
    for (const name of ["Time", "Lots", "Price", "Net P/L", "placedByPlatform", "entry_sl_set", "entry_tp_set"]) {
      expect(screen.getAllByRole("columnheader", { name }).length).toBeGreaterThan(0);
    }
    expect(screen.queryByRole("button", { name: /close|buy|sell|approve|place order/i })).toBeNull();

    const deals = api.mock.calls.map((c) => String(c[0])).find((p) => p.includes("/deals?"));
    expect(deals).toBeTruthy();
    const q = new URLSearchParams(deals!.split("?")[1]);
    const span = Date.parse(q.get("to")!) - Date.parse(q.get("from")!);
    expect(span).toBe(14 * 86_400_000);
    expect(screen.getByRole("combobox", { name: "Range" })).toHaveProperty("value", "14");
  });

  it("asks again when the range changes", async () => {
    api.mockImplementation(async (path: string) => {
      if (path === "admin/audit/accounts") return ok({ accounts: [ACCOUNT] });
      return detail(path);
    });
    render(<AuditPage />);
    await screen.findAllByText("EURUSD");
    fireEvent.change(screen.getByRole("combobox", { name: "Range" }), { target: { value: "7" } });
    await waitFor(() => {
      const deals = api.mock.calls.map((c) => String(c[0])).filter((p) => p.includes("/deals?"));
      const last = deals[deals.length - 1];
      const q = new URLSearchParams(last.split("?")[1]);
      expect(Date.parse(q.get("to")!) - Date.parse(q.get("from")!)).toBe(7 * 86_400_000);
    });
  });
});
