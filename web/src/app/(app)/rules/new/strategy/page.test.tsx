/**
 * The strategy picker's contract with the client, checked through the page.
 *
 * WHAT THIS SCREEN IS FOR
 *
 * The engine ships fifteen ready-made strategies and this platform exposed
 * none of them, so the only way to trade here was to write a rule from
 * scratch. The thing that makes offering them honest rather than a menu of
 * nice words is that a client can read WHAT EACH ONE REFUSES before picking
 * it — five of the fifteen refuse nothing beyond "the setup is not there",
 * and a picker that hides that is selling fifteen strategies when it has ten.
 *
 * So the assertions below are mostly about what is legible without clicking:
 * every strategy present, every refusal visible unexpanded, and nothing on
 * the screen that the server did not say.
 *
 * And two failure shapes:
 *
 *   an empty catalogue is NOT rendered as "no strategies exist" — the server
 *   answers with nothing only when the registry could not be read, and a
 *   confident empty list over that is the fabricated screen this product
 *   forbids;
 *
 *   saving takes two calls (POST builds the draft, PUT writes the strategy,
 *   because POST /rules copies a fixed field list that does not include it).
 *   If the PUT fails, the draft exists and cannot be activated, and the page
 *   has to say so instead of navigating to a rule that looks finished.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult, StrategyCatalogue } from "@/lib/api";

const calls: { path: string; init?: { method?: string; body?: unknown } }[] = [];
let routes: Record<string, unknown> = {};
const pushed: string[] = [];

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: (p: string) => pushed.push(p), refresh: vi.fn() }),
  usePathname: () => "/rules/new/strategy",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string,
                      init?: { method?: string; body?: unknown }) => {
      calls.push({ path, init });
      const key = Object.keys(routes).find((k) => path.startsWith(k));
      if (!key) {
        return { ok: false, status: 404, code: "NOT_FOUND",
                 message: "no stub" };
      }
      return routes[key] as ApiResult<unknown>;
    }),
  };
});

import PickStrategyPage from "./page";

// A trimmed catalogue in the shape the server serves, including one of the
// five that refuse nothing — the case the screen has to be honest about.
const CATALOGUE: StrategyCatalogue = {
  ruleBuilderId: "platform_rule",
  presetField: "strategy",
  strategies: [
    {
      id: "auto", label: "Auto (regime-adaptive)", version: "1.0.0",
      family: "adaptive",
      what: "Reads the market regime every cycle.",
      decides: "detect_regime picks trend, mean reversion or breakout.",
      refuses: "New entries while the regime reads quiet.",
      source: "apex/ai.py:auto_engine",
    },
    {
      id: "trend", label: "Trend Following", version: "1.0.0",
      family: "trend",
      what: "Buys pullbacks inside a confirmed uptrend.",
      decides: "EMA50 over EMA200, then a pullback to EMA20.",
      refuses: "Entries with no confirmed trend, and entries with no pullback.",
      source: "apex/ai.py:trend_signal",
    },
    {
      id: "fvg", label: "Fair Value Gap (FVG)", version: "1.0.0",
      family: "structure",
      what: "Enters when price trades back into an unfilled gap.",
      decides: "Takes the detector's side at a fixed confidence of 70.",
      refuses: "Only the absence of a gap. No trend, session or volatility "
               + "filter.",
      source: "apex/ai.py:fvg_signal",
    },
  ],
  withheld: [
    { id: "grid", label: "Grid (capped, ranging only)", kind: "high_risk",
      reason: "It adds exposure to a position that is already losing." },
    { id: "platform_rule", label: "Your rule", kind: "rule_builder",
      reason: "This is the rule builder, not a preset." },
  ],
};

function baseRoutes() {
  return { strategies: { ok: true, data: CATALOGUE } } as Record<string,
                                                                 unknown>;
}

async function renderPage() {
  await act(async () => {
    render(<PickStrategyPage />);
    await Promise.resolve();
  });
  await screen.findByRole("heading", { name: /Choose a strategy/ });
}

const saveButton = () =>
  screen.getByRole("button", { name: /Save draft/ }) as HTMLButtonElement;

beforeEach(() => { calls.length = 0; pushed.length = 0; routes = baseRoutes(); });
afterEach(() => { vi.clearAllMocks(); });

describe("what a client can read before choosing", () => {
  it("lists every strategy the server sent", async () => {
    await renderPage();
    for (const s of CATALOGUE.strategies) {
      expect(await screen.findByText(s.label)).toBeTruthy();
    }
  });

  it("shows what each one REFUSES without expanding anything", async () => {
    await renderPage();
    // The field that decides whether offering these is honest. A detail
    // behind a disclosure button is a detail nobody read.
    for (const s of CATALOGUE.strategies) {
      expect(screen.getByText(s.refuses, { exact: false })).toBeTruthy();
    }
    // Including the one that refuses nothing. If this ever disappears, the
    // screen is selling a filter that strategy does not have.
    expect(screen.getByText(/No trend, session or volatility filter/))
      .toBeTruthy();
  });

  it("keeps how-it-decides behind a control, and shows it when asked",
     async () => {
    await renderPage();
    expect(screen.queryByText(CATALOGUE.strategies[1].decides)).toBeNull();
    fireEvent.click(screen.getAllByRole("button",
                                        { name: /How it decides/ })[1]);
    expect(await screen.findByText(CATALOGUE.strategies[1].decides))
      .toBeTruthy();
    // The code the sentence was written from, so a claim about money can be
    // checked rather than trusted.
    expect(screen.getByText("apex/ai.py:trend_signal")).toBeTruthy();
  });

  it("answers 'where is grid' with the server's reason, not silence",
     async () => {
    await renderPage();
    expect(screen.getByText(/adds exposure to a position that is already losing/))
      .toBeTruthy();
    expect(screen.getByText(/This is the rule builder, not a preset/))
      .toBeTruthy();
  });

  it("renders nothing the server did not say", async () => {
    // A strategy the server does not serve must not appear from a list kept
    // in the browser. `momentum` is real in the engine and absent here.
    await renderPage();
    expect(screen.queryByText(/Momentum/)).toBeNull();
    expect(screen.queryByText("Z-Score Reversion (statistical)")).toBeNull();
  });
});

describe("saving a chosen strategy", () => {
  // A level nobody chose is a rule that places orders without asking, so the
  // draft needs one picked as well as a strategy. Both are required, and each
  // missing one keeps Save off.
  it("cannot be saved until a strategy AND a level are chosen", async () => {
    await renderPage();
    expect(saveButton().disabled).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: /Trend Following/ }));
    await waitFor(() => expect(document.body.textContent).toContain("before saving"));
    expect(saveButton().disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Approval Required" }));
    await waitFor(() => expect(saveButton().disabled).toBe(false));
  });

  it("a level alone is not enough: a strategy is still needed", async () => {
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Signals Only" }));
    expect(saveButton().disabled).toBe(true);
  });

  it("creates the draft and then writes the strategy onto it", async () => {
    routes["rules/r9"] = { ok: true, data: { rule: { ruleDocId: "r9" } } };
    routes["rules"] = { ok: true, data: { rule: { ruleDocId: "r9" } } };
    await renderPage();
    fireEvent.click(screen.getByRole("radio", { name: /Trend Following/ }));
    fireEvent.click(screen.getByRole("button", { name: "Approval Required" }));
    fireEvent.click(saveButton());

    await waitFor(() => expect(pushed).toEqual(["/rules/r9"]));
    const writes = calls.filter((c) => c.init?.method);
    expect(writes.map((c) => [c.init!.method, c.path])).toEqual([
      ["POST", "rules"],
      ["PUT", "rules/r9"],
    ]);
    const put = writes[1].init!.body as {
      strategy: string;
      entry: { conditions: unknown[] };
      exit: { conditions: unknown[] };
      sizing: unknown;
      stopLoss: unknown;
    };
    expect(put.strategy).toBe("trend");
    // No conditions: the strategy decides its own, and the server refuses a
    // preset document that carries any.
    expect(put.entry.conditions).toEqual([]);
    expect(put.exit.conditions).toEqual([]);
    // The terms that DO reach the engine still travel.
    expect(put.sizing).toBeTruthy();
    expect(put.stopLoss).toBeTruthy();
  });

  it("does not navigate when the strategy write fails, and says the draft "
     + "cannot be activated", async () => {
    routes["rules/r9"] = { ok: false, status: 409, code: "CONFLICT",
                           message: "the draft could not be patched" };
    routes["rules"] = { ok: true, data: { rule: { ruleDocId: "r9" } } };
    await renderPage();
    fireEvent.click(screen.getByRole("radio", { name: /Trend Following/ }));
    fireEvent.click(screen.getByRole("button", { name: "Approval Required" }));
    fireEvent.click(saveButton());

    expect(await screen.findByText(/cannot be activated as it stands/))
      .toBeTruthy();
    // The backend's own words, not a friendlier sentence invented here.
    expect(screen.getByText("the draft could not be patched")).toBeTruthy();
    expect(pushed).toEqual([]);
  });
});

describe("when the catalogue is empty", () => {
  it("says the registry could not be read instead of 'no strategies'",
     async () => {
    routes.strategies = { ok: true,
                          data: { ...CATALOGUE, strategies: [], withheld: [] } };
    await renderPage();
    expect(screen.getByText(/registry could not be read/)).toBeTruthy();
    expect(saveButton().disabled).toBe(true);
  });

  it("names strategies the engine registers that this release cannot "
     + "describe", async () => {
    routes.strategies = { ok: true,
                          data: { ...CATALOGUE, unclassified: ["carry_trade"] } };
    await renderPage();
    expect(screen.getByText(/carry_trade/)).toBeTruthy();
  });
});
