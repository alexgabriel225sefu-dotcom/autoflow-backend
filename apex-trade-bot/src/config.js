require('dotenv').config();

// Accepts: 'true', '1', 'yes', 'on' (case-insensitive)
const isTruthy = v => ['true','1','yes','on'].includes((v || '').toLowerCase().trim());

const PAPER = isTruthy(process.env.PAPER_TRADING);

// Supported exchanges (each has a connector in src/<name>.js)
const SUPPORTED_EXCHANGES = ['binance','bybit','okx','kraken','kucoin','coinbase','bitget','mexc'];

module.exports = {
  // ─── Exchange ────────────────────────────────────────────
  // One of: binance, bybit, okx, kraken, kucoin, coinbase, bitget, mexc
  EXCHANGE: (process.env.EXCHANGE || 'binance').toLowerCase(),
  SUPPORTED_EXCHANGES,

  // ─── Bybit ──────────────────────────────────────────────
  BYBIT_API_KEY:    process.env.BYBIT_API_KEY    || '',
  BYBIT_API_SECRET: process.env.BYBIT_API_SECRET || '',
  BYBIT_TESTNET:    isTruthy(process.env.BYBIT_TESTNET),

  // ─── OKX ────────────────────────────────────────────────
  OKX_API_KEY:        process.env.OKX_API_KEY        || '',
  OKX_API_SECRET:     process.env.OKX_API_SECRET     || '',
  OKX_API_PASSPHRASE: process.env.OKX_API_PASSPHRASE || '',

  // ─── Kraken ─────────────────────────────────────────────
  KRAKEN_API_KEY:    process.env.KRAKEN_API_KEY    || '',
  KRAKEN_API_SECRET: process.env.KRAKEN_API_SECRET || '',

  // ─── KuCoin ─────────────────────────────────────────────
  KUCOIN_API_KEY:        process.env.KUCOIN_API_KEY        || '',
  KUCOIN_API_SECRET:     process.env.KUCOIN_API_SECRET     || '',
  KUCOIN_API_PASSPHRASE: process.env.KUCOIN_API_PASSPHRASE || '',

  // ─── Coinbase (Advanced Trade, JWT key) ─────────────────
  COINBASE_API_KEY:    process.env.COINBASE_API_KEY    || '', // key name: organizations/.../apiKeys/...
  COINBASE_API_SECRET: process.env.COINBASE_API_SECRET || '', // EC private key PEM

  // ─── Bitget ─────────────────────────────────────────────
  BITGET_API_KEY:        process.env.BITGET_API_KEY        || '',
  BITGET_API_SECRET:     process.env.BITGET_API_SECRET     || '',
  BITGET_API_PASSPHRASE: process.env.BITGET_API_PASSPHRASE || '',

  // ─── MEXC ───────────────────────────────────────────────
  MEXC_API_KEY:    process.env.MEXC_API_KEY    || '',
  MEXC_API_SECRET: process.env.MEXC_API_SECRET || '',

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

  // ─── Telegram alerts (optional) ─────────────────────────
  TELEGRAM_BOT_TOKEN: process.env.TELEGRAM_BOT_TOKEN || '',
  TELEGRAM_CHAT_ID:   process.env.TELEGRAM_CHAT_ID   || '',

  // ─── Trading ────────────────────────────────────────────
  SYMBOL:      process.env.TRADE_SYMBOL || 'SOLUSDT',
  QUOTE_ASSET: process.env.QUOTE_ASSET  || 'USDT',
  TIMEFRAME:   process.env.TIMEFRAME    || '5m',
  CANDLES:     200,

  // ─── Multi-symbol scanner ───────────────────────────────
  SCAN_SYMBOLS: (process.env.SCAN_SYMBOLS || 'XRPUSDT,SOLUSDT,BTCUSDT,ADAUSDT,ETHUSDT').split(','),
  MULTI_SYMBOL: process.env.MULTI_SYMBOL !== 'false',

  // ─── Risk ────────────────────────────────────────────────
  RISK_PER_TRADE:  parseFloat(process.env.RISK_PER_TRADE  || '0.05'),
  STOP_LOSS_PCT:   parseFloat(process.env.STOP_LOSS_PCT   || '0.016'),
  TAKE_PROFIT_PCT: parseFloat(process.env.TAKE_PROFIT_PCT || '0.032'),
  MIN_CONFIDENCE:  parseInt(process.env.MIN_CONFIDENCE    || '62'),

  // ─── Trailing Stop ──────────────────────────────────────
  TRAILING_STOP:      process.env.TRAILING_STOP === 'true',
  TRAILING_STOP_DIST: parseFloat(process.env.TRAILING_STOP_DIST || '0.015'),

  // ─── Exit management ────────────────────────────────────
  FEE_PCT:           parseFloat(process.env.FEE_PCT || '0.001'),
  BREAKEVEN_AT_R:    parseFloat(process.env.BREAKEVEN_AT_R || '0'),
  LET_WINNERS_RUN:   process.env.LET_WINNERS_RUN !== 'false',
  RUNNER_TRAIL_DIST: parseFloat(process.env.RUNNER_TRAIL_DIST || '0.005'),

  // ─── Entry filters ───────────────────────────────────────
  HTF_FILTER:    process.env.HTF_FILTER !== 'false',
  HTF_TIMEFRAME: process.env.HTF_TIMEFRAME || '1h',
  COOLDOWN_AFTER_LOSS_MIN: parseInt(process.env.COOLDOWN_AFTER_LOSS_MIN || '15'),

  // ─── ATR dynamic ─────────────────────────────────────────
  ATR_BASED_SL: process.env.ATR_BASED_SL === 'true',
  ATR_SL_MULT:  parseFloat(process.env.ATR_SL_MULT || '1.5'),
  ATR_TP_MULT:  parseFloat(process.env.ATR_TP_MULT || '3.0'),

  // ─── Compound mode ──────────────────────────────────────
  COMPOUND: process.env.COMPOUND !== 'false',

  // ─── Intervals ──────────────────────────────────────────
  LOOP_INTERVAL_MS: parseInt(process.env.LOOP_INTERVAL_MS || String(5 * 60 * 1000)),

  // ─── Paper Trading ──────────────────────────────────────
  PAPER_TRADING: PAPER,
  PAPER_BALANCE: parseFloat(process.env.PAPER_BALANCE || '100'),

  // ─── Testnet flag (legacy) ──────────────────────────────
  get TESTNET() { return this.BYBIT_TESTNET; },

  // ─── License ─────────────────────────────────────────────
  LICENSE_KEY:    process.env.LICENSE_KEY    || '',
  LICENSE_SERVER: process.env.LICENSE_SERVER || 'https://aicashsystem.space',
};

