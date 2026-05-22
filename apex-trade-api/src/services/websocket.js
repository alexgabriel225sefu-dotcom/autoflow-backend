const WebSocket = require('ws');
const jwt = require('jsonwebtoken');

const JWT_SECRET = process.env.JWT_SECRET || 'apextrade-super-secret-key-change-in-prod';
const BINANCE_WS = 'wss://stream.binance.com:9443/ws';

let binanceWs = null;
const subscribers = new Map(); // socketId -> { socket, symbols }

function setupWebSocket(io) {
  io.use((socket, next) => {
    const token = socket.handshake.auth?.token;
    if (!token) return next(new Error('Autentificare necesară'));
    try {
      const payload = jwt.verify(token, JWT_SECRET);
      socket.user = payload;
      next();
    } catch {
      next(new Error('Token invalid'));
    }
  });

  io.on('connection', (socket) => {
    console.log(`[WS] Client conectat: ${socket.user.email}`);
    subscribers.set(socket.id, { socket, symbols: [], market: 'crypto' });

    socket.on('subscribe', ({ symbols, market }) => {
      const entry = subscribers.get(socket.id);
      if (entry) {
        entry.symbols = symbols || [];
        entry.market = market || 'crypto';
      }
      subscribeToMarket(symbols, market);
    });

    socket.on('unsubscribe', ({ symbols, market }) => {
      const entry = subscribers.get(socket.id);
      if (entry) {
        entry.symbols = entry.symbols.filter((s) => !symbols.includes(s));
      }
    });

    socket.on('disconnect', () => {
      subscribers.delete(socket.id);
      console.log(`[WS] Client deconectat: ${socket.user.email}`);
    });
  });

  // Connect to Binance WebSocket for real-time crypto prices
  connectBinanceStream(io);

  // Simulate price updates for stocks/forex (5s interval)
  setInterval(() => {
    broadcastMockUpdates(io);
  }, 5000);

  // Generate AI signals periodically (every 60s)
  setInterval(() => {
    broadcastAISignal(io);
  }, 60000);
}

function connectBinanceStream(io) {
  const streams = ['btcusdt@ticker', 'ethusdt@ticker', 'bnbusdt@ticker', 'solusdt@ticker'];
  const url = `${BINANCE_WS}/${streams.join('/')}`;

  try {
    binanceWs = new WebSocket(url);

    binanceWs.on('open', () => {
      console.log('[WS] Binance stream conectat');
    });

    binanceWs.on('message', (data) => {
      try {
        const ticker = JSON.parse(data);
        const base = ticker.s?.replace('USDT', '');
        if (!base) return;

        const update = {
          symbol: base,
          market: 'crypto',
          price: parseFloat(ticker.c),
          change24h: parseFloat(ticker.p),
          changePercent24h: parseFloat(ticker.P),
        };

        io.emit('price_update', update);
      } catch {}
    });

    binanceWs.on('error', (err) => {
      console.error('[WS Binance] Error:', err.message);
    });

    binanceWs.on('close', () => {
      console.log('[WS Binance] Disconnected, reconnecting in 5s...');
      setTimeout(() => connectBinanceStream(io), 5000);
    });
  } catch (err) {
    console.error('[WS Binance] Connect failed:', err.message);
  }
}

function subscribeToMarket(symbols, market) {
  if (market !== 'crypto' || !symbols?.length) return;
  // Dynamic subscription to Binance
  // In production: manage stream subscriptions properly
}

function broadcastMockUpdates(io) {
  const stocks = ['AAPL', 'MSFT', 'NVDA', 'TSLA'];
  const forexPairs = ['EUR/USD', 'GBP/USD', 'USD/JPY'];

  stocks.forEach((sym) => {
    io.emit('price_update', {
      symbol: sym,
      market: 'stocks',
      price: parseFloat((Math.random() * 100 + 100).toFixed(2)),
      change24h: parseFloat(((Math.random() - 0.5) * 5).toFixed(2)),
      changePercent24h: parseFloat(((Math.random() - 0.5) * 2).toFixed(2)),
    });
  });

  forexPairs.forEach((pair) => {
    io.emit('price_update', {
      symbol: pair,
      market: 'forex',
      price: parseFloat((1 + Math.random() * 0.5).toFixed(5)),
      change24h: parseFloat(((Math.random() - 0.5) * 0.01).toFixed(5)),
      changePercent24h: parseFloat(((Math.random() - 0.5) * 0.5).toFixed(2)),
    });
  });
}

function broadcastAISignal(io) {
  const assets = [
    { symbol: 'BTC', market: 'crypto', price: 67234 },
    { symbol: 'ETH', market: 'crypto', price: 3521 },
    { symbol: 'AAPL', market: 'stocks', price: 189 },
  ];

  const asset = assets[Math.floor(Math.random() * assets.length)];
  const action = Math.random() > 0.5 ? 'BUY' : 'SELL';

  io.emit('signal', {
    id: `sig_live_${Date.now()}`,
    symbol: asset.symbol,
    market: asset.market,
    action,
    confidence: Math.floor(Math.random() * 30 + 60),
    entryPrice: asset.price,
    targetPrice: asset.price * (action === 'BUY' ? 1.04 : 0.96),
    stopLoss: asset.price * (action === 'BUY' ? 0.98 : 1.02),
    createdAt: new Date().toISOString(),
    status: 'active',
  });
}

module.exports = { setupWebSocket };
