/**
 * Rule Detail's contract with the API, checked through the rendered page.
 *
 * Three behaviours, each one a way the screen could lie about the market:
 *
 *   preview cannot run before candles came back ok — otherwise a verdict
 *   would be reached on bars nobody received;
 *
 *   the snapshot's ts is the LAST BAR's time, not this browser's clock —
 *   otherwise every session and weekday condition answers a question about
 *   now instead of about the data;
 *
 *   a failed market read shows the read state, never a verdict — a HOLD
 *   rendered over a 503 reads as "no setup".
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Suspense } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const calls: { path: string; init?: { method?: string; body?: unknown } }[] = [];
let routes: Record<string, unknown> = {};

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/rules/r1",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string, init?: { method?: string; body?: unknown }) => {
      calls.push({ path, init });
      const key = Object.keys(routes).find((k) => path.startsWith(k));
      if (!key) return { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" };
      return routes[key] as ApiResult<unknown>;
    }),
  };
});

import RuleDetail from "./page";

const RULE = {
  ruleDocId: "r1", name: "Test rule", state: "draft", version: 1,
  symbols: ["EUR_USD"], timeframe: "1h", sides: "BUY", updatedAt: 0,
};
const BARS = [
  { open: 1.1, high: 1.11, low: 1.09, close: 1.1, time: 1758542400 },
  { open: 1.1, high: 1.11, low: 1.09, close: 1.105, time: 1758546000 },
];

function baseRoutes() {
  return {
    "rules/r1/preview": { ok: true, data: {
      decision: { verdict: "HOLD", reason: "conditions not met", conditions: [],
                  executable: false, refusalCode: null, confidence: null },
      executable: false, wouldTrade: false,
    } },
    "rules/r1": { ok: true, data: { rule: RULE } },
    me: { ok: true, data: { user: { userId: "u1", email: "a@b.c", emailVerified: true },
                            licence: { state: "active", expiresAt: null, plan: "pro" } } },
    "ctrader/status": { ok: true, data: {
      connected: true, accounts: [{ ctid: 501, mode: "demo" }],
      selected: { ctid: 501, mode: "demo" }, liveAllowed: false,
    } },
    automation: { ok: true, data: { state: "stopped", ruleDocId: null, mode: null, startedAt: null } },
  } as Record<string, unknown>;
}

/**
 * The page reads its route params with React's `use`, which suspends on the
 * first render. Without a boundary the whole tree stays suspended and every
 * query below finds an empty body — which looks exactly like a page that
 * rendered nothing.
 */
/** Renders and flushes the suspended `use(params)` before returning. */
let container: HTMLElement;

async function renderPage() {
  await act(async () => {
    ({ container } = render(
      <Suspense fallback={<p>loading</p>}>
        <RuleDetail params={Promise.resolve({ id: "r1" })} />
      </Suspense>,
    ));
    // Let the params promise settle and the effects that follow it run.
    await Promise.resolve();
  });
}

/**
 * Whether a VERDICT is on screen.
 *
 * queryByText("BUY") is not the same question: the configuration table shows
 * the rule's `sides`, which is often literally "BUY". Scoping to the verdict
 * element is what makes this assert "no decision was rendered" rather than
 * "the string BUY appears nowhere".
 */
const verdictShown = () => container.querySelector(".verdict") !== null;

const isDisabled = (name: RegExp) =>
  (screen.getByRole("button", { name }) as HTMLButtonElement).disabled;

beforeEach(() => { calls.length = 0; routes = baseRoutes(); });
afterEach(() => { vi.clearAllMocks(); });

