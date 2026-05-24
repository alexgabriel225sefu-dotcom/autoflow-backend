// ─── Indicatori tehnici calculați manual ────────────────────────────────────

function sma(data, period) {
  const result = [];
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) { result.push(null); continue; }
    result.push(data.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0) / period);
  }
  return result;
}

function ema(data, period) {
  const k = 2 / (period + 1);
  const result = [];
  let prev = null;
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) { result.push(null); continue; }
    if (prev === null) {
      prev = data.slice(0, period).reduce((a, b) => a + b, 0) / period;
      result.push(prev); continue;
    }
    prev = data[i] * k + prev * (1 - k);
    result.push(prev);
  }
  return result;
}

function rsi(closes, period = 14) {
  const result = [];
  for (let i = 0; i < closes.length; i++) {
    if (i < period) { result.push(null); continue; }
    let gains = 0, losses = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const diff = closes[j] - closes[j - 1];
      if (diff > 0) gains += diff; else losses -= diff;
    }
    const ag = gains / period, al = losses / period;
    if (al === 0) { result.push(100); continue; }
    result.push(100 - 100 / (1 + ag / al));
  }
  return result;
}

// Stochastic RSI — mai sensibil decât RSI simplu
function stochRsi(closes, rsiPeriod = 14, stochPeriod = 14, kPeriod = 3, dPeriod = 3) {
  const rsiVals = rsi(closes, rsiPeriod);
  const stoch   = rsiVals.map((_, i) => {
    if (i < stochPeriod - 1 || rsiVals[i] === null) return null;
    const slice = rsiVals.slice(i - stochPeriod + 1, i + 1).filter(v => v !== null);
    if (slice.length < stochPeriod) return null;
    const lo = Math.min(...slice), hi = Math.max(...slice);
    return hi === lo ? 0 : (rsiVals[i] - lo) / (hi - lo) * 100;
  });
  const kLine = sma(stoch.filter(v => v !== null), kPeriod);
  const dLine = sma(kLine.filter(v => v !== null), dPeriod);
  // Return ultimele valori
  const lastK = kLine.filter(v => v !== null).slice(-1)[0] ?? null;
  const lastD = dLine.filter(v => v !== null).slice(-1)[0] ?? null;
  return { k: lastK, d: lastD };
}

function macd(closes, fast = 12, slow = 26, signal = 9) {
  const emaFast  = ema(closes, fast);
  const emaSlow  = ema(closes, slow);
  const macdLine = emaFast.map((v, i) => v !== null && emaSlow[i] !== null ? v - emaSlow[i] : null);
  const validMcd = macdLine.filter(v => v !== null);
  const sigLine  = ema(validMcd, signal);

  const fullSig = new Array(macdLine.length).fill(null);
  let si = 0;
  for (let i = 0; i < macdLine.length; i++) {
    if (macdLine[i] !== null) fullSig[i] = sigLine[si++] ?? null;
  }
  return {
    macd:      macdLine,
    signal:    fullSig,
    histogram: macdLine.map((v, i) => v !== null && fullSig[i] !== null ? v - fullSig[i] : null),
  };
}

function bollingerBands(closes, period = 20, multiplier = 2) {
  const midLine = sma(closes, period);
  return midLine.map((mid, i) => {
    if (mid === null) return { upper: null, mid: null, lower: null, bandwidth: null };
    const slice = closes.slice(i - period + 1, i + 1);
    const mean  = slice.reduce((a, b) => a + b, 0) / period;
    const std   = Math.sqrt(slice.reduce((a, b) => a + (b - mean) ** 2, 0) / period);
    const upper = mid + multiplier * std;
    const lower = mid - multiplier * std;
    return { upper, mid, lower, bandwidth: (upper - lower) / mid * 100 };
  });
}

// ATR — Average True Range (misura volatilității)
function atr(candles, period = 14) {
  const trValues = [];
  for (let i = 1; i < candles.length; i++) {
    const h = candles[i].high, l = candles[i].low, pc = candles[i - 1].close;
    trValues.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
  }
  const atrValues = sma(trValues, period);
  return atrValues;
}

// Detectează divergențe RSI (bullish/bearish)
function detectDivergence(closes, rsiValues, lookback = 5) {
  const last = closes.length - 1;
  if (last < lookback + 1) return 'NONE';

  const prevPriceMin = Math.min(...closes.slice(last - lookback, last));
  const prevRsiMin   = Math.min(...rsiValues.slice(last - lookback, last).filter(v => v !== null));

  // Bullish divergence: preț lower low, RSI higher low
  if (closes[last] < prevPriceMin && rsiValues[last] > prevRsiMin) return 'BULLISH';

  const prevPriceMax = Math.max(...closes.slice(last - lookback, last));
  const prevRsiMax   = Math.max(...rsiValues.slice(last - lookback, last).filter(v => v !== null));

  // Bearish divergence: preț higher high, RSI lower high
  if (closes[last] > prevPriceMax && rsiValues[last] < prevRsiMax) return 'BEARISH';

  return 'NONE';
}

