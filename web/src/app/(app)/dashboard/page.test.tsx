/**
 * The dashboard, one test per state it can be in.
 *
 * The failure this guards against is the one that looks fine: a read that
 * returned an error, rendered as an empty success. "No open positions" and
 * "we could not reach your broker" are different facts, and only one of them
 * is safe to believe. Several tests below assert the WRONG sentence is
 * absent, not only that the right one is present.
 */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const calls: { path: string; init?: { method?: string; body?: unknown } }[] = [];
let routes: Record<string, unknown> = {};

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { signOut: vi.fn() } }),
}));

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string, init?: { method?: string; body?: unknown }) => {
      calls.push({ path, init });
      const key = Object.keys(routes)
        .sort((a, b) => b.length - a.length)
        .find((k) => path.startsWith(k));
      if (!key) return { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" };
      return routes[key] as ApiResult<unknown>;
    }),
  };
});

import Dashboard from "./page";

const CONNECTED = {
  ok: true, data: {
    connected: true, accounts: [{ ctid: 501, mode: "demo" }],
    selected: { ctid: 501, mode: "demo" }, liveAllowed: false,
  },
};

function base() {
  return {
    me: { ok: true, data: {
      user: { userId: "u1", email: "t@example.test", emailVerified: true },
      licence: { state: "active", expiresAt: null, plan: "demo" },
    } },
    "ctrader/status": CONNECTED,
    automation: { ok: true, data: { state: "stopped", ruleDocId: null, mode: null, startedAt: null } },
    positions: { ok: true, data: { connected: true, status: "ok", accountId: 501, mode: "demo", positions: [] } },
    orders: { ok: true, data: { connected: true, status: "ok", accountId: 501, mode: "demo", orders: [] } },
    journal: { ok: true, data: { status: "ok", entries: [], total: 0, limit: 8, offset: 0, hasMore: false } },
    rules: { ok: true, data: { rules: [] } },
  } as Record<string, unknown>;
}

