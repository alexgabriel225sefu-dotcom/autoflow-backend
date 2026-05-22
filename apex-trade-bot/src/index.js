require('dotenv').config();
const cfg        = require('./config');
const indicators = require('./indicators');
const ai         = require('./ai');
const logger     = require('./logger');

// ─── Exchange ─────────────────────────────────────────────
const exchange = cfg.EXCHANGE === 'binance'
  ? require('./binance')
  : require('./bybit');

// ─── State ────────────────────────────────────────────────
let openPosition = null;
let paperBalance = cfg.PAPER_BALANCE;
let tickCount    = 0;

// ─── Validare startup ─────────────────────────────────────
function validate() {
  const hasAnthropic = !!cfg.ANTHROPIC_API_KEY;
  const hasGroq      = !!process.env.GROQ_API_KEY;

  if (!hasAnthropic && !hasGroq) {
    console.error('❌ Nicio cheie AI găsită! Adaugă ANTHROPIC_API_KEY sau GROQ_API_KEY în Variables.');
    process.exit(1);
  }
  if (!hasAnthropic && hasGroq) {
    console.log('ℹ️  ANTHROPIC_API_KEY lipsă — folosesc Groq (gratuit) ca AI provider.');
  }
  if (hasAnthropic && hasGroq) {
    console.log('ℹ️  Anthropic + Groq configurate — Anthropic primar, Groq fallback.');
  }

  const hasKey = cfg.EXCHANGE === 'binance' ? cfg.BINANCE_API_KEY : cfg.BYBIT_API_KEY;
  if (!hasKey && !cfg.PAPER_TRADING) {
    console.warn('⚠️  Nicio cheie exchange — pornesc automat în PAPER TRADING');
    cfg.PAPER_TRADING = true;
  }
}

// ─── Balanță ──────────────────────────────────────────────
async function getBalance() {
  if (cfg.PAPER_TRADING) return paperBalance;
  try { return await exchange.getBalance(); }
  catch { return 0; }
}

// ─── Calcul cantitate ─────────────────────────────────────
async function calcQuantity(price, balance) {
  const riskAmount = balance * cfg.RISK_PER_TRADE;
  const qty        = riskAmount / price;
  const isWhole    = ['DOGEUSDT','SHIBUSDT','XRPUSDT','ADAUSDT','MATICUSDT','TRXUSDT'].includes(cfg.SYMBOL);
  const result     = isWhole ? Math.floor(qty) : parseFloat(qty.toFixed(6));
  return result;
}

// ─── Calculează SL/TP (fix sau ATR-based) ──────────────────
function calcSLTP(side, price, atrValue) {
  if (cfg.ATR_BASED_SL && atrValue > 0) {
    const slDist = atrValue * cfg.ATR_SL_MULT;
    const tpDist = atrValue * cfg.ATR_TP_MULT;
    return {
      stopLoss:   side === 'BUY' ? price - slDist : price + slDist,
      takeProfit: side === 'BUY' ? price + tpDist : price - tpDist,
    };
  }
  return {
    stopLoss:   side === 'BUY' ? price * (1 - cfg.STOP_LOSS_PCT)   : price * (1 + cfg.STOP_LOSS_PCT),
    takeProfit: side === 'BUY' ? price * (1 + cfg.TAKE_PROFIT_PCT) : price * (1 - cfg.TAKE_PROFIT_PCT),
  };
}

// ─── Verifică SL/TP și Trailing Stop ─────────────────────
function checkPosition(price) {
  if (!openPosition) return null;
  const { side, stopLoss, takeProfit } = openPosition;

  // Actualizează trailing stop
  if (cfg.TRAILING_STOP) {
    if (side === 'BUY') {
      openPosition.trailHigh = Math.max(openPosition.trailHigh ?? price, price);
      const trailSL = openPosition.trailHigh * (1 - cfg.TRAILING_STOP_DIST);
      if (trailSL > openPosition.stopLoss) {
        openPosition.stopLoss = trailSL; // ridică SL-ul cu prețul
      }
    } else {
      openPosition.trailLow = Math.min(openPosition.trailLow ?? price, price);
      const trailSL = openPosition.trailLow * (1 + cfg.TRAILING_STOP_DIST);
      if (trailSL < openPosition.stopLoss) {
        openPosition.stopLoss = trailSL; // coboară SL-ul cu prețul
      }
    }
  }

  const pnlPct = side === 'BUY'
    ? (price - openPosition.entryPrice) / openPosition.entryPrice * 100
    : (openPosition.entryPrice - price) / openPosition.entryPrice * 100;
  openPosition.pnlPct = pnlPct;

  if (side === 'BUY') {
    if (price <= openPosition.stopLoss)  return 'STOP_LOSS';
    if (price >= takeProfit)              return 'TAKE_PROFIT';
  }
  if (side === 'SELL') {
    if (price >= openPosition.stopLoss)  return 'STOP_LOSS';
    if (price <= takeProfit)             return 'TAKE_PROFIT';
  }
  return null;
}

