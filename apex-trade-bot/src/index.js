require('dotenv').config();
const cfg        = require('./config');
const indicators = require('./indicators');
const ai         = require('./ai');
const logger     = require('./logger');

// ─── Alege exchange-ul ────────────────────────────────────
const exchange = cfg.EXCHANGE === 'binance'
  ? require('./binance')
  : require('./bybit');

// ─── State ────────────────────────────────────────────────
let openPosition  = null;
let paperBalance  = cfg.PAPER_BALANCE;

// ─── Validare startup ─────────────────────────────────────
function validate() {
  if (!cfg.ANTHROPIC_API_KEY) {
    console.error('❌ ANTHROPIC_API_KEY lipsă în Variables!');
    process.exit(1);
  }
  if (!cfg.PAPER_TRADING) {
    const hasKey = cfg.EXCHANGE === 'binance'
      ? cfg.BINANCE_API_KEY
      : cfg.BYBIT_API_KEY;
    if (!hasKey) {
      console.error(`❌ ${cfg.EXCHANGE.toUpperCase()}_API_KEY lipsă. Adaugă PAPER_TRADING=true pentru test fără bani reali.`);
      process.exit(1);
    }
  }
}

// ─── Balanță ─────────────────────────────────────────────
async function getBalance() {
  if (cfg.PAPER_TRADING) return paperBalance;
  try { return await exchange.getBalance(); }
  catch { return 0; }
}

// ─── Calcul cantitate ─────────────────────────────────────
async function calcQuantity(price, balance) {
  const riskAmount = balance * cfg.RISK_PER_TRADE;
  const qty = riskAmount / price;
  const isWhole = ['DOGEUSDT','SHIBUSDT','XRPUSDT','ADAUSDT','MATICUSDT'].includes(cfg.SYMBOL);
  return isWhole ? Math.floor(qty) : parseFloat(qty.toFixed(6));
}

// ─── Verifică SL/TP ──────────────────────────────────────
function checkPosition(price) {
  if (!openPosition) return null;
  const { entryPrice, side, stopLoss, takeProfit } = openPosition;
  const pnlPct = side === 'BUY'
    ? (price - entryPrice) / entryPrice * 100
    : (entryPrice - price) / entryPrice * 100;
  openPosition.pnlPct = pnlPct;

  if (side === 'BUY')  { if (price <= stopLoss) return 'STOP_LOSS'; if (price >= takeProfit) return 'TAKE_PROFIT'; }
  if (side === 'SELL') { if (price >= stopLoss) return 'STOP_LOSS'; if (price <= takeProfit) return 'TAKE_PROFIT'; }
  return null;
}

// ─── Deschide poziție ─────────────────────────────────────
async function openTrade(side, price, balance) {
  const quantity = await calcQuantity(price, balance);
  if (quantity <= 0) { logger.warn('Cantitate prea mică — skip'); return; }

  await exchange.placeOrder(side, quantity);

  if (cfg.PAPER_TRADING) {
    paperBalance -= (side === 'BUY' ? price * quantity : 0);
  }

  const sl = side === 'BUY' ? price * (1 - cfg.STOP_LOSS_PCT)   : price * (1 + cfg.STOP_LOSS_PCT);
  const tp = side === 'BUY' ? price * (1 + cfg.TAKE_PROFIT_PCT) : price * (1 - cfg.TAKE_PROFIT_PCT);

  openPosition = { side, entryPrice: price, quantity, stopLoss: sl, takeProfit: tp, openedAt: new Date().toISOString(), pnlPct: 0 };
  logger.printTrade(side, cfg.SYMBOL, price, quantity);
  logger.info(`SL: $${sl.toFixed(5)} | TP: $${tp.toFixed(5)}`);
}

// ─── Închide poziție ──────────────────────────────────────
async function closeTrade(price, reason) {
  if (!openPosition) return;
  const { side, entryPrice, quantity } = openPosition;
  const closeSide = side === 'BUY' ? 'SELL' : 'BUY';

  await exchange.placeOrder(closeSide, quantity);

  const pnl = side === 'BUY'
    ? (price - entryPrice) * quantity
    : (entryPrice - price) * quantity;

  if (cfg.PAPER_TRADING) paperBalance += price * quantity + pnl;

  logger.printTrade(closeSide, cfg.SYMBOL, price, quantity, pnl);
  logger.info(`Motivul închiderii: ${reason}`);
  openPosition = null;
}

// ─── Loop principal ───────────────────────────────────────
async function tick() {
  try {
    logger.info(`Analizez ${cfg.SYMBOL} (${cfg.EXCHANGE})...`);

    const [candles, price] = await Promise.all([
      exchange.getCandles(),
      exchange.getPrice(),
    ]);
    const balance = await getBalance();
    logger.updateBalance(balance);

    // Verifică SL/TP
    const trigger = checkPosition(price);
    if (trigger) {
      logger.warn(`${trigger} atins la $${price}`);
      await closeTrade(price, trigger);
      logger.printStats(await getBalance());
      return;
    }

    // Indicatori + AI
    const ind    = indicators.analyze(candles);
    const signal = await ai.getSignal(ind, balance, openPosition);
    logger.printSignal(signal, ind);

    // Execuție
    if (signal.action === 'HOLD' || signal.confidence < cfg.MIN_CONFIDENCE) {
      logger.info(`HOLD — confidence ${signal.confidence}% < minim ${cfg.MIN_CONFIDENCE}%`);
    } else if (signal.action === 'CLOSE' && openPosition) {
      await closeTrade(price, 'AI_CLOSE');
    } else if (signal.action === 'BUY' && !openPosition) {
      await openTrade('BUY', price, balance);
    } else if (signal.action === 'SELL' && !openPosition) {
      await openTrade('SELL', price, balance);
    } else {
      logger.info(`Poziție ${openPosition ? 'deja deschisă' : 'deja închisă'} — skip`);
    }

    logger.printStats(balance);
  } catch (err) {
    logger.error(`Tick error: ${err.message}`);
  }
}

// ─── Start ────────────────────────────────────────────────
async function main() {
  validate();
  const balance = await getBalance();
  logger.setStartBalance(balance);
  logger.printBanner(balance);
  await tick();
  setInterval(tick, cfg.LOOP_INTERVAL_MS);
}

main().catch(err => { logger.error('Fatal: ' + err.message); process.exit(1); });
