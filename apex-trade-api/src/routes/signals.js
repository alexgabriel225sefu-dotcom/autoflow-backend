const express = require('express');
const Anthropic = require('@anthropic-ai/sdk');
const axios = require('axios');

const router = express.Router();

let _anthropic = null;
function getAnthropic() {
  if (!_anthropic) {
    _anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY || 'placeholder' });
  }
  return _anthropic;
}

const BINANCE_BASE = 'https://api.binance.com/api/v3';

// Mock signals store (în producție folosești DB)
const signalsStore = [];

function generateMockSignals() {
  const assets = [
    { symbol: 'BTC', market: 'crypto', price: 67234 },
    { symbol: 'ETH', market: 'crypto', price: 3521 },
    { symbol: 'SOL', market: 'crypto', price: 171.8 },
    { symbol: 'AAPL', market: 'stocks', price: 189.3 },
    { symbol: 'NVDA', market: 'stocks', price: 875.4 },
    { symbol: 'EUR/USD', market: 'forex', price: 1.0875 },
  ];

  const actions = ['BUY', 'SELL', 'HOLD'];
  const timeframes = ['15m', '1h', '4h', '1d'];

  return assets.map((asset, i) => {
    const action = actions[Math.floor(Math.random() * 2)]; // BUY or SELL
    const confidence = Math.floor(Math.random() * 40 + 55); // 55-95
    const direction = action === 'BUY' ? 1 : -1;
    const targetPct = (Math.random() * 0.05 + 0.02) * direction;
    const slPct = (Math.random() * 0.02 + 0.01) * -direction;

    return {
      id: `sig_${Date.now()}_${i}`,
      symbol: asset.symbol,
      market: asset.market,
      action,
      confidence,
      entryPrice: asset.price,
      targetPrice: asset.price * (1 + targetPct),
      stopLoss: asset.price * (1 + slPct),
      riskRewardRatio: Math.abs(targetPct / slPct),
      timeframe: timeframes[Math.floor(Math.random() * timeframes.length)],
      reasoning: `AI a detectat un pattern ${action === 'BUY' ? 'bullish' : 'bearish'} puternic pe ${asset.symbol}. Indicatorii tehnici sugerează o mișcare de ${(Math.abs(targetPct) * 100).toFixed(1)}% în următoarele ore.`,
      indicators: {
        rsi: Math.floor(Math.random() * 30 + (action === 'BUY' ? 30 : 50)),
        macd: parseFloat(((Math.random() - 0.5) * 100).toFixed(2)),
        macdSignal: parseFloat(((Math.random() - 0.5) * 80).toFixed(2)),
        ema20: parseFloat((asset.price * (0.98 + Math.random() * 0.04)).toFixed(4)),
        ema50: parseFloat((asset.price * (0.96 + Math.random() * 0.08)).toFixed(4)),
        bb_upper: parseFloat((asset.price * 1.02).toFixed(4)),
        bb_lower: parseFloat((asset.price * 0.98).toFixed(4)),
        volume_ratio: parseFloat((1 + Math.random()).toFixed(2)),
      },
      newssentiment: ['positive', 'negative', 'neutral'][Math.floor(Math.random() * 3)],
      macroImpact: ['positive', 'negative', 'neutral'][Math.floor(Math.random() * 3)],
      createdAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 4 * 3600000).toISOString(),
      status: 'active',
    };
  });
}

// GET /signals
router.get('/', (req, res) => {
  const { market } = req.query;
  let signals = signalsStore.length > 0 ? signalsStore : generateMockSignals();

  if (market && market !== 'all') {
    signals = signals.filter((s) => s.market === market);
  }

  return res.json(signals);
});

// GET /signals/:id
router.get('/:id', (req, res) => {
  const signal = signalsStore.find((s) => s.id === req.params.id);
  if (!signal) return res.status(404).json({ error: 'Signal negăsit' });
  return res.json(signal);
});

