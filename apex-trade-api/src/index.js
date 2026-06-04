const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const { createServer } = require('http');
const { Server } = require('socket.io');

const authRoutes = require('./routes/auth');
const marketsRoutes = require('./routes/markets');
const signalsRoutes = require('./routes/signals');
const backtestRoutes = require('./routes/backtest');
const portfolioRoutes = require('./routes/portfolio');
const brokerRoutes = require('./routes/broker');
const botControlRoutes = require('./routes/bot-control');
const { authenticate } = require('./middleware/auth');
const { setupWebSocket } = require('./services/websocket');
const { initEngine } = require('./services/trading-engine');

const app = express();
const httpServer = createServer(app);
const io = new Server(httpServer, {
  cors: { origin: '*', methods: ['GET', 'POST'] },
});

// ─── Middleware ───────────────────────────────────────────
app.use(helmet());
app.use(cors({ origin: '*' }));
app.use(express.json({ limit: '10mb' }));

app.use(rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 200,
  message: { error: 'Prea multe cereri, încearcă din nou mai târziu' },
}));

// ─── Health Check ─────────────────────────────────────────
app.get('/health', (req, res) => {
  res.json({ status: 'ok', version: '1.0.0', timestamp: new Date().toISOString() });
});

// ─── Routes ───────────────────────────────────────────────
app.use('/auth', authRoutes);
app.use('/markets', marketsRoutes);
app.use('/signals', authenticate, signalsRoutes);
app.use('/backtest', authenticate, backtestRoutes);
app.use('/portfolio', authenticate, portfolioRoutes);
app.use('/broker', authenticate, brokerRoutes);
app.use('/bot', botControlRoutes);

// ─── WebSocket ────────────────────────────────────────────
setupWebSocket(io);

// ─── Error Handler ────────────────────────────────────────
app.use((err, req, res, next) => {
  console.error('[Error]', err.message);
  res.status(err.status || 500).json({
    error: err.message || 'Eroare internă server',
  });
});

// ─── Startup Validation ───────────────────────────────────
const REQUIRED_VARS = ['SUPABASE_URL', 'SUPABASE_SERVICE_KEY', 'JWT_SECRET'];
const missing = REQUIRED_VARS.filter((v) => !process.env[v]);
if (missing.length > 0) {
  console.warn(`⚠️  Missing env vars: ${missing.join(', ')} — some features will not work`);
} else {
  console.log('✅ All required env vars present');
}
if (!process.env.ANTHROPIC_API_KEY) {
  console.warn('⚠️  ANTHROPIC_API_KEY not set — AI signals will use fallback');
}

// ─── Start ────────────────────────────────────────────────
const PORT = process.env.PORT || 3001;
httpServer.listen(PORT, '0.0.0.0', () => {
  console.log(`🚀 Apex Trade API running on port ${PORT}`);

  // Auto-start trading engine if API keys are configured
  const { BINANCE_API_KEY, BINANCE_API_SECRET, STRATEGY } = process.env;
  if (BINANCE_API_KEY && BINANCE_API_SECRET && STRATEGY) {
    const engine = initEngine({
      apiKey: BINANCE_API_KEY,
      apiSecret: BINANCE_API_SECRET,
      testnet: process.env.TESTNET,
      strategy: STRATEGY,
      symbol: process.env.TRADING_SYMBOL || 'BTCUSDT',
      orderAmount: process.env.ORDER_AMOUNT_USDT || '20',
      takeProfitPct: process.env.TAKE_PROFIT_PCT || '3',
      stopLossPct: process.env.STOP_LOSS_PCT || '2',
      dcaIntervalHours: process.env.DCA_INTERVAL_HOURS || '4',
      dcaMaxOrders: process.env.DCA_MAX_ORDERS || '10',
      gridLevels: process.env.GRID_LEVELS || '10',
      gridLower: process.env.GRID_LOWER_PRICE,
      gridUpper: process.env.GRID_UPPER_PRICE,
      investmentUSDT: process.env.INVESTMENT_USDT || '100',
      timeframe: process.env.TIMEFRAME || '1h',
      telegramToken: process.env.TELEGRAM_BOT_TOKEN,
      telegramChatId: process.env.TELEGRAM_CHAT_ID,
    });
    engine.start().catch((err) => console.error('[Engine] Start failed:', err.message));
    console.log(`🤖 Trading engine starting — ${STRATEGY} on ${process.env.TRADING_SYMBOL || 'BTCUSDT'}`);
  } else {
    console.log('ℹ️  No BINANCE_API_KEY/STRATEGY set — trading engine not started');
  }
});

module.exports = { app, io };