describe("Rule Detail — preview coupling", () => {
  it("will not preview until candles have come back ok", async () => {
    routes["accounts/501/candles"] = { ok: true, data: {
      connected: true, status: "ok", accountId: 501, mode: "demo",
      candles: BARS, symbol: "EUR_USD", timeframe: "1h", count: 2, requested: 300,
    } };
    await renderPage();
    await screen.findByRole("button", { name: /^Preview$/ });
    // Nothing has been fetched, so there is nothing to evaluate.
    expect(isDisabled(/^Preview$/)).toBe(true);
    expect(calls.some((c) => c.path.includes("/preview"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /Fetch market data/ }));
    await waitFor(() => expect(isDisabled(/^Preview$/)).toBe(false));
  });

  it("sends snapshot.ts from the last bar, not from the clock", async () => {
    routes["accounts/501/candles"] = { ok: true, data: {
      connected: true, status: "ok", accountId: 501, mode: "demo",
      candles: BARS, symbol: "EUR_USD", timeframe: "1h", count: 2, requested: 300,
    } };
    await renderPage();
    await screen.findByRole("button", { name: /Fetch market data/ });
    fireEvent.click(screen.getByRole("button", { name: /Fetch market data/ }));
    await waitFor(() => expect(isDisabled(/^Preview$/)).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: /^Preview$/ }));

    await waitFor(() => expect(
      calls.some((c) => c.path.includes("/preview"))).toBe(true));
    const sent = calls.find((c) => c.path.includes("/preview"))!;
    const body = sent.init!.body as { snapshot: { ts: number; candles: unknown[]; timeframe: string } };
    expect(body.snapshot.ts).toBe(BARS[BARS.length - 1].time);
    // Not "roughly now" — exactly the bar's own time.
    expect(body.snapshot.ts).not.toBe(Math.floor(Date.now() / 1000));
    expect(body.snapshot.candles).toHaveLength(2);
    expect(body.snapshot.timeframe).toBe("1h");
    // Only the four prices travel; `time` is not part of the snapshot contract.
    expect(Object.keys(body.snapshot.candles[0] as object).sort())
      .toEqual(["close", "high", "low", "open"]);
  });

  it.each([
    ["reauth_required", /Reconnect cTrader/],
    ["not_connected", /No account selected/],
  ])("shows the read state for %s instead of a verdict", async (status, expected) => {
    routes["accounts/501/candles"] = { ok: true, data: {
      connected: status !== "not_connected", status,
      reason: "the cTrader authorisation has expired",
    } };
    await renderPage();
    await screen.findByRole("button", { name: /Fetch market data/ });
    fireEvent.click(screen.getByRole("button", { name: /Fetch market data/ }));

    await waitFor(() => expect(screen.getByText(expected)).toBeDefined());
    // No verdict anywhere, and preview stays out of reach.
    expect(verdictShown()).toBe(false);
    expect(isDisabled(/^Preview$/)).toBe(true);
    expect(calls.some((c) => c.path.includes("/preview"))).toBe(false);
  });

  it("shows the broker's own reason when the read is unavailable", async () => {
    routes["accounts/501/candles"] = { ok: true, data: {
      connected: true, status: "unavailable",
      reason: "TimeoutError: cTrader did not answer within 12s",
    } };
    await renderPage();
    await screen.findByRole("button", { name: /Fetch market data/ });
    fireEvent.click(screen.getByRole("button", { name: /Fetch market data/ }));
    await waitFor(() => expect(
      screen.getByText(/TimeoutError: cTrader did not answer/)).toBeDefined());
    expect(verdictShown()).toBe(false);
    expect(isDisabled(/^Preview$/)).toBe(true);
  });

  it("surfaces a failed candles request as an error, not as an empty market", async () => {
    routes["accounts/501/candles"] = {
      ok: false, status: 400, code: "NO_SUCH_ACCOUNT",
      message: "that account is not one of the connected ones",
    };
    await renderPage();
    await screen.findByRole("button", { name: /Fetch market data/ });
    fireEvent.click(screen.getByRole("button", { name: /Fetch market data/ }));
    await waitFor(() => expect(screen.getByText("NO_SUCH_ACCOUNT")).toBeDefined());
    expect(verdictShown()).toBe(false);
    expect(calls.some((c) => c.path.includes("/preview"))).toBe(false);
  });
});

/**
 * The three outcomes a preview can reach, each as its own state on screen.
 *
 * These are the states a client acts on. A HOLD that renders as an empty
 * panel and a REJECT that renders as an empty panel teach the reader that
 * nothing happened, when one of the two means their rule cannot run at all.
 */
