/**
 * Closing one position: what is asked, in what order, and what is said back.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiResult, Position } from "@/lib/api";

const calls: { path: string; init?: { method?: string; body?: unknown } }[] = [];
let answer: ApiResult<unknown> = { ok: true, status: 200, data: {} } as ApiResult<unknown>;

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string, init?: { method?: string; body?: unknown }) => {
      calls.push({ path, init });
      return answer;
    }),
  };
});

import { CLOSE_TIMEOUT_MS, PositionDetail } from "./position-detail";

const POS: Position = {
  symbol: "EURUSD", side: "BUY", units: 1000, entryPrice: 1.1, stopLoss: 1.09,
  takeProfit: 1.12, positionId: 7,
};
const closeOk = (status: string, sentence: string, extra: Record<string, unknown> = {}) =>
  ({ ok: true, status: 200, data: { close: { status, sentence, ...extra }, sentence } }) as ApiResult<unknown>;

function mount(over: Partial<React.ComponentProps<typeof PositionDetail>> = {}) {
  const onClosed = vi.fn();
  const onBack = vi.fn();
  render(<PositionDetail position={POS} accountId={501} mode="demo" stillOpen
                         onBack={onBack} onClosed={onClosed} {...over} />);
  return { onClosed, onBack };
}
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));

afterEach(() => { cleanup(); calls.length = 0; });

describe("PositionDetail — nothing is sent without confirmation", () => {
  it("the first click opens a question and sends nothing", () => {
    mount();
    click("Close position");
    expect(calls.length).toBe(0);
    expect(screen.queryByText(/Close EURUSD position 7 at market now\? This cannot be undone\./)).not.toBeNull();
  });

  it("Cancel returns to the start and sends nothing", () => {
    mount();
    click("Close position");
    click("Cancel");
    expect(calls.length).toBe(0);
    expect(screen.queryByRole("button", { name: "Close position" })).not.toBeNull();
  });

  it("the close waits longer than a read, and a timeout does not blame the connection", async () => {
    answer = closeOk("FILLED", "ok");
    mount();
    click("Close position"); click("Yes, close it");
    await waitFor(() => expect(calls.length).toBe(1));
    const init = calls[0].init as { timeoutMs?: number; timeoutMessage?: string };
    expect(init.timeoutMs).toBe(CLOSE_TIMEOUT_MS);
    expect(init.timeoutMs!).toBeGreaterThan(25_000);
    expect(init.timeoutMessage).toMatch(/may still complete/);
    expect(init.timeoutMessage).not.toMatch(/connection/);
  });

  it("confirming sends ONE POST, by position id, with no symbol anywhere", async () => {
    answer = closeOk("FILLED", "Closed 1000 units of EURUSD.");
    mount();
    click("Close position"); click("Yes, close it");
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0].path).toBe("accounts/501/positions/7/close");
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[0].path).not.toMatch(/EURUSD/);
    expect(JSON.stringify(calls[0].init?.body ?? null)).not.toMatch(/EURUSD|symbol/);
  });
});

describe("PositionDetail — the server's answer, exactly as returned", () => {
  const run = async () => { mount(); click("Close position"); click("Yes, close it"); await waitFor(() => expect(calls.length).toBe(1)); };

  it("FILLED: its status and its sentence, verbatim", async () => {
    answer = closeOk("FILLED", "Closed 1000 units of EURUSD at 1.1012.");
    await run();
    await waitFor(() => expect(document.querySelector('[data-close-status="FILLED"]')).not.toBeNull());
    expect(document.querySelector('[data-close-status="FILLED"]')!.textContent).toContain("Closed 1000 units of EURUSD at 1.1012.");
  });

  it("ALREADY_CLOSED: said as returned, and the close button is gone", async () => {
    answer = closeOk("ALREADY_CLOSED", "The broker reports this position was already closed.");
    await run();
    await waitFor(() => expect(document.querySelector('[data-close-status="ALREADY_CLOSED"]')).not.toBeNull());
    expect(document.body.textContent).toContain("The broker reports this position was already closed.");
    expect(screen.queryByRole("button", { name: "Close position" })).toBeNull();
  });

  it("PARTIAL: not described as closed, the remainder is stated, and it can be closed again", async () => {
    answer = closeOk("PARTIAL", "500 of 1000 units were closed.", { remainingVolume: 500 });
    await run();
    await waitFor(() => expect(document.querySelector('[data-close-status="PARTIAL"]')).not.toBeNull());
    const t = document.querySelector('[data-close-status="PARTIAL"]')!.textContent ?? "";
    expect(t).toContain("500 of 1000 units were closed.");
    expect(t).toContain("500 still open");
    expect(t).toContain("still open at your broker");
    expect(screen.queryByRole("button", { name: "Close position" })).not.toBeNull();
  });

  it("an error is its code and message, never a success", async () => {
    answer = { ok: false, status: 409, code: "NOT_OWNER", message: "another instance owns this account" } as ApiResult<unknown>;
    await run();
    await waitFor(() => expect(document.body.textContent).toMatch(/NOT_OWNER|another instance owns this account/));
    expect(document.querySelector("[data-close-status]")).toBeNull();
  });

  it("calls the caller back so the positions are re-read", async () => {
    answer = closeOk("FILLED", "ok");
    const { onClosed } = (() => { const x = mount(); return x; })();
    click("Close position"); click("Yes, close it");
    await waitFor(() => expect(onClosed).toHaveBeenCalled());
  });
});

describe("PositionDetail — there is no live close path", () => {
  it.each(["live", "unknown", "", undefined])("mode %s: no close button, and the honest sentence", (mode) => {
    mount({ mode: mode as string | undefined });
    expect(screen.queryByRole("button", { name: /Close position/ })).toBeNull();
    expect(screen.queryByText("Closing from here is not available yet. Close it in cTrader.")).not.toBeNull();
    expect(calls.length).toBe(0);
  });

  it("a position the latest read no longer lists cannot be closed", () => {
    mount({ stillOpen: false });
    expect(screen.queryByRole("button", { name: /Close position/ })).toBeNull();
    expect(screen.queryByText(/no longer listed as open/)).not.toBeNull();
  });

  it("without an account id there is nothing to close on", () => {
    mount({ accountId: undefined });
    expect(screen.queryByRole("button", { name: /Close position/ })).toBeNull();
  });
});
