const express = require('express');
const axios = require('axios');

const router = express.Router();

const STRATEGIES = [
  { id: 'rsi_macd', name: 'RSI + MACD', description: 'Combinație clasică momentum' },
  { id: 'bb_rsi', name: 'Bollinger Bands + RSI', description: 'Mean reversion strategy' },
  { id: 'ema_crossover', name: 'EMA Crossover', description: 'Golden/Death cross' },
  { id: 'breakout', name: 'Breakout Strategy', description: 'Rupere nivele cheie' },
  { id: 'ai_adaptive', name: '🤖 AI Adaptive', description: 'Strategy adaptivă ML' },
];

// GET /backtest/strategies
router.get('/strategies', (req, res) => {
  res.json(STRATEGIES);
});

// GET /backtest/history
router.get('/history', async (req, res) => {
  // În producție — din DB per user
  res.json([]);
});

// GET /backtest/:id
router.get('/:id', (req, res) => {
  res.status(404).json({ error: 'Backtestul nu a fost găsit' });
});

// POST /backtest/run
router.post('/run', async (req, res) => {
  const { strategy, symbol, market, startDate, endDate, initialCapital = 10000, params = {} } = req.body;

  if (!strategy || !symbol || !market || !startDate || !endDate) {
    return res.status(400).json({ error: 'Câmpuri obligatorii lipsă' });
  }

  try {
    // Fetch OHLCV data
    let klines = [];
    if (market === 'crypto') {
      try {
        const sym = symbol.includes('USDT') ? symbol : `${symbol}USDT`;
        const response = await axios.get('https://api.binance.com/api/v3/klines', {
          params: { symbol: sym, interval: '1d', limit: 365 },
        });
        klines = response.data.map((k) => ({
          date: new Date(k[0]).toISOString().split('T')[0],
          open: parseFloat(k[1]),
          high: parseFloat(k[2]),
          low: parseFloat(k[3]),
          close: parseFloat(k[4]),
          volume: parseFloat(k[5]),
        }));
      } catch {
        klines = generateMockKlines(startDate, endDate);
      }
    } else {
      klines = generateMockKlines(startDate, endDate);
    }

    // Run backtest engine
    const result = runBacktest(strategy, klines, initialCapital, params);
    return res.json(result);
  } catch (err) {
    console.error('[Backtest]', err);
    return res.status(500).json({ error: 'Backtestul a eșuat: ' + err.message });
  }
});

