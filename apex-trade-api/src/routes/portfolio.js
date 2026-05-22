const express = require('express');

const router = express.Router();

// GET /portfolio — portfolio summary
router.get('/', async (req, res) => {
  // În producție: fetch din DB per user
  return res.json({
    totalValue: 12847.32,
    totalPnL: 2847.32,
    totalPnLPercent: 28.47,
    dailyPnL: 384.21,
    dailyPnLPercent: 3.08,
    winRate: 67,
    totalTrades: 142,
    currency: 'USD',
  });
});

// GET /portfolio/positions
router.get('/positions', async (req, res) => {
  return res.json([
    {
      id: 'pos_1',
      symbol: 'BTC',
      market: 'crypto',
      side: 'long',
      quantity: 0.05,
      entryPrice: 64500,
      currentPrice: 67234,
      pnl: 136.7,
      pnlPercent: 4.24,
      openedAt: new Date(Date.now() - 86400000 * 3).toISOString(),
    },
    {
      id: 'pos_2',
      symbol: 'NVDA',
      market: 'stocks',
      side: 'long',
      quantity: 2,
      entryPrice: 850,
      currentPrice: 875.4,
      pnl: 50.8,
      pnlPercent: 2.99,
      openedAt: new Date(Date.now() - 86400000).toISOString(),
    },
  ]);
});

// GET /portfolio/pnl
router.get('/pnl', async (req, res) => {
  const { period = '1M' } = req.query;
  const days = period === '1D' ? 1 : period === '1W' ? 7 : period === '1M' ? 30
    : period === '3M' ? 90 : period === '1Y' ? 365 : 180;

  let value = 10000;
  const history = Array.from({ length: Math.min(days, 100) }, (_, i) => {
    const date = new Date();
    date.setDate(date.getDate() - (days - i));
    const change = (Math.random() - 0.45) * value * 0.02;
    value += change;
    return { date: date.toISOString().split('T')[0], value: Math.round(value * 100) / 100 };
  });

  return res.json(history);
});

// GET /portfolio/history — trade history
router.get('/history', async (req, res) => {
  return res.json([]);
});

module.exports = router;
