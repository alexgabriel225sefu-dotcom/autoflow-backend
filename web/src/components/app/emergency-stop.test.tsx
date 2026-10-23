/**
 * The emergency button must not fire on one click, must send the server an
 * explicit confirmation, and must never say "flat" on its own authority.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiResult, EmergencyResult } from "@/lib/api";

const calls: { path: string; init?: { method?: string; body?: Record<string, unknown> } }[] = [];
let answer: ApiResult<unknown> = { ok: true, status: 200, data: {} } as ApiResult<unknown>;

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string, init?: { method?: string; body?: Record<string, unknown> }) => {
      calls.push({ path, init });
      return answer;
    }),
  };
});

import { EmergencyStop } from "./emergency-stop";

let reloadState = "stopped";
const reload = vi.fn(async () => ({ ok: true, status: 200, data: { state: reloadState } }) as never);

const result = (over: Partial<EmergencyResult> = {}): EmergencyResult => ({
  status: "ok",
  automation: { stopped: true, alreadyStopped: false, error: null },
  positions: { readable: true, reason: null, found: 1, notAttempted: 0 },
  closes: [{ positionId: "100", symbol: "EURUSD", side: "BUY", outcome: "closed" }],
  verified: { readable: true, stillOpen: 0 },
  allFlat: true,
  sentence: "Automation is stopped. 1 position closed. Confirmed: no positions are open.",
  ...over,
});
const ok = (data: unknown) => ({ ok: true, status: 200, data } as ApiResult<unknown>);
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));

afterEach(() => { cleanup(); calls.length = 0; reload.mockClear(); reloadState = "stopped"; });

describe("EmergencyStop — nothing happens on one click", () => {
  it("opening the panel sends nothing", () => {
    render(<EmergencyStop ctid={501} reloadAutomation={reload} />);
    click(/Emergency/);
    expect(calls.length).toBe(0);
  });

  it("choosing 'stop and close' still sends nothing until the second confirmation", () => {
    render(<EmergencyStop ctid={501} reloadAutomation={reload} />);
    click(/Emergency/);
    click("Stop and close positions");
    expect(calls.length).toBe(0);
    expect(screen.queryByText(/cannot be undone/)).not.toBeNull();
  });

  it("cancel at either step sends nothing and returns to the start", () => {
    render(<EmergencyStop ctid={501} reloadAutomation={reload} />);
    click(/Emergency/);
    click("Cancel");
    expect(calls.length).toBe(0);
    expect(screen.queryByRole("button", { name: /Emergency/ })).not.toBeNull();
  });
});

describe("EmergencyStop — what it sends", () => {
  it("stop and close: confirm true, closePositions true, the account", async () => {
    answer = ok(result());
    render(<EmergencyStop ctid={501} reloadAutomation={reload} />);
    click(/Emergency/); click("Stop and close positions"); click("Yes, stop and close");
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0].path).toBe("emergency/stop");
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[0].init?.body).toEqual({ confirm: true, closePositions: true, ctid: "501" });
  });

  it("stop only: runs the EXISTING automation stop, closes nothing, and re-reads the state", async () => {
    answer = ok({ state: "stopped", stopped: true, flattened: false, flattenDeclined: true,
                  flattenReason: "Stopping ends the trading loop. It does not close positions that are already open." });
    render(<EmergencyStop ctid={501} reloadAutomation={reload} />);
    click(/Emergency/); click("Stop only"); click("Yes, stop only");
    await waitFor(() => expect(calls.some((c) => c.path === "automation/stop")).toBe(true));
    expect(calls.some((c) => c.path === "emergency/stop")).toBe(false);
    expect(calls.some((c) => /close/.test(c.path))).toBe(false);
    await waitFor(() => expect(reload).toHaveBeenCalled());
    await waitFor(() => expect(document.querySelector('[data-stop-only="ok"]')).not.toBeNull());
    expect(document.querySelector('[data-stop-only="ok"]')!.textContent).toContain("does not close positions");
  });

  it("stop only: a stop the next read contradicts is reported, not shown as success", async () => {
    reloadState = "running";
    answer = ok({ state: "stopped", stopped: true });
    render(<EmergencyStop ctid={501} reloadAutomation={reload} />);
    click(/Emergency/); click("Stop only"); click("Yes, stop only");
    await waitFor(() => expect(document.querySelector('[data-stop-only="error"]')).not.toBeNull());
    expect(document.querySelector('[data-stop-only="error"]')!.textContent).toContain("still says RUNNING");
  });
});

describe("EmergencyStop — it does not say more than the server measured", () => {
  const run = async () => {
    render(<EmergencyStop ctid={501} reloadAutomation={reload} />);
    click(/Emergency/); click("Stop and close positions"); click("Yes, stop and close");
    await waitFor(() => expect(calls.length).toBe(1));
  };

  it("shows 'Confirmed flat' only when the server says allFlat", async () => {
    answer = ok(result());
    await run();
    await waitFor(() => expect(screen.queryByText("Confirmed flat.")).not.toBeNull());
  });

  it("a position still open is 'Not confirmed flat', with the server's sentence", async () => {
    answer = ok(result({
      allFlat: false, verified: { readable: true, stillOpen: 1 },
      closes: [{ positionId: "100", symbol: "EURUSD", side: "BUY", outcome: "refused", code: "NOT_OWNER", detail: "another instance owns it" }],
      sentence: "Automation is stopped. 1 position is still open.",
    }));
    await run();
    await waitFor(() => expect(screen.queryByText("Not confirmed flat.")).not.toBeNull());
    expect(screen.queryByText("Confirmed flat.")).toBeNull();
    expect(screen.queryByText(/not closed/)).not.toBeNull();
    expect(screen.queryByText(/another instance owns it/)).not.toBeNull();
  });

  it("an unreadable account is not flat either", async () => {
    answer = ok(result({
      allFlat: false, verified: { readable: false, stillOpen: null },
      sentence: "The account could not be re-read, so it is NOT confirmed flat.",
    }));
    await run();
    await waitFor(() => expect(screen.queryByText("Not confirmed flat.")).not.toBeNull());
    expect(screen.queryByText("Confirmed flat.")).toBeNull();
  });

  it("a failed request is shown with its code, never as success", async () => {
    answer = { ok: false, status: 409, code: "NO_ACCOUNT_SELECTED", message: "select a cTrader account" } as ApiResult<unknown>;
    await run();
    await waitFor(() => expect(document.body.textContent).toMatch(/NO_ACCOUNT_SELECTED|select a cTrader account/));
    expect(screen.queryByText("Confirmed flat.")).toBeNull();
  });
});
