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
  SCAN_SYMBOLS: (process.env.SCAN_SYMBOLS || 'XRPUSDT,SOLUSDT,BTCUSDT,ADAUSDT,ETHUSDT').split(','),  // tuning r7: ADA back (sl1.6-rr3 +0.81% PF2.73 >> BNB -0.27%); ETH kept (rr3 confirmed)
  MULTI_SYMBOL: process.env.MULTI_SYMBOL !== 'false', // activat implicit

  // ─── Risc (optimizat pt 5m + capital mic $10-50) ────────────
  // Pe 5m: mișcări tipice 0.5-1.5% → SL 0.8%, TP 1.6% → R:R 2:1
  // 5% din balanță per poziție default. 20% era iresponsabil ca default —
  // cu Druckenmiller ×2 ajungea la 40% din cont pe un singur trade.
  RISK_PER_TRADE:  parseFloat(process.env.RISK_PER_TRADE  || '0.05'),
  STOP_LOSS_PCT:   parseFloat(process.env.STOP_LOSS_PCT   || '0.016'), // 1.6% — tuning r5: wide SL winner (BTC 69%WR PF3.14, SOL 61%WR PF2.75)
  TAKE_PROFIT_PCT: parseFloat(process.env.TAKE_PROFIT_PCT || '0.032'), // 3.2% → R:R 2:1 (wide SL+rr2 beats narrow SL+rr5)
  MIN_CONFIDENCE:  parseInt(process.env.MIN_CONFIDENCE    || '62'),    // 62% — permite mai multe intrări

  // ─── Trailing Stop ──────────────────────────────────────
  TRAILING_STOP:        process.env.TRAILING_STOP === 'true', // off implicit — tuning sweep: pure-TP bate trailing în chop
  TRAILING_STOP_DIST:   parseFloat(process.env.TRAILING_STOP_DIST || '0.015'), // 1.5% — lasă loc TP-ului

  // ─── Exit management (cut losses, let profits run) ──────
  FEE_PCT:           parseFloat(process.env.FEE_PCT || '0.001'),           // 0.1% taker/side (Binance spot)
  BREAKEVEN_AT_R:    parseFloat(process.env.BREAKEVEN_AT_R || '0'),        // 0 = off; tuning: BE+trail taie câștiguri în chop
  LET_WINNERS_RUN:   process.env.LET_WINNERS_RUN !== 'false',              // la TP nu închide — trailing strâns
  RUNNER_TRAIL_DIST: parseFloat(process.env.RUNNER_TRAIL_DIST || '0.005'), // 0.5% trail în runner mode

  // ─── Entry filters (anti-chop) ───────────────────────────
  HTF_FILTER:    process.env.HTF_FILTER !== 'false',                       // nu intra contra trendului mare
  HTF_TIMEFRAME: process.env.HTF_TIMEFRAME || '1h',
  COOLDOWN_AFTER_LOSS_MIN: parseInt(process.env.COOLDOWN_AFTER_LOSS_MIN || '15'),

  // ─── ATR dinamic ────────────────────────────────────────
  ATR_BASED_SL:  process.env.ATR_BASED_SL === 'true',   // SL/TP bazat pe ATR (volatilitate)
  ATR_SL_MULT:   parseFloat(process.env.ATR_SL_MULT   || '1.5'), // SL = 1.5× ATR
  ATR_TP_MULT:   parseFloat(process.env.ATR_TP_MULT   || '3.0'), // TP = 3.0× ATR

  // ─── Compound mode ──────────────────────────────────────
  COMPOUND:      process.env.COMPOUND !== 'false', // reinvestește profiturile

  // ─── Intervale ──────────────────────────────────────────
  LOOP_INTERVAL_MS: parseInt(process.env.LOOP_INTERVAL_MS || String(5 * 60 * 1000)),

  // ─── Paper Trading ──────────────────────────────────────
  PAPER_TRADING: PAPER,
  PAPER_BALANCE: parseFloat(process.env.PAPER_BALANCE || '100'), // $100 simulat implicit

  // ─── Testnet flag (legacy) ──────────────────────────────
  get TESTNET() { return this.BYBIT_TESTNET; },

  // ─── License ─────────────────────────────────────────────
  LICENSE_KEY:    process.env.LICENSE_KEY    || '',
  LICENSE_SERVER: process.env.LICENSE_SERVER || 'https://aicashsystem.space',
};

// Fetch config saved by the configurator and apply to process.env + module.exports.
// Called once at startup, after license verification.
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
    // Apply each env-var-named key from remote config.
    // Config arrives as strings — coerce to the type of the existing cfg field
    // (e.g. PAPER_TRADING boolean, STOP_LOSS_PCT number) so "false" doesn't
    // stay a truthy string.
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
