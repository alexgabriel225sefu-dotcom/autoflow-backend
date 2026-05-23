require('dotenv').config();
const cfg        = require('./config');
const indicators = require('./indicators');
const ai         = require('./ai');
const logger     = require('./logger');
const strategies = require('./strategies');

// ─── Exchange ─────────────────────────────────────────────
const exchange = cfg.EXCHANGE === 'binance'
  ? require('./binance')
  : require('./bybit');

// ─── State ────────────────────────────────────────────────
let openPosition = null;
let paperBalance = cfg.PAPER_BALANCE;
let tickCount    = 0;
let startBalance = 0; // set in main(), used by strategies

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
async function calcQuantity(price, balance, symbol = cfg.SYMBOL, druckMult = 1.0) {
  const riskAmount = balance * cfg.RISK_PER_TRADE * druckMult;
  const qty        = riskAmount / price;
  // Coins under $1 → whole units; expensive coins (SOL, BNB etc.) → 6 decimals
  const isWhole    = ['DOGEUSDT','SHIBUSDT','XRPUSDT','ADAUSDT','MATICUSDT','TRXUSDT'].includes(symbol);
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
async function openTrade(side, price, balance, atrValue = 0, symbol = cfg.SYMBOL, druckMult = 1.0) {
  const quantity = await calcQuantity(price, balance, symbol, druckMult);
  if (quantity <= 0) { logger.warn(`Cantitate prea mică pentru ${symbol} @ $${price} — skip`); return; }
  if (druckMult !== 1.0) logger.info(`🎯 Druckenmiller: mărime poziție ×${druckMult.toFixed(2)}`);

  await exchange.placeOrder(side, quantity, symbol);

  if (cfg.PAPER_TRADING) {
    if (side === 'BUY') paperBalance -= price * quantity; // cumpărăm: scade balanța
    else                paperBalance += price * quantity; // short: primim încasarea
  }

  const { stopLoss, takeProfit } = calcSLTP(side, price, atrValue);
  const rrRatio = Math.abs(takeProfit - price) / Math.abs(price - stopLoss);

  openPosition = {
    symbol,  // ← stocăm simbolul real al poziției
    side, entryPrice: price, quantity, stopLoss, takeProfit,
    openedAt: new Date().toISOString(), pnlPct: 0,
    trailHigh: side === 'BUY' ? price : null,
    trailLow:  side === 'SELL' ? price : null,
  };

  logger.printTrade(side, symbol, price, quantity);
  logger.info(`SL: $${stopLoss.toFixed(5)} | TP: $${takeProfit.toFixed(5)} | R:R = 1:${rrRatio.toFixed(2)}`);
}

// ─── Închide poziție ──────────────────────────────────────
async function closeTrade(price, reason) {
  if (!openPosition) return;
  const { side, entryPrice, quantity, symbol = cfg.SYMBOL } = openPosition;
  const closeSide = side === 'BUY' ? 'SELL' : 'BUY';

  await exchange.placeOrder(closeSide, quantity, symbol);

  const pnl = side === 'BUY'
    ? (price - entryPrice) * quantity
    : (entryPrice - price) * quantity;

  if (cfg.PAPER_TRADING) {
    // BUY close → vindem coinul, primim price*qty
    // SELL close → cumpărăm coinul înapoi, plătim price*qty
    // Compound sau nu: balanța reflectă automat profitul/pierderea
    if (side === 'BUY') paperBalance += price * quantity;
    else                paperBalance -= price * quantity;
  }

  logger.printTrade(closeSide, symbol, price, quantity, pnl);
  logger.info(`Motivul: ${reason} | PnL: ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)}`);
  strategies.recordTrade(pnl > 0, pnl, startBalance || cfg.PAPER_BALANCE);
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
    // Dacă e poziție deschisă → monitorizăm ACELAȘI simbol, nu lăsăm scannerul să schimbe
    const activeSymbol = openPosition?.symbol ?? null;
    const symbol = activeSymbol || await bestSymbol();

    // La fiecare 5 tick-uri, afișează stats
    if (tickCount % 5 === 0) logger.printStats(await getBalance(), openPosition, await exchange.getPrice(symbol).catch(() => null));

    logger.info(`[${tickCount}] Analizez ${symbol} (${cfg.EXCHANGE})${activeSymbol ? ' 🔒 poziție activă' : ''}...`);

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

    // Indicatori + strategii legendare
    const ind      = indicators.analyze(candles);
    const stratData = strategies.analyze(candles);

    // Paul Tudor Jones / Seykota: verifică dacă trebuie să ne oprim
    const stopCheck = strategies.shouldStop(balance, startBalance || cfg.PAPER_BALANCE);
    if (stopCheck.stop) {
      logger.warn(`🛑 STRATEGY STOP: ${stopCheck.reasons.join(' | ')}`);
      if (openPosition) {
        logger.warn('Poziție deschisă — o păstrăm până la SL/TP natural.');
      }
      logger.printStats(await getBalance(), openPosition, price);
      return;
    }

    // Logare structură de piață detectată
    if (stratData.livermore.trend !== 'NEUTRAL') {
      logger.info(`📊 Livermore: ${stratData.livermore.trend} (${stratData.livermore.reason}) | Putere: ${(stratData.livermore.strength * 100).toFixed(0)}%`);
    }
    if (stratData.turtle.signal) {
      logger.info(`🐢 Turtle: ${stratData.turtle.breakoutStr} breakout ${stratData.turtle.signal} | H20: ${stratData.turtle.high20} | L20: ${stratData.turtle.low20}`);
    }
    if (stratData.soros.direction !== 'NEUTRAL') {
      logger.info(`💡 Soros: momentum ${stratData.soros.direction} (${(stratData.soros.momentum * 100).toFixed(0)}% bullish, velocity ${stratData.soros.velocity?.toFixed(2)}%)`);
    }

    // AI signal (cu context strategie)
    const signal = await ai.getSignal(ind, balance, openPosition, stratData);
    logger.printSignal(signal, ind);

    // Filtre de calitate
    const tooLowBalance = balance < 1;
    const criteriaOk    = (signal.criteriaScore ?? 3) >= 3;

    if (tooLowBalance) {
      logger.warn('Balanță prea mică ($' + balance.toFixed(2) + ') — stop trading');
      return;
    }

    // Stan Druckenmiller: calculează multiplicatorul de poziție
    const druckMult = !openPosition
      ? strategies.druckenmillerMultiplier(signal.confidence, signal.criteriaScore, stratData.livermore, stratData.turtle)
      : 1.0;

    // ─── Hard filter: Jesse Livermore anti-contra-trend rule ──
    // "Never fight the tape." — dacă Livermore + Turtle sunt unanimi,
    // blocăm AI-ul să intre contra trendului (indiferent de RSI/MACD)
    const liveSTR   = stratData.livermore.strength ?? 0;
    const turtleSig = stratData.turtle.signal;
    if (!openPosition && signal.action === 'BUY' &&
        stratData.livermore.trend === 'BEARISH' && liveSTR >= 0.8 && turtleSig === 'SELL') {
      logger.warn(`⚡ Signal filtrat: BUY contra Livermore BEARISH ${(liveSTR*100).toFixed(0)}% + Turtle STRONG SELL — HOLD forțat (PTJ: play defense)`);
      signal.action = 'HOLD';
    }
    if (!openPosition && signal.action === 'SELL' &&
        stratData.livermore.trend === 'BULLISH' && liveSTR >= 0.8 && turtleSig === 'BUY') {
      logger.warn(`⚡ Signal filtrat: SELL contra Livermore BULLISH ${(liveSTR*100).toFixed(0)}% + Turtle STRONG BUY — HOLD forțat (PTJ: play defense)`);
      signal.action = 'HOLD';
    }

    // Execuție
    if (signal.action === 'HOLD' || signal.confidence < cfg.MIN_CONFIDENCE || !criteriaOk) {
      logger.info(`HOLD — confidence: ${signal.confidence}% | criterii: ${signal.criteriaScore ?? '?'}/5`);
    } else if (signal.action === 'CLOSE' && openPosition) {
      await closeTrade(price, 'AI_CLOSE');
    } else if (signal.action === 'BUY' && !openPosition) {
      await openTrade('BUY', price, balance, parseFloat(ind.atr), symbol, druckMult);
    } else if (signal.action === 'SELL' && !openPosition) {
      await openTrade('SELL', price, balance, parseFloat(ind.atr), symbol, druckMult);
    } else {
      logger.info(`Skip — poziție ${openPosition ? 'deja deschisă' : 'deja închisă'}`);
    }

    logger.printStats(await getBalance(), openPosition, price);
  } catch (err) {
    logger.error(`Tick error: ${err.message}`);
  }
}

// ─── Start ────────────────────────────────────────────────
async function main() {
  validate();
  const balance = await getBalance();
  startBalance  = balance; // pentru shouldStop + recordTrade
  logger.setStartBalance(balance);
  logger.printBanner(balance);

  logger.info('🚀 Prima analiză...');
  await tick();
  setInterval(tick, cfg.LOOP_INTERVAL_MS);
  logger.info(`⏱️  Analiză la fiecare ${cfg.LOOP_INTERVAL_MS / 60000} minute.`);
}

main().catch(err => { logger.error('Fatal: ' + err.message); process.exit(1); });
