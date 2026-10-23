/**
 * The market view's contract with the data hook, the broker read and the
 * chart.
 *
 * `useRead` is replaced here so each test can hand the panel exactly the read
 * it wants to see — fresh, old, failed, for the wrong instrument — and assert
 * on the path and interval it asked for. The real hook, with a real timer,
 * is exercised in market-panel.live.test.tsx.
 *
 * Several tests assert the chart is NOT created. That is the point: a failed
 * read, an expired authorisation and a missing account all produce "no
 * bars", and drawing an empty chart for them would say "nothing is
 * happening" about data nobody received.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult, CandlesRead, PositionsRead } from "@/lib/api";

type Hook = { result: ApiResult<unknown> | null; loading: boolean; lastSync: number | null; reload: () => void };
const h = vi.hoisted(() => ({
  candles: null as unknown,
  positions: null as unknown,
  useRead: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));
vi.mock("@/lib/use-api", async (orig) => ({ ...(await orig<typeof import("@/lib/use-api")>()), useRead: h.useRead }));
vi.mock("lightweight-charts", async () => (await import("@/test/lightweight-charts-mock")).factory());

import { lwc } from "@/test/lightweight-charts-mock";
import { createChart } from "lightweight-charts";
import { TIMEFRAMES } from "@/components/app/rule-form";
import { CHART_REFRESH_MS, MarketPanel } from "./market-panel";

const T0 = 1_758_542_400;
const BARS = [
  { open: 1.1000, high: 1.1050, low: 1.0980, close: 1.1030, time: T0 },
  { open: 1.1030, high: 1.1060, low: 1.1010, close: 1.1015, time: T0 + 3600 },
  { open: 1.1015, high: 1.1040, low: 1.0990, close: 1.0995, time: T0 + 7200 },
];
const okRead: CandlesRead = {
  connected: true, status: "ok", accountId: 501, mode: "demo",
  candles: BARS, symbol: "EURUSD", timeframe: "1h", count: 3, requested: 200,
};
const hook = (result: ApiResult<unknown> | null, lastSync: number | null = Date.now(), loading = false): Hook =>
  ({ result, loading, lastSync, reload: vi.fn() });
const ok = (data: unknown): ApiResult<unknown> => ({ ok: true, data });
const err = (code: string, message: string, status = 503): ApiResult<unknown> => ({ ok: false, status, code, message });

const position = (over: Record<string, unknown> = {}) => ({
  symbol: "EURUSD", side: "BUY", units: 1000, entryPrice: 1.1, stopLoss: 1.09, takeProfit: 1.12, positionId: 7, ...over,
});
const positionsRead = (positions: unknown[], over: Record<string, unknown> = {}): PositionsRead =>
  ({ connected: true, status: "ok", accountId: 501, mode: "demo", positions, ...over }) as PositionsRead;

beforeEach(() => {
  lwc.reset();
  vi.mocked(createChart).mockClear();
  h.useRead.mockReset();
  h.candles = hook(ok(okRead));
  h.positions = hook(ok(positionsRead([])));
  h.useRead.mockImplementation((path: string | null) => {
    if (path === null) return hook(null, null, false);
    return path === "positions" ? h.positions : h.candles;
  });
});
afterEach(() => { vi.useRealTimers(); });

const mount = (props: Partial<React.ComponentProps<typeof MarketPanel>> = {}) =>
  render(<MarketPanel ctid={501} mode="demo" symbols={["EURUSD", "XAUUSD"]} timeframe="1h" {...props} />);
const chartDrawn = () => lwc.charts.length > 0 && document.querySelector(".price-chart") !== null;
const candleSeries = () => lwc.seriesOf("candlestick")[0];

describe("market panel — what it asks the hook for", () => {
  it("reads the candles endpoint for the selected account, symbol and timeframe", () => {
    mount();
    const path = h.useRead.mock.calls.map((c) => c[0] as string | null).find((p) => p?.startsWith("accounts/"))!;
    expect(path).toMatch(/^accounts\/501\/candles\?/);
    const q = new URLSearchParams(path.split("?")[1]);
    expect(q.get("symbol")).toBe("EURUSD");
    expect(q.get("timeframe")).toBe("1h");
    expect(Number(q.get("limit"))).toBeGreaterThan(0);
  });

  it("refreshes every 15000 ms, and never faster than 5000", () => {
    expect(CHART_REFRESH_MS).toBe(15000);
    mount();
    expect(h.useRead).toHaveBeenCalledWith(expect.stringMatching(/^accounts\/501\/candles\?/), 15000);
    // The broker's historical budget is shared; no read on this panel may poll quicker.
    for (const [, interval] of h.useRead.mock.calls) {
      expect(interval).toBeGreaterThanOrEqual(5000);
    }
  });

  it("reads open positions for the lines on the chart, at the same cadence", () => {
    mount();
    expect(h.useRead).toHaveBeenCalledWith("positions", CHART_REFRESH_MS);
  });

  it("asks for the new timeframe when it is changed", () => {
    mount();
    h.useRead.mockClear();
    fireEvent.change(screen.getByRole("combobox", { name: /Timeframe/i }), { target: { value: "15m" } });
    const path = h.useRead.mock.calls.map((c) => c[0] as string | null).find((p) => p?.startsWith("accounts/"))!;
    expect(new URLSearchParams(path.split("?")[1]).get("timeframe")).toBe("15m");
  });

  it("offers the timeframes the rule form offers, and only the instruments it was given", () => {
    mount();
    const tf = screen.getByRole("combobox", { name: /Timeframe/i });
    expect(within(tf).getAllByRole("option").map((o) => (o as HTMLOptionElement).value)).toEqual(TIMEFRAMES);
    const sym = screen.getByRole("combobox", { name: /Instrument/i });
    expect(within(sym).getAllByRole("option").map((o) => (o as HTMLOptionElement).value)).toEqual(["EURUSD", "XAUUSD"]);
  });

  it("asks for nothing without an account, and says no account is SELECTED", () => {
    mount({ ctid: null });
    for (const [path] of h.useRead.mock.calls) expect(path).toBeNull();
    expect(screen.getByText(/No account selected/)).toBeDefined();
    // This panel knows only that none is selected, not whether cTrader is
    // linked; saying "not connected" sent an owner round OAuth a second time.
    expect(screen.queryByText(/not connected/i)).toBeNull();
    expect(screen.getByRole("link", { name: /choose an account/i })).toHaveProperty("href", expect.stringContaining("/accounts"));
    expect(chartDrawn()).toBe(false);
  });

  it("asks for nothing, and says so, when there is no instrument", () => {
    mount({ symbols: [] });
    for (const [path] of h.useRead.mock.calls) expect(path).toBeNull();
    expect(screen.getByText(/No instrument to chart yet/)).toBeDefined();
    expect(chartDrawn()).toBe(false);
  });
});

describe("market panel — states that must not look like a quiet market", () => {
  it("a failed read shows the existing error component with its code, and creates no chart", () => {
    h.candles = hook(err("BROKER_TIMEOUT", "cTrader did not answer within 12s"));
    mount();
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText("BROKER_TIMEOUT")).toBeDefined();
    expect(within(alert).getByText(/did not answer/)).toBeDefined();
    expect(createChart).not.toHaveBeenCalled();
    expect(chartDrawn()).toBe(false);
  });

  it("a read that fails AFTER a good one removes the chart rather than leaving old bars up as if live", () => {
    const { rerender } = mount();
    expect(chartDrawn()).toBe(true);
    h.candles = hook(err("NETWORK", "Failed to fetch", 0));
    rerender(<MarketPanel ctid={501} mode="demo" symbols={["EURUSD", "XAUUSD"]} timeframe="1h" />);
    expect(screen.getByText("NETWORK")).toBeDefined();
    expect(document.querySelector(".price-chart")).toBeNull();
    expect(lwc.charts[0].remove).toHaveBeenCalled();
  });

  it.each([
    ["not_connected", /No account selected/],
    ["reauth_required", /cTrader needs reconnecting/],
    ["unavailable", /Market data unavailable/],
  ])("read status %s is shown as itself, with no chart", (status, expected) => {
    h.candles = hook(ok({ connected: status !== "not_connected", status, reason: "TimeoutError: cTrader did not answer" }));
    mount();
    expect(screen.getByText(expected)).toBeDefined();
    expect(createChart).not.toHaveBeenCalled();
  });

  it("an expired authorisation offers reconnecting, the only thing that fixes it", () => {
    h.candles = hook(ok({ connected: true, status: "reauth_required", reason: "the cTrader authorisation has expired" }));
    mount();
    expect(screen.getByRole("link", { name: /Reconnect cTrader/ })).toBeDefined();
  });

  it("an ok read with no bars says the broker returned none, and creates no chart", () => {
    h.candles = hook(ok({ ...okRead, candles: [], count: 0 }));
    mount();
    expect(screen.getByText(/answered with no bars/)).toBeDefined();
    expect(createChart).not.toHaveBeenCalled();
  });

  it("shows a loading state, not a chart, before the first answer", () => {
    h.candles = hook(null, null, true);
    mount();
    expect(screen.getByRole("status", { name: /Loading market data/i })).toBeDefined();
    expect(createChart).not.toHaveBeenCalled();
  });

  it("never draws one instrument's bars under another's name while the new read is on its way", () => {
    // useRead keeps the previous answer while a new path loads. The user has
    // just picked XAUUSD; the answer still on hand is for EURUSD.
    mount();
    fireEvent.change(screen.getByRole("combobox", { name: /Instrument/i }), { target: { value: "XAUUSD" } });
    expect(document.querySelector(".price-chart")).toBeNull();
    expect(screen.getByRole("status", { name: /Loading market data/i })).toBeDefined();
  });

  it("likewise for the timeframe", () => {
    mount();
    fireEvent.change(screen.getByRole("combobox", { name: /Timeframe/i }), { target: { value: "4h" } });
    expect(document.querySelector(".price-chart")).toBeNull();
  });
});

describe("market panel — honesty about freshness", () => {
  it("says when it last synced, from the app's own helper", () => {
    h.candles = hook(ok(okRead), Date.now() - 12_000);
    mount();
    expect(screen.getByText(/Last synced 12s ago/)).toBeDefined();
  });

  it("shows no stale marker on a fresh read", () => {
    h.candles = hook(ok(okRead), Date.now() - 4_000);
    mount();
    expect(screen.queryByText(/stale/i)).toBeNull();
  });

  it("shows a visible stale marker when the last answer is older than 30 seconds", () => {
    h.candles = hook(ok(okRead), Date.now() - 45_000);
    mount();
    expect(screen.getByText(/Last synced 45s ago/)).toBeDefined();
    expect(screen.getByText("stale")).toBeDefined();
  });

  it("flags the chart itself as stale, not only the text beside it", () => {
    h.candles = hook(ok(okRead), Date.now() - 45_000);
    mount();
    expect(document.querySelector(".chart-frame.is-stale")).not.toBeNull();
  });

  it("goes stale on its own as time passes, with no new read to tell it", () => {
    vi.useFakeTimers();
    h.candles = hook(ok(okRead), Date.now());
    mount();
    expect(screen.queryByText("stale")).toBeNull();
    act(() => { vi.advanceTimersByTime(31_000); });
    expect(screen.getByText("stale")).toBeDefined();
  });

  it("marks a failed read stale too, so the error is never mistaken for a current state", () => {
    h.candles = hook(err("BROKER_TIMEOUT", "no answer"), Date.now() - 2_000);
    mount();
    expect(screen.getByText("stale")).toBeDefined();
    expect(screen.getByText(/Last read failed/)).toBeDefined();
  });

  it("states the source, the bar count and the time of the latest bar", () => {
    mount();
    expect(screen.getByText(/Source: cTrader account/)).toBeDefined();
    expect(screen.getByText(/#501/)).toBeDefined();
    expect(screen.getByText(/3 bars of EURUSD 1h/)).toBeDefined();
    expect(screen.getAllByText(/2025-09-22 14:00 UTC/).length).toBeGreaterThan(0);
  });

  it("does not present a cache as live: it says the platform caches broker bars", () => {
    mount();
    expect(screen.getByText(/caches broker bars/i)).toBeDefined();
  });

  it("says the count asked for when the broker returned fewer", () => {
    h.candles = hook(ok({ ...okRead, count: 3, requested: 200 }));
    mount();
    expect(screen.getByText(/asked for 200/)).toBeDefined();
  });
});

describe("market panel — what it hands the chart", () => {
  it("passes the broker's bars through unchanged", () => {
    mount();
    expect(candleSeries().setData).toHaveBeenCalledWith(
      BARS.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })),
    );
  });

  it("passes a rule's evaluation marker through", () => {
    mount({ markers: [{ time: T0 + 7200, label: "Evaluated here", tone: "long" }] });
    expect(lwc.markerPlugins[0].markers).toEqual([expect.objectContaining({ text: "Evaluated here" })]);
  });

  it("hands the bars to a caller that wants to evaluate exactly what is on screen", () => {
    const onLoaded = vi.fn();
    mount({ onLoaded });
    expect(onLoaded).toHaveBeenCalledWith(okRead);
  });
});

describe("market panel — position lines", () => {
  const lineTitles = () => candleSeries().lines.filter((l) => !l.removed).map((l) => String(l.options.title));
  const linePrices = () => candleSeries().lines.filter((l) => !l.removed).map((l) => l.options.price).sort();

  it("draws entry, stop and target for an open position in the selected instrument", () => {
    h.positions = hook(ok(positionsRead([position()])));
    mount();
    expect(linePrices()).toEqual([1.09, 1.1, 1.12]);
  });

  it("draws no stop and shows 'no stop' for a position whose stop is null", () => {
    h.positions = hook(ok(positionsRead([position({ stopLoss: null })])));
    mount();
    expect(linePrices()).toEqual([1.1, 1.12]);
    expect(lineTitles().some((t) => /Stop/.test(t))).toBe(false);
    expect(screen.getByText("no stop")).toBeDefined();
  });

  it("ignores positions in other instruments", () => {
    h.positions = hook(ok(positionsRead([position({ symbol: "GBPUSD" })])));
    mount();
    expect(candleSeries().lines).toHaveLength(0);
    expect(screen.queryByText("no stop")).toBeNull();
  });

  it("says position lines are unavailable when the positions read failed, instead of drawing none silently", () => {
    h.positions = hook(err("STORE_UNAVAILABLE", "positions read failed"));
    mount();
    expect(screen.getByText(/Position lines unavailable/)).toBeDefined();
    expect(screen.getByText(/STORE_UNAVAILABLE/)).toBeDefined();
    expect(candleSeries().lines).toHaveLength(0);
    expect(chartDrawn()).toBe(true);
  });

  it("says so, and draws none, when the positions belong to a different account", () => {
    h.positions = hook(ok(positionsRead([position()], { accountId: 999 })));
    mount();
    expect(screen.getByText(/Position lines hidden/)).toBeDefined();
    expect(candleSeries().lines).toHaveLength(0);
  });

  it("says position lines are unavailable when the positions read is not ok", () => {
    h.positions = hook(ok({ connected: true, status: "unavailable", reason: "no answer" }));
    mount();
    expect(screen.getByText(/Position lines unavailable/)).toBeDefined();
  });

  it("stays quiet while the positions have simply not arrived yet", () => {
    h.positions = hook(null, null, true);
    mount();
    expect(screen.queryByText(/Position lines/)).toBeNull();
  });
});

describe("market panel — indicator controls", () => {
  const overlaySelect = () => screen.getByRole("combobox", { name: /Overlay/i });
  const period = () => screen.getByRole("spinbutton", { name: /Period/i });
  const lines = () => lwc.seriesOf("line");

  it("draws no overlay and no RSI until asked", () => {
    mount();
    expect(lines()).toHaveLength(0);
  });

  it("draws an SMA of the chosen period, labelled computed", () => {
    mount();
    fireEvent.change(overlaySelect(), { target: { value: "sma" } });
    fireEvent.change(period(), { target: { value: "2" } });
    // closes 1.1030, 1.1015, 1.0995 -> SMA(2) = 1.10225, 1.1005
    const data = lines()[0].setData.mock.calls.at(-1)![0] as { time: number; value: number }[];
    expect(data.map((p) => p.time)).toEqual([T0 + 3600, T0 + 7200]);
    expect(data[0].value).toBeCloseTo(1.10225, 10);
    expect(data[1].value).toBeCloseTo(1.1005, 10);
    expect(screen.getByText(/SMA\(2\)/)).toBeDefined();
    expect(document.body.textContent).toMatch(/computed/i);
  });

  it("draws an EMA when that is chosen", () => {
    mount();
    fireEvent.change(overlaySelect(), { target: { value: "ema" } });
    fireEvent.change(period(), { target: { value: "3" } });
    // seed = (1.1030 + 1.1015 + 1.0995) / 3 at the third bar
    const data = lines()[0].setData.mock.calls.at(-1)![0] as { time: number; value: number }[];
    expect(data).toHaveLength(1);
    expect(data[0].value).toBeCloseTo((1.1030 + 1.1015 + 1.0995) / 3, 10);
  });

  it.each(["", "1", "0", "500", "2.5", "abc"])(
    "draws nothing, and says why, for the period %j — it does not guess",
    (value) => {
      mount();
      fireEvent.change(overlaySelect(), { target: { value: "sma" } });
      fireEvent.change(period(), { target: { value } });
      expect(lines()).toHaveLength(0);
      expect(screen.getByText(/whole number from 2 to 200/)).toBeDefined();
    },
  );

  it("adds RSI(14) in a second pane when ticked", () => {
    mount();
    fireEvent.click(screen.getByRole("checkbox", { name: /RSI/i }));
    expect(lines().some((s) => s.paneIndex === 1)).toBe(true);
    expect(screen.getByText(/RSI\(14\)/)).toBeDefined();
  });
});

describe("market panel — read-only, structurally", () => {
  const dir = __dirname;
  const SRC = ["market-panel.tsx", "price-chart.tsx", "chart-data.ts", "chart-theme.ts", "indicators.ts"]
    .map((f) => readFileSync(join(dir, f), "utf8")).join("\n");

  it("never references an order, close or amend endpoint", () => {
    for (const forbidden of [
      "automation/start", "automation/stop", "force_trade", "place_order",
      "/close", "/amend", "authorize_order",
    ]) {
      expect(SRC, `the chart references ${forbidden}`).not.toContain(forbidden);
    }
  });

  it("makes no request of its own: no fetch, no method, no direct api call", () => {
    expect(SRC).not.toMatch(/\bfetch\(/);
    expect(SRC).not.toMatch(/\bmethod\s*:/);
    expect(SRC).not.toMatch(/\bapi\s*[<(]/);
    expect(SRC).not.toMatch(/\bpublicApi\b/);
  });

  it("reads from the existing hook and from no other data source", () => {
    expect(SRC).toContain("useRead");
    for (const feed of ["tradingview.com/widget", "s3.tradingview.com", "tv.js", "binance", "yahoo", "alphavantage", "twelvedata"]) {
      expect(SRC.toLowerCase(), `a third-party feed (${feed}) is referenced`).not.toContain(feed);
    }
  });
});
