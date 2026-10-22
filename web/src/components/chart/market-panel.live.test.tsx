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
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: vi.fn(async (path: string, init?: { method?: string }) => {
    h.calls.push({ path, method: init?.method });
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

const candleCalls = () => h.calls.filter((c) => c.path.startsWith("accounts/"));
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
    expect(screen.getByText("stale")).toBeDefined();
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
