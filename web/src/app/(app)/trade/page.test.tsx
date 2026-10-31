/**
 * The automation setup: five steps, checked through the page.
 *
 * Start is one POST to /automation/setup. A closed live account never posts
 * a start; it shows Request live access or Awaiting approval. No strategy
 * card shows a result the server did not publish.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      refuses: "Counter-trend entries.", source: "apex/ai.py",
      timeframeNote: "Runs on the timeframe you choose.", backtest: null },
    { id: "fvg", label: "Fair Value Gap", version: "1", family: "structure",
      what: "Forwards a detector's side.", decides: "A gap is detected.",
      refuses: "Nothing beyond the setup not being there.", source: "apex/strategy_extra.py",
      timeframeNote: "Runs on the timeframe you choose.", backtest: null },
  ],
  withheld: [{ id: "grid", label: "Grid", reason: "It adds exposure to a losing position.", kind: "high_risk" }],
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
const LIBRARY = ok({
  ...CATALOGUE,
  disclaimer: "Past performance does not guarantee future results.",
  tradedSymbolNote: "This release trades the first symbol. Any others are recorded on the rule and are not watched.",
  bounds: {},
});

let autoState = "stopped";
function baseRoutes() {
  autoState = "stopped";
  routes = {
    "automation/setup": (init?: Call["init"]) => {
      if (init?.method === "POST") {
        autoState = "running";
        return ok({ started: true, executed: true, account: "demo", ruleDocId: "r1" });
      }
      return LIBRARY;
    },
    symbols: BROKER,
    rules: RULES,
    "ctrader/status": demo,
    me: me(),
    automation: () => ok({ state: autoState, ruleDocId: null, mode: "demo" }),
    "rules/m1": ok({ rule: { ruleDocId: "m1", entry: { combine: "AND", conditions: [{ id: "rsi" }, { id: "ema" }] },
      exit: { combine: "OR", conditions: [{ id: "rsi" }] }, sides: "BUY" } }),
  };
}

async function loaded() {
  render(<TradePage />);
  await screen.findByRole("radio", { name: "EURUSD" });
}
const choose = (name: RegExp) => fireEvent.click(screen.getByRole("radio", { name }));
const cont = () => fireEvent.click(screen.getByRole("button", { name: "Continue" }));

async function toStrategy(symbol: RegExp = /^EURUSD$/) {
  await loaded();
  choose(symbol);
  cont();
  await screen.findByRole("radio", { name: /Trend Following/ });
}
async function toRisk() {
  await toStrategy();
  choose(/Trend Following/);
  cont();
  await screen.findByLabelText("Capital allocated");
}
async function toAccount() {
  await toRisk();
  fireEvent.change(screen.getByLabelText("Capital allocated"), { target: { value: "10000" } });
  choose(/Approval Required/);
  cont();
  await screen.findByRole("radio", { name: "Demo" });
}
async function toReview() {
  await toAccount();
  choose(/^Demo$/);
  cont();
  await screen.findByRole("heading", { name: /Review/ });
}

beforeEach(() => { calls.length = 0; fireStartConfetti.mockClear(); baseRoutes(); });
afterEach(() => { vi.clearAllMocks(); });

describe("the choices", () => {
  it("offers every strategy the server lists, each with what it will not trade", async () => {
    await toStrategy();
    expect(screen.getByText(/Buys pullbacks inside a confirmed uptrend/)).toBeDefined();
    expect(screen.getAllByText(/Will not trade:/).length).toBe(2);
    expect(screen.getByText(/Nothing beyond the setup not being there/)).toBeDefined();
    expect(screen.getAllByText(/No stored backtest/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Past performance does not guarantee future results/)).toBeDefined();
    expect(screen.getByText(/It adds exposure to a losing position/)).toBeDefined();
  });

  it("shows no performance number", async () => {
    await toStrategy();
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/No stored backtest is published/i);
    expect(text).not.toMatch(/win rate|profit factor/i);
  });

  it("does not choose an instrument, a strategy or who acts on the client's behalf", async () => {
    await toRisk();
    for (const r of screen.getAllByRole("radio")) {
      const name = r.textContent ?? "";
      if (/Signals Only|Approval Required|Full Automation/.test(name)) {
        expect(r.getAttribute("aria-checked"), name).toBe("false");
      }
    }
  });

  it("keeps Continue disabled until the step is filled, then enables Start", async () => {
    await loaded();
    expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Choose an instrument/)).toBeDefined();
  });

  it("enables Start once every step is filled", async () => {
    await toReview();
    expect((screen.getByRole("button", { name: "Start on demo" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("works the money estimate out from the capital allocated, and says it is not a forecast", async () => {
    await toRisk();
    fireEvent.change(screen.getByLabelText("Capital allocated"), { target: { value: "10000" } });
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
  async function methods() {
    await toStrategy();
    fireEvent.click(screen.getByRole("tab", { name: /My methods/ }));
  }
  it("lists only methods built from conditions, not the preset rules the page made", async () => {
    await methods();
    expect(screen.getByRole("radio", { name: /My RSI dip/ })).toBeDefined();
    expect(screen.queryByText(/Trend Following · EURUSD/)).toBeNull();
    expect(screen.getByText(/2 entry and 1 exit conditions/)).toBeDefined();
    expect(screen.getByRole("link", { name: "Build a new method" }).getAttribute("href")).toBe("/rules/new");
  });

  it("starts from the client's own method, with no strategy field", async () => {
    await toStrategy(/^XAUUSD$/);
    fireEvent.click(screen.getByRole("tab", { name: /My methods/ }));
    fireEvent.click(screen.getByRole("radio", { name: /My RSI dip/ }));
    await waitFor(() => expect(
      screen.getByRole("radio", { name: /My RSI dip/ }).getAttribute("aria-checked")).toBe("true"));
    cont();
    fireEvent.change(await screen.findByLabelText("Capital allocated"), { target: { value: "10000" } });
    choose(/Approval Required/);
    cont();
    choose(/^Demo$/);
    cont();
    fireEvent.click(await screen.findByRole("button", { name: "Start on demo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes" }));
    await waitFor(() => expect(calls.some((c) => c.path === "automation/setup" && c.init?.method === "POST")).toBe(true));
    const body = calls.find((c) => c.path === "automation/setup" && c.init?.method === "POST")!
      .init!.body as Record<string, unknown>;
    expect(body.strategy).toBeUndefined();
    expect(body.sourceRuleId).toBe("m1");
    expect(body.symbols).toEqual(["XAUUSD"]);
    expect(body.account).toBe("demo");
  });
});

describe("the minimum-size warning", () => {
  const MIN_LOT = (over: Record<string, unknown> = {}) => ok({
    connected: true, status: "ok", accountId: 7, mode: "demo",
    minLot: {
      symbol: "XAUUSD", timeframe: "1h", minUnits: 1, unitLabel: "oz", units: 1,
      stopDistance: 100, targetUsd: 38.17, targetPct: 1, riskUsd: 97.4, riskPct: 2.55,
      exceeds: true, basis: "2.5 x ATR(14) on the last bars", ...over,
    },
  });

  it("appears under Risk when the broker's smallest order risks more than was chosen", async () => {
    routes["trade/min-lot"] = MIN_LOT();
    await toStrategy(/^XAUUSD$/);
    choose(/Trend Following/);
    cont();
    const note = await screen.findByText(/smallest order for XAUUSD is 1 oz/i, undefined, { timeout: 3000 });
    expect(note.textContent).toMatch(/more than the \$38\.17/);
    expect(note.textContent).toMatch(/estimate/i);
    expect(calls.some((c) => c.path.startsWith("trade/min-lot?symbol=XAUUSD"))).toBe(true);
  });

  it("does not appear when the minimum fits", async () => {
    routes["trade/min-lot"] = MIN_LOT({ exceeds: false, riskUsd: 30, riskPct: 0.8 });
    await toStrategy(/^XAUUSD$/);
    choose(/Trend Following/);
    cont();
    await waitFor(() => expect(calls.some((c) => c.path.startsWith("trade/min-lot"))).toBe(true), { timeout: 3000 });
    expect(screen.queryByText(/smallest order for/i)).toBeNull();
  });

  it("says it could not check, rather than staying silent, when the broker did not answer", async () => {
    routes["trade/min-lot"] = ok({ connected: true, status: "unavailable", reason: "timeout" });
    await toStrategy(/^XAUUSD$/);
    choose(/Trend Following/);
    cont();
    expect(await screen.findByText(/could not check the broker's minimum size/i, undefined, { timeout: 3000 })).toBeDefined();
  });

  it("asks nothing until an instrument is chosen", async () => {
    routes["trade/min-lot"] = MIN_LOT();
    await loaded();
    await new Promise((r) => setTimeout(r, 600));
    expect(calls.some((c) => c.path.startsWith("trade/min-lot"))).toBe(false);
  });

  it("does not stop Start: it informs, the client decides", async () => {
    routes["trade/min-lot"] = MIN_LOT();
    await toStrategy(/^XAUUSD$/);
    choose(/Trend Following/);
    cont();
    await screen.findByText(/smallest order for XAUUSD/i, undefined, { timeout: 3000 });
    fireEvent.change(screen.getByLabelText("Capital allocated"), { target: { value: "10000" } });
    choose(/Approval Required/);
    cont();
    choose(/^Demo$/);
    cont();
    expect((screen.getByRole("button", { name: "Start on demo" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("Start on demo", () => {
  it("posts the setup once, with what was chosen", async () => {
    await toRisk();
    choose(/^0\.5%$/);
    fireEvent.change(screen.getByLabelText("Capital allocated"), { target: { value: "10000" } });
    fireEvent.change(screen.getByLabelText(/Stop the day at/i), { target: { value: "3" } });
    choose(/Approval Required/);
    cont();
    choose(/^Demo$/);
    cont();
    fireEvent.click(await screen.findByRole("button", { name: "Start on demo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes" }));

    await waitFor(() => expect(calls.some((c) => c.path === "automation/setup" && c.init?.method === "POST")).toBe(true));
    const posts = calls.filter((c) => c.init?.method === "POST").map((c) => c.path);
    expect(posts.filter((p) => p === "automation/setup")).toEqual(["automation/setup"]);
    expect(posts).not.toContain("automation/start");
    const body = calls.find((c) => c.path === "automation/setup" && c.init?.method === "POST")!.init!.body as Record<string, unknown>;
    expect(body.symbols).toEqual(["EURUSD"]);
    expect(body.strategy).toBe("trend");
    expect(body.automationLevel).toBe("approval");
    expect(body.riskPercent).toBe(0.5);
    expect(body.maxDailyLossPercent).toBe(3);
    expect(body.capitalAllocated).toBe(10000);
    expect(body.account).toBe("demo");
    expect(body.stopLossPips).toBe(20);
    expect(body.takeProfitPips).toBe(40);
    expect(body.maxOpenPositions).toBe(1);
    await waitFor(() => expect(fireStartConfetti).toHaveBeenCalledTimes(1));
  });

  it("stops when the server refuses, and does not celebrate", async () => {
    routes["automation/setup"] = (init?: Call["init"]) => init?.method === "POST"
      ? { ok: false, status: 400, code: "SETUP_INVALID", message: "refused", problems: ["riskPercent: too high"] }
      : LIBRARY;
    await toReview();
    fireEvent.click(await screen.findByRole("button", { name: "Start on demo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes" }));
    await screen.findByText("SETUP_INVALID");
    expect(fireStartConfetti).not.toHaveBeenCalled();
  });

  it("is disabled with the reason while automation is already running", async () => {
    autoState = "running";
    await toReview();
    await screen.findByText(/already running/i);
    expect((screen.getByRole("button", { name: "Start on demo" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("live", () => {
  it("a closed live account turns Start into the next step and starts nothing", async () => {
    routes["ctrader/status"] = live;
    routes.me = me({ canAutomate: false, accountMode: "live", liveGate: {
      open: false, status: "closed", summary: "Terms not accepted yet.", conditions: [], missing: [],
      request: { status: "none" }, checkoutOpen: false } });
    await toAccount();
    choose(/^Live$/);
    cont();
    const links = await screen.findAllByRole("link", { name: "Request live access" });
    expect(links.length).toBeGreaterThan(0);
    expect(links[0].getAttribute("href")).toBe("/live");
    expect(screen.queryByRole("button", { name: /Start on/ })).toBeNull();
    expect(screen.getByText(/Terms not accepted yet/)).toBeDefined();
    expect(calls.some((c) => c.path === "automation/setup" && c.init?.method === "POST")).toBe(false);
  });

  it("a pending request reads as waiting for approval", async () => {
    routes["ctrader/status"] = live;
    routes.me = me({ canAutomate: false, accountMode: "live", liveGate: {
      open: false, status: "closed", summary: "x", conditions: [], missing: [],
      request: { status: "pending" }, checkoutOpen: false } });
    await toAccount();
    choose(/^Live$/);
    expect((await screen.findAllByText(/Awaiting approval/)).length).toBeGreaterThan(0);
  });

  it("an account the server allows still needs a confirmation that names it and says real money", async () => {
    routes["ctrader/status"] = live;
    routes.me = me({ canAutomate: true, accountMode: "live", liveGate: { open: true, status: "open", summary: "cleared", request: { status: "approved" } } });
    await toAccount();
    choose(/^Live$/);
    cont();
    fireEvent.click(await screen.findByRole("button", { name: "Start on live" }));
    const q = await screen.findByText(/LIVE account #9/);
    expect(q.textContent).toMatch(/Real money moves/);
    expect(calls.some((c) => c.init?.method === "POST" && c.path === "automation/setup")).toBe(false);
    screen.getByRole("button", { name: "Cancel" });
  });

  it("a server that refuses to execute live does not celebrate", async () => {
    routes["ctrader/status"] = live;
    routes.me = me({ canAutomate: true, accountMode: "live" });
    routes["automation/setup"] = (init?: Call["init"]) => init?.method === "POST"
      ? ok({ started: false, executed: false, account: "live",
             live: { open: false, state: "request", label: "Request live access", summary: "The gate is closed." } })
      : LIBRARY;
    await toAccount();
    choose(/^Live$/);
    cont();
    fireEvent.click(await screen.findByRole("button", { name: "Start on live" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes" }));
    expect(await screen.findByText(/The gate is closed/)).toBeDefined();
    expect(fireStartConfetti).not.toHaveBeenCalled();
  });
});
