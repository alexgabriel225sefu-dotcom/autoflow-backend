/**
 * The whole chain with the REAL `useRead`: timer, tab visibility, the api
 * call, the panel, and the chart (the charting library itself is still the
 * recorder). This is the test that the 5-second claim is true of the running
 * code and not only of a number passed to a mock.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const h = vi.hoisted(() => ({
  calls: [] as { path: string; method?: string }[],
  candles: null as unknown,
  positions: null as unknown,
  quote: null as unknown,
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: vi.fn(async (path: string, init?: { method?: string }) => {
    h.calls.push({ path, method: init?.method });
    if (path.includes("/quote")) return h.quote as ApiResult<unknown>;
    return (path.startsWith("accounts/") ? h.candles : h.positions) as ApiResult<unknown>;
  }),
}));
vi.mock("lightweight-charts", async () => (await import("@/test/lightweight-charts-mock")).factory());

import { lwc } from "@/test/lightweight-charts-mock";
import { createChart } from "lightweight-charts";
import { MarketPanel } from "./market-panel";

const T0 = 1_758_542_400;
const bar = (i: number, close: number) => ({ time: T0 + i * 3600, open: close - 0.001, high: close + 0.002, low: close - 0.002, close });
const readOf = (closes: number[]) => ({
  ok: true, data: {
    connected: true, status: "ok", accountId: 501, mode: "demo",
    candles: closes.map((c, i) => bar(i, c)), symbol: "EURUSD", timeframe: "1h", count: closes.length, requested: 200,
  },
});
const asBar = (i: number, close: number) => bar(i, close);

const candleCalls = () => h.calls.filter((c) => c.path.includes("/candles"));
const quoteCalls = () => h.calls.filter((c) => c.path.includes("/quote"));
const QUOTE_OK = (over: Record<string, unknown> = {}) => ({
  ok: true, data: {
    connected: true, status: "ok", accountId: 501, mode: "demo", symbol: "EURUSD",
    bid: 1.1215, ask: 1.1217, mid: 1.1216, receivedAt: T0 + 2 * 3600 + 60,
    ageSec: 1, stale: false, ...over,
  },
});
const positionCalls = () => h.calls.filter((c) => c.path === "positions");

async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}
function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "Date"] });
  h.calls.length = 0;
  lwc.reset();
  vi.mocked(createChart).mockClear();
  h.candles = readOf([1.10, 1.11, 1.12]);
  h.quote = QUOTE_OK();
  h.positions = { ok: true, data: { connected: true, status: "ok", accountId: 501, mode: "demo", positions: [] } };
  setHidden(false);
});
afterEach(() => { vi.useRealTimers(); setHidden(false); });

async function mount() {
  await act(async () => {
    render(<MarketPanel ctid={501} mode="demo" symbols={["EURUSD"]} timeframe="1h" />);
    await vi.advanceTimersByTimeAsync(0);
  });
}

describe("the live loop, with the real hook", () => {
  it("reads once on mount, then once every 5 seconds — not sooner", async () => {
    await mount();
    expect(candleCalls()).toHaveLength(1);
    await tick(4_999);
    expect(candleCalls(), "polled before 5 s").toHaveLength(1);
    await tick(1);
    expect(candleCalls()).toHaveLength(2);
    await tick(5_000);
    expect(candleCalls()).toHaveLength(3);
    // The positions behind the lines run on the same clock.
    expect(positionCalls()).toHaveLength(3);
  });

  it("only ever issues GETs", async () => {
    await mount();
    await tick(10_000);
    expect(h.calls.length).toBeGreaterThan(2);
    for (const c of h.calls) expect(c.method ?? "GET").toBe("GET");
  });

  it("applies each refresh to the same chart with series.update", async () => {
    // This test is about how the CANDLE read reaches the chart. The live price
    // is made stale so it cannot move the last bar and muddy that: what a
    // quote does to the last candle has its own tests below.
    h.quote = QUOTE_OK({ stale: true, ageSec: 60 });
    await mount();
    expect(createChart).toHaveBeenCalledTimes(1);
    const series = lwc.seriesOf("candlestick")[0];
    expect(series.setData).toHaveBeenCalledTimes(1);

    // The last candle moves.
    h.candles = readOf([1.10, 1.11, 1.125]);
    await tick(5_000);
    expect(series.update).toHaveBeenLastCalledWith(asBar(2, 1.125));

    // A new candle opens.
    h.candles = readOf([1.10, 1.11, 1.125, 1.13]);
    await tick(5_000);
    expect(series.update).toHaveBeenLastCalledWith(asBar(3, 1.13));

    expect(createChart, "the chart was recreated on refresh").toHaveBeenCalledTimes(1);
    expect(series.setData, "the data was reset on refresh").toHaveBeenCalledTimes(1);
  });

  it("pauses while the tab is hidden and catches up when it returns", async () => {
    await mount();
    setHidden(true);
    await tick(20_000);
    expect(candleCalls(), "polled a hidden tab").toHaveLength(1);

    setHidden(false);
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(candleCalls()).toHaveLength(2);
  });

  it("goes stale on screen while the tab is hidden, because nothing has refreshed it", async () => {
    await mount();
    setHidden(true);
    await tick(40_000);
    // The candle sync line carries its own marker (the live price has one too,
    // so the text alone is no longer unique).
    expect(document.querySelector(".sync-line .pill-warn")?.textContent).toBe("stale");
    expect(screen.getByText(/Last synced \d+s ago/)).toBeDefined();
  });

  it("replaces the chart with the error, and marks it stale, when a refresh fails", async () => {
    await mount();
    expect(document.querySelector(".price-chart")).not.toBeNull();
    h.candles = { ok: false, status: 0, code: "NETWORK", message: "Failed to fetch" };
    await tick(5_000);
    expect(screen.getByText("NETWORK")).toBeDefined();
    expect(document.querySelector(".price-chart")).toBeNull();
    expect(screen.getByText("stale")).toBeDefined();
  });

  it("recovers to a live chart when the broker comes back", async () => {
    await mount();
    h.candles = { ok: false, status: 503, code: "BROKER_DOWN", message: "no answer" };
    await tick(5_000);
    expect(document.querySelector(".price-chart")).toBeNull();
    h.candles = readOf([1.10, 1.11, 1.12]);
    await tick(5_000);
    expect(document.querySelector(".price-chart")).not.toBeNull();
    expect(screen.queryByText("stale")).toBeNull();
  });
});


describe("the live price, with the real hook", () => {
  it("reads the quote on mount, then every 3 seconds — not sooner", async () => {
    await mount();
    expect(quoteCalls()).toHaveLength(1);
    await tick(2_999);
    expect(quoteCalls(), "polled before 3 s").toHaveLength(1);
    await tick(1);
    expect(quoteCalls()).toHaveLength(2);
  });

  it("asks for the instrument that is charted", async () => {
    await mount();
    expect(quoteCalls()[0].path).toBe("accounts/501/quote?symbol=EURUSD");
  });

  it("does not spend the historical budget faster: candles still every 5 s", async () => {
    await mount();
    await tick(12_000);
    // 1 on mount + 2 refreshes in 12 s. The faster quote cadence must not
    // have dragged the candle read along with it.
    expect(candleCalls()).toHaveLength(3);
    expect(quoteCalls().length).toBeGreaterThanOrEqual(4);
  });

  it("only ever issues GETs for the price", async () => {
    await mount();
    await tick(10_000);
    for (const c of quoteCalls()) expect(c.method ?? "GET").toBe("GET");
  });

  it("shows bid, ask and how old the price is", async () => {
    await mount();
    const line = screen.getByTestId("live-price");
    // Four decimals, as the broker sent them. With the precision taken from
    // the candles alone these read "1.121" and "1.122": less than the broker
    // gave, and not the price the client would see in cTrader.
    expect(line.textContent).toContain("Bid 1.1215");
    expect(line.textContent).toContain("Ask 1.1217");
    expect(line.textContent).toMatch(/just now|\d+ s ago/);
  });

  it("moves the last candle to the bid when the price is inside it", async () => {
    await mount();
    const series = lwc.seriesOf("candlestick")[0];
    const lastSet = series.setData.mock.calls.at(-1)![0];
    expect(lastSet.at(-1).close).toBe(1.1215);
  });

  it("does NOT move the candle with a stale price", async () => {
    h.quote = QUOTE_OK({ stale: true, ageSec: 60 });
    await mount();
    const series = lwc.seriesOf("candlestick")[0];
    const lastSet = series.setData.mock.calls.at(-1)![0];
    expect(lastSet.at(-1).close).toBe(1.12);               // the candle read, untouched
    expect(screen.getByTestId("live-price").textContent).toMatch(/stale/);
  });

  it("ages the price on screen when polls stop, instead of freezing at '1 s ago'", async () => {
    await mount();
    expect(screen.getByTestId("live-price").textContent).not.toMatch(/stale/);
    // A hidden tab stops polling. Nothing refreshes the price, so the age it
    // was shown with must keep growing on its own clock.
    setHidden(true);
    await tick(20_000);
    const text = screen.getByTestId("live-price").textContent ?? "";
    expect(text).toMatch(/stale/);
    expect(text).toMatch(/\b(1[5-9]|2\d) s ago/);
  });

  it("says so, and keeps the chart, when the price cannot be read", async () => {
    h.quote = { ok: false, status: 503, code: "STORE_UNAVAILABLE", message: "broker down" };
    await mount();
    expect(screen.getByTestId("live-price").textContent).toMatch(/Live price unavailable/);
    expect(screen.getByTestId("live-price").textContent).toMatch(/last candles received/);
    expect(createChart).toHaveBeenCalledTimes(1);          // the chart is still there
  });

  it("does not show a price for a different instrument", async () => {
    h.quote = QUOTE_OK({ symbol: "GBPUSD" });
    await mount();
    expect(screen.getByTestId("live-price").textContent).toMatch(/unavailable/);
    expect(screen.getByTestId("live-price").textContent).not.toContain("1.1215");
  });
});
