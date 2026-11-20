import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

let answer: ApiResult<unknown> = { ok: false, status: 404, code: "NOT_FOUND", message: "x" } as ApiResult<unknown>;
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: vi.fn(async () => answer) };
});
import { HealthView, IncidentsView, RiskView } from "./analysis-views";

const okv = (data: unknown) => ({ ok: true, status: 200, data } as ApiResult<unknown>);
afterEach(cleanup);

describe("analysis views", () => {
  it("health shows unknown parts as unknown, not healthy", async () => {
    answer = okv({ score: 14, status: "blocked", checks: { broker: true, data: null, rule: false },
                   warnings: ["data status is unknown"] });
    render(<HealthView />);
    await waitFor(() => expect(screen.queryByText("14/100")).not.toBeNull());
    expect(screen.queryByText("could not be read")).not.toBeNull();
    expect(document.querySelector('[data-check="unknown"]')).not.toBeNull();
  });
  it("health says what is needed when no cTrader account is connected", async () => {
    answer = okv({ score: 100, status: "not_connected", checks: {
      broker: "not_applicable", data: "not_applicable", session: "not_applicable",
      rule: true, risk: "not_applicable", store: true, incidents: true,
    }, warnings: ["Connect a cTrader account to check data and session."] });
    render(<HealthView />);
    await waitFor(() => expect(screen.queryByText(/Connect a cTrader account/)).not.toBeNull());
    expect(screen.queryByText("could not be read")).toBeNull();
    expect(document.querySelector('[data-check="not-applicable"]')).not.toBeNull();
  });
  it("a closed market is not shown as a failed price feed", async () => {
    answer = okv({ score: 80, status: "degraded", checks: {
      broker: true, data: "market_closed", quotes: "market_closed", risk: false,
    }, warnings: ["The market is closed, so candle age and quote age are not treated as a feed failure."] });
    render(<HealthView />);
    await waitFor(() => expect(screen.getAllByText("market closed").length).toBe(2));
    expect(screen.queryByText("Price data fresh")).not.toBeNull();
    expect(document.querySelector('[data-check="market-closed"]')).not.toBeNull();
  });
  it("incidents render when the healthy payload omits notChecked", async () => {
    answer = okv({ status: "ok", incidents: [] });
    render(<IncidentsView />);
    await waitFor(() => expect(screen.queryByText(/not an all-clear/i)).not.toBeNull());
    expect(screen.queryByText("Something went wrong")).toBeNull();
  });
  it("incidents say what was not checked", async () => {
    answer = okv({ incidents: [], checked: ["brokerStatus"], notChecked: ["riskBlocked"],
                   message: "Nothing wrong in what was checked (brokerStatus). Not checked: riskBlocked." });
    render(<IncidentsView />);
    await waitFor(() => expect(screen.queryByText(/Not checked yet: riskBlocked/)).not.toBeNull());
  });
  it("risk map: unreadable positions are not shown as no risk", async () => {
    answer = okv({ status: "unavailable", reason: "positions could not be read" });
    render(<RiskView />);
    await waitFor(() => expect(screen.queryByText("Risk could not be read")).not.toBeNull());
    expect(screen.queryByText(/No open positions/)).toBeNull();
  });
  it("risk map: unknown balance is unknown, not zero percent", async () => {
    answer = okv({ status: "ok", totalRisk: 120, riskFraction: null, symbols: {}, unreadablePositions: 1,
                   warnings: ["account balance is unknown; risk percentage is unavailable"] });
    render(<RiskView />);
    await waitFor(() => expect(screen.queryByText("unknown")).not.toBeNull());
  });
});
