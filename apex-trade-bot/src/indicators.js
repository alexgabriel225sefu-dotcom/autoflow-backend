// ─── Indicatori tehnici calculați manual (fără librării externe) ───────────────

function sma(data, period) {
  const result = [];
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) { result.push(null); continue; }
    const slice = data.slice(i - period + 1, i + 1);
    result.push(slice.reduce((a, b) => a + b, 0) / period);
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
    const avgGain = gains / period;
    const avgLoss = losses / period;
    if (avgLoss === 0) { result.push(100); continue; }
    const rs = avgGain / avgLoss;
    result.push(100 - 100 / (1 + rs));
  }
  return result;
}

function macd(closes, fast = 12, slow = 26, signal = 9) {
  const emaFast   = ema(closes, fast);
  const emaSlow   = ema(closes, slow);
  const macdLine  = emaFast.map((v, i) => v !== null && emaSlow[i] !== null ? v - emaSlow[i] : null);
  const validMacd = macdLine.filter(v => v !== null);
  const sigLine   = ema(validMacd, signal);

  const fullSig = new Array(macdLine.length).fill(null);
  let si = 0;
  for (let i = 0; i < macdLine.length; i++) {
    if (macdLine[i] !== null) { fullSig[i] = sigLine[si++] ?? null; }
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
    if (mid === null) return { upper: null, mid: null, lower: null };
    const slice = closes.slice(i - period + 1, i + 1);
    const mean  = slice.reduce((a, b) => a + b, 0) / period;
    const std   = Math.sqrt(slice.reduce((a, b) => a + (b - mean) ** 2, 0) / period);
    return { upper: mid + multiplier * std, mid, lower: mid - multiplier * std };
  });
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

  const last = closes.length - 1;
  const price = closes[last];

  return {
    price,
    rsi:         rsiValues[last]?.toFixed(2),
    macd:        macdData.macd[last]?.toFixed(4),
    macdSignal:  macdData.signal[last]?.toFixed(4),
    macdHist:    macdData.histogram[last]?.toFixed(4),
    ema20:       ema20[last]?.toFixed(4),
    ema50:       ema50[last]?.toFixed(4),
    bb_upper:    bbData[last]?.upper?.toFixed(4),
    bb_mid:      bbData[last]?.mid?.toFixed(4),
    bb_lower:    bbData[last]?.lower?.toFixed(4),
    volume:      volumes[last]?.toFixed(0),
    volumeAvg:   (volumes.slice(-20).reduce((a, b) => a + b, 0) / 20).toFixed(0),
    high24h:     Math.max(...highs.slice(-24)).toFixed(4),
    low24h:      Math.min(...lows.slice(-24)).toFixed(4),
    // Trend
    emaTrend:    ema20[last] > ema50[last] ? 'BULLISH' : 'BEARISH',
    priceVsEma20: ((price - ema20[last]) / ema20[last] * 100).toFixed(2) + '%',
    // Candles recente
    recentCandles: candles.slice(-5).map(c => ({
      open: c.open, high: c.high, low: c.low, close: c.close,
      direction: c.close > c.open ? '🟢' : '🔴',
    })),
  };
}

module.exports = { analyze, rsi, macd, ema, bollingerBands };
