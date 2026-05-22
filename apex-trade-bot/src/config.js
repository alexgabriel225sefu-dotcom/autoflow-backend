require('dotenv').config();

const TESTNET = process.env.BINANCE_TESTNET === 'true';
const PAPER  = process.env.PAPER_TRADING  === 'true';

module.exports = {
  // ─── Binance ────────────────────────────────────────────
  BINANCE_API_KEY:    process.env.BINANCE_API_KEY    || '',
  BINANCE_API_SECRET: process.env.BINANCE_API_SECRET || '',
  BINANCE_BASE: TESTNET
    ? 'https://testnet.binance.vision/api/v3'
    : 'https://api.binance.com/api/v3',

  // ─── Anthropic ──────────────────────────────────────────
  ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY || '',

  // ─── Trading ────────────────────────────────────────────
  SYMBOL:        process.env.TRADE_SYMBOL    || 'DOGEUSDT',  // schimbă cu ce vrei
  QUOTE_ASSET:   process.env.QUOTE_ASSET     || 'USDT',
  TIMEFRAME:     process.env.TIMEFRAME       || '1h',
  CANDLES:       100,                                         // câte lumânări analizează

  // ─── Risc ───────────────────────────────────────────────
  RISK_PER_TRADE:  parseFloat(process.env.RISK_PER_TRADE  || '0.02'), // 2% din balanță
  STOP_LOSS_PCT:   parseFloat(process.env.STOP_LOSS_PCT   || '0.02'), // -2% stop loss
  TAKE_PROFIT_PCT: parseFloat(process.env.TAKE_PROFIT_PCT || '0.04'), // +4% take profit
  MIN_CONFIDENCE:  parseInt(process.env.MIN_CONFIDENCE    || '72'),   // minim 72% confidence AI

  // ─── Intervale ──────────────────────────────────────────
  LOOP_INTERVAL_MS: parseInt(process.env.LOOP_INTERVAL_MS || String(15 * 60 * 1000)), // 15 min

  // ─── Mod ────────────────────────────────────────────────
  TESTNET,
  PAPER_TRADING: PAPER || TESTNET, // testnet = paper automat
};