describe("Rule Detail — preview outcomes are first-class", () => {
  const candlesOk = {
    ok: true, data: {
      connected: true, status: "ok", accountId: 501, mode: "demo",
      candles: BARS, symbol: "EUR_USD", timeframe: "1h", count: 2, requested: 300,
    },
  };

  async function previewWith(decision: Record<string, unknown>, wouldTrade: boolean) {
    routes["accounts/501/candles"] = candlesOk;
    routes["rules/r1/preview"] = {
      ok: true,
      data: { decision, executable: false, wouldTrade },
    };
    await renderPage();
    await screen.findByRole("button", { name: /Fetch market data/ });
    fireEvent.click(screen.getByRole("button", { name: /Fetch market data/ }));
    await waitFor(() => expect(isDisabled(/^Preview$/)).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: /^Preview$/ }));
    await waitFor(() => expect(container.querySelector(".verdict")).not.toBeNull());
    return container.querySelector(".verdict")!;
  }

  it("a tradeable decision reads SETUP and names the side", async () => {
    const v = await previewWith({
      verdict: "BUY", reason: "all conditions met",
      conditions: [{ id: "rsi", passed: true, detail: "RSI 61 > 55" }],
      executable: true, refusalCode: null, confidence: null,
    }, true);
    expect(v.textContent).toContain("SETUP");
    expect(v.textContent).toContain("BUY");
    expect(screen.getByText(/would open a BUY position/)).toBeDefined();
    // Even a tradeable preview must say it placed nothing.
    expect(screen.getByText(/This preview placed nothing/)).toBeDefined();
  });

  it("HOLD says the rule ran and chose not to act", async () => {
    const v = await previewWith({
      verdict: "HOLD", reason: "RSI below the threshold",
      conditions: [{ id: "rsi", passed: false, detail: "RSI 41 < 55" }],
      executable: false, refusalCode: null, confidence: null,
    }, false);
    expect(v.textContent).toContain("HOLD");
    expect(v.textContent).not.toContain("SETUP");
    expect(screen.getByText(/ran and chose not to act/)).toBeDefined();
  });

  it("REJECT carries the refusal code and says no order would be placed", async () => {
    const v = await previewWith({
      verdict: "REJECT", reason: "not enough history for ATR(14)",
      conditions: [{ id: "atr", passed: null, detail: "20 bars, needs 15" }],
      executable: false, refusalCode: "INSUFFICIENT_DATA", confidence: null,
    }, false);
    expect(v.textContent).toContain("REJECT");
    expect(screen.getByText(/INSUFFICIENT_DATA/)).toBeDefined();
    expect(screen.getByText(/No order would be placed/)).toBeDefined();
  });

  it("an unknown condition is reported as unknown, never folded into 'not met'", async () => {
    await previewWith({
      verdict: "REJECT", reason: "not enough history",
      conditions: [
        { id: "atr", passed: null, detail: "20 bars, needs 15" },
        { id: "rsi", passed: false, detail: "RSI 41 < 55" },
      ],
      executable: false, refusalCode: "INSUFFICIENT_DATA", confidence: null,
    }, false);
    expect(screen.getByText("unknown")).toBeDefined();
    expect(screen.getByText("not met")).toBeDefined();
    expect(screen.getByText(/1 condition could not be computed/)).toBeDefined();
    // Counted as met/total, with unknown excluded from "met".
    expect(screen.getByText("0/2")).toBeDefined();
  });

  it("shows the whole rule document, not only symbols and timeframe", async () => {
    routes["rules/r1"] = { ok: true, data: { rule: {
      ...RULE,
      sizing: { mode: "risk_percent", riskPercent: 1.0 },
      stopLoss: { mode: "atr", atrMultiple: 1.5 },
      takeProfit: { mode: "rr", rr: 2 },
      limits: { maxOpenPositions: 2, onLimit: "block", maxSpreadPips: 3 },
      entry: { combine: "AND", conditions: [{ id: "rsi", params: { period: 14 } }] },
    } } };
    await renderPage();
    await screen.findByText("Rule terms");
    for (const term of ["Sizing", "Stop loss", "Take profit", "Trailing stop",
                        "Break even", "Max open positions", "Max spread",
                        "Schedule", "Order type", "Max slippage"]) {
      expect(screen.getByText(term), `${term} is missing from the terms`).toBeDefined();
    }
    expect(screen.getByText("risk 1% per trade")).toBeDefined();
    expect(screen.getByText("stop 1.5× ATR")).toBeDefined();
    expect(screen.getByText("3 pips")).toBeDefined();
  });
});

/**
 * Preview is read-only, proven three ways.
 *
 * A screen that says "this is what would happen" is the one place where an
 * "…and do it" button is most tempting to add. Asserting the current
 * behaviour is not enough — the assertions below are structural, so they
 * still hold after somebody rewrites the component.
 */
