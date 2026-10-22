"use client";
/**
 * A read-only candlestick chart, drawn by TradingView's `lightweight-charts`.
 *
 * It draws what it is given. It does not fetch, it does not invent a price,
 * and it imports nothing that could place, close or amend an order — a test
 * reads this module's source to keep that true, because a chart is exactly
 * where an "and also close this position" button gets added without anyone
 * thinking about it.
 *
 * ONE CHART FOR THE LIFE OF THE COMPONENT
 *
 * The chart object is created once. A refresh arrives as new props and is
 * applied with `series.update` — the last bar changed in place, new bars
 * appended — so the user's zoom and scroll survive a refresh. Only when an
 * earlier bar was revised, or the instrument/timeframe changed, is the data
 * set again (`planUpdate` decides), and that is still the same chart.
 *
 * Everything here is a PRESENTATION of data the caller already has. Whether
 * that data is fresh, failed or stale is the caller's to say; see
 * market-panel.tsx.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, CrosshairMode, LineSeries, LineStyle,
  createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi,
  type MouseEventParams, type Time, type UTCTimestamp,
} from "lightweight-charts";
import type { Candle } from "@/lib/api";
import {
  applyPlan, planUpdate, precisionFor, sameBar, sameLinePoint, snapMarkers,
  toChartBars, toLinePoints,
  type ChartBar, type ChartMarker, type LinePoint, type PositionOverlay,
} from "./chart-data";
import { defined, readTheme, watchTheme, type ChartTheme } from "./chart-theme";
import { ema, rsi, sma } from "./indicators";

export type { ChartMarker };

export type Overlay = { kind: "sma" | "ema"; period: number };

export type PriceChartProps = {
  candles: readonly Candle[];
  symbol?: string;
  timeframe?: string;
  /** A moving average on the price pane. Computed here from `candles`. */
  overlay?: Overlay | null;
  /** RSI(14) in a pane of its own. Computed here from `candles`. */
  showRsi?: boolean;
  /** Entry / stop / target lines. From the positions read, never guessed. */
  positions?: readonly PositionOverlay[];
  markers?: readonly ChartMarker[];
  height?: number;
};

export const RSI_PERIOD = 14;

export function PriceChart(props: PriceChartProps) {
  const checked = useMemo(() => toChartBars(props.candles), [props.candles]);
  if (!checked.ok) {
    // Not repaired and not drawn. A chart built from bars we had to guess at
    // would be showing something the broker did not give.
    return (
      <div className="notice notice-error" role="alert">
        <p style={{ fontWeight: 600 }}>These bars cannot be drawn</p>
        <p className="muted" style={{ fontSize: ".82rem" }}>{checked.reason}</p>
      </div>
    );
  }
  if (!checked.bars.length) return <p className="empty">No bars to draw.</p>;
  return <Canvas {...props} bars={checked.bars} />;
}

/* ── option builders ──────────────────────────────────────────────────── */

const toData = (b: ChartBar) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close });
const toPoint = (p: LinePoint) => ({ time: p.time as UTCTimestamp, value: p.value });

function chartOptions(t: ChartTheme) {
  const crosshair = defined({ color: t.crosshair, labelBackgroundColor: t.crosshair });
  return {
    autoSize: true,
    layout: {
      // The library's terms ask for a link to tradingview.com; this is the
      // mechanism it offers for that. Not a styling choice to be turned off.
      attributionLogo: true,
      fontSize: 11,
      ...defined({ textColor: t.text, fontFamily: t.fontFamily }),
      ...(t.background ? { background: { type: ColorType.Solid, color: t.background } } : {}),
    },
    grid: { vertLines: defined({ color: t.grid }), horzLines: defined({ color: t.grid }) },
    rightPriceScale: defined({ borderColor: t.border }),
    timeScale: { timeVisible: true, secondsVisible: false, ...defined({ borderColor: t.border }) },
    crosshair: { mode: CrosshairMode.Normal, vertLine: crosshair, horzLine: crosshair },
    // Leave vertical touch-drags to the page, so scrolling past the chart on
    // a phone does not get stuck inside it.
    handleScroll: { vertTouchDrag: false },
  };
}

