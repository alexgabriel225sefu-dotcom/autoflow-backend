require('dotenv').config();
const cfg        = require('./config');
const binance    = require('./binance');
const indicators = require('./indicators');
const ai         = require('./ai');
const logger     = require('./logger');

// ─── State ────────────────────────────────────────────────
let openPosition = null;
// { side, entryPrice, quantity, stopLoss, takeProfit, openedAt, pnlPct }

// ─── Calcul cantitate ─────────────────────────────────────
async function calcQuantity(price, balance) {
  const riskAmount = balance * cfg.RISK_PER_TRADE;
  const quantity   = riskAmount / price;
  // DOGE/SHIB = întregi, BTC/ETH = zecimale
  const isWhole = ['DOGEUSDT', 'SHIBUSDT', 'XRPUSDT', 'ADAUSDT'].includes(cfg.SYMBOL);
  return isWhole ? Math.floor(quantity) : parseFloat(quantity.toFixed(6));
}

// ─── Verifică stop loss / take profit ─────────────────────
function checkPosition(price) {
  if (!openPosition) return null;
  const { entryPrice, side, stopLoss, takeProfit } = openPosition;
  const pnlPct = side === 'BUY'
    ? (price - entryPrice) / entryPrice * 100
    : (entryPrice - price) / entryPrice * 100;

  openPosition.pnlPct = pnlPct;

  if (side === 'BUY') {
    if (price <= stopLoss)   return 'STOP_LOSS';
    if (price >= takeProfit) return 'TAKE_PROFIT';
  } else {
    if (price >= stopLoss)   return 'STOP_LOSS';
    if (price <= takeProfit) return 'TAKE_PROFIT';
  }
  return null;
}

// ─── Deschide poziție ─────────────────────────────────────
async function openTrade(side, price, balance) {
  const quantity = await calcQuantity(price, balance);
  if (quantity <= 0) { logger.warn('Cantitate prea mică — skip'); return; }

  const result = await binance.placeOrder(side, quantity);

  const sl = side === 'BUY'
    ? price * (1 - cfg.STOP_LOSS_PCT)
    : price * (1 + cfg.STOP_LOSS_PCT);
  const tp = side === 'BUY'
    ? price * (1 + cfg.TAKE_PROFIT_PCT)
    : price * (1 - cfg.TAKE_PROFIT_PCT);

  openPosition = { side, entryPrice: price, quantity, stopLoss: sl, takeProfit: tp, openedAt: new Date().toISOString(), pnlPct: 0 };

  logger.printTrade(side, cfg.SYMBOL, price, quantity);
  logger.info(`Stop Loss: $${sl.toFixed(4)} | Take Profit: $${tp.toFixed(4)}`);
}

// ─── Închide poziție ──────────────────────────────────────
async function closeTrade(price, reason) {
  if (!openPosition) return;
  const { side, entryPrice, quantity } = openPosition;
  const closeSide = side === 'BUY' ? 'SELL' : 'BUY';

  await binance.placeOrder(closeSide, quantity);

  const pnl = side === 'BUY'
    ? (price - entryPrice) * quantity
    : (entryPrice - price) * quantity;

  logger.printTrade(closeSide, cfg.SYMBOL, price, quantity, pnl);
  logger.info(`Motivul închiderii: ${reason}`);
  openPosition = null;
}

// ─── Loop principal ───────────────────────────────────────
async function tick() {
  try {
    logger.info(`Analizez ${cfg.SYMBOL}...`);

    // 1. Date piață
    const [candles, balance, price] = await Promise.all([
      binance.getCandles(),
      binance.getBalance(),
      binance.getPrice(),
    ]);

    logger.updateBalance(balance);

    // 2. Verifică SL/TP cu prețul curent
    const trigger = checkPosition(price);
    if (trigger) {
      logger.warn(`${trigger} atins la $${price}`);
      await closeTrade(price, trigger);
      logger.printStats(await binance.getBalance());
      return;
    }

    // 3. Indicatori tehnici
    const ind = indicators.analyze(candles);

    // 4. AI Signal
    const signal = await ai.getSignal(ind, balance, openPosition);
    logger.printSignal(signal, ind);

    // 5. Execuție
    if (signal.action === 'HOLD' || signal.confidence < cfg.MIN_CONFIDENCE) {
      logger.info(`HOLD — confidence ${signal.confidence}% < minim ${cfg.MIN_CONFIDENCE}%`);
      return;
    }

    if (signal.action === 'CLOSE' && openPosition) {
      await closeTrade(price, 'AI_SIGNAL_CLOSE');
    } else if (signal.action === 'BUY' && !openPosition) {
      if (balance < 1) { logger.warn('Balanță insuficientă'); return; }
      await openTrade('BUY', price, balance);
    } else if (signal.action === 'SELL' && !openPosition) {
      if (balance < 1) { logger.warn('Balanță insuficientă'); return; }
      await openTrade('SELL', price, balance);
    } else {
      logger.info(`Poziție deja ${openPosition ? 'deschisă' : 'închisă'} — skip`);
    }

    logger.printStats(balance);

  } catch (err) {
    logger.error(`Tick error: ${err.message}`);
  }
}

// ─── Start ────────────────────────────────────────────────
async function main() {
  // Validare
  if (!cfg.ANTHROPIC_API_KEY) { console.error('❌ ANTHROPIC_API_KEY lipsă în .env'); process.exit(1); }
  if (!cfg.PAPER_TRADING && !cfg.BINANCE_API_KEY) {
    console.error('❌ BINANCE_API_KEY lipsă. Pornește cu: npm run paper');
    process.exit(1);
  }

  const balance = await binance.getBalance().catch(() => cfg.PAPER_TRADING ? 10 : 0);
  logger.setStartBalance(balance);
  logger.printBanner(balance);

  // Primul tick imediat
  await tick();

  // Loop la interval
  setInterval(tick, cfg.LOOP_INTERVAL_MS);
}

main().catch(err => { logger.error('Fatal: ' + err.message); process.exit(1); });
