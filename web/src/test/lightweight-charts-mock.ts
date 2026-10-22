/**
 * A stand-in for `lightweight-charts`, for tests only.
 *
 * jsdom has no canvas, so the real library cannot draw here. The tests do not
 * need it to: what matters is what OUR code asks of it — which options, which
 * data, which price lines, whether it updates in place or starts again. This
 * records every such call so a test can assert on it.
 *
 * Use it from a test file with:
 *
 *   vi.mock("lightweight-charts", async () => (await import("@/test/lightweight-charts-mock")).factory());
 *   import { lwc } from "@/test/lightweight-charts-mock";
 *
 * It draws nothing, so a passing test says nothing about how the chart looks.
 */
import { vi } from "vitest";

export type FakeLine = { options: Record<string, unknown>; removed: boolean };

export type FakeSeries = {
  definition: { kind: string };
  options: Record<string, unknown>;
  paneIndex: number | undefined;
  setData: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  createPriceLine: ReturnType<typeof vi.fn>;
  removePriceLine: ReturnType<typeof vi.fn>;
  lines: FakeLine[];
  removed: boolean;
};

export type FakeChart = {
  container: unknown;
  options: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  series: FakeSeries[];
  applyOptions: ReturnType<typeof vi.fn>;
  remove: ReturnType<typeof vi.fn>;
  fitContent: ReturnType<typeof vi.fn>;
  paneHeights: Record<number, number>;
  crosshairHandlers: ((p: { time?: number }) => void)[];
  subscribeCrosshairMove: ReturnType<typeof vi.fn>;
  unsubscribeCrosshairMove: ReturnType<typeof vi.fn>;
};

export type FakeMarkers = { markers: unknown[]; setMarkers: ReturnType<typeof vi.fn>; detach: ReturnType<typeof vi.fn> };

const charts: FakeChart[] = [];
const markerPlugins: FakeMarkers[] = [];

export const lwc: {
  charts: FakeChart[];
  markerPlugins: FakeMarkers[];
  reset(): void;
  /** Live (not removed) series of one kind on the most recent chart. */
  seriesOf(kind: "candlestick" | "line", chart?: FakeChart): FakeSeries[];
} = {
  charts,
  markerPlugins,
  reset() {
    charts.length = 0;
    markerPlugins.length = 0;
  },
  seriesOf(kind, chart = charts[charts.length - 1]) {
    return chart.series.filter((s) => s.definition.kind === kind && !s.removed);
  },
};

function makeSeries(definition: { kind: string }, options: Record<string, unknown>, paneIndex?: number): FakeSeries {
  const s: FakeSeries = {
    definition, options, paneIndex, lines: [], removed: false,
    setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn(),
    createPriceLine: vi.fn(),
    removePriceLine: vi.fn(),
  };
  s.createPriceLine.mockImplementation((opts: Record<string, unknown>) => {
    const line: FakeLine = { options: opts, removed: false };
    s.lines.push(line);
    return line;
  });
  s.removePriceLine.mockImplementation((line: FakeLine) => { line.removed = true; });
  return s;
}

export function createChart(container: unknown, options: Record<string, unknown> = {}): FakeChart {
  const chart: FakeChart = {
    container, options, series: [], paneHeights: {}, crosshairHandlers: [],
    applyOptions: vi.fn(),
    remove: vi.fn(),
    fitContent: vi.fn(),
    subscribeCrosshairMove: vi.fn(),
    unsubscribeCrosshairMove: vi.fn(),
  };
  chart.subscribeCrosshairMove.mockImplementation((fn: (p: { time?: number }) => void) => {
    chart.crosshairHandlers.push(fn);
  });
  chart.unsubscribeCrosshairMove.mockImplementation((fn: (p: { time?: number }) => void) => {
    chart.crosshairHandlers = chart.crosshairHandlers.filter((h) => h !== fn);
  });
  const api = {
    addSeries: vi.fn((def: { kind: string }, opts: Record<string, unknown> = {}, pane?: number) => {
      const s = makeSeries(def, opts, pane);
      chart.series.push(s);
      return s;
    }),
    removeSeries: vi.fn((s: FakeSeries) => { s.removed = true; }),
    applyOptions: chart.applyOptions,
    remove: chart.remove,
    timeScale: () => ({ fitContent: chart.fitContent }),
    panes: () => [0, 1, 2].map((i) => ({ setHeight: (h: number) => { chart.paneHeights[i] = h; } })),
    subscribeCrosshairMove: chart.subscribeCrosshairMove,
    unsubscribeCrosshairMove: chart.unsubscribeCrosshairMove,
  };
  charts.push(chart);
  return Object.assign(chart, api) as unknown as FakeChart;
}

export function createSeriesMarkers(_series: unknown, markers: unknown[] = []): FakeMarkers {
  const m: FakeMarkers = {
    markers, setMarkers: vi.fn((next: unknown[]) => { m.markers = next; }), detach: vi.fn(),
  };
  markerPlugins.push(m);
  return m;
}

/** The module factory passed to `vi.mock("lightweight-charts", ...)`. */
export function factory() {
  return {
    createChart: vi.fn(createChart),
    createSeriesMarkers: vi.fn(createSeriesMarkers),
    CandlestickSeries: { kind: "candlestick" },
    LineSeries: { kind: "line" },
    ColorType: { Solid: "solid", VerticalGradient: "gradient" },
    CrosshairMode: { Normal: 0, Magnet: 1, Hidden: 2, MagnetOHLC: 3 },
    LineStyle: { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3, SparseDotted: 4 },
  };
}