const candleOptions = (t: ChartTheme) => defined({
  upColor: t.up, downColor: t.down, wickUpColor: t.up, wickDownColor: t.down,
  borderVisible: false,
});

const lineOptions = (color: string | undefined, width: 1 | 2) => ({
  ...defined({ color }), lineWidth: width,
  priceLineVisible: false, crosshairMarkerVisible: false, lastValueVisible: false,
});

const fmtTime = (t: number) => new Date(t * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC";

type HeldLine = { key: string; points: LinePoint[] };

/**
 * Sets or updates a line series from points, using the same in-place rule as
 * the bars. A different `key` (another instrument, timeframe or period) means
 * what the series holds is about something else, so it starts again.
 */
function syncLine(
  series: ISeriesApi<"Line">, held: React.MutableRefObject<HeldLine>,
  next: LinePoint[], key: string,
) {
  const base = held.current.key === key ? held.current.points : [];
  const plan = planUpdate(base, next, sameLinePoint);
  if (plan.kind === "replace") series.setData(plan.items.map(toPoint));
  else for (const p of plan.items) series.update(toPoint(p));
  held.current = { key, points: applyPlan(base, plan) };
}

/* ── the chart ────────────────────────────────────────────────────────── */

function Canvas({
  bars, symbol, timeframe, overlay = null, showRsi = false,
  positions = [], markers = [], height = 360,
}: Omit<PriceChartProps, "candles"> & { bars: ChartBar[] }) {
  const box = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const overlayRef = useRef<ISeriesApi<"Line"> | null>(null);
  const rsiRef = useRef<ISeriesApi<"Line"> | null>(null);
  const markerRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLines = useRef<IPriceLine[]>([]);
  // What each series really holds, so a refresh can be applied as a diff.
  const heldBars = useRef<ChartBar[]>([]);
  const heldOverlay = useRef<HeldLine>({ key: "", points: [] });
  const heldRsi = useRef<HeldLine>({ key: "", points: [] });
  const lastKey = useRef<string | null>(null);
  const lastPrecision = useRef<number | null>(null);

  const [hover, setHover] = useState<number | null>(null);
  const [themeVersion, setThemeVersion] = useState(0);

  const key = `${symbol ?? ""}|${timeframe ?? ""}`;
  const precision = useMemo(() => precisionFor(bars), [bars]);
  const closes = useMemo(() => bars.map((b) => b.close), [bars]);
  const times = useMemo(() => bars.map((b) => b.time), [bars]);
  const overlayKind = overlay?.kind ?? null;
  const overlayPeriod = overlay?.period ?? null;
  const linesSig = JSON.stringify(positions.flatMap((p) => p.lines));
  const markersSig = JSON.stringify(markers);

  // The chart itself: once.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const theme = readTheme();
    const chart = createChart(el, chartOptions(theme));
    const candles = chart.addSeries(CandlestickSeries, candleOptions(theme));
    const onMove = (p: MouseEventParams) => setHover(typeof p.time === "number" ? p.time : null);
    chart.subscribeCrosshairMove(onMove);
    chartRef.current = chart;
    candleRef.current = candles;
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      overlayRef.current = null;
      rsiRef.current = null;
      markerRef.current = null;
      priceLines.current = [];
      heldBars.current = [];
      heldOverlay.current = { key: "", points: [] };
      heldRsi.current = { key: "", points: [] };
      lastKey.current = null;
      lastPrecision.current = null;
    };
  }, []);

  // Theme: re-read when the document says it changed.
  useEffect(() => watchTheme(() => setThemeVersion((v) => v + 1)), []);
  useEffect(() => {
    if (themeVersion === 0) return;
    const theme = readTheme();
    chartRef.current?.applyOptions(chartOptions(theme));
    candleRef.current?.applyOptions(candleOptions(theme));
    overlayRef.current?.applyOptions(defined({ color: theme.overlay }));
    rsiRef.current?.applyOptions(defined({ color: theme.rsi }));
  }, [themeVersion]);

  // The bars: update in place when that is provably the same as redrawing.
  useEffect(() => {
    const chart = chartRef.current;
    const series = candleRef.current;
    if (!chart || !series) return;
    const switched = lastKey.current !== key;
    const base = switched ? [] : heldBars.current;
    if (lastPrecision.current !== precision) {
      series.applyOptions({ priceFormat: { type: "price", precision, minMove: 1 / 10 ** precision } });
      lastPrecision.current = precision;
    }
    if (switched) chart.applyOptions({ timeScale: { timeVisible: timeframe !== "1d" } });
    const plan = planUpdate(base, bars, sameBar);
    if (plan.kind === "replace") {
      series.setData(plan.items.map(toData));
      // Refit only for a different chart; a revised bar must not move the view.
      if (switched || base.length === 0) chart.timeScale().fitContent();
    } else {
      for (const b of plan.items) series.update(toData(b));
    }
    heldBars.current = applyPlan(base, plan);
    lastKey.current = key;
  }, [bars, key, precision, timeframe]);

  // The moving average: a series that exists only while it is asked for.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !overlayKind) return;
    const s = chart.addSeries(LineSeries, lineOptions(readTheme().overlay, 2));
    overlayRef.current = s;
    heldOverlay.current = { key: "", points: [] };
    return () => {
      if (chartRef.current) chartRef.current.removeSeries(s);
      overlayRef.current = null;
    };
  }, [overlayKind]);
  useEffect(() => {
    const s = overlayRef.current;
    if (!s || !overlayKind || !overlayPeriod) return;
    const values = overlayKind === "sma" ? sma(closes, overlayPeriod) : ema(closes, overlayPeriod);
    syncLine(s, heldOverlay, toLinePoints(times, values), `${overlayKind}:${overlayPeriod}|${key}`);
  }, [closes, times, overlayKind, overlayPeriod, key]);

  // RSI(14) in a pane of its own.
  useEffect(() => {
    const chart = chartRef.current;
    if (!showRsi || !chart) return;
    const theme = readTheme();
    const s = chart.addSeries(LineSeries, {
      ...lineOptions(theme.rsi, 1),
      lastValueVisible: true,
      priceFormat: { type: "price", precision: 1, minMove: 0.1 },
      // RSI is bounded; a fixed 0..100 keeps a quiet market from stretching it.
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
    }, 1);
    for (const price of [30, 70]) {
      s.createPriceLine({ price, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "", ...defined({ color: theme.grid }) });
    }
    chart.panes()[1]?.setHeight(110);
    rsiRef.current = s;
    heldRsi.current = { key: "", points: [] };
    return () => {
      if (chartRef.current) chartRef.current.removeSeries(s);
      rsiRef.current = null;
    };
  }, [showRsi]);
  useEffect(() => {
    const s = rsiRef.current;
    if (!s) return;
    syncLine(s, heldRsi, toLinePoints(times, rsi(closes, RSI_PERIOD)), key);
  }, [closes, times, showRsi, key]);

  // Position lines: redrawn only when a level actually changed.
  useEffect(() => {
    const series = candleRef.current;
    if (!series) return;
    const theme = readTheme();
    for (const l of priceLines.current) series.removePriceLine(l);
    priceLines.current = (JSON.parse(linesSig) as PositionOverlay["lines"]).map((l) => {
      const color = l.kind === "stop" ? theme.down : l.kind === "target" ? theme.up : theme.entry;
      return series.createPriceLine({
        price: l.price, title: l.title, lineWidth: 1, axisLabelVisible: true,
        lineStyle: l.kind === "entry" ? LineStyle.Solid : LineStyle.Dashed,
        ...defined({ color }),
      });
    });
  }, [linesSig, themeVersion]);

  // Markers, snapped to a bar that exists.
  useEffect(() => {
    const series = candleRef.current;
    if (!series) return;
    const theme = readTheme();
    const list = snapMarkers(JSON.parse(markersSig) as ChartMarker[], bars).map((m) => ({
      time: m.time as UTCTimestamp, position: "aboveBar" as const, shape: "circle" as const,
      text: m.label,
      color: (m.tone === "long" ? theme.up : m.tone === "short" ? theme.down : theme.crosshair) ?? "#888888",
    }));
    if (markerRef.current) markerRef.current.setMarkers(list);
    else if (list.length) markerRef.current = createSeriesMarkers(series, list);
  }, [markersSig, bars, themeVersion]);

  const shown = useMemo(() => {
    const byTime = new Map(bars.map((b) => [b.time, b]));
    return (hover !== null ? byTime.get(hover) : undefined) ?? bars[bars.length - 1];
  }, [bars, hover]);
  const up = shown.close >= shown.open;
  const f = (n: number) => n.toFixed(precision);

  return (
    <div>
      {/* The OHLC readout. Always present, so the numbers are legible even
          where a candle is one pixel wide. */}
      <div className="ohlc" role="status" aria-live="off">
        <span className="sym">{symbol ?? "—"}</span>
        {timeframe ? <span className="pill pill-muted">{timeframe}</span> : null}
        <span><i>O</i> <b className="mono">{f(shown.open)}</b></span>
        <span><i>H</i> <b className="mono">{f(shown.high)}</b></span>
        <span><i>L</i> <b className="mono">{f(shown.low)}</b></span>
        <span><i>C</i> <b className={up ? "mono side-long" : "mono side-short"}>{f(shown.close)}</b></span>
        <time className="dim mono" dateTime={new Date(shown.time * 1000).toISOString()}>{fmtTime(shown.time)}</time>
      </div>

      <div
        ref={box}
        className="price-chart"
        style={{ height }}
        role="img"
        aria-label={`Candlestick chart, ${bars.length} bars of ${symbol ?? "the selected instrument"}${timeframe ? ` on ${timeframe}` : ""}`}
      />

      <Legend overlay={overlay} showRsi={showRsi} positions={positions} />
    </div>
  );
}

