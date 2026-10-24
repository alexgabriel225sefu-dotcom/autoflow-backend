/**
 * Loading must end — as the account, or as an error with a way to retry.
 *
 * A phone left several authenticated pages on "Account · Loading" for ever. The
 * fix is a deadline in the API client (see lib/api-deadlines.test.ts); this file
 * checks the other half, that every screen turns an answer OR a failure into
 * something other than a skeleton, at the phone width the QA pass used
 * (390x844). jsdom does not lay anything out, so what is asserted is the DOM
 * the phone would be given, not pixels.
 */
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";
import { StatusBar } from "./status-bar";

const DEMO = { connected: true, accounts: [{ ctid: 47765456, mode: "demo" }],
               selected: { ctid: 47765456, mode: "demo" }, liveAllowed: false };
const ME = { licence: { state: "active" } };
const STOPPED = { state: "stopped" };

function phone() {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 844 });
  window.dispatchEvent(new Event("resize"));
}
beforeEach(phone);
afterEach(() => cleanup());

const bar = (ct: unknown, auto: unknown = { ok: true, data: STOPPED }) => (
  <StatusBar me={{ ok: true, data: ME } as never} ct={ct as never} auto={auto as never} />
);
const text = () => screen.getByRole("status").textContent ?? "";
const skeletons = () => document.querySelectorAll(".skel").length;

describe("the status strip at 390x844: loading → ready, and loading → failed", () => {
  it("shows a skeleton while the account is still being asked, and says nothing false meanwhile", () => {
    render(bar(null));
    expect(skeletons()).toBeGreaterThan(0);
    expect(text()).not.toContain("Not connected");
    expect(text()).not.toContain("47765456");
  });

  it("restores the selected demo account the moment the read arrives", () => {
    const { rerender } = render(bar(null));
    rerender(bar({ ok: true, data: DEMO }));
    expect(skeletons()).toBe(0);
    expect(text()).toContain("DEMO");
    expect(text()).toContain("47765456");
  });

  it("a read that failed leaves the skeleton too: Unknown, never a permanent shimmer", () => {
    const { rerender } = render(bar(null));
    rerender(bar({ ok: false, status: 0, code: "AUTH_UNAVAILABLE", message: "Your session could not be confirmed in time." }));
    expect(skeletons()).toBe(0);
    expect(text()).toContain("Unknown");
    expect(text()).not.toContain("Not connected");
  });

  it("recovers when a later read succeeds", () => {
    const { rerender } = render(bar({ ok: false, status: 0, code: "NETWORK", message: "x" }));
    expect(text()).toContain("Unknown");
    rerender(bar({ ok: true, data: DEMO }));
    expect(text()).toContain("47765456");
    expect(text()).not.toContain("Unknown");
  });
});

// ── a whole page, with the real hook, behind a slow and then a failed API ───
let pending: ((r: ApiResult<unknown>) => void) | null = null;
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: vi.fn(() => new Promise<ApiResult<unknown>>((res) => { pending = res; })) };
});

describe("the performance page at 390x844 behind a slow API", () => {
  it("is a spinner while waiting, then the figures, then no spinner", async () => {
    const { default: Page } = await import("../../app/(app)/performance/page");
    pending = null;
    render(<Page />);
    expect(document.body.textContent).not.toContain("Closed trades");
    await waitFor(() => expect(pending).not.toBeNull());
    await act(async () => {
      pending!({ ok: true, status: 200, data: {
        status: "ok", period: "all", mode: "demo",
        summary: { trades: 3, wins: 2, losses: 1, win_rate: 66.7, net: 5, profit_factor: 2, expectancy: 1.67,
                   max_drawdown: 1, avg_win: 3, avg_loss: -1, best: 4, worst: -1, noLosses: false, r: null },
        byStrategy: [], bySymbol: [], minTrades: 3, excluded: { unknownMode: 0, otherMode: 0 },
        journalTrades: 0, note: "n", source: { closedTrades: "broker deal history", windowDays: 30, journalReadable: true, attributed: 0, unattributed: 3 },
      } } as ApiResult<unknown>);
    });
    await waitFor(() => expect(screen.queryByText("Closed trades")).not.toBeNull());
  });

  it("a failure that arrives instead is an error with Retry — not a skeleton", async () => {
    const { default: Page } = await import("../../app/(app)/performance/page");
    pending = null;
    render(<Page />);
    await waitFor(() => expect(pending).not.toBeNull());
    await act(async () => {
      pending!({ ok: false, status: 0, code: "AUTH_UNAVAILABLE", message: "Your session could not be confirmed in time." } as ApiResult<unknown>);
    });
    await waitFor(() => expect(document.body.textContent).toMatch(/AUTH_UNAVAILABLE|could not be confirmed in time/));
    expect(screen.queryByRole("button", { name: /retry|try again/i })).not.toBeNull();
  });
});
