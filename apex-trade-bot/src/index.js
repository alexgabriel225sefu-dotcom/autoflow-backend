require('dotenv').config();
const cfg        = require('./config');
const indicators = require('./indicators');
const ai         = require('./ai');
const logger     = require('./logger');
const strategies = require('./strategies');
const tg         = require('./telegram');
const state      = require('./state');
const http       = require('http');

// ─── Exchange ─────────────────────────────────────────────
const exchange = cfg.EXCHANGE === 'binance'
  ? require('./binance')
  : require('./bybit');

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
    console.error('\n❌  LICENSE_KEY is not set.');
    console.error('    Add your license key from your purchase email to Railway Variables.');
    console.error('    Purchase at: https://aicashsystem.space\n');
    process.exit(1);
  }

  try {
    const res  = await fetch(`${server}/api/verify-license`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ key }),
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

  const hasKey = cfg.EXCHANGE === 'binance' ? cfg.BINANCE_API_KEY : cfg.BYBIT_API_KEY;
  if (!hasKey && !cfg.PAPER_TRADING) {
    console.warn('⚠️  No exchange API key found — falling back to PAPER TRADING automatically');
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
  dash.openPosition = openPosition;

  logger.printTrade(side, symbol, price, quantity);
  logger.info(`SL: $${stopLoss.toFixed(5)} | TP: $${takeProfit.toFixed(5)} | R:R = 1:${rrRatio.toFixed(2)}`);
  tg.alertOpen(side, symbol, price, quantity, stopLoss, takeProfit, druckMult);
  state.save(paperBalance, openPosition);
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
  const bal = await getBalance();
  tg.alertClose(reason, symbol, side, entryPrice, price, pnl, bal);

  // ─── Dashboard: înregistrează trade încheiat ──────────────
  dash.trades.unshift({
    time:       new Date().toLocaleString('ro-RO'),
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
  state.save(paperBalance, null);
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

    // La fiecare 5 tick-uri, afișează stats în consolă
    if (tickCount % 5 === 0) logger.printStats(await getBalance(), openPosition, await exchange.getPrice(symbol).catch(() => null));

    // La fiecare 6 tick-uri (30 min), trimite heartbeat pe Telegram
    if (tickCount % 6 === 0) {
      const hbBalance = await getBalance();
      const hbPrice   = await exchange.getPrice(symbol).catch(() => null);
      tg.alertHeartbeat(tickCount, hbBalance, openPosition, hbPrice);
    }

    logger.info(`[${tickCount}] Analizez ${symbol} (${cfg.EXCHANGE})${activeSymbol ? ' 🔒 poziție activă' : ''}...`);

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
    const minCriteria   = parseInt(process.env.MIN_CRITERIA   || '3');   // 3/5 default (era 4)
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
    const liveSTR   = stratData.livermore.strength ?? 0;
    const turtleSig = stratData.turtle.signal;
    if (!openPosition && signal.action === 'BUY' &&
        stratData.livermore.trend === 'BEARISH' && liveSTR >= 0.8 && turtleSig === 'SELL') {
      logger.warn(`⚡ Signal filtrat: BUY contra Livermore BEARISH ${(liveSTR*100).toFixed(0)}% + Turtle STRONG SELL — HOLD forțat (PTJ: play defense)`);
      tg.alertFiltered('BUY', 'BEARISH 85%', 'STRONG SELL');
      signal.action = 'HOLD';
    }
    if (!openPosition && signal.action === 'SELL' &&
        stratData.livermore.trend === 'BULLISH' && liveSTR >= 0.8 && turtleSig === 'BUY') {
      logger.warn(`⚡ Signal filtrat: SELL contra Livermore BULLISH ${(liveSTR*100).toFixed(0)}% + Turtle STRONG BUY — HOLD forțat (PTJ: play defense)`);
      tg.alertFiltered('SELL', 'BULLISH 85%', 'STRONG BUY');
      signal.action = 'HOLD';
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

  // Restaurează starea după restart
  if (cfg.PAPER_TRADING) {
    const saved = state.load(cfg.PAPER_BALANCE);
    if (saved) {
      paperBalance = saved.paperBalance;
      openPosition = saved.openPosition;
    }
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

  // ─── Dashboard HTTP server ────────────────────────────────
  const PORT = parseInt(process.env.PORT || process.env.DASHBOARD_PORT || '3000');
  http.createServer((req, res) => {
    if (req.url === '/api/status') {
      res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
      res.end(JSON.stringify(dash));
      return;
    }
    // Dashboard HTML
    const sym = (dash.currentSymbol || cfg.SYMBOL).replace('USDT', '_USDT');
    const tvSym = `${dash.exchange === 'BINANCE' ? 'BINANCE' : 'BYBIT'}:${sym}`;
    const pnlTotal  = dash.startBalance > 0 ? ((dash.balance - dash.startBalance) / dash.startBalance * 100).toFixed(2) : '0.00';
    const pnlColor  = parseFloat(pnlTotal) >= 0 ? '#00ff88' : '#ff4466';
    const wins      = dash.trades.filter(t => t.win).length;
    const losses    = dash.trades.filter(t => !t.win).length;
    const winRate   = dash.trades.length > 0 ? ((wins / dash.trades.length) * 100).toFixed(0) : '—';
    const posHtml   = dash.openPosition
      ? `<div class="pos-box ${dash.openPosition.side === 'BUY' ? 'long' : 'short'}">
           <span class="pos-label">${dash.openPosition.side === 'BUY' ? '🟢 LONG' : '🔴 SHORT'} ${dash.openPosition.symbol}</span>
           <span>Entry: <b>$${dash.openPosition.entryPrice?.toFixed(5)}</b></span>
           <span>Qty: <b>${dash.openPosition.quantity}</b></span>
           <span>SL: <b>$${dash.openPosition.stopLoss?.toFixed(5)}</b></span>
           <span>TP: <b>$${dash.openPosition.takeProfit?.toFixed(5)}</b></span>
           <span class="${(dash.openPosition.currentPnl ?? 0) >= 0 ? 'green' : 'red'}">PnL: <b>${(dash.openPosition.currentPnl ?? 0) >= 0 ? '+' : ''}$${(dash.openPosition.currentPnl ?? 0).toFixed(4)}</b></span>
         </div>`
      : `<div class="pos-box neutral">⏳ Fără poziție deschisă — așteptăm semnal...</div>`;
    const tradesHtml = dash.trades.length === 0
      ? '<tr><td colspan="7" style="text-align:center;color:#666">Niciun trade încă</td></tr>'
      : dash.trades.map(t => `<tr class="${t.win ? 'win' : 'loss'}">
           <td>${t.time}</td><td>${t.symbol}</td>
           <td>${t.side === 'BUY' ? '🟢 LONG' : '🔴 SHORT'}</td>
           <td>$${t.entry?.toFixed(5)}</td><td>$${t.exit?.toFixed(5)}</td>
           <td>${t.win ? '+' : ''}$${t.pnl} (${t.pnlPct}%)</td>
           <td>${t.reason}</td>
         </tr>`).join('');
    const html = `<!DOCTYPE html><html lang="ro"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Apex Trade Bot Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0a0f;color:#e0e0e0;font-family:'Segoe UI',sans-serif;min-height:100vh}
header{background:linear-gradient(135deg,#1a1a2e,#16213e);padding:16px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #222}
header h1{font-size:1.2rem;background:linear-gradient(90deg,#00ff88,#00cfff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.badge{font-size:.75rem;padding:3px 10px;border-radius:20px;background:#00ff8820;color:#00ff88;border:1px solid #00ff8840}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;padding:16px}
.card{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:14px;text-align:center}
.card .val{font-size:1.4rem;font-weight:700;margin:4px 0}
.card .lbl{font-size:.72rem;color:#6b7280;text-transform:uppercase;letter-spacing:.05em}
.green{color:#00ff88}.red{color:#ff4466}.blue{color:#60a5fa}.yellow{color:#fbbf24}
.chart-wrap{margin:0 16px;border-radius:12px;overflow:hidden;border:1px solid #1f2937}
.section{padding:16px}
.section h2{font-size:.9rem;color:#6b7280;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px}
.pos-box{padding:14px;border-radius:10px;display:flex;flex-wrap:wrap;gap:10px;font-size:.88rem;margin-bottom:4px}
.pos-box.long{background:#00ff8812;border:1px solid #00ff8840}
.pos-box.short{background:#ff446612;border:1px solid #ff446640}
.pos-box.neutral{background:#1f293780;border:1px solid #374151;color:#6b7280}
.pos-label{font-weight:700;font-size:1rem;width:100%}
table{width:100%;border-collapse:collapse;font-size:.8rem}
th{color:#6b7280;font-weight:600;padding:8px 6px;border-bottom:1px solid #1f2937;text-align:left;text-transform:uppercase;letter-spacing:.05em}
td{padding:7px 6px;border-bottom:1px solid #111827}
tr.win td{color:#d1fae5}tr.loss td{color:#fee2e2}
.refresh{font-size:.7rem;color:#374151;padding:8px 16px}
@media(max-width:600px){.grid{grid-template-columns:repeat(2,1fr)}.chart-wrap{margin:0 8px}.section{padding:10px}}
</style>
<script>setTimeout(()=>location.reload(),30000)</script>
</head><body>
<header>
  <h1>⚡ Apex Trade Bot</h1>
  <span class="badge">${dash.mode} · ${dash.exchange}</span>
</header>
<div class="grid">
  <div class="card"><div class="lbl">Balanță</div><div class="val green">$${dash.balance.toFixed(2)}</div></div>
  <div class="card"><div class="lbl">PnL Total</div><div class="val" style="color:${pnlColor}">${parseFloat(pnlTotal) >= 0 ? '+' : ''}${pnlTotal}%</div></div>
  <div class="card"><div class="lbl">Trades</div><div class="val blue">${dash.trades.length}</div></div>
  <div class="card"><div class="lbl">Win Rate</div><div class="val yellow">${winRate}${winRate !== '—' ? '%' : ''}</div></div>
  <div class="card"><div class="lbl">Tick #</div><div class="val">${tickCount}</div></div>
  <div class="card"><div class="lbl">Preț Curent</div><div class="val">$${dash.currentPrice?.toFixed(4) || '—'}</div></div>
</div>
<div class="chart-wrap">
  <iframe src="https://www.tradingview.com/widgetembed/?frameElementId=tv&symbol=${tvSym}&interval=5&hidesidetoolbar=1&hidetoptoolbar=0&theme=dark&style=1&timezone=Europe%2FBucharest&withdateranges=1&hide_side_toolbar=0&allow_symbol_change=0&save_image=0&studies=RSI%401%2CMASimple%401&calendar=0&support_host=https%3A%2F%2Fwww.tradingview.com" width="100%" height="400" frameborder="0" allowtransparency="true" scrolling="no"></iframe>
</div>
<div class="section"><h2>📊 Poziție Activă</h2>${posHtml}</div>
<div class="section"><h2>📋 Istoric Tranzacții</h2>
  <div style="overflow-x:auto"><table>
    <thead><tr><th>Timp</th><th>Simbol</th><th>Tip</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Motiv</th></tr></thead>
    <tbody>${tradesHtml}</tbody>
  </table></div>
</div>
<div class="refresh">Actualizare automată la 30s · Ultimul tick: ${dash.lastTick || '—'}</div>
</body></html>`;
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(html);
  }).listen(PORT, () => logger.info(`📊 Dashboard: http://localhost:${PORT}`));

  await verifyLicense();
  logger.info('🚀 Prima analiză...');
  await tick();
  setInterval(tick, cfg.LOOP_INTERVAL_MS);
  logger.info(`⏱️  Analiză la fiecare ${cfg.LOOP_INTERVAL_MS / 60000} minute.`);
}

main().catch(err => { logger.error('Fatal: ' + err.message); process.exit(1); });