module.exports.loadRemote = async function loadRemote() {
  const key    = module.exports.LICENSE_KEY;
  const server = module.exports.LICENSE_SERVER;
  if (!key) { console.warn('⚠️   loadRemote: LICENSE_KEY not set — skipping remote config.'); return false; }
  try {
    const resp = await fetch(`${server}/api/bot-config?key=${encodeURIComponent(key)}`, {
      signal: AbortSignal.timeout(10000),
    });
    if (!resp.ok) {
      const body = await resp.text().catch(() => '');
      console.warn(`⚠️   loadRemote: server returned ${resp.status} — ${body.slice(0,200)}`);
      console.warn('     → Did you complete the configurator and click "Save Config & Deploy" for this license key?');
      return false;
    }
    const data = await resp.json();
    if (!data.success || !data.config) { console.warn('⚠️   loadRemote: no config in response.'); return false; }
    for (const [k, v] of Object.entries(data.config)) {
      if (v === undefined || v === null || v === '') continue;
      process.env[k] = String(v);
      if (Object.prototype.hasOwnProperty.call(module.exports, k)) {
        const cur = module.exports[k];
        if (typeof cur === 'boolean')      module.exports[k] = isTruthy(String(v));
        else if (typeof cur === 'number')  module.exports[k] = parseFloat(v);
        else                               module.exports[k] = v;
      }
    }
    console.log('✅  Remote config loaded from license server.');
    return true;
  } catch(e) {
    console.warn(`⚠️   Could not load remote config (${e.message}) — using env vars only.`);
    return false;
  }
};