// Detectează structura de piață (trend)
function marketStructure(candles, lookback = 20) {
  const recent = candles.slice(-lookback);
  const highs  = recent.map(c => c.high);
  const lows   = recent.map(c => c.low);

  // Swing highs și lows
  let hhCount = 0, llCount = 0, hlCount = 0, lhCount = 0;
  for (let i = 2; i < recent.length; i++) {
    if (highs[i] > highs[i - 1] && highs[i] > highs[i - 2]) hhCount++;
    if (lows[i] > lows[i - 1] && lows[i] > lows[i - 2]) hlCount++;
    if (highs[i] < highs[i - 1] && highs[i] < highs[i - 2]) lhCount++;
    if (lows[i] < lows[i - 1] && lows[i] < lows[i - 2]) llCount++;
  }

  if (hhCount >= 2 && hlCount >= 2) return 'UPTREND';
  if (lhCount >= 2 && llCount >= 2) return 'DOWNTREND';
  return 'SIDEWAYS';
}

function analyze(candles) {
  const closes  = candles.map(c => c.close);
  const highs   = candles.map(c => c.high);
  const lows    = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume);

  const rsiValues = rsi(closes);
  const macdData  = macd(closes);
  const bbData    = bollingerBands(closes);
  const ema20     = ema(closes, 20);
  const ema50     = ema(closes, 50);
  const ema200    = ema(closes, 200);
  const atrValues = atr(candles);
  const srsi      = stochRsi(closes);

  const last  = closes.length - 1;
  const price = closes[last];

  // ATR curent (volatilitate absolută)
  const currentAtr     = atrValues.filter(v => v !== null).slice(-1)[0] ?? 0;
  const atrPct         = (currentAtr / price * 100).toFixed(3);

  // Volum ratio
  const volRecent      = volumes.slice(-5).reduce((a, b) => a + b, 0) / 5;
  const volAvg20       = volumes.slice(-20).reduce((a, b) => a + b, 0) / 20;
  const volumeRatio    = (volRecent / volAvg20).toFixed(2);

  // Divergență RSI
  const divergence     = detectDivergence(closes, rsiValues);

  // Structura de piață
  const structure      = marketStructure(candles);

  // Poziția prețului față de BB
  const bbLast         = bbData[last];
  const bbPosition     = bbLast?.upper && bbLast?.lower
    ? ((price - bbLast.lower) / (bbLast.upper - bbLast.lower) * 100).toFixed(0)
    : null;

  return {
    price,
    rsi:          rsiValues[last]?.toFixed(2),
    macd:         macdData.macd[last]?.toFixed(6),
    macdSignal:   macdData.signal[last]?.toFixed(6),
    macdHist:     macdData.histogram[last]?.toFixed(6),
    ema20:        ema20[last]?.toFixed(6),
    ema50:        ema50[last]?.toFixed(6),
    ema200:       ema200[last]?.toFixed(6),
    bb_upper:     bbLast?.upper?.toFixed(6),
    bb_mid:       bbLast?.mid?.toFixed(6),
    bb_lower:     bbLast?.lower?.toFixed(6),
    bb_bandwidth: bbLast?.bandwidth?.toFixed(2),
    bb_position:  bbPosition,            // 0=la lower band, 100=la upper band
    atr:          currentAtr.toFixed(6),
    atrPct,                              // ATR ca % din preț
    volume:       volumes[last]?.toFixed(0),
    volumeAvg:    volAvg20.toFixed(0),
    volumeRatio,                         // >1.5 = volum mare (confirmare)
    high24h:      Math.max(...highs.slice(-96)).toFixed(6),
    low24h:       Math.min(...lows.slice(-96)).toFixed(6),
    // Trend
    emaTrend:     ema20[last] > ema50[last] ? 'BULLISH' : 'BEARISH',
    ema200Trend:  ema50[last] > ema200[last] ? 'BULLISH' : 'BEARISH',
    priceVsEma20: ((price - ema20[last]) / ema20[last] * 100).toFixed(2) + '%',
    // Avansate
    stochRsiK:    srsi.k?.toFixed(2),
    stochRsiD:    srsi.d?.toFixed(2),
    divergence,                          // BULLISH / BEARISH / NONE
    marketStructure: structure,          // UPTREND / DOWNTREND / SIDEWAYS
    // Lumânări recente
    recentCandles: candles.slice(-5).map(c => ({
      open: c.open, high: c.high, low: c.low, close: c.close,
      direction: c.close > c.open ? '🟢' : '🔴',
      bodyPct: (Math.abs(c.close - c.open) / c.open * 100).toFixed(2),
    })),
  };
}

module.exports = { analyze, rsi, macd, ema, bollingerBands, atr, stochRsi };