async function renderDash() {
  await act(async () => { render(<Dashboard />); });
  // Let the queued first loads resolve.
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

beforeEach(() => { calls.length = 0; routes = base(); });
afterEach(() => vi.clearAllMocks());

describe("dashboard — account state", () => {
  it("says the account is not connected, in words a trader would use", async () => {
    routes["ctrader/status"] = { ok: true, data: {
      connected: false, accounts: [], selected: null, liveAllowed: false,
    } };
    await renderDash();
    await waitFor(() => expect(screen.getAllByText(/cTrader account not connected/).length)
      .toBeGreaterThan(0));
    // Offered by both the automation card and the market panel — each is the
    // fix for the state it is showing.
    expect(screen.getAllByRole("link", { name: /Connect cTrader/ }).length)
      .toBeGreaterThan(0);
    // Not offered a Start button it could not honour.
    expect(screen.queryByRole("button", { name: /^Start$/ })).toBeNull();
  });

  it("offers the connected demo accounts and never a live one", async () => {
    routes["ctrader/status"] = { ok: true, data: {
      connected: true,
      accounts: [{ ctid: 501, mode: "demo" }, { ctid: 902, mode: "live" }],
      selected: { ctid: 501, mode: "demo" }, liveAllowed: false,
    } };
    await renderDash();
    const select = await screen.findByRole("combobox", { name: /Account/i });
    const live = within(select).getByRole("option", { name: /902/ }) as HTMLOptionElement;
    const demo = within(select).getByRole("option", { name: /501/ }) as HTMLOptionElement;
    expect(live.disabled, "a live account must not be selectable").toBe(true);
    expect(demo.disabled).toBe(false);
    expect(live.textContent).toMatch(/not available/);
  });

  it("refuses to offer automation controls on a non-demo selection", async () => {
    routes["ctrader/status"] = { ok: true, data: {
      connected: true, accounts: [{ ctid: 902, mode: "live" }],
      selected: { ctid: 902, mode: "live" }, liveAllowed: true,
    } };
    await renderDash();
    await waitFor(() => expect(screen.getByText(/runs on demo accounts only/)).toBeDefined());
    expect(screen.queryByRole("button", { name: /^Start$/ })).toBeNull();
    expect(calls.some((c) => c.path.startsWith("automation/"))).toBe(false);
  });
});

describe("dashboard — automation state", () => {
  it.each([
    ["running", "Watching market"],
    ["paused", "Automation paused"],
    ["stopped", "Not running"],
  ])("renders %s as %s", async (state, label) => {
    routes.automation = { ok: true, data: { state, ruleDocId: "r1", mode: "demo", startedAt: 0 } };
    routes.rules = { ok: true, data: { rules: [
      { ruleDocId: "r1", name: "EURUSD trend", state: "active", version: 1, symbols: ["EURUSD"], timeframe: "1h", updatedAt: 0 },
    ] } };
    await renderDash();
    await waitFor(() => expect(screen.getByText(label)).toBeDefined());
  });

  it("start is refused without an active rule, and says why", async () => {
    routes.rules = { ok: true, data: { rules: [] } };
    await renderDash();
    const start = await screen.findByRole("button", { name: /^Start$/ });
    expect((start as HTMLButtonElement).disabled).toBe(true);
    // Said twice on purpose: once as the state, once next to the disabled control.
    expect(screen.getAllByText(/Activate a rule first/).length).toBeGreaterThan(0);
  });

  it("start is refused without an active licence, and says why", async () => {
    routes.me = { ok: true, data: {
      user: { userId: "u1", email: "t@example.test", emailVerified: true },
      licence: { state: "expired", expiresAt: 1, plan: "demo" },
    } };
    routes.rules = { ok: true, data: { rules: [
      { ruleDocId: "r1", name: "R", state: "active", version: 1, symbols: ["EURUSD"], timeframe: "1h", updatedAt: 0 },
    ] } };
    await renderDash();
    const start = await screen.findByRole("button", { name: /^Start$/ });
    expect((start as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/active licence is required/)).toBeDefined();
  });
});

describe("dashboard — reads that failed are not empty successes", () => {
  it.each([
    ["not_connected", /cTrader account not connected/],
    ["reauth_required", /cTrader needs reconnecting/],
    ["unavailable", /Market data unavailable/],
  ])("positions status %s shows the reason, not 'No open positions'", async (status, expected) => {
    routes.positions = { ok: true, data: {
      connected: status !== "not_connected", status,
      reason: "TimeoutError: the broker did not answer",
    } };
    await renderDash();
    await waitFor(() => expect(screen.getAllByText(expected).length).toBeGreaterThan(0));
    // The sentence that would be a lie here.
    expect(screen.queryByText("No open positions.")).toBeNull();
  });

  it("an API error is shown with its code, never as an empty list", async () => {
    routes.positions = {
      ok: false, status: 503, code: "BROKER_UNAVAILABLE",
      message: "cTrader did not answer within 12s",
    };
    await renderDash();
    await waitFor(() => expect(screen.getByText("BROKER_UNAVAILABLE")).toBeDefined());
    expect(screen.getByText(/did not answer within 12s/)).toBeDefined();
    expect(screen.queryByText("No open positions.")).toBeNull();
  });

  it("says 'No open positions' only when the broker actually confirmed it", async () => {
    await renderDash();
    await waitFor(() => expect(screen.getByText("No open positions.")).toBeDefined());
  });
});

describe("dashboard — decisions in plain language", () => {
  const entry = (status: string, extra: Record<string, unknown> = {}) => ({
    entryId: `e-${status}`, kind: "decision", status, ts: 1758546000,
    symbol: "EURUSD", accountId: "501", ruleDocId: "r1", correlationId: "c1",
    ...extra,
  });

  it.each([
    ["hold", "Conditions not met", "No order placed."],
    ["order_confirmed", "Order placed in demo", null],
    ["broker_error", "Broker error", null],
    ["automation_paused", "Automation paused", null],
  ])("renders %s as %s", async (status, label, detail) => {
    routes.journal = { ok: true, data: {
      status: "ok", entries: [entry(status)], total: 1, limit: 8, offset: 0, hasMore: false,
    } };
    await renderDash();
    await waitFor(() => expect(screen.getAllByText(label).length).toBeGreaterThan(0));
    if (detail) expect(screen.getAllByText(detail).length).toBeGreaterThan(0);
    // The raw engine token must not be what the reader sees.
    expect(screen.queryByText(status)).toBeNull();
  });

  it("a refusal carries its code and still says no order was placed", async () => {
    routes.journal = { ok: true, data: {
      status: "ok",
      entries: [entry("reject", {
        decision: { verdict: "REJECT", reason: "not enough history", conditions: [],
                    executable: false, refusalCode: "INSUFFICIENT_DATA", confidence: null },
      })],
      total: 1, limit: 8, offset: 0, hasMore: false,
    } };
    await renderDash();
    await waitFor(() => expect(screen.getByText("Could not run")).toBeDefined());
    expect(screen.getByText(/No order placed — INSUFFICIENT_DATA/)).toBeDefined();
  });

  it("an empty journal explains itself instead of showing a bare dash", async () => {
    await renderDash();
    await waitFor(() => expect(screen.getByText(/Nothing recorded yet/)).toBeDefined());
  });
});

describe("dashboard — the demo-only promise", () => {
  it("states demo-only on the page, not only in the status strip", async () => {
    await renderDash();
    await waitFor(() => expect(screen.getByText(/Live trading is not available in this release/))
      .toBeDefined());
  });

  it("never calls an order, close or amend endpoint", async () => {
    await renderDash();
    const forbidden = calls.filter((c) =>
      /order|close|amend|force/i.test(c.path) && c.init?.method === "POST");
    expect(forbidden, `dashboard called ${forbidden.map((c) => c.path).join(", ")}`)
      .toHaveLength(0);
  });
});
