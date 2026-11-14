/**
 * Indicators computed in the browser from the bars on screen.
 *
 * These are pure functions of a list of numbers: no clock, no network, no
 * state. They exist so the chart can overlay a moving average or an RSI, and
 * the chart labels what they draw as "computed".
 *
 * WHAT THESE ARE NOT
 *
 * They are not the rule engine's series. The engine evaluates a rule on its
 * own bars with its own seeding, and the two will differ at the edges — on
 * the first bars of a window, across a gap, in the last decimals. They are
 * also not claimed to match any other platform: EMA and RSI both have
 * several seeding conventions in use, and the ones chosen here are stated so
 * they can be compared rather than assumed.
 *
 *   SMA  the mean of the last `period` values.
 *   EMA  seeded with the SMA of the first `period` values, then
 *        ema = alpha * value + (1 - alpha) * previous, alpha = 2 / (period + 1).
 *   RSI  Wilder's: the first average gain and loss are plain means of the
 *        first `period` changes; after that avg = (previous * (period - 1) +
 *        current) / period. RSI = 100 - 100 / (1 + avgGain / avgLoss).
 *
 * Every function returns an array the SAME LENGTH as its input, with `null`
 * where the indicator is not yet defined. A null is "no value yet", and the
 * caller must draw nothing for it — never zero, never the nearest value.
 */

export type Series = readonly number[];
export type Computed = (number | null)[];

function assertPeriod(period: number): void {
  if (!Number.isInteger(period) || period < 1) {
    throw new RangeError(`period must be a whole number of at least 1, got ${period}`);
  }
}

export function sma(values: Series, period: number): Computed {
  assertPeriod(period);
  const out: Computed = new Array(values.length).fill(null);
  if (values.length < period) return out;
  // Each window is summed afresh rather than slid with add-one-drop-one. The
  // series is at most a thousand bars, so the O(n * period) cost is
  // negligible, and a running sum would accumulate float error along it.
  for (let i = period - 1; i < values.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j];
    out[i] = sum / period;
  }
  return out;
}

export function ema(values: Series, period: number): Computed {
  assertPeriod(period);
  const out: Computed = new Array(values.length).fill(null);
  if (values.length < period) return out;
  const alpha = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) seed += values[i];
  let prev = seed / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = alpha * values[i] + (1 - alpha) * prev;
    out[i] = prev;
  }
  return out;
}

export function rsi(values: Series, period = 14): Computed {
  assertPeriod(period);
  const out: Computed = new Array(values.length).fill(null);
  // `period` changes need `period + 1` values.
  if (values.length <= period) return out;

  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const change = values[i] - values[i - 1];
    if (change > 0) avgGain += change;
    else avgLoss -= change;
  }
  avgGain /= period;
  avgLoss /= period;
  out[period] = fromAverages(avgGain, avgLoss);

  for (let i = period + 1; i < values.length; i++) {
    const change = values[i] - values[i - 1];
    const gain = change > 0 ? change : 0;
    const loss = change < 0 ? -change : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    out[i] = fromAverages(avgGain, avgLoss);
  }
  return out;
}

/**
 * The RSI for one pair of averages.
 *
 * No losses at all is 100, by the definition's limit. No movement at all is
 * 0/0, which has no value: null rather than a made-up 50 or 100, so a flat
 * market draws a gap instead of a reading.
 */
function fromAverages(avgGain: number, avgLoss: number): number | null {
  if (avgLoss === 0) return avgGain === 0 ? null : 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}
