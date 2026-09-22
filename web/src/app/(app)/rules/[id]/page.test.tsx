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
    ["not_connected", /No cTrader account is connected/],
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
