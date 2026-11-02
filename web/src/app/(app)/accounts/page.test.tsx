import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

let routes: Record<string, unknown> = {};
const calls: { path: string; method?: string }[] = [];

vi.mock("next/navigation", () => ({
  usePathname: () => "/accounts",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: vi.fn(async (path: string, init?: { method?: string }) => {
    calls.push({ path, method: init?.method });
    const v = routes[path];
    return (typeof v === "function" ? v() : v) ?? { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" };
  }) as never,
}));

import AccountsPage from "./page";

const STATUS = (over: Record<string, unknown> = {}) => ({ ok: true, data: {
  connected: true,
  accounts: [{ ctid: 501, mode: "demo" }, { ctid: 502, mode: "demo" }, { ctid: 902, mode: "live" }],
  selected: { ctid: 501, mode: "demo" }, liveAllowed: false, ...over,
} });

async function mount() {
  await act(async () => { render(<AccountsPage />); });
  await act(async () => { await Promise.resolve(); });
}

beforeEach(() => { routes = { "ctrader/status": STATUS() }; calls.length = 0; });

describe("accounts", () => {
  it("not connected: says so and offers Connect", async () => {
    routes["ctrader/status"] = { ok: true, data: { connected: false, accounts: [], selected: null, liveAllowed: false } };
    await mount();
    expect(await screen.findByText(/no ctrader account is connected/i)).toBeTruthy();
    expect(screen.getByRole("link", { name: /connect ctrader/i }).getAttribute("href")).toBe("/connect");
  });

  it("lists accounts, marks the selected one, and offers no select on a live one", async () => {
    await mount();
    expect(await screen.findByText("Selected")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /select this account/i })).toHaveLength(1);
    expect(screen.getByText(/live accounts are not available here/i)).toBeTruthy();
  });

  it("a failed read shows the error, not an empty list", async () => {
    routes["ctrader/status"] = { ok: false, status: 503, code: "ACCOUNTS_FAILED", message: "cTrader did not answer" };
    await mount();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("cTrader did not answer");
    expect(alert.textContent).toMatch(/could not be loaded/i);
    expect(screen.queryByText(/no ctrader account is connected/i)).toBeNull();
  });

  it("a refused select reads as a sentence, with the server's wait kept", async () => {
    routes["ctrader/select"] = { ok: false, status: 429, code: "RATE_LIMITED", message: "Try again in 42 seconds.", retryAfterSec: 42 };
    await mount();
    fireEvent.click(await screen.findByRole("button", { name: /select this account/i }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Try again in 42 seconds.");
    expect(alert.textContent).not.toMatch(/RATE_LIMITED:/);
  });

  it("an account-limit refusal renders the notice instead of red text", async () => {
    routes["ctrader/select"] = { ok: false, status: 403, code: "ACCOUNT_LIMIT", message: "Limit reached." } as ApiResult<never>;
    await mount();
    fireEvent.click(await screen.findByRole("button", { name: /select this account/i }));
    const note = await screen.findByText("Limit reached.");
    expect(within(note.closest("[role=status]") as HTMLElement).getByText(/contact support/i)).toBeTruthy();
  });
});