describe("Rule Detail — preview cannot trade", () => {
  const SRC = readFileSync(join(__dirname, "page.tsx"), "utf8");

  it("the page references no order, close or amend endpoint", () => {
    for (const forbidden of ["force_trade", "place_order", "positions/close",
                             "orders/close", "/amend", "authorize_order"]) {
      expect(SRC, `the rule page references ${forbidden}`).not.toContain(forbidden);
    }
  });

  it("previewing issues exactly one POST, to the preview endpoint", async () => {
    routes["accounts/501/candles"] = { ok: true, data: {
      connected: true, status: "ok", accountId: 501, mode: "demo",
      candles: BARS, symbol: "EUR_USD", timeframe: "1h", count: 2, requested: 300,
    } };
    await renderPage();
    await screen.findByRole("button", { name: /Fetch market data/ });
    fireEvent.click(screen.getByRole("button", { name: /Fetch market data/ }));
    await waitFor(() => expect(isDisabled(/^Preview$/)).toBe(false));

    calls.length = 0;
    fireEvent.click(screen.getByRole("button", { name: /^Preview$/ }));
    await waitFor(() => expect(calls.some((c) => c.path.includes("/preview"))).toBe(true));

    const writes = calls.filter((c) => c.init?.method && c.init.method !== "GET");
    expect(writes.map((w) => w.path)).toEqual([`rules/r1/preview`]);
  });

  it("the verdict states that nothing was placed, whatever it decided", async () => {
    routes["accounts/501/candles"] = { ok: true, data: {
      connected: true, status: "ok", accountId: 501, mode: "demo",
      candles: BARS, symbol: "EUR_USD", timeframe: "1h", count: 2, requested: 300,
    } };
    routes["rules/r1/preview"] = { ok: true, data: {
      decision: { verdict: "BUY", reason: "met", conditions: [],
                  executable: true, refusalCode: null, confidence: null },
      executable: false, wouldTrade: true,
    } };
    await renderPage();
    await screen.findByRole("button", { name: /Fetch market data/ });
    fireEvent.click(screen.getByRole("button", { name: /Fetch market data/ }));
    await waitFor(() => expect(isDisabled(/^Preview$/)).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: /^Preview$/ }));
    await waitFor(() => expect(screen.getByText(/This preview placed nothing/)).toBeDefined());
  });

  it("draws the evaluated bars, and marks the bar the snapshot was stamped with", async () => {
    routes["accounts/501/candles"] = { ok: true, data: {
      connected: true, status: "ok", accountId: 501, mode: "demo",
      candles: BARS, symbol: "EUR_USD", timeframe: "1h", count: 2, requested: 300,
    } };
    await renderPage();
    await screen.findByRole("button", { name: /Fetch market data/ });
    // No chart before the bars arrive — there is nothing to draw.
    expect(container.querySelector("svg.candles")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Fetch market data/ }));
    await waitFor(() => expect(container.querySelector("svg.candles")).not.toBeNull());
    // And no marker until something has actually been evaluated.
    expect(screen.queryAllByTestId("chart-marker")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: /^Preview$/ }));
    await waitFor(() => expect(screen.getAllByTestId("chart-marker")).toHaveLength(1));
  });

  it("no chart is drawn over a read that failed", async () => {
    routes["accounts/501/candles"] = { ok: true, data: {
      connected: true, status: "unavailable", reason: "TimeoutError",
    } };
    await renderPage();
    await screen.findByRole("button", { name: /Fetch market data/ });
    fireEvent.click(screen.getByRole("button", { name: /Fetch market data/ }));
    await waitFor(() => expect(screen.getByText(/TimeoutError/)).toBeDefined());
    expect(container.querySelector("svg.candles")).toBeNull();
    expect(verdictShown()).toBe(false);
  });
});

/**
 * Activation is the server's call, not this page's.
 *
 * The page used to test `licence !== "active"` and refuse activation itself.
 * That is stricter than the server, which only refuses a WITHDRAWN licence —
 * activation records terms, it does not trade — and it dead-ended the entire
 * free tier: a demo client could build a rule through eleven steps and then
 * never activate it, so they could never start anything. Found by driving the
 * real screens in a browser.
 */
