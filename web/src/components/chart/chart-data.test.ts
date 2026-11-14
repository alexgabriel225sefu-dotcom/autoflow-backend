/**
 * The decisions the chart makes before it draws anything.
 *
 * None of this touches a canvas, so it is checked as plain data: which bars
 * are acceptable, when an update may be applied in place, which lines a
 * position earns, and when a read counts as stale.
 */
import { describe, expect, it } from "vitest";
import type { Position } from "@/lib/api";
import {
  STALE_AFTER_MS, applyPlan, isStale, planUpdate, positionOverlays,
  precisionFor, sameInstrument, snapMarkers, toChartBars, toLinePoints,
  type ChartBar,
} from "./chart-data";

const bar = (time: number, close: number, over: Partial<ChartBar> = {}): ChartBar => ({
  time, open: close - 0.001, high: close + 0.002, low: close - 0.002, close, ...over,
});
const sameBar = (a: ChartBar, b: ChartBar) =>
  a.time === b.time && a.open === b.open && a.high === b.high && a.low === b.low && a.close === b.close;

describe("toChartBars", () => {
  it("accepts well-formed, ascending bars unchanged", () => {
    const r = toChartBars([
      { open: 1, high: 2, low: 0.5, close: 1.5, time: 100 },
      { open: 1.5, high: 2, low: 1, close: 1.2, time: 200 },
    ]);
    expect(r).toEqual({ ok: true, bars: [
      { time: 100, open: 1, high: 2, low: 0.5, close: 1.5 },
      { time: 200, open: 1.5, high: 2, low: 1, close: 1.2 },
    ] });
  });

  it("refuses bars with no timestamp instead of inventing an index axis", () => {
    const r = toChartBars([{ open: 1, high: 2, low: 0.5, close: 1.5 }]);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toMatch(/timestamp/i);
  });

  it("refuses non-finite prices", () => {
    const r = toChartBars([{ open: NaN, high: 2, low: 0.5, close: 1.5, time: 1 }]);
    expect(r.ok).toBe(false);
  });

  it("refuses out-of-order or duplicated times rather than silently sorting them", () => {
    expect(toChartBars([
      { open: 1, high: 1, low: 1, close: 1, time: 200 },
      { open: 1, high: 1, low: 1, close: 1, time: 100 },
    ]).ok).toBe(false);
    expect(toChartBars([
      { open: 1, high: 1, low: 1, close: 1, time: 100 },
      { open: 1, high: 1, low: 1, close: 1, time: 100 },
    ]).ok).toBe(false);
  });

  it("treats no bars as ok-and-empty; the caller decides what to say about that", () => {
    expect(toChartBars([])).toEqual({ ok: true, bars: [] });
  });
});

describe("planUpdate — update in place, never rebuild without cause", () => {
  const held = [bar(100, 1.10), bar(200, 1.11), bar(300, 1.12)];

  it("replaces when nothing is held yet", () => {
    expect(planUpdate([], held, sameBar)).toEqual({ kind: "replace", items: held });
  });

  it("updates only the last bar when it alone changed", () => {
    const next = [held[0], held[1], bar(300, 1.125)];
    expect(planUpdate(held, next, sameBar)).toEqual({ kind: "update", items: [bar(300, 1.125)] });
  });

  it("updates the last bar and appends the new one when a bar opened", () => {
    const next = [...held.slice(0, 2), bar(300, 1.121), bar(400, 1.13)];
    expect(planUpdate(held, next, sameBar)).toEqual({
      kind: "update", items: [bar(300, 1.121), bar(400, 1.13)],
    });
  });

  it("copes with the window sliding: the oldest bar drops off, a new one arrives", () => {
    const next = [held[1], held[2], bar(400, 1.13)];
    expect(planUpdate(held, next, sameBar)).toEqual({
      kind: "update", items: [held[2], bar(400, 1.13)],
    });
  });

  it("replaces when an older bar was revised, because patching only the tail would leave it wrong", () => {
    const next = [held[0], bar(200, 1.5), held[2]];
    expect(planUpdate(held, next, sameBar).kind).toBe("replace");
  });

  it("replaces when a bar is missing from the middle", () => {
    const next = [held[0], held[2]];
    expect(planUpdate(held, next, sameBar).kind).toBe("replace");
  });

  it("replaces when the data goes backwards in time — series.update would throw", () => {
    const next = [held[0], held[1]];
    expect(planUpdate(held, next, sameBar).kind).toBe("replace");
  });

  it("replaces when the new read starts after everything held — continuity cannot be shown", () => {
    const next = [bar(500, 1.2), bar(600, 1.21)];
    expect(planUpdate(held, next, sameBar).kind).toBe("replace");
  });

  it("replaces when the new read reaches further back than what is held", () => {
    const next = [bar(50, 1.0), ...held];
    expect(planUpdate(held, next, sameBar).kind).toBe("replace");
  });

  it("applyPlan keeps what the chart really holds, without mutating the old array", () => {
    const snapshot = [...held];
    const plan = planUpdate(held, [held[1], held[2], bar(400, 1.13)], sameBar);
    const after = applyPlan(held, plan);
    expect(after.map((b) => b.time)).toEqual([100, 200, 300, 400]);
    expect(held).toEqual(snapshot);
  });

  it("applyPlan on a replace is exactly the new data", () => {
    const next = [bar(500, 1.2)];
    expect(applyPlan(held, planUpdate(held, next, sameBar))).toEqual(next);
  });
});