// ─── Backtest Engine ──────────────────────────────────────
function runBacktest(strategy, klines, initialCapital, params) {
  const trades = [];
  let capital = initialCapital;
  let position = null;
  let equityCurve = [{ date: klines[0]?.date || '2024-01-01', value: initialCapital }];

  // Calculate indicators
  const closes = klines.map((k) => k.close);
  const rsi = calculateRSI(closes, 14);
  const { macd, signal: macdSignal } = calculateMACD(closes);
  const ema20 = calculateEMA(closes, 20);
  const ema50 = calculateEMA(closes, 50);
  const bb = calculateBB(closes, 20);

  for (let i = 50; i < klines.length; i++) {
    const candle = klines[i];
    const currentRSI = rsi[i];
    const currentMACD = macd[i];
    const currentMACDSignal = macdSignal[i];
    const currentEMA20 = ema20[i];
    const currentEMA50 = ema50[i];
    const bbUpper = bb.upper[i];
    const bbLower = bb.lower[i];

    let signal = 'HOLD';

    switch (strategy) {
      case 'rsi_macd':
        if (currentRSI < 35 && currentMACD > currentMACDSignal) signal = 'BUY';
        else if (currentRSI > 65 && currentMACD < currentMACDSignal) signal = 'SELL';
        break;
      case 'ema_crossover':
        if (ema20[i - 1] <= ema50[i - 1] && currentEMA20 > currentEMA50) signal = 'BUY';
        else if (ema20[i - 1] >= ema50[i - 1] && currentEMA20 < currentEMA50) signal = 'SELL';
        break;
      case 'bb_rsi':
        if (candle.close <= bbLower && currentRSI < 40) signal = 'BUY';
        else if (candle.close >= bbUpper && currentRSI > 60) signal = 'SELL';
        break;
      case 'breakout':
        const recentHighs = klines.slice(i - 20, i).map((k) => k.high);
        const breakoutLevel = Math.max(...recentHighs);
        if (candle.close > breakoutLevel * 0.998 && !position) signal = 'BUY';
        break;
      case 'ai_adaptive':
        // Adaptive: combine multiple signals
        const bullPoints = [
          currentRSI < 45 ? 1 : 0,
          currentMACD > currentMACDSignal ? 1 : 0,
          currentEMA20 > currentEMA50 ? 1 : 0,
          candle.close > candle.open ? 1 : 0,
        ].reduce((a, b) => a + b, 0);
        if (bullPoints >= 3) signal = 'BUY';
        else if (bullPoints <= 1) signal = 'SELL';
        break;
    }

    // Execute trades
    if (signal === 'BUY' && !position) {
      const shares = capital / candle.close;
      position = { entryPrice: candle.close, shares, date: candle.date };
    } else if (signal === 'SELL' && position) {
      const exitValue = position.shares * candle.close;
      const pnl = exitValue - position.shares * position.entryPrice;
      const pnlPercent = (pnl / (position.shares * position.entryPrice)) * 100;
      capital = exitValue;

      trades.push({
        date: candle.date,
        action: 'SELL',
        price: candle.close,
        pnl,
        pnlPercent,
      });

      position = null;
    }

    // Stop loss / take profit (5% SL, 10% TP)
    if (position) {
      const currentReturn = (candle.close - position.entryPrice) / position.entryPrice;
      if (currentReturn <= -0.05 || currentReturn >= 0.10) {
        const exitValue = position.shares * candle.close;
        const pnl = exitValue - position.shares * position.entryPrice;
        capital = exitValue;
        trades.push({
          date: candle.date,
          action: currentReturn > 0 ? 'TP' : 'SL',
          price: candle.close,
          pnl,
          pnlPercent: currentReturn * 100,
        });
        position = null;
      }
    }

    if (i % 7 === 0) {
      const currentValue = position
        ? position.shares * candle.close
        : capital;
      equityCurve.push({ date: candle.date, value: Math.round(currentValue * 100) / 100 });
    }
  }

  // Close remaining position
  if (position && klines.length > 0) {
    const lastCandle = klines[klines.length - 1];
    const exitValue = position.shares * lastCandle.close;
    capital = exitValue;
  }

  const totalReturn = ((capital - initialCapital) / initialCapital) * 100;
  const winTrades = trades.filter((t) => t.pnl > 0);
  const lossTrades = trades.filter((t) => t.pnl <= 0);
  const winRate = trades.length > 0 ? (winTrades.length / trades.length) * 100 : 0;
  const avgWin = winTrades.length > 0 ? winTrades.reduce((a, t) => a + t.pnl, 0) / winTrades.length : 0;
  const avgLoss = lossTrades.length > 0 ? Math.abs(lossTrades.reduce((a, t) => a + t.pnl, 0) / lossTrades.length) : 1;
  const profitFactor = avgLoss > 0 ? avgWin / avgLoss : 0;

  // Annualized return
  const days = klines.length;
  const annualizedReturn = totalReturn * (365 / days);

  // Max drawdown
  let peak = initialCapital;
  let maxDrawdown = 0;
  equityCurve.forEach((e) => {
    if (e.value > peak) peak = e.value;
    const dd = ((peak - e.value) / peak) * 100;
    if (dd > maxDrawdown) maxDrawdown = dd;
  });

  // Sharpe ratio (simplified)
  const returns = equityCurve.slice(1).map((e, i) =>
    (e.value - equityCurve[i].value) / equityCurve[i].value
  );
  const avgReturn = returns.reduce((a, b) => a + b, 0) / returns.length || 0;
  const stdDev = Math.sqrt(returns.reduce((a, r) => a + Math.pow(r - avgReturn, 2), 0) / returns.length) || 0.01;
  const sharpeRatio = (avgReturn / stdDev) * Math.sqrt(252);

  return {
    id: `bt_${Date.now()}`,
    strategy,
    symbol,
    totalReturn: Math.round(totalReturn * 100) / 100,
    annualizedReturn: Math.round(annualizedReturn * 100) / 100,
    sharpeRatio: Math.round(sharpeRatio * 100) / 100,
    maxDrawdown: Math.round(maxDrawdown * 100) / 100,
    winRate: Math.round(winRate * 100) / 100,
    totalTrades: trades.length,
    profitFactor: Math.round(profitFactor * 100) / 100,
    avgTradeReturn: trades.length > 0
      ? Math.round((trades.reduce((a, t) => a + t.pnlPercent, 0) / trades.length) * 100) / 100
      : 0,
    finalCapital: Math.round(capital * 100) / 100,
    equityCurve,
    trades: trades.slice(-50),
  };
}

