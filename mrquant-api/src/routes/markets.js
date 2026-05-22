const express = require('express');
const axios = require('axios');

const router = express.Router();

const BINANCE_BASE = 'https://api.binance.com/api/v3';
const ALPHA_VANTAGE_KEY = process.env.ALPHA_VANTAGE_KEY || 'demo';
const ALPHA_BASE = 'https://www.alphavantage.co/query';
const NEWS_API_KEY = process.env.NEWS_API_KEY;

// Cache simple în memorie (30 secunde)
const cache = new Map();
function getCache(key) {
  const entry = cache.get(key);
  if (entry && Date.now() - entry.ts < 30_000) return entry.data;
  return null;
}
function setCache(key, data) {
  cache.set(key, { data, ts: Date.now() });
}

// ─── Crypto (Binance) ─────────────────────────────────────
const DEFAULT_CRYPTO = [
  'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
  'ADAUSDT', 'DOGEUSDT', 'MATICUSDT', 'DOTUSDT', 'LINKUSDT',
  'AVAXUSDT', 'LTCUSDT', 'UNIUSDT', 'ATOMUSDT', 'NEARUSDT',
];

const CRYPTO_NAMES = {
  BTC: 'Bitcoin', ETH: 'Ethereum', BNB: 'BNB', SOL: 'Solana',
  XRP: 'Ripple', ADA: 'Cardano', DOGE: 'Dogecoin', MATIC: 'Polygon',
  DOT: 'Polkadot', LINK: 'Chainlink', AVAX: 'Avalanche', LTC: 'Litecoin',
  UNI: 'Uniswap', ATOM: 'Cosmos', NEAR: 'NEAR Protocol',
};

router.get('/crypto', async (req, res) => {
  const cached = getCache('crypto');
  if (cached) return res.json(cached);

  try {
    const symbols = req.query.symbols
      ? req.query.symbols.split(',')
      : DEFAULT_CRYPTO;

    const response = await axios.get(`${BINANCE_BASE}/ticker/24hr`);
    const tickers = response.data;

    const filtered = symbols.map((sym) => {
      const ticker = tickers.find((t) => t.symbol === sym);
      if (!ticker) return null;
      const base = sym.replace('USDT', '');
      return {
        symbol: base,
        name: CRYPTO_NAMES[base] || base,
        price: parseFloat(ticker.lastPrice),
        change24h: parseFloat(ticker.priceChange),
        changePercent24h: parseFloat(ticker.priceChangePercent),
        volume24h: parseFloat(ticker.quoteVolume),
        high24h: parseFloat(ticker.highPrice),
        low24h: parseFloat(ticker.lowPrice),
        market: 'crypto',
      };
    }).filter(Boolean);

    setCache('crypto', filtered);
    return res.json(filtered);
  } catch (err) {
    console.error('[Crypto]', err.message);
    return res.json(getMockCrypto());
  }
});

// ─── Stocks (Alpha Vantage) ───────────────────────────────
const DEFAULT_STOCKS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'JPM', 'V', 'JNJ'];

router.get('/stocks', async (req, res) => {
  const cached = getCache('stocks');
  if (cached) return res.json(cached);

  try {
    // Batch quote
    const symbols = req.query.symbols ? req.query.symbols.split(',') : DEFAULT_STOCKS;
    const results = await Promise.allSettled(
      symbols.slice(0, 5).map((sym) =>
        axios.get(ALPHA_BASE, {
          params: {
            function: 'GLOBAL_QUOTE',
            symbol: sym,
            apikey: ALPHA_VANTAGE_KEY,
          },
        })
      )
    );

    const stocks = results
      .filter((r) => r.status === 'fulfilled')
      .map((r, i) => {
        const q = r.value.data['Global Quote'];
        if (!q || !q['05. price']) return null;
        return {
          symbol: q['01. symbol'] || symbols[i],
          name: q['01. symbol'] || symbols[i],
          price: parseFloat(q['05. price']),
          change24h: parseFloat(q['09. change']),
          changePercent24h: parseFloat((q['10. change percent'] || '0').replace('%', '')),
          volume24h: parseFloat(q['06. volume']),
          high24h: parseFloat(q['03. high']),
          low24h: parseFloat(q['04. low']),
          market: 'stocks',
        };
      }).filter(Boolean);

    const data = stocks.length > 0 ? stocks : getMockStocks();
    setCache('stocks', data);
    return res.json(data);
  } catch (err) {
    console.error('[Stocks]', err.message);
    return res.json(getMockStocks());
  }
});

