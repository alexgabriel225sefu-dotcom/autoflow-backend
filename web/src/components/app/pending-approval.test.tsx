/**
 * The card that answers a proposal, and the four lies it must not tell.
 *
 * WHY THIS FILE IS AS LONG AS IT IS
 *
 * The engine's Approval Required level proposes a trade and places nothing
 * until somebody says yes. For every client of this platform that "somebody"
 * did not exist: the only approve action in the codebase was a Telegram
 * button, so the loop found setups and waited for ever while the dashboard
 * said Running. This card is the answer, which makes it the one component on
 * the dashboard whose absence is indistinguishable from the bug.
 *
 * So the tests below are mostly about what it must NOT render:
 *
 *   nothing waiting      → no card, and no sentence either way
 *   the read failed      → it SAYS so. A card that quietly does not appear
 *                          is the original silence, wearing a different hat
 *   an unknown price     → said out loud, never a blank space that reads as
 *                          nothing to say
 *   expired / not running → Approve is disabled with the server's own reason,
 *                          and the clock is obeyed between polls rather than
 *                          offering a setup that has gone
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import type { ApiResult } from "@/lib/api";

const calls: { path: string; init?: { method?: string } }[] = [];
let routes: Record<string, unknown> = {};

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string, init?: { method?: string }) => {
      calls.push({ path, init });
      const key = Object.keys(routes)
        .sort((a, b) => b.length - a.length)
        .find((k) => path.startsWith(k));
      if (!key) return { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" };
      return routes[key] as ApiResult<unknown>;
    }),
  };
});

import { PendingApproval } from "./pending-approval";

function approval(over: Record<string, unknown> = {}) {
  return {
    symbol: "EURUSD", side: "BUY", price: 1.0987, confidence: 60,
    reasoning: "RSI(14) 24.3 below 30", keyFactors: ["rsi"],
    detailKnown: true, proposedAt: 1_000, ageSec: 30,
    expiresAt: 1_300, expiresInSec: 270, expired: false,
    actionable: true, refusal: null,
    ...over,
  };
}

function waiting(over: Record<string, unknown> = {}) {
  return { ok: true, data: { status: "ok", approval: approval(over) } };
}

async function renderCard() {
  await act(async () => { render(<PendingApproval />); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

beforeEach(() => {
  calls.length = 0;
  routes = { approvals: { ok: true, data: { status: "ok", approval: null } } };
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); });

describe("when nothing is waiting", () => {
  it("renders nothing at all", async () => {
    const { container } = render(<PendingApproval />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(container.textContent).toBe("");
  });

  it("and says nothing when the account's state could not be read", async () => {
    // `unknown` is the server declining to claim either way. There is
    // nothing a client can do about it from here, and "no setup is waiting"
    // would be a statement the server refused to make.
    routes.approvals = { ok: true, data: { status: "unknown", reason: "x" } };
    const { container } = render(<PendingApproval />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(container.textContent).toBe("");
  });
});

describe("when the read fails", () => {
  it("says so, and never implies that nothing is waiting", async () => {
    routes.approvals = {
      ok: false, status: 503, code: "STORE_UNAVAILABLE",
      message: "upstash GET failed: ReadTimeout",
    };
    await renderCard();
    // The failure is on the screen...
    await waitFor(() => expect(screen.getByText(/cannot tell you whether one is waiting/i))
      .toBeTruthy());
    // ...and nothing on it offers an action that would need a setup to exist.
    expect(screen.queryByRole("button", { name: /^Approve$/ })).toBeNull();
  });
});

describe("the setup itself", () => {
  it("shows the side, the instrument, the price and the rule's own reason", async () => {
    routes.approvals = waiting();
    await renderCard();
    await waitFor(() => expect(screen.getByText("BUY")).toBeTruthy());
    expect(screen.getByText(/EURUSD/)).toBeTruthy();
    expect(screen.getByText(/1\.0987/)).toBeTruthy();
    // The reason is the whole basis for risking money, so it is rendered in
    // full rather than summarised.
    expect(screen.getByText("RSI(14) 24.3 below 30")).toBeTruthy();
  });

  it("counts down to the expiry, from the server's number", async () => {
    routes.approvals = waiting({ expiresInSec: 270 });
    await renderCard();
    // 4:30 as the server saw it, less however long this test has been
    // running — the elapsed time on THIS device, which is the only clock
    // reading the card trusts. A browser whose clock is minutes out must not
    // show a live setup as gone.
    await waitFor(() => expect(screen.getByLabelText(/time left/i).textContent?.trim())
      .toMatch(/^4:(30|2\d)$/));
  });

  it("SAYS the price is unknown rather than leaving a gap", async () => {
    // The price arrives in a separate write from the proposal, so it can
    // genuinely be missing. A blank where a number belongs reads as "nothing
    // to say about the price", which is not the same fact.
    routes.approvals = waiting({ price: null, detailKnown: false, reasoning: null });
    await renderCard();
    await waitFor(() => expect(screen.getByText(/price it was found at was not recorded/i))
      .toBeTruthy());
    expect(screen.getByText(/reason for this setup was not recorded/i)).toBeTruthy();
    // And a missing price is never shown as a zero.
    expect(screen.queryByText(/\b0\b/)).toBeNull();
  });
});

describe("what it refuses to offer", () => {
  it("disables Approve on an expired setup and gives the reason", async () => {
    routes.approvals = waiting({
      expired: true, expiresInSec: 0, actionable: false, refusal: "EXPIRED",
    });
    await renderCard();
    await waitFor(() => expect(screen.getByText(/This setup has expired/i)).toBeTruthy());
    expect((screen.getByRole("button", { name: /^Approve$/ }) as HTMLButtonElement).disabled)
      .toBe(true);
    // Dismissing is always available: a client must be able to say no to
    // anything the product asks them, and while it sits there the rule
    // proposes nothing else.
    expect((screen.getByRole("button", { name: /^Dismiss$/ }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it("disables Approve while the loop is not running, in the server's words", async () => {
    routes.approvals = waiting({ actionable: false, refusal: "NOT_RUNNING" });
    await renderCard();
    await waitFor(() => expect(screen.getByText(/Automation is not running/i)).toBeTruthy());
    expect((screen.getByRole("button", { name: /^Approve$/ }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("stops offering a setup that expires BETWEEN polls", async () => {
    // The read can be ten seconds old. A setup with five seconds left must
    // stop being offered on the clock, not on the next answer from the
    // server — otherwise a client presses Approve on something gone and
    // reads the refusal as a fault.
    vi.useFakeTimers({ shouldAdvanceTime: false });
    routes.approvals = waiting({ expiresInSec: 5 });
    render(<PendingApproval />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect((screen.getByRole("button", { name: /^Approve$/ }) as HTMLButtonElement).disabled)
      .toBe(false);
    // Six seconds: past the expiry, and still inside the ten-second poll, so
    // nothing has been re-read.
    await act(async () => { await vi.advanceTimersByTimeAsync(6_000); });
    expect(screen.getByLabelText(/time left/i).textContent).toContain("0:00");
    expect((screen.getByRole("button", { name: /^Approve$/ }) as HTMLButtonElement).disabled)
      .toBe(true);
    expect(screen.getByText(/This setup has expired/i)).toBeTruthy();
  });
});

describe("answering it", () => {
  it("approves through the API and shows the server's own outcome", async () => {
    routes.approvals = waiting();
    routes["approvals/approve"] = { ok: true, data: {
      status: "ok", outcome: "placed",
      order: { symbol: "EURUSD", side: "BUY", price: 1.0988, units: 1000,
               stopLoss: 1.0963, takeProfit: 1.1013 },
      detail: "BUY EURUSD opened at 1.0988 — 1000 units, stop 1.0963, target 1.1013.",
    } };
    await renderCard();
    fireEvent.click(await screen.findByRole("button", { name: /^Approve$/ }));
    // Every money-moving control on this screen asks once more first.
    expect(screen.getByText(/Open BUY EURUSD now\?/)).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Yes$/ }));
    });
    await waitFor(() => expect(calls.some((c) => c.path === "approvals/approve"
      && c.init?.method === "POST")).toBe(true));
    // The server's sentence, not one written here. It is the only thing that
    // knows what the broker did.
    await waitFor(() => expect(screen.getByText(/opened at 1\.0988/)).toBeTruthy());
  });

  it("shows an approval that was refused, rather than looking like it worked", async () => {
    routes.approvals = waiting();
    routes["approvals/approve"] = {
      ok: false, status: 409, code: "EXPIRED",
      message: "this setup was found 400 seconds ago and is no longer current",
    };
    await renderCard();
    fireEvent.click(await screen.findByRole("button", { name: /^Approve$/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Yes$/ }));
    });
    await waitFor(() => expect(screen.getByText(/EXPIRED: this setup was found/))
      .toBeTruthy());
  });

  it("reports an order the broker never confirmed as exactly that", async () => {
    // The one outcome that must never be collapsed into success or failure:
    // a retry on an order that did go through opens a second position.
    routes.approvals = waiting();
    routes["approvals/approve"] = { ok: true, data: {
      status: "ok", outcome: "unknown", order: null,
      detail: "The order for BUY EURUSD was sent and the broker did not "
        + "confirm whether it was executed, so it may be open.",
    } };
    await renderCard();
    fireEvent.click(await screen.findByRole("button", { name: /^Approve$/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Yes$/ }));
    });
    await waitFor(() => expect(screen.getByText(/may be open/)).toBeTruthy());
  });

  it("dismisses through the API and says nothing was opened", async () => {
    routes.approvals = waiting();
    routes["approvals/reject"] = { ok: true, data: {
      status: "ok", rejected: true, alreadyGone: false,
    } };
    await renderCard();
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: /^Dismiss$/ }));
    });
    await waitFor(() => expect(calls.some((c) => c.path === "approvals/reject"
      && c.init?.method === "POST")).toBe(true));
    await waitFor(() => expect(screen.getByText(/Nothing was opened/)).toBeTruthy());
  });

  it("can dismiss a proposal that cannot be read", async () => {
    // It can never be approved, and while it is stored the rule proposes
    // nothing else — so the one action that matters has to be available.
    routes.approvals = { ok: true, data: { status: "ok", approval: null, unreadable: true } };
    routes["approvals/reject"] = { ok: true, data: { status: "ok", rejected: true } };
    await renderCard();
    await waitFor(() => expect(screen.getByText(/stored and cannot be read/i)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /^Approve$/ })).toBeNull();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Dismiss$/ }));
    });
    await waitFor(() => expect(calls.some((c) => c.path === "approvals/reject")).toBe(true));
  });
});