describe("Rule Detail — who decides activation", () => {
  function withExecution(exec: unknown) {
    const r = baseRoutes();
    r.me = { ok: true, data: {
      user: { userId: "u1", email: "a@b.c", emailVerified: true },
      licence: { state: "none", expiresAt: null, plan: null },
      ...(exec === undefined ? {} : { execution: exec }),
    } };
    return r;
  }

  it("offers activation to a client with NO licence when the server allows it", async () => {
    routes = withExecution({ canActivate: true, activationRefusal: null });
    await renderPage();
    expect(await screen.findByRole("button", { name: /activate this rule/i })).toBeTruthy();
    expect(screen.queryByText(/needs an active licence/i)).toBeNull();
  });

  it("refuses in the server's words when the server refuses", async () => {
    routes = withExecution({
      canActivate: false,
      activationRefusal: "this licence was withdrawn — contact support",
    });
    await renderPage();
    expect(await screen.findByText(/withdrawn — contact support/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /activate this rule/i })).toBeNull();
  });

  it("neither offers nor refuses while the answer is still missing", async () => {
    // A body with no `execution` has not said what this account may do.
    // Offering the control would be a guess; refusing would be a lie.
    routes = withExecution(undefined);
    await renderPage();
    expect(await screen.findByText(/checking what this account may do/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /activate this rule/i })).toBeNull();
    expect(screen.queryByText(/cannot activate/i)).toBeNull();
  });

  it("and does not crash on it, which is how this guard was found", async () => {
    routes = withExecution(undefined);
    await renderPage();
    expect(document.body.textContent).toContain("Checking what this account");
    expect(document.body.textContent!.length).toBeGreaterThan(200);
  });
});

/**
 * Who decides whether automation may START.
 *
 * The same defect as the activation block above, and it survived the fix that
 * removed it from there: `licence !== "active"` sat on the Start button
 * twenty lines below the comment explaining why it had been wrong.
 *
 * Demo automation is free. A client with no licence is `free_demo` and the
 * server answers canAutomate: true for them — so this screen refused with
 * "An active licence is required" while the dashboard's Start button, reading
 * the same account, was enabled and worked. Two screens in one product
 * disagreeing about whether somebody may start, and the one that says no is
 * the one you reach from the rule itself.
 */
describe("Rule Detail — who decides whether automation may start", () => {
  function withExecution(exec: unknown, licence = "none") {
    const r = baseRoutes();
    // ACTIVE, because a draft is refused by the step before this one and
    // every case below would then pass for the wrong reason.
    r["rules/r1"] = { ok: true, data: { rule: { ...RULE, state: "active" } } };
    r.me = { ok: true, data: {
      user: { userId: "u1", email: "a@b.c", emailVerified: true },
      licence: { state: licence, expiresAt: null, plan: null },
      ...(exec === undefined ? {} : { execution: exec }),
    } };
    return r;
  }

  it("lets a client with NO licence start, when the server says they may", async () => {
    routes = withExecution(
      { canActivate: true, activationRefusal: null, canAutomate: true });
    await renderPage();
    const start = await screen.findByRole("button", { name: /start on demo/i });
    expect(start).toHaveProperty("disabled", false);
    expect(screen.queryByText(/an active licence is required/i)).toBeNull();
  });

  it("refuses in the SERVER's words, not in a sentence this page invented", async () => {
    routes = withExecution({
      canActivate: true, activationRefusal: null,
      canAutomate: false,
      message: "this licence was withdrawn — contact support",
    });
    await renderPage();
    expect(await screen.findByText(/withdrawn — contact support/i)).toBeTruthy();
    expect((await screen.findByRole("button", { name: /start on demo/i })))
      .toHaveProperty("disabled", true);
  });

  it("does not claim access while the answer is still missing", async () => {
    // No `execution` key: the server has not said. Enabling the control would
    // be a guess, and naming a licence as the reason would be an invention.
    routes = withExecution(undefined);
    await renderPage();
    const start = await screen.findByRole("button", { name: /start on demo/i });
    expect(start).toHaveProperty("disabled", true);
    expect(document.body.textContent).toMatch(/access is being checked/i);
  });

  it("an ACTIVE licence is not what unlocks it either", async () => {
    // The mirror of the first case, and the one that makes it non-vacuous:
    // if the gate were still reading the licence, this would pass while a
    // free-tier client stayed locked out. Here the licence is active and the
    // server still says no, and the server wins.
    routes = withExecution(
      { canActivate: true, activationRefusal: null, canAutomate: false,
        message: "connect a cTrader demo account and select it" },
      "active");
    await renderPage();
    expect((await screen.findByRole("button", { name: /start on demo/i })))
      .toHaveProperty("disabled", true);
    expect(await screen.findByText(/connect a ctrader demo account/i)).toBeTruthy();
  });
});