// ─── Deschide poziție ─────────────────────────────────────
async function openTrade(side, price, balance, atrValue = 0) {
  const quantity = await calcQuantity(price, balance);
  if (quantity <= 0) { logger.warn('Cantitate prea mică — skip'); return; }

  await exchange.placeOrder(side, quantity);

  if (cfg.PAPER_TRADING) {
    if (side === 'BUY') paperBalance -= price * quantity;
  }

  const { stopLoss, takeProfit } = calcSLTP(side, price, atrValue);
  const rrRatio = Math.abs(takeProfit - price) / Math.abs(price - stopLoss);

  openPosition = {
    side, entryPrice: price, quantity, stopLoss, takeProfit,
    openedAt: new Date().toISOString(), pnlPct: 0,
    trailHigh: side === 'BUY' ? price : null,
    trailLow:  side === 'SELL' ? price : null,
  };

  logger.printTrade(side, cfg.SYMBOL, price, quantity);
  logger.info(`SL: $${stopLoss.toFixed(5)} | TP: $${takeProfit.toFixed(5)} | R:R = 1:${rrRatio.toFixed(2)}`);
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

  if (cfg.PAPER_TRADING) {
    const proceeds = price * quantity + pnl;
    if (cfg.COMPOUND) {
      paperBalance += proceeds; // reinvestește tot
    } else {
      paperBalance += entryPrice * quantity + pnl; // recuperează investiția + profit
    }
  }

  logger.printTrade(closeSide, cfg.SYMBOL, price, quantity, pnl);
  logger.info(`Motivul: ${reason} | PnL: ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)}`);
  openPosition = null;
}

// ─── Selectează cel mai bun simbol (scanner) ──────────────
async function bestSymbol() {
  if (!cfg.MULTI_SYMBOL || cfg.SCAN_SYMBOLS.length <= 1) return cfg.SYMBOL;

  const results = await Promise.all(cfg.SCAN_SYMBOLS.map(async sym => {
    try {
      const candles = await exchange.getCandles(sym, cfg.TIMEFRAME, 50);
      const ind     = indicators.analyze(candles);
      const rsiNum  = parseFloat(ind.rsi);
      const macdH   = parseFloat(ind.macdHist);
      const volR    = parseFloat(ind.volumeRatio);
      // Scor simplu: momentum + volum
      const score = (Math.abs(rsiNum - 50) / 50) * 0.4 + Math.min(volR / 3, 1) * 0.4 + (Math.abs(macdH) > 0 ? 0.2 : 0);
      return { sym, score, ind };
    } catch { return { sym, score: 0, ind: null }; }
  }));

  results.sort((a, b) => b.score - a.score);
  const best = results[0];
  if (best.sym !== cfg.SYMBOL) logger.info(`📡 Scanner: cel mai bun simbol → ${best.sym} (scor: ${best.score.toFixed(2)})`);
  return best.sym;
}

// ─── Loop principal ───────────────────────────────────────
async function tick() {
  tickCount++;
  try {
    // La fiecare 5 tick-uri, afișează stats
    if (tickCount % 5 === 0) logger.printStats(await getBalance(), openPosition, await exchange.getPrice(cfg.SYMBOL).catch(() => null));

    const symbol = await bestSymbol();
    logger.info(`[${tickCount}] Analizez ${symbol} (${cfg.EXCHANGE})...`);

    const [candles, price] = await Promise.all([
      exchange.getCandles(symbol, cfg.TIMEFRAME, cfg.CANDLES),
      exchange.getPrice(symbol),
    ]);
    const balance = await getBalance();
    logger.updateBalance(balance);

    // Verifică SL/TP/Trailing
    const trigger = checkPosition(price);
    if (trigger) {
      logger.warn(`${trigger} atins la $${price} (SL curent: $${openPosition?.stopLoss?.toFixed(5)})`);
      await closeTrade(price, trigger);
      logger.printStats(await getBalance(), null, null);
      return;
    }

    // Indicatori + AI signal
    const ind    = indicators.analyze(candles);
    const signal = await ai.getSignal(ind, balance, openPosition);
    logger.printSignal(signal, ind);

    // Filtre de calitate
    const tooLowBalance = balance < 1; // Sub $1 nu mai putem tranzacționa
    const criteriaOk    = (signal.criteriaScore ?? 3) >= 3;

    if (tooLowBalance) {
      logger.warn('Balanță prea mică ($' + balance.toFixed(2) + ') — stop trading');
      return;
    }

    // Execuție
    if (signal.action === 'HOLD' || signal.confidence < cfg.MIN_CONFIDENCE || !criteriaOk) {
      logger.info(`HOLD — confidence: ${signal.confidence}% | criterii: ${signal.criteriaScore ?? '?'}/5`);
    } else if (signal.action === 'CLOSE' && openPosition) {
      await closeTrade(price, 'AI_CLOSE');
    } else if (signal.action === 'BUY' && !openPosition) {
      await openTrade('BUY', price, balance, parseFloat(ind.atr));
    } else if (signal.action === 'SELL' && !openPosition) {
      await openTrade('SELL', price, balance, parseFloat(ind.atr));
    } else {
      logger.info(`Skip — poziție ${openPosition ? 'deja deschisă' : 'deja închisă'}`);
    }

    logger.printStats(balance, openPosition, price);
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

  logger.info('🚀 Prima analiză...');
  await tick();
  setInterval(tick, cfg.LOOP_INTERVAL_MS);
  logger.info(`⏱️  Analiză la fiecare ${cfg.LOOP_INTERVAL_MS / 60000} minute.`);
}

main().catch(err => { logger.error('Fatal: ' + err.message); process.exit(1); });
