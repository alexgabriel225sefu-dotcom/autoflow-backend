/**
 * The indicator functions, checked against numbers worked out by hand.
 *
 * Every expected value below was derived on paper from the definition, not
 * produced by running the function and pasting the output — a test whose
 * expectations come from the code under test only proves the code agrees
 * with itself. The working is shown beside each fixture so a reviewer can
 * redo it.
 *
 * These are COMPUTED values. The chart labels them that way, and nothing
 * here claims to match the rule engine's own series or any other platform's
 * (the seeding conventions below are the ones that differ between them).
 */
import { describe, expect, it } from "vitest";
import { ema, rsi, sma } from "./indicators";

describe("sma", () => {
  it("is the mean of the last `period` values, and null before there are enough", () => {
    // [1,2,3,4,5], period 3:
    //   i=2: (1+2+3)/3 = 2   i=3: (2+3+4)/3 = 3   i=4: (3+4+5)/3 = 4
    expect(sma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });

  it("is the value itself at period 1", () => {
    expect(sma([5, 7, 9], 1)).toEqual([5, 7, 9]);
  });

  it("gives all nulls, not a short mean, when the series is shorter than the period", () => {
    // A mean of two values called "SMA(3)" would be a different indicator.
    expect(sma([1, 2], 3)).toEqual([null, null]);
  });

  it("returns an array the same length as its input, and an empty one for empty input", () => {
    expect(sma([], 3)).toEqual([]);
    expect(sma([1, 2, 3, 4], 2)).toHaveLength(4);
  });

  it("does not mutate its input", () => {
    const v = [1, 2, 3, 4];
    sma(v, 2);
    expect(v).toEqual([1, 2, 3, 4]);
  });

  it("handles a window that does not accumulate float error across a long series", () => {
    // 1000 values of 0.1: every window of 10 is 1.0/10 = 0.1 to within 1e-12.
    const out = sma(Array(1000).fill(0.1), 10);
    expect(out[999]).toBeCloseTo(0.1, 12);
  });
});

describe("ema", () => {
  it("seeds with the SMA of the first `period` values, then applies alpha = 2/(period+1)", () => {
    // [2,4,6,8,4], period 3, alpha = 2/4 = 0.5
    //   seed at i=2: (2+4+6)/3 = 4
    //   i=3: 0.5*8 + 0.5*4 = 6
    //   i=4: 0.5*4 + 0.5*6 = 5
    expect(ema([2, 4, 6, 8, 4], 3)).toEqual([null, null, 4, 6, 5]);
  });

  it("differs from the SMA on the same data, which is the point of having both", () => {
    // SMA(3) of the same series at i=4 is (6+8+4)/3 = 6, not 5.
    expect(sma([2, 4, 6, 8, 4], 3)[4]).toBe(6);
    expect(ema([2, 4, 6, 8, 4], 3)[4]).toBe(5);
  });

  it("is the value itself at period 1 (alpha = 1)", () => {
    expect(ema([5, 7, 9], 1)).toEqual([5, 7, 9]);
  });

  it("gives all nulls when the series is shorter than the period", () => {
    expect(ema([1, 2], 3)).toEqual([null, null]);
  });

  it("stays constant on a constant series", () => {
    expect(ema([3, 3, 3, 3, 3, 3], 4)).toEqual([null, null, null, 3, 3, 3]);
  });
});

describe("rsi (Wilder smoothing)", () => {
  // closes: 10, 11, 10, 12, 11, 13      period 3
  // changes:   +1, -1, +2, -1, +2
  //
  // first value at i=3, from the first 3 changes (+1,-1,+2):
  //   avgGain = (1+0+2)/3 = 1        avgLoss = (0+1+0)/3 = 1/3
  //   RS = 1 / (1/3) = 3             RSI = 100 - 100/(1+3) = 75
  // i=4, change -1:
  //   avgGain = (1*2 + 0)/3 = 2/3    avgLoss = ((1/3)*2 + 1)/3 = 5/9
  //   RS = (2/3)/(5/9) = 6/5         RSI = 100 - 100/(11/5) = 600/11 = 54.5454…
  // i=5, change +2:
  //   avgGain = ((2/3)*2 + 2)/3 = 10/9   avgLoss = ((5/9)*2 + 0)/3 = 10/27
  //   RS = (10/9)/(10/27) = 3        RSI = 75
  const closes = [10, 11, 10, 12, 11, 13];

  it("matches the hand-computed Wilder values", () => {
    const out = rsi(closes, 3);
    expect(out.slice(0, 3)).toEqual([null, null, null]);
    expect(out[3]).toBeCloseTo(75, 10);
    expect(out[4]).toBeCloseTo(600 / 11, 10);
    expect(out[5]).toBeCloseTo(75, 10);
  });

  it("needs period+1 closes before the first value", () => {
    // 3 closes give 2 changes: not enough for period 3.
    expect(rsi([1, 2, 3], 3)).toEqual([null, null, null]);
    expect(rsi([1, 2, 3, 4], 3)[3]).toBe(100);
  });

  it("is 100 when every change is a gain, and 0 when every change is a loss", () => {
    expect(rsi([1, 2, 3, 4, 5, 6], 3).slice(3)).toEqual([100, 100, 100]);
    expect(rsi([6, 5, 4, 3, 2, 1], 3).slice(3)).toEqual([0, 0, 0]);
  });

  it("is null, not 50 or 100, on a flat series — the ratio is 0/0", () => {
    expect(rsi([5, 5, 5, 5, 5], 3)).toEqual([null, null, null, null, null]);
  });

  it("stays within 0..100 on a noisy series", () => {
    const noisy = Array.from({ length: 200 }, (_, i) => 100 + Math.sin(i / 3) * 5 + (i % 7));
    for (const v of rsi(noisy, 14)) {
      if (v !== null) {
        expect(v).toBeGreaterThanOrEqual(0);
        expect(v).toBeLessThanOrEqual(100);
      }
    }
  });

  it("defaults to the conventional period of 14", () => {
    const series = Array.from({ length: 20 }, (_, i) => 100 + (i % 3));
    const out = rsi(series);
    expect(out.slice(0, 14).every((v) => v === null)).toBe(true);
    expect(out[14]).not.toBeNull();
  });
});

describe("period validation", () => {
  it.each([0, -1, 1.5, NaN, Infinity])("refuses period %s rather than guessing", (p) => {
    expect(() => sma([1, 2, 3], p)).toThrow(RangeError);
    expect(() => ema([1, 2, 3], p)).toThrow(RangeError);
    expect(() => rsi([1, 2, 3], p)).toThrow(RangeError);
  });
});