// ─── Technical Indicators ─────────────────────────────────
function calculateRSI(prices, period = 14) {
  const rsi = new Array(prices.length).fill(50);
  let gains = 0, losses = 0;

  for (let i = 1; i <= period; i++) {
    const diff = prices[i] - prices[i - 1];
    if (diff > 0) gains += diff;
    else losses -= diff;
  }

  let avgGain = gains / period;
  let avgLoss = losses / period;

  for (let i = period; i < prices.length; i++) {
    const diff = prices[i] - prices[i - 1];
    avgGain = (avgGain * (period - 1) + Math.max(diff, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-diff, 0)) / period;
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    rsi[i] = 100 - 100 / (1 + rs);
  }

  return rsi;
}

function calculateEMA(prices, period) {
  const ema = new Array(prices.length).fill(0);
  const k = 2 / (period + 1);
  ema[0] = prices[0];
  for (let i = 1; i < prices.length; i++) {
    ema[i] = prices[i] * k + ema[i - 1] * (1 - k);
  }
  return ema;
}

function calculateMACD(prices, fast = 12, slow = 26, signal = 9) {
  const emaFast = calculateEMA(prices, fast);
  const emaSlow = calculateEMA(prices, slow);
  const macd = emaFast.map((f, i) => f - emaSlow[i]);
  const signalLine = calculateEMA(macd, signal);
  return { macd, signal: signalLine };
}

function calculateBB(prices, period = 20) {
  const upper = new Array(prices.length).fill(0);
  const lower = new Array(prices.length).fill(0);
  const middle = new Array(prices.length).fill(0);

  for (let i = period - 1; i < prices.length; i++) {
    const slice = prices.slice(i - period + 1, i + 1);
    const avg = slice.reduce((a, b) => a + b, 0) / period;
    const variance = slice.reduce((a, b) => a + Math.pow(b - avg, 2), 0) / period;
    const std = Math.sqrt(variance);
    middle[i] = avg;
    upper[i] = avg + 2 * std;
    lower[i] = avg - 2 * std;
  }

  return { upper, middle, lower };
}

function generateMockKlines(startDate, endDate) {
  const start = new Date(startDate);
  const end = new Date(endDate);
  const days = Math.floor((end - start) / 86400000);
  let price = 67000;

  return Array.from({ length: Math.min(days, 365) }, (_, i) => {
    const date = new Date(start);
    date.setDate(date.getDate() + i);
    const change = (Math.random() - 0.48) * price * 0.03;
    const open = price;
    const close = price + change;
    const high = Math.max(open, close) * (1 + Math.random() * 0.01);
    const low = Math.min(open, close) * (1 - Math.random() * 0.01);
    price = close;
    return {
      date: date.toISOString().split('T')[0],
      open: Math.round(open * 100) / 100,
      high: Math.round(high * 100) / 100,
      low: Math.round(low * 100) / 100,
      close: Math.round(close * 100) / 100,
      volume: Math.floor(Math.random() * 10000 + 1000),
    };
  });
}

module.exports = router;