describe("toLinePoints", () => {
  it("pairs values with times and drops the nulls, never zero-filling them", () => {
    expect(toLinePoints([1, 2, 3], [null, 5, 6])).toEqual([
      { time: 2, value: 5 }, { time: 3, value: 6 },
    ]);
  });
});

describe("precisionFor", () => {
  it("uses the decimals the data actually has, ignoring float noise from the broker scaling", () => {
    expect(precisionFor([bar(1, 1.10005, { open: 1.1000500000000001, high: 1.1, low: 1.1, close: 1.10005 })])).toBe(5);
    expect(precisionFor([{ time: 1, open: 150.123, high: 150.2, low: 150.1, close: 150.15 }])).toBe(3);
  });
  it("never goes below 2", () => {
    expect(precisionFor([{ time: 1, open: 2000, high: 2001, low: 1999, close: 2000 }])).toBe(2);
  });
  it("is capped at 6", () => {
    expect(precisionFor([{ time: 1, open: 0.123456789, high: 0.2, low: 0.1, close: 0.15 }])).toBe(6);
  });
});

describe("sameInstrument", () => {
  it("ignores case and separators, because the broker and the rule spell the same pair differently", () => {
    expect(sameInstrument("EURUSD", "EUR_USD")).toBe(true);
    expect(sameInstrument("eur/usd", "EURUSD")).toBe(true);
  });
  it("does not conflate different instruments", () => {
    expect(sameInstrument("EURUSD", "GBPUSD")).toBe(false);
    expect(sameInstrument("", "")).toBe(false);
  });
});

describe("positionOverlays", () => {
  const pos = (over: Partial<Position> = {}): Position => ({
    symbol: "EURUSD", side: "BUY", units: 1000, entryPrice: 1.1, stopLoss: 1.095,
    takeProfit: 1.11, positionId: 7, ...over,
  });

  it("draws entry, stop and target for a fully specified position", () => {
    const [o] = positionOverlays([pos()], "EURUSD");
    expect(o.lines.map((l) => [l.kind, l.price])).toEqual([
      ["entry", 1.1], ["stop", 1.095], ["target", 1.11],
    ]);
    expect(o.missing).toEqual([]);
  });

  it("draws NOTHING for a null stop and records that it is missing — never a guessed line", () => {
    const [o] = positionOverlays([pos({ stopLoss: null })], "EURUSD");
    expect(o.lines.some((l) => l.kind === "stop")).toBe(false);
    expect(o.missing).toContain("stop");
    expect(o.lines.map((l) => l.kind)).toEqual(["entry", "target"]);
  });

  it("trusts the backend's own hasStop=false over a stopLoss value", () => {
    const [o] = positionOverlays([pos({ hasStop: false, stopLoss: 1.09 })], "EURUSD");
    expect(o.lines.some((l) => l.kind === "stop")).toBe(false);
    expect(o.missing).toContain("stop");
  });

  it("treats a zero or non-finite stop as missing; zero is not a price", () => {
    expect(positionOverlays([pos({ stopLoss: 0 })], "EURUSD")[0].missing).toContain("stop");
    expect(positionOverlays([pos({ stopLoss: NaN })], "EURUSD")[0].missing).toContain("stop");
  });

  it("does the same for a missing target and a missing entry", () => {
    const [o] = positionOverlays([pos({ takeProfit: null, entryPrice: null })], "EURUSD");
    expect(o.lines).toEqual([expect.objectContaining({ kind: "stop" })]);
    expect(o.missing.sort()).toEqual(["entry", "target"]);
  });

  it("only includes positions of the selected instrument", () => {
    const out = positionOverlays(
      [pos({ positionId: 1 }), pos({ positionId: 2, symbol: "GBPUSD" }), pos({ positionId: 3, symbol: "EUR_USD" })],
      "EURUSD",
    );
    expect(out.map((o) => o.positionId)).toEqual(["1", "3"]);
  });

  it("gives every line a distinct key and a title that names side and position", () => {
    const [o] = positionOverlays([pos()], "EURUSD");
    expect(new Set(o.lines.map((l) => l.key)).size).toBe(3);
    expect(o.lines[0].title).toMatch(/Entry/);
    expect(o.lines[0].title).toMatch(/BUY/);
    expect(o.lines[0].title).toMatch(/7/);
  });

  it("returns nothing for an undefined positions list", () => {
    expect(positionOverlays(undefined, "EURUSD")).toEqual([]);
  });
});

describe("snapMarkers", () => {
  it("moves a marker onto the nearest bar time", () => {
    const bars = [bar(100, 1), bar(200, 1), bar(300, 1)];
    const out = snapMarkers([{ time: 240, label: "x", tone: "long" }], bars);
    expect(out[0].time).toBe(200);
    expect(out[0].label).toBe("x");
  });
  it("draws none when there are no bars to snap to", () => {
    expect(snapMarkers([{ time: 1, label: "x", tone: "long" }], [])).toEqual([]);
  });
});

describe("isStale", () => {
  const now = 1_000_000;
  it("is fresh within the window and stale beyond it", () => {
    expect(isStale({ lastSync: now - STALE_AFTER_MS, now, failed: false })).toBe(false);
    expect(isStale({ lastSync: now - STALE_AFTER_MS - 1, now, failed: false })).toBe(true);
  });
  it("is stale whenever the last read failed, however recent", () => {
    expect(isStale({ lastSync: now - 100, now, failed: true })).toBe(true);
  });
  it("is stale when nothing was ever synced", () => {
    expect(isStale({ lastSync: null, now, failed: false })).toBe(true);
  });
  it("uses a 30 second window", () => {
    expect(STALE_AFTER_MS).toBe(30_000);
  });
});
