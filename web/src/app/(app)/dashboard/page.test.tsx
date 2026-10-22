/**
 * The dashboard, one test per state it can be in.
 *
 * The failure this guards against is the one that looks fine: a read that
 * returned an error, rendered as an empty success. "No open positions" and
 * "we could not reach your broker" are different facts, and only one of them
 * is safe to believe. Several tests below assert the WRONG sentence is
 * absent, not only that the right one is present.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

/**
 * The server's verdict, as `me.execution` carries it.
 *
 * The dashboard renders this rather than recombining a licence state with an
 * account mode, so a test that wants a refusal states the refusal — which is
 * also what the backend would send.
 */
function execution(over: Record<string, unknown> = {}) {
  return {
    accountMode: "demo", entitlement: "paid_live", licenceState: "active",
    liveExecutionEnabled: false,
    planNotice: "Demo accounts are free. Real-money account access will be a paid plan, and live execution is not enabled in this release.",
    canAutomate: true, reason: null,
    message: "demo automation is available on this account",
    badge: "DEMO",
    ...over,
  };
}

function base() {
  return {
    me: { ok: true, data: {
      user: { userId: "u1", email: "t@example.test", emailVerified: true },
      licence: { state: "active", expiresAt: null, plan: "demo" },
      execution: execution(),
    } },
    "ctrader/status": CONNECTED,
    automation: { ok: true, data: { state: "stopped", ruleDocId: null, mode: null, startedAt: null } },
    // The "why no trade" card reads this. It is a READ, so it must not count
    // as a control call in the assertions below.
    "automation/why": { ok: true, data: {
      status: "ok", state: "stopped", reason: "stopped",
      summary: "Automation is stopped, which is why nothing is happening.",
      level: null, levelLabel: null, loopActive: null, marketOpen: null,
      halted: false, openPosition: null, maxPositions: null, riskGuard: { state: "unknown", reasons: [] }, skipsToday: null,
      skips: [], recorded: [], recordedCount: 0, recordedReadable: true } },
    positions: { ok: true, data: { connected: true, status: "ok", accountId: 501, mode: "demo", positions: [] } },
    orders: { ok: true, data: { connected: true, status: "ok", accountId: 501, mode: "demo", orders: [] } },
    journal: { ok: true, data: { status: "ok", entries: [], total: 0, limit: 8, offset: 0, hasMore: false } },
    rules: { ok: true, data: { rules: [] } },
    // The pending-approval card reads this. Stubbed as "we asked, and none is
    // waiting" — the ordinary case. Left out, every test here would render
    // the card's read-failed notice instead, which is exactly what it is
    // supposed to do with a 404 and not what these tests are about.
    approvals: { ok: true, data: { status: "ok", approval: null } },
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
    routes.me = { ok: true, data: {
      user: { userId: "u1", email: "t@example.test", emailVerified: true },
      licence: { state: "active", expiresAt: null, plan: "demo" },
      execution: execution({
        accountMode: "live", canAutomate: false, badge: "LIVE BLOCKED",
        reason: "LIVE_NOT_AVAILABLE",
        message: "live trading is not available in this release",
      }),
    } };
    await renderDash();
    // Said in more than one place on purpose: once in the automation card as
    // the reason this account cannot run, once in the standing footer note.
    await waitFor(() =>
      expect(screen.getAllByText(/Live trading is not available in this release/).length)
        .toBeGreaterThan(0));
    expect(screen.getAllByText("LIVE BLOCKED").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /^Start$/ })).toBeNull();
    // Controls only. `automation/why` is a read and is allowed; what this
    // pins is that no start/pause/resume/stop is ever sent.
    expect(calls.some((c) => c.path.startsWith("automation/") && c.init?.method === "POST")).toBe(false);
  });

  it("DOES offer them when the server has cleared this live account", async () => {
    // The other side of the test above, and the one that was missing while
    // the refusal was hardcoded to `!isDemo`. Without it, a browser that
    // overruled a server saying yes would have passed every test in this
    // file — the paying client simply never sees a Start button and nobody
    // finds out until one of them complains.
    routes["ctrader/status"] = { ok: true, data: {
      connected: true, accounts: [{ ctid: 902, mode: "live" }],
      selected: { ctid: 902, mode: "live" }, liveAllowed: true,
    } };
    routes.me = { ok: true, data: {
      user: { userId: "u1", email: "t@example.test", emailVerified: true },
      licence: { state: "active", expiresAt: null, plan: "founder_lifetime" },
      execution: execution({
        accountMode: "live", entitlement: "paid_live", canAutomate: true,
        liveExecutionEnabled: true, badge: "LIVE", reason: null,
        message: "live automation is available on this account",
      }),
    } };
    await renderDash();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /^Start$/ })).not.toBeNull());
    // The word, not the absence of a word: a client must never have to infer
    // that they are trading real money from a badge that stopped appearing.
    expect(screen.getAllByText("LIVE").length).toBeGreaterThan(0);
  });

  it("does not unlock live controls on a verdict about the OTHER account", async () => {
    // The picker and `me` refresh on different clocks. A client who switches
    // from their cleared demo account to a live one briefly holds a verdict
    // that says canAutomate — and it is a verdict about the demo account.
    routes["ctrader/status"] = { ok: true, data: {
      connected: true, accounts: [{ ctid: 902, mode: "live" }],
      selected: { ctid: 902, mode: "live" }, liveAllowed: true,
    } };
    routes.me = { ok: true, data: {
      user: { userId: "u1", email: "t@example.test", emailVerified: true },
      licence: { state: "active", expiresAt: null, plan: "demo_trial" },
      execution: execution({
        accountMode: "demo", canAutomate: true, badge: "DEMO", reason: null,
        message: "demo automation is available on this account",
      }),
    } };
    await renderDash();
    await waitFor(() =>
      expect(screen.getAllByText(/Live trading is not available in this release/).length)
        .toBeGreaterThan(0));
    expect(screen.queryByRole("button", { name: /^Start$/ })).toBeNull();
  });

  it("shows the server's badge rather than deriving one", async () => {
    routes.me = { ok: true, data: {
      user: { userId: "u1", email: "t@example.test", emailVerified: true },
      licence: { state: "none", expiresAt: null, plan: null },
      execution: execution({
        accountMode: "unknown", entitlement: "free_demo", licenceState: "none",
        canAutomate: false, badge: "NOT CONNECTED", reason: "NOT_CONNECTED",
        message: "connect a cTrader demo account and select it",
      }),
    } };
    await renderDash();
    await waitFor(() => expect(screen.getAllByText("NOT CONNECTED").length).toBeGreaterThan(0));
  });

  it("states what is free and what is not, in the server's words", async () => {
    await renderDash();
    await waitFor(() =>
      expect(screen.getByText(/Demo accounts are free\./)).toBeDefined());
    expect(screen.getByText(/live execution is not enabled in this release/)).toBeDefined();
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

  // A lapsed licence no longer blocks anything: demo access is free, and the
  // paid tier is what expired. The refusal that remains is a WITHDRAWN one,
  // and the UI takes it from the server rather than inferring it.
  it("a lapsed licence still offers demo automation", async () => {
    routes.me = { ok: true, data: {
      user: { userId: "u1", email: "t@example.test", emailVerified: true },
      licence: { state: "expired", expiresAt: 1, plan: "demo" },
      execution: execution({ entitlement: "free_demo", licenceState: "expired" }),
    } };
    routes.rules = { ok: true, data: { rules: [
      { ruleDocId: "r1", name: "R", state: "active", version: 1, symbols: ["EURUSD"], timeframe: "1h", updatedAt: 0 },
    ] } };
    await renderDash();
    const start = await screen.findByRole("button", { name: /^Start$/ });
    expect((start as HTMLButtonElement).disabled).toBe(false);
  });

  it("start is refused when the server says it may not run, and says why", async () => {
    routes.me = { ok: true, data: {
      user: { userId: "u1", email: "t@example.test", emailVerified: true },
      licence: { state: "revoked", expiresAt: null, plan: "demo" },
      execution: execution({
        entitlement: "free_demo", licenceState: "revoked", canAutomate: false,
        reason: "LICENCE_REVOKED",
        message: "this licence was withdrawn — contact support",
      }),
    } };
    routes.rules = { ok: true, data: { rules: [
      { ruleDocId: "r1", name: "R", state: "active", version: 1, symbols: ["EURUSD"], timeframe: "1h", updatedAt: 0 },
    ] } };
    await renderDash();
    const start = await screen.findByRole("button", { name: /^Start$/ });
    expect((start as HTMLButtonElement).disabled).toBe(true);
    // The server's sentence, not a second version of it written in the UI.
    expect(screen.getByText(/withdrawn — contact support/)).toBeDefined();
  });
});

