/**
 * The decisions the chart makes before it draws: which bars are acceptable,
 * how a new read becomes an in-place update, which lines a position earns,
 * and when a read has stopped being current.
 *
 * Plain data in, plain data out. No canvas, no React, no network, which is
 * what lets each rule be checked without a browser.
 *
 * The recurring rule here is the one the rest of the app keeps: when
 * something is missing, SAY it is missing. A position with no stop gets no
 * stop line and a "no stop" label; a bar with no timestamp stops the chart
 * rather than being given a made-up one.
 */
import type { Candle, Position } from "@/lib/api";

/* ── bars ─────────────────────────────────────────────────────────────── */

export type ChartBar = { time: number; open: number; high: number; low: number; close: number };

export type BarsResult = { ok: true; bars: ChartBar[] } | { ok: false; reason: string };

/**
 * The broker's candles, checked for what a time axis needs.
 *
 * `Candle.time` is optional in the API type. A bar without one cannot be put
 * on a time axis honestly (an index would invent the spacing), and the
 * library requires strictly ascending times. Anything that does not meet
 * that is refused with a reason, not repaired: sorting or de-duplicating
 * would mean showing bars the broker did not give in the order it gave them.
 */
export function toChartBars(candles: readonly Candle[]): BarsResult {
  const bars: ChartBar[] = [];
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i];
    if (typeof c.time !== "number" || !Number.isFinite(c.time)) {
      return { ok: false, reason: `Bar ${i + 1} arrived without a timestamp, so it cannot be placed on the time axis.` };
    }
    for (const k of ["open", "high", "low", "close"] as const) {
      if (typeof c[k] !== "number" || !Number.isFinite(c[k])) {
        return { ok: false, reason: `Bar ${i + 1} has an unreadable ${k} price.` };
      }
    }
    if (bars.length && c.time <= bars[bars.length - 1].time) {
      return { ok: false, reason: `Bar ${i + 1} is not later than the bar before it; the read is out of order.` };
    }
    bars.push({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close });
  }
  return { ok: true, bars };
}

/**
 * Decimal places to show: what the data really has, between 2 and 6.
 *
 * Counted after rounding to 6 places, because the broker's integer prices are
 * divided by a scale and arrive as 1.1000500000000001.
 */
export function precisionFor(bars: readonly ChartBar[]): number {
  let most = 0;
  for (const b of bars) {
    for (const v of [b.open, b.high, b.low, b.close]) {
      const s = v.toFixed(6).replace(/0+$/, "");
      const dot = s.indexOf(".");
      const decimals = dot === -1 ? 0 : s.length - dot - 1;
      if (decimals > most) most = decimals;
    }
  }
  return Math.min(6, Math.max(2, most));
}

/* ── updating in place ────────────────────────────────────────────────── */

type Timed = { time: number };

export type UpdatePlan<T> = { kind: "replace" | "update"; items: T[] };

/**
 * How to bring the chart's series from `held` to `next`.
 *
 * An "update" is `series.update` per item: the last bar changed in place,
 * and any later bars appended. It is chosen only when that is PROVABLY
 * equivalent to showing `next`, which means the two agree on every bar they
 * both cover before the last held bar. Otherwise the answer is "replace",
 * which is `setData` on the same chart. Either way the chart object lives on;
 * the difference is whether the bars already drawn are touched.
 *
 * Cases that fall to "replace", and why:
 *  - nothing held yet;
 *  - `next` ends earlier than what is held: `update` would throw on a bar
 *    older than the last;
 *  - `next` starts later than what is held ends: no overlap to compare, so
 *    continuity cannot be shown;
 *  - `next` reaches back further than what is held;
 *  - any bar in the overlap differs, or one is missing: patching only the tail
 *    would leave a revised bar showing its old values.
 */
