/**
 * The Trade page: the product's front door, checked through the page.
 *
 * WHAT HAS TO HOLD
 *
 *  - Nothing is chosen for the client that changes what is risked or who acts:
 *    Start stays disabled, with the reason, until an instrument, a strategy, a
 *    risk and "who acts on a setup" are chosen.
 *  - Start is four calls in a fixed order (save, write the strategy, activate,
 *    start) and the body carries exactly what was chosen. A failure stops the
 *    sequence at that step and never reaches `automation/start`.
 *  - Live never starts from here on the browser's say-so. A closed live
 *    account turns the button into the next step towards access; an open one
 *    asks for a confirmation that names the account and says real money moves.
 *  - Nothing the server did not say is shown as a result: there is no number
 *    about any strategy's performance on the page.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult, StrategyCatalogue } from "@/lib/api";

type Call = { path: string; init?: { method?: string; body?: unknown } };
const calls: Call[] = [];
let routes: Record<string, unknown | ((init?: Call["init"]) => unknown)> = {};

const fireStartConfetti = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/start-confetti", () => ({ fireStartConfetti }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/trade",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { signOut: vi.fn(async () => ({})) } }),
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string, init?: Call["init"]) => {
      calls.push({ path, init });
      const key = Object.keys(routes)
        .sort((a, b) => b.length - a.length)
        .find((k) => path === k || path.startsWith(k));
      if (!key) return { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" };
      const v = routes[key];
      return (typeof v === "function" ? (v as (i?: Call["init"]) => unknown)(init) : v) as ApiResult<unknown>;
    }),
  };
});

import TradePage from "./page";

const CATALOGUE: StrategyCatalogue = {
  ruleBuilderId: "platform_rule", presetField: "strategy",
  strategies: [
    { id: "trend", label: "Trend Following", version: "1", family: "trend",
      what: "Buys pullbacks inside a confirmed uptrend.", decides: "EMA50 over EMA200.",
      refuses: "Counter-trend entries.", source: "apex/ai.py" },
    { id: "fvg", label: "Fair Value Gap", version: "1", family: "structure",
      what: "Forwards a detector's side.", decides: "A gap is detected.",
      refuses: "Nothing beyond the setup not being there.", source: "apex/strategy_extra.py" },
  ],
  withheld: [],
};
const ok = (data: unknown) => ({ ok: true, data });
const execution = (over: Record<string, unknown> = {}) => ({
  accountMode: "demo", entitlement: "free_demo", licenceState: "active",
  liveExecutionEnabled: false, planNotice: "", canAutomate: true, canActivate: true,
  activationRefusal: null, plan: "trial", onTrial: true, trialDaysLeft: 5,
  trialExpiresAt: null, message: null, ...over,
});
const me = (over?: Record<string, unknown>) => ok({
  user: { userId: "u1", email: "a@b.test", emailVerified: true },
  licence: { state: "active", expiresAt: null, plan: "trial" },
  execution: execution(over),
});
const demo = ok({ connected: true, accounts: [{ ctid: 7, mode: "demo" }],
  selected: { ctid: 7, mode: "demo" }, liveAllowed: false });
const live = ok({ connected: true, accounts: [{ ctid: 9, mode: "live" }],
  selected: { ctid: 9, mode: "live" }, liveAllowed: true });

const BROKER = ok({ connected: true, status: "ok", accountId: 7, mode: "demo", symbols: [
  { id: "EURUSD", class: "forex", tradeable: true, reason: null },
  { id: "XAUUSD", class: "metal", tradeable: true, reason: null },
  { id: "GBPJPY", class: "forex_cross", tradeable: false, reason: "A cross has no USD leg." },
  { id: "US30", class: "index", tradeable: false, reason: "Indices need exchange trading calendars." },
] });
const RULES = ok({ rules: [
  { ruleDocId: "m1", name: "My RSI dip", state: "draft", version: 1, symbols: ["EURUSD"],
    timeframe: "1h", updatedAt: 1, strategy: "", entryConditions: 2, exitConditions: 1 },
  { ruleDocId: "p1", name: "Trend Following · EURUSD", state: "active", version: 1, symbols: ["EURUSD"],
    timeframe: "1h", updatedAt: 1, strategy: "trend", entryConditions: 0, exitConditions: 0 },
] });

let autoState = "stopped";
function baseRoutes() {
  autoState = "stopped";
  routes = {
    strategies: ok(CATALOGUE),
    symbols: BROKER,
    rules: (init?: Call["init"]) =>
      init?.method === "POST" ? ok({ rule: { ruleDocId: "r1" } }) : RULES,
    "ctrader/status": demo,
    me: me(),
    automation: () => ok({ state: autoState, ruleDocId: null, mode: "demo" }),
    "automation/start": () => { autoState = "running"; return ok({ state: "running", ruleDocId: "r1", mode: "demo" }); },
    "rules/m1": ok({ rule: { ruleDocId: "m1", entry: { combine: "AND", conditions: [{ id: "rsi" }, { id: "ema" }] },
      exit: { combine: "OR", conditions: [{ id: "rsi" }] }, sides: "BUY" } }),
    "rules/r1/activate": ok({}),
    "rules/r1": ok({ rule: { ruleDocId: "r1" } }),
  };
}

async function loaded() {
  render(<TradePage />);
  await screen.findByRole("radio", { name: /Trend Following/ });
}
const choose = (name: RegExp) => fireEvent.click(screen.getByRole("radio", { name }));
function chooseEverything() {
  choose(/^EURUSD$/);
  choose(/Trend Following/);
  choose(/Approval Required/);
}

beforeEach(() => { calls.length = 0; fireStartConfetti.mockClear(); baseRoutes(); });
afterEach(() => { vi.clearAllMocks(); });

describe("the choices", () => {
  it("offers every strategy the server lists, each with what it will not trade", async () => {
    await loaded();
    expect(screen.getByText(/Buys pullbacks inside a confirmed uptrend/)).toBeDefined();
    expect(screen.getAllByText(/Will not trade:/).length).toBe(2);
    expect(screen.getByText(/Nothing beyond the setup not being there/)).toBeDefined();
  });

  it("shows no performance number", async () => {
    await loaded();
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/no result is shown here/i);
    expect(text).not.toMatch(/win rate|profit factor|backtest result/i);
  });

  it("does not choose an instrument, a strategy or who acts on the client's behalf", async () => {
    await loaded();
    for (const r of screen.getAllByRole("radio")) {
      const name = r.textContent ?? "";
      if (/^EURUSD$|Trend Following|Signals Only|Approval Required|Full Automation/.test(name)) {
        expect(r.getAttribute("aria-checked"), name).toBe("false");
      }
    }
  });

  it("keeps Start disabled and says what is still to choose", async () => {
    await loaded();
    const start = await screen.findByRole("button", { name: "Start on demo" });
    expect((start as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Still to choose: an instrument, a strategy or a method of your own, who acts on a setup/)).toBeDefined();
    chooseEverything();
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "Start on demo" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("works the money estimate out from the size typed, and says it is not a forecast", async () => {
    await loaded();
    fireEvent.change(screen.getByLabelText(/Account size/i), { target: { value: "10000" } });
    expect(screen.getByText("$100.00")).toBeDefined();
    expect(screen.getByText("$200.00")).toBeDefined();
    expect(screen.getByText(/not a forecast/)).toBeDefined();
  });
});

describe("the broker's own instruments", () => {
  it("lists what can be traded and says how many of the broker's the rest are", async () => {
    await loaded();
    expect(screen.getByRole("radio", { name: "EURUSD" })).toBeDefined();
    expect(screen.queryByRole("radio", { name: "US30" })).toBeNull();
    expect(screen.getByText(/Your broker lists 4 instruments\. 2 can be traded now/)).toBeDefined();
  });

  it("shows the unsupported ones disabled, with the reason, when asked", async () => {
    await loaded();
    fireEvent.click(screen.getByLabelText(/Also list the 2 the engine cannot trade yet/));
    const us30 = screen.getByRole("radio", { name: "US30" }) as HTMLButtonElement;
    expect(us30.disabled).toBe(true);
    expect(us30.getAttribute("title")).toMatch(/exchange trading calendars/);
    expect(screen.getAllByText(/Indices need exchange trading calendars/).length).toBeGreaterThan(0);
    fireEvent.click(us30);
    expect(us30.getAttribute("aria-checked")).toBe("false");
  });

  it("a search finds an instrument the engine cannot trade and explains it", async () => {
    await loaded();
    fireEvent.change(screen.getByLabelText("Search instruments"), { target: { value: "gbpjpy" } });
    const chip = screen.getByRole("radio", { name: "GBPJPY" }) as HTMLButtonElement;
    expect(chip.disabled).toBe(true);
    expect(screen.getByText(/A cross has no USD leg/)).toBeDefined();
  });

  it("falls back to the engine's list and says the broker's could not be read", async () => {
    routes.symbols = { ok: false, status: 503, code: "UNAVAILABLE", message: "down" };
    await loaded();
    expect(screen.getByText(/Your broker's list could not be read/)).toBeDefined();
    expect(screen.getByRole("radio", { name: "EURUSD" })).toBeDefined();
    expect(screen.getByRole("radio", { name: "XAUUSD" })).toBeDefined();
  });
});

describe("my methods", () => {
  it("lists only methods built from conditions, not the preset rules the page made", async () => {
    await loaded();
    fireEvent.click(screen.getByRole("tab", { name: /My methods/ }));
    expect(screen.getByRole("radio", { name: /My RSI dip/ })).toBeDefined();
    expect(screen.queryByText(/Trend Following · EURUSD/)).toBeNull();
    expect(screen.getByText(/2 entry and 1 exit conditions/)).toBeDefined();
    expect(screen.getByRole("link", { name: "Build a new method" }).getAttribute("href")).toBe("/rules/new");
  });

  it("starts from the client's own conditions, with no strategy field", async () => {
    await loaded();
    fireEvent.click(screen.getByRole("tab", { name: /My methods/ }));
    fireEvent.click(screen.getByRole("radio", { name: /My RSI dip/ }));
    await waitFor(() => expect(
      screen.getByRole("radio", { name: /My RSI dip/ }).getAttribute("aria-checked")).toBe("true"));
    choose(/^XAUUSD$/);
    choose(/Approval Required/);
    fireEvent.click(await screen.findByRole("button", { name: "Start on demo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes" }));
    await waitFor(() => expect(calls.some((c) => c.path === "automation/start")).toBe(true));
    const body = calls.find((c) => c.path === "rules" && c.init?.method === "POST")!
      .init!.body as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(body.strategy).toBeUndefined();
    expect(body.entry.conditions.map((x: { id: string }) => x.id)).toEqual(["rsi", "ema"]);
    expect(body.exit.conditions.length).toBe(1);
    expect(body.sides).toBe("BUY");
    expect(body.symbols).toEqual(["XAUUSD"]);
  });
});

describe("Start on demo", () => {
  it("saves, writes the strategy, activates and starts, in that order, with what was chosen", async () => {
    await loaded();
    chooseEverything();
    choose(/^0\.5%$/);
    fireEvent.change(screen.getByLabelText(/Stop the day at/i), { target: { value: "3" } });
    fireEvent.click(await screen.findByRole("button", { name: "Start on demo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes" }));

    await waitFor(() => expect(calls.some((c) => c.path === "automation/start")).toBe(true));
    const writes = calls.filter((c) => c.init?.method === "POST" || c.init?.method === "PUT")
      .map((c) => `${c.init!.method} ${c.path}`);
    expect(writes).toEqual([
      "POST rules", "PUT rules/r1", "POST rules/r1/activate", "POST automation/start",
    ]);
    const body = calls.find((c) => c.path === "rules" && c.init?.method === "POST")!.init!.body as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(body.symbols).toEqual(["EURUSD"]);
    expect(body.strategy).toBe("trend");
    expect(body.automationLevel).toBe("approval");
    expect(body.sizing.riskPercent).toBe(0.5);
    expect(body.limits.maxDailyLossPercent).toBe(3);
    expect(body.entry.conditions).toEqual([]);
    expect(calls.find((c) => c.path === "automation/start")!.init!.body).toEqual({ ruleDocId: "r1" });
    // The server accepted Start, so the confetti fires, once.
    await waitFor(() => expect(fireStartConfetti).toHaveBeenCalledTimes(1));
  });

  it("stops at activation, says so, and never reaches automation/start", async () => {
    routes["rules/r1/activate"] = { ok: false, status: 422, code: "NOT_ACTIVATABLE", message: "no stop" };
    await loaded();
    chooseEverything();
    fireEvent.click(await screen.findByRole("button", { name: "Start on demo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes" }));
    await screen.findByText("NOT_ACTIVATABLE");
    expect(calls.some((c) => c.path === "automation/start")).toBe(false);
    expect(screen.getByText(/saved but did not start/i)).toBeDefined();
    expect(fireStartConfetti).not.toHaveBeenCalled();
  });

  it("is disabled with the reason while automation is already running", async () => {
    autoState = "running";
    await loaded();
    chooseEverything();
    await screen.findByText(/already running/i);
    expect((screen.getByRole("button", { name: "Start on demo" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("live", () => {
  it("a closed live account turns Start into the next step and starts nothing", async () => {
    routes["ctrader/status"] = live;
    routes.me = me({ canAutomate: false, liveGate: {
      open: false, status: "closed", summary: "Terms not accepted yet.", conditions: [], missing: [],
      request: { status: "none" }, checkoutOpen: false } });
    await loaded();
    chooseEverything();
    const link = await screen.findByRole("link", { name: "Request live access" });
    expect(link.getAttribute("href")).toBe("/live");
    expect(screen.queryByRole("button", { name: /Start on/ })).toBeNull();
    expect(screen.getByText(/Terms not accepted yet/)).toBeDefined();
    expect(calls.some((c) => c.path === "automation/start")).toBe(false);
  });

  it("a pending request reads as waiting for approval", async () => {
    routes["ctrader/status"] = live;
    routes.me = me({ canAutomate: false, liveGate: {
      open: false, status: "closed", summary: "x", conditions: [], missing: [],
      request: { status: "pending" }, checkoutOpen: false } });
    await loaded();
    expect((await screen.findAllByText(/Awaiting approval/)).length).toBeGreaterThan(0);
  });

  it("an account the server allows still needs a confirmation that names it and says real money", async () => {
    routes["ctrader/status"] = live;
    routes.me = me({ canAutomate: true });
    await loaded();
    chooseEverything();
    fireEvent.click(await screen.findByRole("button", { name: "Start on live" }));
    const q = await screen.findByText(/LIVE account #9/);
    expect(q.textContent).toMatch(/Real money moves/);
    expect(calls.some((c) => c.path === "automation/start")).toBe(false);
    within(document.body).getByRole("button", { name: "Cancel" });
  });
});
