import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

let answer: ApiResult<unknown> = {
  ok: false, status: 503, code: "UNAVAILABLE", message: "could not be read",
};
const calls: { path: string; init: unknown }[] = [];

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string, init: unknown) => {
      calls.push({ path, init });
      return answer;
    }),
  };
});

import { availableBacktestRules, ForwardView, OverfitView, RiskGuardView, RuleLayerView } from "./simulation-views";
import { RuleLayerResultCard } from "./simulation-result-cards";

afterEach(cleanup);
beforeEach(() => {
  answer = { ok: false, status: 503, code: "UNAVAILABLE", message: "could not be read" };
  calls.length = 0;
});

describe("simulation screens", () => {
  it("offers only active rules to backtest", () => {
    expect(availableBacktestRules([
      { ruleDocId: "draft", name: "Draft", state: "draft" },
      { ruleDocId: "active", name: "Active", state: "active" },
      { ruleDocId: "paused", name: "Paused", state: "paused" },
    ] as never)).toEqual([{ ruleDocId: "active", name: "Active", state: "active" }]);
  });

  it("starts forward testing with an honest empty state and reports a failed read", async () => {
    render(<ForwardView />);
    expect(screen.getByText("No hypothetical signals recorded in this session.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Record signal" }));
    expect((await screen.findByRole("alert")).textContent).toContain("could not be read");
  });

  it("sends blank overfit inputs as unknown and renders the server warning", async () => {
    answer = { ok: true, status: 200, data: {
      status: "warning", warnings: ["trade count is unknown; evidence cannot be judged"],
      disclaimer: "Evidence is not a guarantee.",
    } } as ApiResult<unknown>;
    render(<OverfitView />);
    fireEvent.click(screen.getByRole("button", { name: "Check evidence" }));
    await waitFor(() => expect(screen.getByText(/trade count is unknown/)).toBeTruthy());
    const body = calls[0]?.init as { body?: { tradeCount?: unknown } };
    expect(body.body?.tradeCount).toBeUndefined();
    expect(screen.getAllByPlaceholderText("unknown").length).toBeGreaterThan(0);
  });

  it("does not present an unreadable risk guard as ready", async () => {
    answer = { ok: true, status: 200, data: {
      allowed: false, mode: "blocked",
      blocks: [{ guard: "weekly_loss", reason: "weekly loss is unknown" }],
    } } as ApiResult<unknown>;
    render(<RiskGuardView />);
    fireEvent.click(screen.getByRole("button", { name: "Evaluate guard" }));
    await waitFor(() => expect(screen.getByText("Blocked")).toBeTruthy());
    expect(screen.queryByText("Ready")).toBeNull();
    expect(screen.getByText(/weekly loss is unknown/)).toBeTruthy();
  });

  it("keeps a failed rule-layer calculation distinct from zero", async () => {
    render(<RuleLayerView />);
    fireEvent.click(screen.getByRole("button", { name: "Calculate" }));
    expect((await screen.findByRole("alert")).textContent).toContain("could not be read");
    expect(screen.queryByText("0")).toBeNull();
  });

  it("shows a successful response with unavailable data as a failed read", () => {
    render(<RuleLayerResultCard result={{
      status: "unavailable", reason: "account data could not be read",
    }} />);
    expect(screen.getByRole("alert").textContent).toContain("could not be read");
    expect(screen.getByRole("alert").textContent).toContain("No sizing");
    expect(screen.queryByText("Units")).toBeNull();
    expect(screen.queryByText("0")).toBeNull();
  });
});