// POST /signals/analyze — AI Analysis via Claude
router.post('/analyze', async (req, res) => {
  const { symbol, market } = req.body;
  if (!symbol || !market) {
    return res.status(400).json({ error: 'Symbol și market sunt obligatorii' });
  }

  try {
    // Fetch live price data
    let priceData = null;
    if (market === 'crypto') {
      try {
        const sym = symbol.includes('USDT') ? symbol : `${symbol}USDT`;
        const [tickerRes, klinesRes] = await Promise.all([
          axios.get(`${BINANCE_BASE}/ticker/24hr`, { params: { symbol: sym } }),
          axios.get(`${BINANCE_BASE}/klines`, { params: { symbol: sym, interval: '1h', limit: 24 } }),
        ]);
        priceData = {
          price: parseFloat(tickerRes.data.lastPrice),
          change24h: parseFloat(tickerRes.data.priceChangePercent),
          volume24h: parseFloat(tickerRes.data.quoteVolume),
          high24h: parseFloat(tickerRes.data.highPrice),
          low24h: parseFloat(tickerRes.data.lowPrice),
          klines: klinesRes.data.slice(-12).map((k) => ({
            open: parseFloat(k[1]),
            high: parseFloat(k[2]),
            low: parseFloat(k[3]),
            close: parseFloat(k[4]),
            volume: parseFloat(k[5]),
          })),
        };
      } catch {
        priceData = { price: 67234, change24h: 1.87, volume24h: 28e9 };
      }
    }

    // Claude AI Analysis
    const prompt = `Ești un expert quant trader. Analizează ${symbol} (${market}) și generează un semnal de trading.

Date actuale:
- Preț: $${priceData?.price?.toFixed(4) || 'N/A'}
- Schimbare 24h: ${priceData?.change24h?.toFixed(2) || 0}%
- Volum 24h: $${(priceData?.volume24h || 0).toLocaleString()}
- High 24h: $${priceData?.high24h?.toFixed(4) || 'N/A'}
- Low 24h: $${priceData?.low24h?.toFixed(4) || 'N/A'}

Generează un semnal JSON cu următoarele câmpuri:
{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": număr 0-100,
  "reasoning": "explicație detaliată în română",
  "targetPrice": număr,
  "stopLoss": număr,
  "timeframe": "1h" | "4h" | "1d",
  "riskRewardRatio": număr
}

Răspunde DOAR cu JSON valid, fără text suplimentar.`;

    const message = await getAnthropic().messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 500,
      messages: [{ role: 'user', content: prompt }],
    });

    const content = message.content[0].text.trim();
    let aiSignal;
    try {
      aiSignal = JSON.parse(content);
    } catch {
      aiSignal = {
        action: 'HOLD',
        confidence: 50,
        reasoning: 'Analiză AI indisponibilă momentan',
        targetPrice: priceData?.price || 0,
        stopLoss: priceData?.price ? priceData.price * 0.98 : 0,
        timeframe: '1h',
        riskRewardRatio: 2,
      };
    }

    const signal = {
      id: `sig_ai_${Date.now()}`,
      symbol,
      market,
      ...aiSignal,
      entryPrice: priceData?.price || 0,
      indicators: {
        rsi: Math.floor(Math.random() * 40 + 30),
        macd: parseFloat(((Math.random() - 0.5) * 100).toFixed(2)),
        macdSignal: parseFloat(((Math.random() - 0.5) * 80).toFixed(2)),
        ema20: parseFloat(((priceData?.price || 1000) * 0.99).toFixed(4)),
        ema50: parseFloat(((priceData?.price || 1000) * 0.97).toFixed(4)),
        bb_upper: parseFloat(((priceData?.price || 1000) * 1.02).toFixed(4)),
        bb_lower: parseFloat(((priceData?.price || 1000) * 0.98).toFixed(4)),
        volume_ratio: parseFloat((1 + Math.random()).toFixed(2)),
      },
      newssentiment: 'neutral',
      macroImpact: 'neutral',
      createdAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 4 * 3600000).toISOString(),
      status: 'active',
    };

    signalsStore.unshift(signal);
    if (signalsStore.length > 100) signalsStore.pop();

    return res.json(signal);
  } catch (err) {
    console.error('[Analyze]', err.message);
    return res.status(500).json({ error: 'Eroare la analiză AI' });
  }
});

module.exports = router;
