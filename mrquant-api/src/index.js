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
const { authenticate } = require('./middleware/auth');
const { setupWebSocket } = require('./services/websocket');

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

// ─── WebSocket ────────────────────────────────────────────
setupWebSocket(io);

// ─── Error Handler ────────────────────────────────────────
app.use((err, req, res, next) => {
  console.error('[Error]', err.message);
  res.status(err.status || 500).json({
    error: err.message || 'Eroare internă server',
  });
});

// ─── Start ────────────────────────────────────────────────
const PORT = process.env.PORT || 3001;
httpServer.listen(PORT, () => {
  console.log(`🚀 MrQuant API running on port ${PORT}`);
});

module.exports = { app, io };
