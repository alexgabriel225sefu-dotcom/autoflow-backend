require('dotenv').config();

// Accepts: 'true', '1', 'yes', 'on' (case-insensitive)
const isTruthy = v => ['true','1','yes','on'].includes((v || '').toLowerCase().trim());

const PAPER = isTruthy(process.env.PAPER_TRADING);

module.exports = {
  // ─── Exchange ────────────────────────────────────────────
  EXCHANGE: process.env.EXCHANGE || 'binance', // 'binance' (global) or 'bybit' (non-EU only)

  // ─── Bybit ──────────────────────────────────────────────
  BYBIT_API_KEY:    process.env.BYBIT_API_KEY    || '',
  BYBIT_API_SECRET: process.env.BYBIT_API_SECRET || '',
  BYBIT_TESTNET:    isTruthy(process.env.BYBIT_TESTNET),

  // ─── Binance ────────────────────────────────────────────
  BINANCE_API_KEY:    process.env.BINANCE_API_KEY    || '',
  BINANCE_API_SECRET: process.env.BINANCE_API_SECRET || '',
  BINANCE_TESTNET:    isTruthy(process.env.BINANCE_TESTNET),
  get BINANCE_BASE() {
    return this.BINANCE_TESTNET
      ? 'https://testnet.binance.vision/api/v3'
      : 'https://api.binance.com/api/v3';
  },

  // ─── Anthropic ──────────────────────────────────────────
  ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY || '',

  // ─── Telegram alerts (opțional) ─────────────────────────
  TELEGRAM_BOT_TOKEN: process.env.TELEGRAM_BOT_TOKEN || '',
  TELEGRAM_CHAT_ID:   process.env.TELEGRAM_CHAT_ID   || '',

  // ─── Trading ────────────────────────────────────────────
  SYMBOL:      process.env.TRADE_SYMBOL || 'SOLUSDT',
  QUOTE_ASSET: process.env.QUOTE_ASSET  || 'USDT',
  TIMEFRAME:   process.env.TIMEFRAME    || '5m',
  CANDLES:     200,

  // ─── Scanner multi-simbol ───────────────────────────────
  // Ordonate după volatilitate + lichiditate + potențial profit pe capital mic
  SCAN_SYMBOLS: (process.env.SCAN_SYMBOLS || 'SOLUSDT,XRPUSDT,DOGEUSDT,TRXUSDT,ADAUSDT').split(','),
  MULTI_SYMBOL: process.env.MULTI_SYMBOL !== 'false', // activat implicit

  // ─── Risc (optimizat pt 5m + capital mic $10-50) ────────────
  // Pe 5m: mișcări tipice 0.5-1.5% → SL 0.8%, TP 1.6% → R:R 2:1
  RISK_PER_TRADE:  parseFloat(process.env.RISK_PER_TRADE  || '0.20'),  // 20% → mai mulți bani/trade
  STOP_LOSS_PCT:   parseFloat(process.env.STOP_LOSS_PCT   || '0.008'), // 0.8% (potrivit pt 5m)
  TAKE_PROFIT_PCT: parseFloat(process.env.TAKE_PROFIT_PCT || '0.016'), // 1.6% → R:R = 2:1
  MIN_CONFIDENCE:  parseInt(process.env.MIN_CONFIDENCE    || '62'),    // 62% — permite mai multe intrări

  // ─── Trailing Stop ──────────────────────────────────────
  TRAILING_STOP:        process.env.TRAILING_STOP !== 'false', // activat implicit
  TRAILING_STOP_DIST:   parseFloat(process.env.TRAILING_STOP_DIST || '0.01'), // 1%

  // ─── ATR dinamic ────────────────────────────────────────
  ATR_BASED_SL:  process.env.ATR_BASED_SL === 'true',  // SL/TP bazat pe ATR (volatilitate)
  ATR_SL_MULT:   parseFloat(process.env.ATR_SL_MULT  || '1.5'), // SL = 1.5× ATR
  ATR_TP_MULT:   parseFloat(process.env.ATR_TP_MULT  || '3.0'), // TP = 3.0× ATR

  // ─── Compound mode ──────────────────────────────────────
  COMPOUND:      process.env.COMPOUND !== 'false', // reinvestește profiturile

  // ─── Intervale ──────────────────────────────────────────
  LOOP_INTERVAL_MS: parseInt(process.env.LOOP_INTERVAL_MS || String(5 * 60 * 1000)),

  // ─── Paper Trading ──────────────────────────────────────
  PAPER_TRADING: PAPER,
  PAPER_BALANCE: parseFloat(process.env.PAPER_BALANCE || '10'), // $10 simulat

  // ─── Testnet flag (legacy) ──────────────────────────────
  get TESTNET() { return this.BYBIT_TESTNET; },

  // ─── License ─────────────────────────────────────────────
  LICENSE_KEY:    process.env.LICENSE_KEY    || '',
  LICENSE_SERVER: process.env.LICENSE_SERVER || 'https://aicashsystem.space',
};
