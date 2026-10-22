/**
 * The last candle follows the live price — only when that is true.
 *
 * `applyQuote` is the one place a live price is allowed to change what the
 * chart shows. Everything it must NOT do matters more than what it does:
 *
 *  - it must not make a stale price look current,
 *  - it must not invent a bar the broker has not produced (a quote past the
 *    end of the last candle means the candles are behind, and the honest
 *    answer is to leave them alone and let the next read catch up),
 *  - it must not move an old bar with a price from a different bar,
 *  - it must not touch the array it was given.
 */
import { describe, expect, it } from "vitest";
import type { Candle } from "@/lib/api";
import { applyQuote, TIMEFRAME_SECONDS } from "./chart-data";

const HOUR = 3600;
const T0 = 1_700_000_000 - (1_700_000_000 % HOUR);     // an hour boundary

const bars = (): Candle[] => [
  { time: T0 - HOUR, open: 1.1000, high: 1.1010, low: 1.0990, close: 1.1005 },
  { time: T0,        open: 1.1005, high: 1.1020, low: 1.1000, close: 1.1010 },
];
const quote = (over: Partial<{ bid: number; ask: number; receivedAt: number; stale: boolean }> = {}) =>
  ({ bid: 1.1015, ask: 1.1017, receivedAt: T0 + 600, stale: false, ...over });

describe("a fresh quote inside the last candle", () => {
  it("moves the close to the bid", () => {
    const out = applyQuote(bars(), quote(), "1h");
    expect(out[1].close).toBe(1.1015);
  });

  it("uses the BID, not the ask or the mid", () => {
    // Broker trendbars are bid-based. Closing a bar on the ask would draw a
    // spread-sized step that the market never printed.
    const out = applyQuote(bars(), quote({ bid: 1.1015, ask: 1.2000 }), "1h");
    expect(out[1].close).toBe(1.1015);
  });

  it("extends the high when the price makes a new high", () => {
    const out = applyQuote(bars(), quote({ bid: 1.1030 }), "1h");
    expect(out[1].high).toBe(1.1030);
    expect(out[1].low).toBe(1.1000);
  });

  it("extends the low when the price makes a new low", () => {
    const out = applyQuote(bars(), quote({ bid: 1.0990 }), "1h");
    expect(out[1].low).toBe(1.0990);
    expect(out[1].high).toBe(1.1020);
  });

  it("never changes the open, or any earlier candle", () => {
    const out = applyQuote(bars(), quote({ bid: 1.1030 }), "1h");
    expect(out[1].open).toBe(1.1005);
    expect(out[0]).toEqual(bars()[0]);
  });

  it("works at the first instant of the bar, and not at the first of the next", () => {
    expect(applyQuote(bars(), quote({ receivedAt: T0 }), "1h")[1].close).toBe(1.1015);
    expect(applyQuote(bars(), quote({ receivedAt: T0 + HOUR - 1 }), "1h")[1].close).toBe(1.1015);
    expect(applyQuote(bars(), quote({ receivedAt: T0 + HOUR }), "1h")[1].close).toBe(1.1010);
  });
});

describe("what it refuses to do", () => {
  it("ignores a stale quote", () => {
    const original = bars();
    const out = applyQuote(original, quote({ stale: true }), "1h");
    expect(out).toBe(original);                      // the very same array
  });

  it("ignores a quote from before the last candle", () => {
    // The price belongs to an earlier bar. Applying it to the last one would
    // draw a price the market was not at during that bar.
    const original = bars();
    expect(applyQuote(original, quote({ receivedAt: T0 - 5 }), "1h")).toBe(original);
  });

  it("does NOT invent a new bar when the quote is past the last candle", () => {
    // The candles are behind the market (they come through a cache). The
    // honest move is to leave them alone, not to fabricate an open the
    // broker never gave.
    const original = bars();
    const out = applyQuote(original, quote({ receivedAt: T0 + HOUR + 30 }), "1h");
    expect(out).toBe(original);
    expect(out.length).toBe(2);
  });

  it("does nothing for a timeframe it cannot size", () => {
    const original = bars();
    expect(applyQuote(original, quote(), "7m")).toBe(original);
    expect(applyQuote(original, quote(), "")).toBe(original);
  });

  it("does nothing without a usable price", () => {
    const original = bars();
    for (const bad of [0, -1, NaN]) {
      expect(applyQuote(original, quote({ bid: bad }), "1h")).toBe(original);
    }
    expect(applyQuote(original, null, "1h")).toBe(original);
  });

  it("does nothing when the last candle has no time", () => {
    const noTime: Candle[] = [{ open: 1, high: 2, low: 0.5, close: 1.5 }];
    expect(applyQuote(noTime, quote(), "1h")).toBe(noTime);
  });

  it("does nothing on an empty list", () => {
    const empty: Candle[] = [];
    expect(applyQuote(empty, quote(), "1h")).toBe(empty);
  });

  it("never mutates the array or the candle it was given", () => {
    const original = bars();
    const snapshot = JSON.parse(JSON.stringify(original));
    applyQuote(original, quote({ bid: 1.1030 }), "1h");
    expect(original).toEqual(snapshot);
  });
});

describe("the timeframe table", () => {
  it("covers every timeframe the app offers", async () => {
    const { TIMEFRAMES } = await import("@/components/app/rule-form");
    for (const tf of TIMEFRAMES) {
      expect(TIMEFRAME_SECONDS[tf], `no period for ${tf}`).toBeGreaterThan(0);
    }
  });
});