describe("dashboard — reads that failed are not empty successes", () => {
  it.each([
    ["not_connected", /No account selected/],
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

/**
 * Choosing an account must never fail in silence.
 *
 * The owner could not select the account he had just connected. The server
 * was answering `429 RATE_LIMITED retryAfterSec=42` — select shared a rate
 * bucket with the OAuth round he had spent getting there — and this page
 * discarded the result of the call entirely. So the picker snapped back, the
 * status strip went on reading "No account selected", and nothing on screen
 * said why, on any of the five screenshots he sent.
 *
 * The rate limit is fixed in apex/platform/ratelimit.py. These assertions are
 * about the other half: a refusal has to reach the reader, whatever its cause,
 * because the next one will have a different cause.
 */
describe("dashboard — the account picker reports a refusal", () => {
  const REFUSED = {
    ok: false, status: 429, code: "RATE_LIMITED",
    message: "too many requests — wait 42s and try again",
  };

  async function pick() {
    const combo = await screen.findByRole("combobox", { name: /Account/i });
    await act(async () => { fireEvent.change(combo, { target: { value: "902" } }); });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  }

  beforeEach(() => {
    routes["ctrader/status"] = { ok: true, data: {
      connected: true,
      accounts: [{ ctid: 501, mode: "demo" }, { ctid: 902, mode: "demo" }],
      selected: null, liveAllowed: false,
    } };
  });

  it("shows the server's own words when the selection is refused", async () => {
    routes["ctrader/select"] = REFUSED;
    await renderDash();
    await pick();
    expect(await screen.findByText(/wait 42s and try again/)).toBeTruthy();
    expect(screen.getByText(/RATE_LIMITED/)).toBeTruthy();
  });

  it("does not fail silently — the whole defect in one assertion", async () => {
    routes["ctrader/select"] = REFUSED;
    await renderDash();
    const before = document.body.textContent ?? "";
    await pick();
    const after = document.body.textContent ?? "";
    // Something on the page has to change. The old code reloaded the status
    // and rendered exactly what was there before, which is indistinguishable
    // from nothing having been pressed.
    expect(after).not.toBe(before);
  });

  it("says nothing when the selection succeeds", async () => {
    routes["ctrader/select"] = { ok: true, data: { selected: { ctid: 902, mode: "demo" } } };
    await renderDash();
    await pick();
    expect(screen.queryByText(/RATE_LIMITED/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

/**
 * A proposal waiting for an answer, on the screen that has to show it.
 *
 * The component has its own tests. These two are about the WIRING, which is
 * the half that was missing in the shipped bug: in Approval Required the
 * engine proposed setups and the only thing that could answer them was a
 * Telegram tap, so a platform client's loop ran, found setups, and waited
 * for ever while this dashboard said Running. A card nobody renders is the
 * same silence with extra steps.
 */
describe("dashboard — a setup waiting for approval", () => {
  it("shows it, above everything else on the page", async () => {
    routes.approvals = { ok: true, data: { status: "ok", approval: {
      symbol: "EURUSD", side: "BUY", price: 1.0987, confidence: 60,
      reasoning: "RSI(14) 24.3 below 30", keyFactors: [], detailKnown: true,
      proposedAt: 1_000, ageSec: 10, expiresAt: 1_300, expiresInSec: 290,
      expired: false, actionable: true, refusal: null,
    } } };
    await renderDash();
    await waitFor(() =>
      expect(screen.getByText(/Waiting for your approval/)).toBeTruthy());
    expect(screen.getByText("RSI(14) 24.3 below 30")).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Approve$/ })).toBeTruthy();
    // It leads the page: a client scrolling past the account picker to find
    // a setup that expires in five minutes is a setup that expires.
    const body = document.body.textContent ?? "";
    expect(body.indexOf("Waiting for your approval"))
      .toBeLessThan(body.indexOf("Automation"));
  });

  it("and nothing about approvals when none is waiting", async () => {
    await renderDash();
    expect(screen.queryByText(/Waiting for your approval/)).toBeNull();
    expect(screen.queryByRole("button", { name: /^Approve$/ })).toBeNull();
  });
});
