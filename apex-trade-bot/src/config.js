require('dotenv').config();

const PAPER = process.env.PAPER_TRADING === 'true' || process.env.PAPER_TRADING === '1';

module.exports = {
  // ─── Exchange ────────────────────────────────────────────
  EXCHANGE: process.env.EXCHANGE || 'bybit', // 'bybit' sau 'binance'

  // ─── Bybit ──────────────────────────────────────────────
  BYBIT_API_KEY:    process.env.BYBIT_API_KEY    || '',
  BYBIT_API_SECRET: process.env.BYBIT_API_SECRET || '',
  BYBIT_TESTNET:    process.env.BYBIT_TESTNET    === 'true',

  // ─── Binance ────────────────────────────────────────────
  BINANCE_API_KEY:    process.env.BINANCE_API_KEY    || '',
  BINANCE_API_SECRET: process.env.BINANCE_API_SECRET || '',
  BINANCE_TESTNET:    process.env.BINANCE_TESTNET    === 'true',
  get BINANCE_BASE() {
    return this.BINANCE_TESTNET
      ? 'https://testnet.binance.vision/api/v3'
      : 'https://api.binance.com/api/v3';
  },

  // ─── Anthropic ──────────────────────────────────────────
  ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY || '',

  // ─── Trading ────────────────────────────────────────────
  SYMBOL:      process.env.TRADE_SYMBOL || 'DOGEUSDT',
  QUOTE_ASSET: process.env.QUOTE_ASSET  || 'USDT',
  TIMEFRAME:   process.env.TIMEFRAME    || '15m',  // 15m = mai multe semnale
  CANDLES:     150,

  // ─── Scanner multi-simbol ───────────────────────────────
  SCAN_SYMBOLS: (process.env.SCAN_SYMBOLS || 'DOGEUSDT,XRPUSDT,ADAUSDT,TRXUSDT,SHIBUSDT').split(','),
  MULTI_SYMBOL: process.env.MULTI_SYMBOL === 'true',

  // ─── Risc (optimizat pt capital mic $5-10) ───────────────
  // Cu $10 și 15% risc → $1.50/trade (suficient pt min order)
  RISK_PER_TRADE:  parseFloat(process.env.RISK_PER_TRADE  || '0.15'),  // 15%
  STOP_LOSS_PCT:   parseFloat(process.env.STOP_LOSS_PCT   || '0.015'), // 1.5%
  TAKE_PROFIT_PCT: parseFloat(process.env.TAKE_PROFIT_PCT || '0.03'),  // 3% → R:R = 2:1
  MIN_CONFIDENCE:  parseInt(process.env.MIN_CONFIDENCE    || '70'),

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
  LOOP_INTERVAL_MS: parseInt(process.env.LOOP_INTERVAL_MS || String(15 * 60 * 1000)),

  // ─── Paper Trading ──────────────────────────────────────
  PAPER_TRADING: PAPER,
  PAPER_BALANCE: parseFloat(process.env.PAPER_BALANCE || '10'), // $10 simulat

  // ─── Testnet flag (legacy) ──────────────────────────────
  get TESTNET() { return this.BYBIT_TESTNET; },
};