// ─── Forex ────────────────────────────────────────────────
const DEFAULT_FOREX_PAIRS = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'AUD/USD', 'USD/CAD'];

router.get('/forex', async (req, res) => {
  const cached = getCache('forex');
  if (cached) return res.json(cached);

  try {
    const pairs = req.query.pairs ? req.query.pairs.split(',') : DEFAULT_FOREX_PAIRS;
    const data = getMockForex(pairs); // Alpha Vantage forex needs paid plan for real-time
    setCache('forex', data);
    return res.json(data);
  } catch (err) {
    return res.json(getMockForex(DEFAULT_FOREX_PAIRS));
  }
});

// ─── Klines / OHLCV (Binance) ────────────────────────────
router.get('/klines', async (req, res) => {
  const { symbol, interval = '1h', market = 'crypto' } = req.query;
  if (!symbol) return res.status(400).json({ error: 'Symbol required' });

  const cacheKey = `klines_${symbol}_${interval}`;
  const cached = getCache(cacheKey);
  if (cached) return res.json(cached);

  try {
    let klines;
    if (market === 'crypto') {
      const sym = symbol.includes('USDT') ? symbol : `${symbol}USDT`;
      const response = await axios.get(`${BINANCE_BASE}/klines`, {
        params: { symbol: sym, interval, limit: 100 },
      });
      klines = response.data.map((k) => ({
        time: k[0],
        open: parseFloat(k[1]),
        high: parseFloat(k[2]),
        low: parseFloat(k[3]),
        close: parseFloat(k[4]),
        volume: parseFloat(k[5]),
      }));
    } else {
      klines = generateMockKlines(100);
    }

    setCache(cacheKey, klines);
    return res.json(klines);
  } catch (err) {
    return res.json(generateMockKlines(100));
  }
});

// ─── News ─────────────────────────────────────────────────
router.get('/news', async (req, res) => {
  const cached = getCache('news');
  if (cached) return res.json(cached);

  try {
    if (!NEWS_API_KEY) return res.json(getMockNews());

    const response = await axios.get('https://newsapi.org/v2/everything', {
      params: {
        q: 'trading cryptocurrency stocks market',
        language: 'en',
        sortBy: 'publishedAt',
        pageSize: 20,
        apiKey: NEWS_API_KEY,
      },
    });

    const articles = response.data.articles.map((a, i) => ({
      id: `news_${i}`,
      title: a.title,
      summary: a.description || a.title,
      source: a.source.name,
      url: a.url,
      publishedAt: a.publishedAt,
      sentiment: ['positive', 'negative', 'neutral'][Math.floor(Math.random() * 3)],
      relatedSymbols: [],
    }));

    setCache('news', articles);
    return res.json(articles);
  } catch {
    return res.json(getMockNews());
  }
});

// ─── Macro Events ─────────────────────────────────────────
router.get('/macro', async (req, res) => {
  return res.json(getMockMacroEvents());
});

// ─── Mock Data ────────────────────────────────────────────
function getMockCrypto() {
  return [
    { symbol: 'BTC', name: 'Bitcoin', price: 67234.5, change24h: 1234, changePercent24h: 1.87, volume24h: 28_000_000_000, high24h: 68000, low24h: 65500, market: 'crypto' },
    { symbol: 'ETH', name: 'Ethereum', price: 3521.3, change24h: -45.2, changePercent24h: -1.27, volume24h: 15_000_000_000, high24h: 3600, low24h: 3480, market: 'crypto' },
    { symbol: 'BNB', name: 'BNB', price: 589.4, change24h: 12.3, changePercent24h: 2.13, volume24h: 1_200_000_000, high24h: 600, low24h: 578, market: 'crypto' },
    { symbol: 'SOL', name: 'Solana', price: 171.8, change24h: 8.9, changePercent24h: 5.47, volume24h: 4_500_000_000, high24h: 178, low24h: 162, market: 'crypto' },
    { symbol: 'XRP', name: 'Ripple', price: 0.612, change24h: -0.015, changePercent24h: -2.39, volume24h: 2_300_000_000, high24h: 0.635, low24h: 0.605, market: 'crypto' },
  ];
}

