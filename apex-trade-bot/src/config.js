require('dotenv').config();

const PAPER = process.env.PAPER_TRADING === 'true' || process.env.PAPER_TRADING === '1';

module.exports = {
  // ─── Exchange (Bybit sau Binance) ───────────────────────
  EXCHANGE: process.env.EXCHANGE || 'bybit', // 'bybit' sau 'binance'

  // ─── Bybit ──────────────────────────────────────────────
  BYBIT_API_KEY:    process.env.BYBIT_API_KEY    || '',
  BYBIT_API_SECRET: process.env.BYBIT_API_SECRET || '',
  BYBIT_TESTNET:    process.env.BYBIT_TESTNET    === 'true',

  // ─── Binance (fallback) ─────────────────────────────────
  BINANCE_API_KEY:    process.env.BINANCE_API_KEY    || '',
  BINANCE_API_SECRET: process.env.BINANCE_API_SECRET || '',

  // ─── Anthropic ──────────────────────────────────────────
  ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY || '',

  // ─── Trading ────────────────────────────────────────────
  SYMBOL:          process.env.TRADE_SYMBOL    || 'DOGEUSDT',
  QUOTE_ASSET:     process.env.QUOTE_ASSET     || 'USDT',
  TIMEFRAME:       process.env.TIMEFRAME       || '1h',
  CANDLES:         100,

  // ─── Risc ───────────────────────────────────────────────
  RISK_PER_TRADE:  parseFloat(process.env.RISK_PER_TRADE  || '0.02'),
  STOP_LOSS_PCT:   parseFloat(process.env.STOP_LOSS_PCT   || '0.02'),
  TAKE_PROFIT_PCT: parseFloat(process.env.TAKE_PROFIT_PCT || '0.04'),
  MIN_CONFIDENCE:  parseInt(process.env.MIN_CONFIDENCE    || '72'),

  // ─── Intervale ──────────────────────────────────────────
  LOOP_INTERVAL_MS: parseInt(process.env.LOOP_INTERVAL_MS || String(15 * 60 * 1000)),

  // ─── Paper Trading ──────────────────────────────────────
  PAPER_TRADING: PAPER,
  PAPER_BALANCE: parseFloat(process.env.PAPER_BALANCE || '10'), // $10 simulat
};