/* ── words under the chart ────────────────────────────────────────────── */

function Legend({ overlay, showRsi, positions }: {
  overlay: Overlay | null; showRsi: boolean; positions: readonly PositionOverlay[];
}) {
  return (
    <div className="chart-legend">
      {overlay || showRsi ? (
        <p className="dim">
          {overlay ? <span className="pill pill-muted">{overlay.kind.toUpperCase()}({overlay.period}) · computed</span> : null}
          {showRsi ? <> <span className="pill pill-muted">RSI({RSI_PERIOD}) · computed</span></> : null}
          {" "}Computed in your browser from the bars shown. These are not the rule engine&rsquo;s values.
        </p>
      ) : null}

      {positions.map((p) => (
        <p key={p.positionId} className="dim" data-testid="position-legend">
          <span className={p.side === "BUY" ? "side-long" : "side-short"}>{p.side}</span>{" "}
          <span className="mono">#{p.positionId}</span>
          {p.missing.includes("stop") ? <> · <span className="pill pill-warn">no stop</span></> : null}
          {p.missing.includes("target") ? <> · no target</> : null}
          {p.missing.includes("entry") ? <> · entry price unknown</> : null}
        </p>
      ))}

      {/* Stated, not hidden: the platform has no volume to draw. */}
      <p className="dim">Price only — the broker read does not carry volume, so none is shown.</p>
      <p className="dim">
        Chart by{" "}
        <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
          TradingView Lightweight Charts&trade;
        </a>
        . Prices are the broker&rsquo;s, not TradingView&rsquo;s. Times are UTC.
      </p>
    </div>
  );
}