function getMockStocks() {
  return [
    { symbol: 'AAPL', name: 'Apple Inc.', price: 189.3, change24h: 2.1, changePercent24h: 1.12, volume24h: 58_000_000, high24h: 191, low24h: 187, market: 'stocks' },
    { symbol: 'MSFT', name: 'Microsoft', price: 412.7, change24h: -3.2, changePercent24h: -0.77, volume24h: 21_000_000, high24h: 416, low24h: 410, market: 'stocks' },
    { symbol: 'NVDA', name: 'NVIDIA', price: 875.4, change24h: 25.6, changePercent24h: 3.01, volume24h: 45_000_000, high24h: 890, low24h: 848, market: 'stocks' },
    { symbol: 'TSLA', name: 'Tesla', price: 245.2, change24h: -8.7, changePercent24h: -3.43, volume24h: 112_000_000, high24h: 255, low24h: 240, market: 'stocks' },
  ];
}

function getMockForex(pairs) {
  const rates = { 'EUR/USD': 1.0875, 'GBP/USD': 1.2734, 'USD/JPY': 149.23, 'USD/CHF': 0.8921, 'AUD/USD': 0.6543, 'USD/CAD': 1.3612 };
  return pairs.map((p) => ({
    symbol: p,
    name: p,
    price: rates[p] || 1.0 + Math.random() * 0.5,
    change24h: (Math.random() - 0.5) * 0.01,
    changePercent24h: (Math.random() - 0.5) * 0.8,
    volume24h: Math.floor(Math.random() * 1_000_000_000),
    high24h: (rates[p] || 1.0) * 1.003,
    low24h: (rates[p] || 1.0) * 0.997,
    market: 'forex',
  }));
}

function getMockNews() {
  return [
    { id: 'n1', title: 'Bitcoin atinge noi maxime istorice în 2025', summary: 'BTC a depășit pragul de 70,000$...', source: 'CoinDesk', url: '#', publishedAt: new Date().toISOString(), sentiment: 'positive', relatedSymbols: ['BTC'] },
    { id: 'n2', title: 'Fed menține ratele dobânzilor stabile', summary: 'Federal Reserve a decis să mențină...', source: 'Reuters', url: '#', publishedAt: new Date().toISOString(), sentiment: 'neutral', relatedSymbols: [] },
    { id: 'n3', title: 'NVIDIA raportează profituri record', summary: 'NVDA a anunțat venituri de 26 mld $...', source: 'Bloomberg', url: '#', publishedAt: new Date().toISOString(), sentiment: 'positive', relatedSymbols: ['NVDA'] },
  ];
}

function getMockMacroEvents() {
  return [
    { id: 'e1', title: 'Fed Interest Rate Decision', date: '2025-06-11', importance: 'high', forecast: '5.25%', previous: '5.25%', currency: 'USD' },
    { id: 'e2', title: 'US CPI m/m', date: '2025-06-12', importance: 'high', forecast: '0.3%', previous: '0.4%', currency: 'USD' },
    { id: 'e3', title: 'ECB Interest Rate Decision', date: '2025-06-12', importance: 'high', forecast: '4.0%', previous: '4.0%', currency: 'EUR' },
  ];
}

function generateMockKlines(count) {
  let price = 67000;
  return Array.from({ length: count }, (_, i) => {
    const change = (Math.random() - 0.48) * 500;
    const open = price;
    const close = price + change;
    const high = Math.max(open, close) + Math.random() * 200;
    const low = Math.min(open, close) - Math.random() * 200;
    price = close;
    return {
      time: Date.now() - (count - i) * 3600000,
      open: Math.round(open * 100) / 100,
      high: Math.round(high * 100) / 100,
      low: Math.round(low * 100) / 100,
      close: Math.round(close * 100) / 100,
      volume: Math.floor(Math.random() * 1000 + 100),
    };
  });
}

module.exports = router;
