process.stdout.write(`[APEX BOT] Starting... Node ${process.version}\n`);
require('dotenv').config();
const cfg            = require('./config');
const indicators     = require('./indicators');
const ai             = require('./ai');
const logger         = require('./logger');
const strategies     = require('./strategies');
const tg             = require('./telegram');
const state          = require('./state');
const buildDashboard = require('./dashboard');

// ─── Exchange ─────────────────────────────────────────────
// Factory selects the connector for cfg.EXCHANGE (8 supported).
const exchange = require('./exchange');

// ─── State ────────────────────────────────────────────────
let openPosition      = null;
let paperBalance      = cfg.PAPER_BALANCE;
let tickCount         = 0;
let startBalance      = 0; // set in main(), used by strategies
let stopAlertedAt     = 0; // previne spam Strategy Stop pe Telegram

// ─── Dashboard Data ───────────────────────────────────────
const dash = {
  balance:       0,
  startBalance:  0,
  currentSymbol: cfg.SYMBOL,
  currentPrice:  0,
  openPosition:  null,
  trades:        [], // max 50 trades history
  lastTick:      null,
  mode:          cfg.PAPER_TRADING ? 'PAPER' : cfg.BYBIT_TESTNET || cfg.BINANCE_TESTNET ? 'TESTNET' : 'LIVE',
  exchange:      cfg.EXCHANGE.toUpperCase(),
};

// ─── License verification ─────────────────────────────────
async function verifyLicense() {
  const key    = cfg.LICENSE_KEY;
  const server = cfg.LICENSE_SERVER;

  if (!key) {
    if (process.env.BYPASS_LICENSE === 'true') {
      console.warn('⚠️  LICENSE_KEY not set — running in owner/dev mode (BYPASS_LICENSE=true).');
      return;
    }
    console.error('\n❌  LICENSE_KEY is not set.');
    console.error('    Add your license key from your purchase email to Railway Variables.');
    console.error('    Purchase at: https://aicashsystem.space\n');
    process.exit(1);
  }

  try {
    const res  = await fetch(`${server}/api/verify-license`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ key, product: 'apex-bot' }),
      signal:  AbortSignal.timeout(10000),
    });
    const data = await res.json();
    if (!data.valid) {
      console.error(`\n❌  License invalid: ${data.message}`);
      console.error('    Make sure LICENSE_KEY in Variables matches the key from your email.\n');
      process.exit(1);
    }
    console.log(`✅  License verified — welcome, ${data.email || 'trader'}!`);
  } catch (e) {
    // Network error → allow startup with warning (don't block on transient issues)
    console.warn(`⚠️   License server unreachable (${e.message}) — starting in grace mode.`);
  }
}

// ─── Validare startup ─────────────────────────────────────
function validate() {
  const hasAnthropic = !!cfg.ANTHROPIC_API_KEY;
  const hasGroq      = !!process.env.GROQ_API_KEY;

  if (!hasAnthropic && !hasGroq) {
    console.error('❌ No AI key found! Add ANTHROPIC_API_KEY or GROQ_API_KEY to Variables.');
    process.exit(1);
  }
  if (!hasAnthropic && hasGroq) {
    console.log('ℹ️  ANTHROPIC_API_KEY missing — using Groq (free) as AI provider.');
  }
  if (hasAnthropic && hasGroq) {
    console.log('ℹ️  Anthropic + Groq configured — Anthropic primary, Groq fallback.');
  }

  const KEY_FIELD = {
    binance: 'BINANCE_API_KEY', bybit: 'BYBIT_API_KEY', okx: 'OKX_API_KEY',
    kraken: 'KRAKEN_API_KEY', kucoin: 'KUCOIN_API_KEY', coinbase: 'COINBASE_API_KEY',
    bitget: 'BITGET_API_KEY', mexc: 'MEXC_API_KEY',
  };
  const hasKey = cfg[KEY_FIELD[cfg.EXCHANGE]] || '';
  if (!hasKey && !cfg.PAPER_TRADING) {
    console.warn('⚠️  No exchange API key found — falling back to PAPER TRADING automatically');
    cfg.PAPER_TRADING = true;
  }

  // Live trading e validat (ordine corecte + stop server-side) doar pe Binance.
  // Celelalte exchange-uri: date + paper. Override explicit pentru experți.
  const LIVE_VALIDATED = ['binance'];
  if (!cfg.PAPER_TRADING && !LIVE_VALIDATED.includes(cfg.EXCHANGE)
      && process.env.ALLOW_EXPERIMENTAL_LIVE !== 'true') {
    console.warn(`⚠️  Live trading pe "${cfg.EXCHANGE}" nu e validat cu bani reali — trec pe PAPER TRADING.`);
    console.warn('    Suportat live: Binance. Override (pe riscul tău): ALLOW_EXPERIMENTAL_LIVE=true');
    cfg.PAPER_TRADING = true;
  }
}