export function planUpdate<T extends Timed>(
  held: readonly T[],
  next: readonly T[],
  same: (a: T, b: T) => boolean,
): UpdatePlan<T> {
  const replace: UpdatePlan<T> = { kind: "replace", items: [...next] };
  if (!held.length || !next.length) return replace;

  const heldFirst = held[0].time;
  const heldLast = held[held.length - 1].time;
  if (next[next.length - 1].time < heldLast) return replace;
  if (next[0].time > heldLast) return replace;
  if (next[0].time < heldFirst) return replace;

  // The overlap, before the last held bar: both sides must be identical.
  const before = (xs: readonly T[]) => xs.filter((x) => x.time >= next[0].time && x.time < heldLast);
  const a = before(held);
  const b = before(next);
  if (a.length !== b.length) return replace;
  for (let i = 0; i < a.length; i++) {
    if (a[i].time !== b[i].time || !same(a[i], b[i])) return replace;
  }
  return { kind: "update", items: next.filter((x) => x.time >= heldLast) };
}

/** What the chart holds after the plan is applied. A new array; nothing mutated. */
export function applyPlan<T extends Timed>(held: readonly T[], plan: UpdatePlan<T>): T[] {
  if (plan.kind === "replace") return [...plan.items];
  if (!plan.items.length) return [...held];
  const from = plan.items[0].time;
  return [...held.filter((x) => x.time < from), ...plan.items];
}

export const sameBar = (a: ChartBar, b: ChartBar) =>
  a.time === b.time && a.open === b.open && a.high === b.high && a.low === b.low && a.close === b.close;

export type LinePoint = { time: number; value: number };

/** Indicator values as line points; undefined values are omitted, not zeroed. */
export function toLinePoints(times: readonly number[], values: readonly (number | null)[]): LinePoint[] {
  const out: LinePoint[] = [];
  for (let i = 0; i < times.length; i++) {
    const v = values[i];
    if (v !== null && v !== undefined && Number.isFinite(v)) out.push({ time: times[i], value: v });
  }
  return out;
}

export const sameLinePoint = (a: LinePoint, b: LinePoint) => a.time === b.time && a.value === b.value;

/* ── position lines ───────────────────────────────────────────────────── */

export type LineKind = "entry" | "stop" | "target";

export type OverlayLine = {
  /** Stable across refreshes, so an unchanged line is not redrawn. */
  key: string;
  kind: LineKind;
  price: number;
  title: string;
};

export type PositionOverlay = {
  positionId: string;
  side: "BUY" | "SELL";
  units: number;
  lines: OverlayLine[];
  /** Levels the position does not have. Shown as words, never drawn. */
  missing: LineKind[];
};

