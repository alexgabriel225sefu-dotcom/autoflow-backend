/**
 * The chart's contract with `lightweight-charts`.
 *
 * jsdom has no canvas, so the library is replaced by a recorder
 * (src/test/lightweight-charts-mock.ts) and these tests assert on what this
 * component ASKS of it: one chart for the life of the component, bars
 * updated in place rather than rebuilt, price lines only where a level
 * exists, indicators on the right pane, colours taken from the app's tokens.
 *
 * What none of this can tell you is whether the result looks right in a
 * browser. That needs a browser.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Candle } from "@/lib/api";

vi.mock("lightweight-charts", async () => (await import("@/test/lightweight-charts-mock")).factory());

import { lwc } from "@/test/lightweight-charts-mock";
import { createChart } from "lightweight-charts";
import { positionOverlays } from "./chart-data";
import { PriceChart } from "./price-chart";

const T0 = 1_700_000_000;
const STEP = 3600;
const candle = (i: number, close: number, over: Partial<Candle> = {}): Candle => ({
  time: T0 + i * STEP, open: close - 0.001, high: close + 0.002, low: close - 0.002, close, ...over,
});
const series = (closes: number[]) => closes.map((c, i) => candle(i, c));
const BASE = series([1.10, 1.11, 1.12, 1.13, 1.12]);

const TOKENS = (long: string, short: string, bg: string) =>
  `:root{--a4t-long:${long};--a4t-short:${short};--a4t-bg-2:${bg};--a4t-dim:#726f67;`
  + "--a4t-line-soft:#edeae3;--a4t-line:#e4e1d9;--a4t-link:#1a5fb4;--a4t-link-strong:#10407d;"
  + "--a4t-text:#111113;--a4t-muted:#56544e;}";

let style: HTMLStyleElement;
beforeEach(() => {
  lwc.reset();
  vi.mocked(createChart).mockClear();
  style = document.createElement("style");
  style.textContent = TOKENS("#1a7f4b", "#a62b19", "#fbfaf7");
  document.head.append(style);
});
afterEach(() => {
  style.remove();
  document.documentElement.removeAttribute("data-theme");
});

const chart = () => lwc.charts[lwc.charts.length - 1];
const candles = () => lwc.seriesOf("candlestick")[0];
const lines = () => lwc.seriesOf("line");

const asBar = (c: Candle) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close });

describe("creating the chart", () => {
  it("creates exactly one chart, on a real element, and one candlestick series", () => {
    render(<PriceChart candles={BASE} symbol="EURUSD" timeframe="1h" />);
    expect(createChart).toHaveBeenCalledTimes(1);
    expect(chart().container).toBeInstanceOf(HTMLElement);
    expect(lwc.seriesOf("candlestick")).toHaveLength(1);
  });

  it("hands the library exactly the bars the broker gave, in order, and nothing else", () => {
    render(<PriceChart candles={BASE} symbol="EURUSD" timeframe="1h" />);
    expect(candles().setData).toHaveBeenCalledTimes(1);
    expect(candles().setData).toHaveBeenCalledWith(BASE.map(asBar));
  });

  it("sizes itself to its container and keeps the vendor attribution switched on", () => {
    render(<PriceChart candles={BASE} />);
    expect(chart().options.autoSize).toBe(true);
    // The library's terms ask for a link to tradingview.com, and its own
    // attribution logo is the mechanism it offers for that. Turning it off
    // would be a legal change, not a styling one.
    expect(chart().options.layout.attributionLogo).toBe(true);
    expect(screen.getByRole("link", { name: /TradingView/i })).toHaveProperty("href", "https://www.tradingview.com/");
  });

  it("shows times in UTC, and says so", () => {
    render(<PriceChart candles={BASE} />);
    expect(chart().options.timeScale.timeVisible).toBe(true);
    expect(document.body.textContent).toMatch(/UTC/);
  });

  it("formats prices with the decimals the data has", () => {
    render(<PriceChart candles={[candle(0, 1.10005), candle(1, 1.10010)]} />);
    const applied = candles().applyOptions.mock.calls.map((c) => c[0]).find((o) => o.priceFormat);
    expect(applied.priceFormat).toMatchObject({ type: "price", precision: 5 });
  });

  it("destroys the chart when it unmounts", () => {
    const { unmount } = render(<PriceChart candles={BASE} />);
    unmount();
    expect(chart().remove).toHaveBeenCalledTimes(1);
  });
});

describe("refreshing live — update in place, never rebuild", () => {
  it("changes the last bar with series.update and does not set the data again", () => {
    const { rerender } = render(<PriceChart candles={BASE} symbol="EURUSD" timeframe="1h" />);
    const revised = [...BASE.slice(0, 4), candle(4, 1.125)];
    rerender(<PriceChart candles={revised} symbol="EURUSD" timeframe="1h" />);

    expect(createChart).toHaveBeenCalledTimes(1);
    expect(candles().setData).toHaveBeenCalledTimes(1);
    expect(candles().update).toHaveBeenCalledTimes(1);
    expect(candles().update).toHaveBeenCalledWith(asBar(candle(4, 1.125)));
  });

  it("appends a new bar with series.update, after refreshing the one before it", () => {
    const { rerender } = render(<PriceChart candles={BASE} symbol="EURUSD" timeframe="1h" />);
    rerender(<PriceChart candles={[...BASE.slice(0, 4), candle(4, 1.121), candle(5, 1.13)]} symbol="EURUSD" timeframe="1h" />);

    expect(createChart).toHaveBeenCalledTimes(1);
    expect(candles().setData).toHaveBeenCalledTimes(1);
    expect(candles().update.mock.calls.map((c) => c[0])).toEqual([asBar(candle(4, 1.121)), asBar(candle(5, 1.13))]);
  });

  it("copes with the broker window sliding forward by one bar", () => {
    const { rerender } = render(<PriceChart candles={BASE} symbol="EURUSD" timeframe="1h" />);
    rerender(<PriceChart candles={[...BASE.slice(1), candle(5, 1.13)]} symbol="EURUSD" timeframe="1h" />);
    expect(candles().setData).toHaveBeenCalledTimes(1);
    expect(candles().update.mock.calls.map((c) => c[0].time)).toEqual([candle(4, 0).time, candle(5, 0).time]);
  });

  it("starts the data again (still on the same chart) when an earlier bar was revised", () => {
    const { rerender } = render(<PriceChart candles={BASE} symbol="EURUSD" timeframe="1h" />);
    const revised = [BASE[0], candle(1, 1.5), ...BASE.slice(2)];
    rerender(<PriceChart candles={revised} symbol="EURUSD" timeframe="1h" />);
    expect(createChart).toHaveBeenCalledTimes(1);
    expect(candles().setData).toHaveBeenCalledTimes(2);
    expect(candles().setData).toHaveBeenLastCalledWith(revised.map(asBar));
  });

  it("starts the data again, and refits the view, when the instrument or timeframe changes", () => {
    const { rerender } = render(<PriceChart candles={BASE} symbol="EURUSD" timeframe="1h" />);
    expect(chart().fitContent).toHaveBeenCalledTimes(1);
    rerender(<PriceChart candles={BASE} symbol="GBPUSD" timeframe="1h" />);
    expect(createChart).toHaveBeenCalledTimes(1);
    expect(candles().setData).toHaveBeenCalledTimes(2);
    expect(chart().fitContent).toHaveBeenCalledTimes(2);
  });

  it("does not yank the view back to the latest bar on an ordinary refresh", () => {
    const { rerender } = render(<PriceChart candles={BASE} symbol="EURUSD" timeframe="1h" />);
    rerender(<PriceChart candles={[...BASE.slice(0, 4), candle(4, 1.125)]} symbol="EURUSD" timeframe="1h" />);
    expect(chart().fitContent).toHaveBeenCalledTimes(1);
  });
});

describe("bars that cannot be drawn honestly", () => {
  it("does not create a chart for bars without timestamps, and says why", () => {
    render(<PriceChart candles={[{ open: 1, high: 2, low: 0.5, close: 1.5 }]} />);
    expect(createChart).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toMatch(/timestamp/i);
  });

  it("does not create a chart for no bars at all", () => {
    render(<PriceChart candles={[]} />);
    expect(createChart).not.toHaveBeenCalled();
  });
});

describe("position lines", () => {
  const pos = (over = {}) => ({
    symbol: "EURUSD", side: "BUY" as const, units: 1000, entryPrice: 1.105,
    stopLoss: 1.09, takeProfit: 1.14, positionId: 7, ...over,
  });
  const lineOptions = () => candles().lines.filter((l) => !l.removed).map((l) => l.options);

  it("draws entry, stop and target at the position's own prices", () => {
    render(<PriceChart candles={BASE} symbol="EURUSD" positions={positionOverlays([pos()], "EURUSD")} />);
    expect(lineOptions().map((o) => o.price).sort()).toEqual([1.09, 1.105, 1.14]);
    const titles = lineOptions().map((o) => String(o.title));
    expect(titles.some((t) => /Entry/.test(t))).toBe(true);
    expect(titles.some((t) => /Stop/.test(t))).toBe(true);
    expect(titles.some((t) => /Target/.test(t))).toBe(true);
  });

  it("colours the stop and the target by what they mean, from the app's tokens", () => {
    render(<PriceChart candles={BASE} symbol="EURUSD" positions={positionOverlays([pos()], "EURUSD")} />);
    const byTitle = (re: RegExp) => lineOptions().find((o) => re.test(String(o.title)))!;
    expect(byTitle(/Stop/).color).toBe("#a62b19");
    expect(byTitle(/Target/).color).toBe("#1a7f4b");
  });

  it("draws NO stop line for a position with a null stop, and shows the words 'no stop'", () => {
    render(<PriceChart candles={BASE} symbol="EURUSD" positions={positionOverlays([pos({ stopLoss: null })], "EURUSD")} />);
    expect(lineOptions().map((o) => o.price).sort()).toEqual([1.105, 1.14]);
    expect(lineOptions().some((o) => /Stop/.test(String(o.title)))).toBe(false);
    expect(screen.getByText(/no stop/i)).toBeDefined();
  });

  it("does not say 'no stop' for a position that has one", () => {
    render(<PriceChart candles={BASE} symbol="EURUSD" positions={positionOverlays([pos()], "EURUSD")} />);
    expect(screen.queryByText(/no stop/i)).toBeNull();
  });

  it("leaves unchanged lines alone across refreshes, and replaces them when a level moves", () => {
    const { rerender } = render(<PriceChart candles={BASE} symbol="EURUSD" positions={positionOverlays([pos()], "EURUSD")} />);
    expect(candles().createPriceLine).toHaveBeenCalledTimes(3);

    // A fresh array with the same levels: what every poll produces.
    rerender(<PriceChart candles={BASE} symbol="EURUSD" positions={positionOverlays([pos()], "EURUSD")} />);
    expect(candles().createPriceLine).toHaveBeenCalledTimes(3);
    expect(candles().removePriceLine).not.toHaveBeenCalled();

    // The stop was moved.
    rerender(<PriceChart candles={BASE} symbol="EURUSD" positions={positionOverlays([pos({ stopLoss: 1.1 })], "EURUSD")} />);
    expect(candles().removePriceLine).toHaveBeenCalledTimes(3);
    expect(lineOptions().map((o) => o.price).sort()).toEqual([1.1, 1.105, 1.14]);
  });

  it("removes every line when the position closes", () => {
    const { rerender } = render(<PriceChart candles={BASE} symbol="EURUSD" positions={positionOverlays([pos()], "EURUSD")} />);
    rerender(<PriceChart candles={BASE} symbol="EURUSD" positions={[]} />);
    expect(lineOptions()).toHaveLength(0);
  });
});

describe("indicator overlays — labelled as computed", () => {
  // closes 2,4,6,8,4 : SMA(3) = 4,6,6 at bars 3..5 ; EMA(3) = 4,6,5 (see indicators.test.ts)
  const C = series([2, 4, 6, 8, 4]);
  const t = (i: number) => T0 + i * STEP;

  it("draws no indicator unless asked", () => {
    render(<PriceChart candles={C} />);
    expect(lines()).toHaveLength(0);
  });

  it("draws an SMA on the price pane with the hand-computed values", () => {
    render(<PriceChart candles={C} overlay={{ kind: "sma", period: 3 }} />);
    const [s] = lines();
    expect(s.paneIndex ?? 0).toBe(0);
    expect(s.setData).toHaveBeenCalledWith([
      { time: t(2), value: 4 }, { time: t(3), value: 6 }, { time: t(4), value: 6 },
    ]);
  });

  it("draws an EMA with the hand-computed values", () => {
    render(<PriceChart candles={C} overlay={{ kind: "ema", period: 3 }} />);
    expect(lines()[0].setData).toHaveBeenCalledWith([
      { time: t(2), value: 4 }, { time: t(3), value: 6 }, { time: t(4), value: 5 },
    ]);
  });

  it("says in words that the line is computed here, and names the period", () => {
    render(<PriceChart candles={C} overlay={{ kind: "sma", period: 3 }} />);
    expect(screen.getByText(/SMA\(3\)/)).toBeDefined();
    expect(document.body.textContent).toMatch(/computed/i);
  });

  it("changing the period reuses the series and sets new values", () => {
    const { rerender } = render(<PriceChart candles={C} overlay={{ kind: "sma", period: 3 }} />);
    rerender(<PriceChart candles={C} overlay={{ kind: "sma", period: 2 }} />);
    expect(lines()).toHaveLength(1);
    // SMA(2) of 2,4,6,8,4 = 3,5,7,6
    expect(lines()[0].setData).toHaveBeenLastCalledWith([
      { time: t(1), value: 3 }, { time: t(2), value: 5 }, { time: t(3), value: 7 }, { time: t(4), value: 6 },
    ]);
  });

  it("turning it off removes the series", () => {
    const { rerender } = render(<PriceChart candles={C} overlay={{ kind: "sma", period: 3 }} />);
    const s = lines()[0];
    rerender(<PriceChart candles={C} overlay={null} />);
    expect(s.removed).toBe(true);
    expect(lines()).toHaveLength(0);
  });

  it("a refresh updates the overlay's last point in place too", () => {
    const { rerender } = render(<PriceChart candles={C} overlay={{ kind: "sma", period: 3 }} />);
    const s = lines()[0];
    rerender(<PriceChart candles={[...C.slice(0, 4), candle(4, 7)]} overlay={{ kind: "sma", period: 3 }} />);
    expect(s.setData).toHaveBeenCalledTimes(1);
    // SMA(3) at the last bar is now (6+8+7)/3 = 7
    expect(s.update).toHaveBeenLastCalledWith({ time: t(4), value: 7 });
  });

  it("draws RSI(14) in its own pane, below the price", () => {
    // 20 rising closes: every change is a gain, so RSI is 100 from bar 15 on.
    const rising = series(Array.from({ length: 20 }, (_, i) => 1 + i * 0.01));
    render(<PriceChart candles={rising} showRsi />);
    const rsiSeries = lines().find((s) => s.paneIndex === 1)!;
    expect(rsiSeries).toBeDefined();
    const data = rsiSeries.setData.mock.calls[0][0] as { time: number; value: number }[];
    expect(data).toHaveLength(6);
    expect(data.every((p) => p.value === 100)).toBe(true);
    expect(data[0].time).toBe(T0 + 14 * STEP);
    expect(screen.getByText(/RSI\(14\)/)).toBeDefined();
  });

  it("removes the RSI pane's series when it is switched off", () => {
    const rising = series(Array.from({ length: 20 }, (_, i) => 1 + i * 0.01));
    const { rerender } = render(<PriceChart candles={rising} showRsi />);
    const s = lines().find((x) => x.paneIndex === 1)!;
    rerender(<PriceChart candles={rising} showRsi={false} />);
    expect(s.removed).toBe(true);
  });
});

describe("the app's colours, not the library's", () => {
  it("takes candle and background colours from the CSS variables", () => {
    render(<PriceChart candles={BASE} />);
    expect(candles().options).toMatchObject({ upColor: "#1a7f4b", downColor: "#a62b19" });
    expect(chart().options.layout.background).toMatchObject({ color: "#fbfaf7" });
  });

  it("re-applies them when the theme changes, without recreating the chart", async () => {
    render(<PriceChart candles={BASE} />);
    style.textContent = TOKENS("#4ade80", "#f87171", "#0e0e10");
    await act(async () => {
      document.documentElement.setAttribute("data-theme", "dark");
      await Promise.resolve();
    });
    expect(createChart).toHaveBeenCalledTimes(1);
    const calls = candles().applyOptions.mock.calls.map((c) => c[0]);
    expect(calls.some((o) => o.upColor === "#4ade80" && o.downColor === "#f87171")).toBe(true);
    const layout = chart().applyOptions.mock.calls.map((c) => c[0]).find((o) => o.layout?.background?.color === "#0e0e10");
    expect(layout).toBeDefined();
  });

  it("passes the library nothing at all for a token that does not resolve, rather than a colour it made up", () => {
    style.textContent = ":root{}";
    render(<PriceChart candles={BASE} />);
    expect(candles().options.upColor).toBeUndefined();
    expect(chart().options.layout.background).toBeUndefined();
  });
});

describe("markers", () => {
  it("places a marker on the nearest bar, with its label", () => {
    render(<PriceChart candles={BASE} markers={[{ time: T0 + 2 * STEP + 100, label: "Evaluated here", tone: "long" }]} />);
    const [plugin] = lwc.markerPlugins;
    expect(plugin.markers).toEqual([expect.objectContaining({ time: T0 + 2 * STEP, text: "Evaluated here", color: "#1a7f4b" })]);
  });

  it("creates no marker plugin when there are none", () => {
    render(<PriceChart candles={BASE} />);
    expect(lwc.markerPlugins).toHaveLength(0);
  });
});

describe("the OHLC readout", () => {
  it("shows the last bar until the crosshair is over another, then that one", async () => {
    render(<PriceChart candles={BASE} symbol="EURUSD" timeframe="1h" />);
    const readout = () => document.querySelector(".ohlc")!.textContent!;
    expect(readout()).toContain("EURUSD");
    expect(readout()).toContain("1.120"); // last close, at the 3 decimals this fixture has
    await act(async () => { chart().crosshairHandlers[0]({ time: T0 + 3 * STEP }); });
    expect(readout()).toContain("1.130");
    await act(async () => { chart().crosshairHandlers[0]({ time: undefined }); });
    expect(readout()).toContain("1.120");
  });

  it("states that no volume is shown, rather than drawing one", () => {
    render(<PriceChart candles={BASE} />);
    expect(screen.getByText(/does not carry volume/)).toBeDefined();
  });
});

describe("the library's NOTICE is on the page that shows its chart", () => {
  // lightweight-charts is licensed Apache-2.0 with an added term: the page
  // that shows the chart must carry the attribution notice from the library's
  // NOTICE file and a link to tradingview.com. The logo satisfies the link;
  // the notice text has to be there too, and was an open item until now.
  //
  // Reproduced VERBATIM from the NOTICE shipped at v5.2.1, including the
  // Cyrillic letter U+0441 the upstream file uses inside "(с)". Normalising it
  // to a Latin "c" would make the page say something other than the notice it
  // is meant to reproduce.
  const TITLE = "TradingView Lightweight Charts™";
  const COPYRIGHT = "Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/";

  it("shows the notice title and copyright line exactly", () => {
    render(<PriceChart candles={BASE} symbol="EURUSD" timeframe="1h" />);
    // The title also appears as the link text ("Chart by ..."), so the notice
    // is the one that is NOT inside an anchor.
    const notice = screen.getAllByText(TITLE).filter((el) => !el.closest("a"));
    expect(notice.length).toBe(1);
    expect(screen.getByText(COPYRIGHT)).toBeTruthy();
  });

  it("keeps the link to tradingview.com", () => {
    render(<PriceChart candles={BASE} symbol="EURUSD" timeframe="1h" />);
    const links = screen.getAllByRole("link") as HTMLAnchorElement[];
    expect(links.some((a) => a.href.startsWith("https://www.tradingview.com"))).toBe(true);
  });
});