// ─── Balanță ──────────────────────────────────────────────
async function getBalance() {
  if (cfg.PAPER_TRADING) return paperBalance;
  try { return await exchange.getBalance(); }
  catch (e) {
    logger.warn(`[BALANCE] API error: ${e.message} — check API keys & BINANCE_TESTNET flag`);
    return 0;
  }
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

// ─── Exit management (SL/TP/breakeven/trailing/runner) ─────
const { calcSLTP, checkPosition } = require('./position');

// ─── Deschide poziție ─────────────────────────────────────
async function openTrade(side, price, balance, atrValue = 0, symbol = cfg.SYMBOL, druckMult = 1.0) {
  // Pe spot live nu există short — un SELL ar vinde monede pe care clientul
  // nu le are (ordin respins) sau pe care le deținea deja (pierdere reală).
  if (side === 'SELL' && !cfg.PAPER_TRADING) {
    logger.warn(`⛔ SELL pe spot LIVE blocat (${symbol}) — short doar în paper trading`);
    return;
  }
  const quantity = await calcQuantity(price, balance, symbol, druckMult);
  if (quantity <= 0) { logger.warn(`Quantity too small for ${symbol} @ $${price} — skip`); return; }
  if (druckMult !== 1.0) logger.info(`🎯 Druckenmiller: position size ×${druckMult.toFixed(2)}`);

  const order = await exchange.placeOrder(side, quantity, symbol);
  // Live: folosește fill-ul real (preț mediu + cantitate executată), nu ticker-ul
  const fillPrice = !cfg.PAPER_TRADING && order?.avgPrice    ? order.avgPrice    : price;
  const fillQty   = !cfg.PAPER_TRADING && order?.executedQty ? order.executedQty : quantity;

  if (cfg.PAPER_TRADING) {
    const fee = price * quantity * cfg.FEE_PCT; // comision real, altfel paper-ul minte
    if (side === 'BUY') paperBalance -= price * quantity + fee; // cumpărăm: scade balanța
    else                paperBalance += price * quantity - fee; // short: primim încasarea
  }

  const { stopLoss, takeProfit } = calcSLTP(side, fillPrice, atrValue);
  const rrRatio = Math.abs(takeProfit - fillPrice) / Math.abs(fillPrice - stopLoss);

  openPosition = {
    symbol,  // ← stocăm simbolul real al poziției
    side, entryPrice: fillPrice, quantity: fillQty, stopLoss, takeProfit,
    initialStop: stopLoss, // referință pentru breakeven (+1R)
    openedAt: new Date().toISOString(), pnlPct: 0,
    openFee: order?.quoteFee ?? 0, // comision real de intrare (live)
    trailHigh: side === 'BUY' ? fillPrice : null,
    trailLow:  side === 'SELL' ? fillPrice : null,
  };

  // Live: pune SL/TP și la exchange (OCO) — dacă botul moare, poziția rămâne protejată
  if (!cfg.PAPER_TRADING && typeof exchange.placeProtection === 'function') {
    try {
      await exchange.placeProtection(symbol, fillQty, stopLoss, takeProfit);
      openPosition.hasProtection = true;
    } catch (e) {
      // Fără protecție server-side nu ținem poziție live deschisă — închidem imediat
      logger.error(`❌ OCO eșuat (${e.message}) — închid poziția imediat, nu las trade live neprotejat`);
      await exchange.placeOrder('SELL', fillQty, symbol).catch(err =>
        logger.error(`‼️ Închiderea de siguranță a eșuat: ${err.message} — ÎNCHIDE MANUAL ${symbol}!`));
      openPosition = null;
      return;
    }
  }
  dash.openPosition = openPosition;

  logger.printTrade(side, symbol, fillPrice, fillQty);
  logger.info(`SL: $${stopLoss.toFixed(5)} | TP: $${takeProfit.toFixed(5)} | R:R = 1:${rrRatio.toFixed(2)}`);
  tg.alertOpen(side, symbol, fillPrice, fillQty, stopLoss, takeProfit, druckMult);
  state.save(paperBalance, openPosition, strategies.sessionSnapshot());
}

// ─── Închide poziție ──────────────────────────────────────
async function closeTrade(price, reason, alreadyClosed = false) {
  if (!openPosition) return;
  const { side, entryPrice, quantity, symbol = cfg.SYMBOL } = openPosition;
  const closeSide = side === 'BUY' ? 'SELL' : 'BUY';

  let fillPrice = price, closeFee = 0;
  if (!alreadyClosed) {
    // Live: anulează OCO-ul de protecție înainte de market-close, altfel ar rămâne agățat
    if (!cfg.PAPER_TRADING && openPosition.hasProtection && typeof exchange.cancelAllOrders === 'function') {
      await exchange.cancelAllOrders(symbol).catch(e => logger.warn(`Cancel OCO: ${e.message}`));
    }
    const order = await exchange.placeOrder(closeSide, quantity, symbol);
    if (!cfg.PAPER_TRADING && order?.avgPrice) { fillPrice = order.avgPrice; closeFee = order.quoteFee ?? 0; }
  }

  let pnl = (side === 'BUY' ? fillPrice - entryPrice : entryPrice - fillPrice) * quantity;

  if (cfg.PAPER_TRADING) {
    // vinzi (BUY) sau răscumperi (SELL) — comision pe fiecare parte
    const fee = price * quantity * cfg.FEE_PCT;
    if (side === 'BUY') paperBalance += price * quantity - fee;
    else                paperBalance -= price * quantity + fee;
    pnl -= (entryPrice + price) * quantity * cfg.FEE_PCT; // PnL net de comisioane (ambele părți)
  } else {
    // Live: scade comisioanele reale (sau estimate la FEE_PCT dacă lipsesc din fill)
    const fees = (openPosition.openFee || entryPrice * quantity * cfg.FEE_PCT)
               + (closeFee            || fillPrice  * quantity * cfg.FEE_PCT);
    pnl -= fees;
  }
  price = fillPrice;

  logger.printTrade(closeSide, symbol, price, quantity, pnl);
  logger.info(`Motivul: ${reason} | PnL: ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)}`);
  strategies.recordTrade(pnl > 0, pnl, startBalance || cfg.PAPER_BALANCE);
  const bal = await getBalance();
  tg.alertClose(reason, symbol, side, entryPrice, price, pnl, bal);

  // ─── Dashboard: înregistrează trade încheiat ──────────────
  dash.trades.unshift({
    time:       new Date().toLocaleString('en-US'),
    symbol,
    side,
    entry:      entryPrice,
    exit:       price,
    qty:        quantity,
    pnl:        parseFloat(pnl.toFixed(4)),
    pnlPct:     parseFloat(((pnl / (entryPrice * quantity)) * 100).toFixed(2)),
    reason,
    win:        pnl > 0,
  });
  if (dash.trades.length > 50) dash.trades.pop();
  dash.openPosition = null;
  dash.balance      = bal;

  openPosition = null;
  state.save(paperBalance, null, strategies.sessionSnapshot());
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
  if (best.sym !== cfg.SYMBOL) logger.info(`📡 Scanner: best symbol → ${best.sym} (score: ${best.score.toFixed(2)})`);
  return best.sym;
}

// ─── Loop principal ───────────────────────────────────────
let ticking = false; // guard: AI-ul poate dura >interval → fără tick-uri suprapuse
async function tick() {
  if (ticking) { logger.warn('Tick anterior încă rulează — skip'); return; }
  ticking = true;
  tickCount++;
  try {
    // Live: dacă OCO-ul de la exchange s-a executat (SL sau TP), poziția nu mai
    // există acolo — sincronizăm, altfel botul ar deschide alta peste ea
    if (!cfg.PAPER_TRADING && openPosition?.hasProtection && typeof exchange.getOpenOrders === 'function') {
      const open = await exchange.getOpenOrders(openPosition.symbol).catch(() => null);
      if (Array.isArray(open) && open.length === 0) {
        const px = await exchange.getPrice(openPosition.symbol);
        logger.warn(`🛡️ OCO executat la exchange (${openPosition.symbol}) — închid poziția în evidență`);
        await closeTrade(px, 'EXCHANGE_SLTP', true);
      }
    }
    // Dacă e poziție deschisă → monitorizăm ACELAȘI simbol, nu lăsăm scannerul să schimbe
    const activeSymbol = openPosition?.symbol ?? null;
    const symbol = activeSymbol || await bestSymbol();

    // La fiecare 5 tick-uri, afișează stats în consolă
    if (tickCount % 5 === 0) logger.printStats(await getBalance(), openPosition, await exchange.getPrice(symbol).catch(() => null));

    // La fiecare 6 tick-uri (30 min), trimite heartbeat pe Telegram
    if (tickCount % 6 === 0) {
      const hbBalance = await getBalance();
      const hbPrice   = await exchange.getPrice(symbol).catch(() => null);
      tg.alertHeartbeat(tickCount, hbBalance, openPosition, hbPrice);
    }

    logger.info(`[${tickCount}] Analyzing ${symbol} (${cfg.EXCHANGE})${activeSymbol ? ' 🔒 active position' : ''}...`);

    const [candles, price] = await Promise.all([
      exchange.getCandles(symbol, cfg.TIMEFRAME, cfg.CANDLES),
      exchange.getPrice(symbol),
    ]);
    const balance = await getBalance();
    logger.updateBalance(balance);

    // ─── Actualizează dashboard ───────────────────────────────
    dash.balance       = balance;
    dash.currentSymbol = symbol;
    dash.currentPrice  = price;
    dash.lastTick      = new Date().toLocaleString('ro-RO');
    if (openPosition) {
      const posPnl = openPosition.side === 'BUY'
        ? (price - openPosition.entryPrice) * openPosition.quantity
        : (openPosition.entryPrice - price) * openPosition.quantity;
      dash.openPosition = { ...openPosition, currentPnl: parseFloat(posPnl.toFixed(4)) };
    }

    // Verifică SL/TP/Trailing
    const trigger = checkPosition(openPosition, price);
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
    // Folosim valoarea totală a portofoliului (USDT + poziție deschisă) nu doar USDT liber
    let portfolioValue = balance;
    if (openPosition && price) {
      portfolioValue = openPosition.side === 'BUY'
        ? balance + openPosition.quantity * price
        : balance - openPosition.quantity * price;
    }
    const stopCheck = strategies.shouldStop(portfolioValue, startBalance || cfg.PAPER_BALANCE);
    if (stopCheck.stop) {
      logger.warn(`🛑 STRATEGY STOP: ${stopCheck.reasons.join(' | ')}`);
      if (openPosition) {
        logger.warn('Poziție deschisă — o păstrăm până la SL/TP natural.');
      }
      // Trimite alertă Telegram maxim o dată la 30 minute (nu la fiecare tick)
      const now = Date.now();
      if (now - stopAlertedAt > 30 * 60 * 1000) {
        tg.alertStop(stopCheck.reasons);
        stopAlertedAt = now;
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
      const sorosDir  = stratData.soros.direction;
      const sorosPct  = stratData.soros.direction === 'BEARISH'
        ? ((1 - stratData.soros.momentum) * 100).toFixed(0) + '% bearish'
        : (stratData.soros.momentum * 100).toFixed(0) + '% bullish';
      logger.info(`💡 Soros: momentum ${sorosDir} (${sorosPct}, velocity ${stratData.soros.velocity?.toFixed(2)}%)`);
    }

    // AI signal (cu context strategie)
    const signal = await ai.getSignal(ind, balance, openPosition, stratData);
    logger.printSignal(signal, ind);

    // Filtre de calitate
    const tooLowBalance = balance < 1;
    const minCriteria   = parseInt(process.env.MIN_CRITERIA   || '5');   // 5/5 — tuning r3: mc5 dă 40% WR vs 24% la mc4
    const minVolume     = parseFloat(process.env.MIN_VOLUME_RATIO || '0.7'); // 0.7× default (era 1.0)
    const criteriaOk    = (signal.criteriaScore ?? 0) >= minCriteria;
    const volumeOk      = parseFloat(ind.volumeRatio) >= minVolume;

    if (tooLowBalance) {
      logger.warn('Balanță prea mică ($' + balance.toFixed(2) + ') — stop trading');
      return;
    }
    if (!volumeOk && !openPosition) {
      logger.info(`⚠️ Volum insuficient (${ind.volumeRatio}× < ${minVolume}×) — HOLD, așteptăm confirmare volum`);
    }

    // Stan Druckenmiller: calculează multiplicatorul de poziție
    const druckMult = !openPosition
      ? strategies.druckenmillerMultiplier(signal.confidence, signal.criteriaScore, stratData.livermore, stratData.turtle)
      : 1.0;

    // ─── Hard filter: Jesse Livermore anti-contra-trend rule ──
    // "Never fight the tape." — dacă Livermore + Turtle sunt unanimi,
    // blocăm AI-ul să intre contra trendului (indiferent de RSI/MACD)
    const liveSTR    = stratData.livermore.strength ?? 0;
    const liveTrend  = stratData.livermore.trend;
    const turtleSig  = stratData.turtle.signal;
    const contraSide = liveTrend === 'BEARISH' && turtleSig === 'SELL' ? 'BUY'
                     : liveTrend === 'BULLISH' && turtleSig === 'BUY'  ? 'SELL' : null;
    if (!openPosition && liveSTR >= 0.8 && signal.action === contraSide) {
      logger.warn(`⚡ Signal filtrat: ${contraSide} contra Livermore ${liveTrend} ${(liveSTR*100).toFixed(0)}% + Turtle STRONG ${turtleSig} — HOLD forțat (PTJ: play defense)`);
      tg.alertFiltered(contraSide, `${liveTrend} ${(liveSTR*100).toFixed(0)}%`, `STRONG ${turtleSig}`);
      signal.action = 'HOLD';
    }

    // ─── Seykota: cooldown după pierdere — fără revenge trading ──
    const cdMin = strategies.cooldownRemaining(cfg.COOLDOWN_AFTER_LOSS_MIN);
    if (!openPosition && cdMin > 0 && (signal.action === 'BUY' || signal.action === 'SELL')) {
      logger.info(`⏸️ Cooldown după pierdere: mai aștept ${cdMin} min înainte de re-intrare`);
      signal.action = 'HOLD';
    }

    // ─── Filtru trend HTF: nu tranzacționa 5m contra trendului 1h ──
    if (cfg.HTF_FILTER && !openPosition && (signal.action === 'BUY' || signal.action === 'SELL')) {
      const htf = strategies.htfTrend(await exchange.getCandles(symbol, cfg.HTF_TIMEFRAME, 60).catch(() => null));
      if ((signal.action === 'BUY' && htf === 'BEARISH') || (signal.action === 'SELL' && htf === 'BULLISH')) {
        logger.warn(`⚡ Filtru ${cfg.HTF_TIMEFRAME}: ${signal.action} contra trend ${htf} — HOLD (trade with the tape)`);
        signal.action = 'HOLD';
      }
    }

    // Execuție
    if (signal.action === 'HOLD' || signal.confidence < cfg.MIN_CONFIDENCE || !criteriaOk || (!volumeOk && !openPosition)) {
      logger.info(`HOLD — confidence: ${signal.confidence}% | criterii: ${signal.criteriaScore ?? '?'}/5 | volum: ${ind.volumeRatio}×`);
    } else if (signal.action === 'CLOSE' && openPosition) {
      await closeTrade(price, 'AI_CLOSE');
    } else if (signal.action === 'BUY' && !openPosition) {
      await openTrade('BUY', price, balance, parseFloat(ind.atr), symbol, druckMult);
    } else if (signal.action === 'SELL' && !openPosition) {
      await openTrade('SELL', price, balance, parseFloat(ind.atr), symbol, druckMult);
    } else {
      logger.info(`Skip — position ${openPosition ? 'already open' : 'already closed'}`);
    }

    logger.printStats(await getBalance(), openPosition, price);
  } catch (err) {
    logger.error(`Tick error: ${err.message}`);
  } finally {
    ticking = false;
  }
}

// ─── Start ────────────────────────────────────────────────
async function main() {
  // Load config saved in the configurator FIRST — it provides the AI key,
  // exchange keys, strategy and mode. Must run before validate()/getBalance(),
  // otherwise validate() exits (no AI key yet) and the deploy "fails".
  await cfg.loadRemote();
  validate();

  // Re-sync paper balance from the (now loaded) remote config. `paperBalance`
  // was initialized at module load from the default cfg value, before
  // loadRemote() updated it — without this it would stay at the $100 default.
  paperBalance = cfg.PAPER_BALANCE;

  // Restaurează starea după restart — și în live, altfel botul uită poziția
  // deschisă și ar deschide alta peste ea (dublă expunere)
  const saved = state.load(cfg.PAPER_BALANCE);
  if (saved) {
    if (cfg.PAPER_TRADING) paperBalance = saved.paperBalance;
    openPosition = saved.openPosition;
    strategies.restoreSession(saved.session);
    if (openPosition) dash.openPosition = openPosition;
  }

  const balance = await getBalance();
  startBalance       = balance;
  dash.balance       = balance;
  dash.startBalance  = balance;
  logger.setStartBalance(balance);
  logger.printBanner(balance);

  // For Binance: default is testnet (live api.binance.com is geo-blocked from EU cloud servers)
  // BINANCE_TESTNET=false only when explicitly going live
  const isBinanceTestnet = cfg.EXCHANGE === 'binance'
    ? (process.env.BINANCE_TESTNET || '').toLowerCase().trim() !== 'false'
    : false;
  const isTestnet = cfg.BYBIT_TESTNET || isBinanceTestnet;
  const mode = cfg.PAPER_TRADING ? '📝 PAPER TRADING' : isTestnet ? '🧪 TESTNET' : '🔴 LIVE';
  dash.mode = mode.replace(/[📝🧪🔴]/g, '').trim();
  tg.alertStart(cfg.SYMBOL, cfg.TIMEFRAME, balance, mode);

  // ─── Dashboard HTTP server (auth cu DASHBOARD_TOKEN) ──────
  buildDashboard.serve(() => ({ ...dash, tickCount }), logger);

  tg.startPolling(() => dash, exchange);

  await verifyLicense();
  logger.info('🚀 First analysis...');
  await tick();
  setInterval(tick, cfg.LOOP_INTERVAL_MS);
  logger.info(`⏱️  Analyzing every ${cfg.LOOP_INTERVAL_MS / 60000} minutes.`);
}

main().catch(err => { logger.error('Fatal: ' + err.message); process.exit(1); });