/** "EUR_USD", "eur/usd" and "EURUSD" are one instrument. */
function squash(s: string): string {
  return s.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

export function sameInstrument(a: string, b: string): boolean {
  const x = squash(a);
  return x !== "" && x === squash(b);
}

const isPrice = (v: number | null | undefined): v is number =>
  typeof v === "number" && Number.isFinite(v) && v > 0;

/**
 * Entry, stop and target lines for the open positions of one instrument.
 *
 * A level that is absent is reported in `missing` and gets no line. Not a
 * line at the entry, not one at some default distance: the stop a position
 * does not have must not look like one it does. When the backend says
 * `hasStop: false` that wins over a `stopLoss` value, because the backend is
 * the one that knows.
 */
export function positionOverlays(
  positions: readonly Position[] | undefined,
  symbol: string,
): PositionOverlay[] {
  const out: PositionOverlay[] = [];
  for (const p of positions ?? []) {
    if (!sameInstrument(p.symbol, symbol)) continue;
    const id = String(p.positionId);
    const tag = `${p.side} #${id}`;
    const lines: OverlayLine[] = [];
    const missing: LineKind[] = [];

    if (isPrice(p.entryPrice)) lines.push({ key: `${id}:entry`, kind: "entry", price: p.entryPrice, title: `Entry ${tag}` });
    else missing.push("entry");

    if (p.hasStop !== false && isPrice(p.stopLoss)) {
      lines.push({ key: `${id}:stop`, kind: "stop", price: p.stopLoss, title: `Stop ${tag}` });
    } else missing.push("stop");

    if (isPrice(p.takeProfit)) lines.push({ key: `${id}:target`, kind: "target", price: p.takeProfit, title: `Target ${tag}` });
    else missing.push("target");

    out.push({ positionId: id, side: p.side, units: p.units, lines, missing });
  }
  return out;
}

/* ── markers ──────────────────────────────────────────────────────────── */

export type ChartMarker = {
  /** Unix seconds. Snapped to the nearest bar. */
  time: number;
  label: string;
  tone: "long" | "short" | "neutral";
};

export function snapMarkers(markers: readonly ChartMarker[], bars: readonly ChartBar[]): ChartMarker[] {
  if (!bars.length) return [];
  return markers.map((m) => {
    let best = bars[0].time;
    let bestD = Infinity;
    for (const b of bars) {
      const d = Math.abs(b.time - m.time);
      if (d < bestD) { bestD = d; best = b.time; }
    }
    return { ...m, time: best };
  });
}

/* ── a live price on the last candle ───────────────────────────────────── */

/** Seconds in each timeframe the app offers. */
export const TIMEFRAME_SECONDS: Readonly<Record<string, number>> = {
  "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
};

/** A quote older than this is not "live". Matches QUOTE_STALE_AFTER_S in broker_read.py. */
export const QUOTE_STALE_AFTER_S = 15;

export type LiveQuote = { bid: number; ask: number; receivedAt: number; stale?: boolean };

/**
 * The candles, with the LAST one following the live price — only when that is
 * true, and otherwise the very same array.
 *
 * Candles reach the browser through a cache of up to a minute, so the newest
 * bar can lag the market. A quote says where price is now. When that quote
 * falls INSIDE the last candle's span, the candle's close, high and low can
 * honestly follow it. In every other case this leaves the candles alone:
 *
 *  - a stale quote is not current, so it moves nothing,
 *  - a quote from before the last bar belongs to a different bar,
 *  - a quote past the end of the last bar means the candles are BEHIND. The
 *    bar that should now exist has an open the broker has not given us, and
 *    inventing one would draw a price that never printed. The next candle
 *    read catches up; until then the price is shown as a number beside the
 *    chart instead.
 *
 * The BID is used because broker trendbars are bid-based; closing a bar on the
 * ask would draw a spread-sized step the market never made.
 *
 * Containment is tested as `bar start <= received < bar start + period`
 * rather than by rounding to an epoch multiple, so a timeframe whose bars do
 * not align to UTC midnight (a daily bar at the broker's rollover) is handled
 * correctly instead of silently never matching.
 *
 * Returns the same array when nothing changes, so a caller can tell "no
 * change" by identity; never mutates its input.
 */
export function applyQuote(
  candles: Candle[], quote: LiveQuote | null | undefined, timeframe: string,
): Candle[] {
  if (!quote || quote.stale || !candles.length) return candles;
  const period = TIMEFRAME_SECONDS[String(timeframe || "").toLowerCase()];
  const bid = quote.bid;
  if (!period || !(bid > 0) || !(quote.receivedAt > 0)) return candles;
  const last = candles[candles.length - 1];
  if (typeof last.time !== "number") return candles;
  if (quote.receivedAt < last.time || quote.receivedAt >= last.time + period) return candles;
  const moved: Candle = {
    ...last, close: bid, high: Math.max(last.high, bid), low: Math.min(last.low, bid),
  };
  return [...candles.slice(0, -1), moved];
}

/* ── staleness ────────────────────────────────────────────────────────── */

/** A read older than this is not "live", whatever else is true of it. */
export const STALE_AFTER_MS = 30_000;

/**
 * Whether what is on screen has stopped being current.
 *
 * Stale when the last read failed, when nothing has ever been read, or when
 * the last answer is more than 30 seconds old (polling is every 5, so that
 * is six missed refreshes, or a hidden tab that has just come back).
 */
export function isStale({ lastSync, now, failed }: { lastSync: number | null; now: number; failed: boolean }): boolean {
  if (failed || lastSync === null) return true;
  return now - lastSync > STALE_AFTER_MS;
}
