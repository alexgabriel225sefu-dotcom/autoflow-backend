/**
 * Per-user trading runner — extracted + parameterized from index.js.
 * Uses a UserContext object instead of global module-level variables.
 * Called by botManager once per interval tick per active user.
 */
const indicators = require('./indicators');
const ai         = require('./ai');
const strategies = require('./strategies');

const TIMEFRAME = '5m';
const CANDLES   = 200;
const FEE_PCT   = 0.001;

// ─── Per-user session helpers ─────────────────────────────────
function resetDay(s) {
  const today = new Date().toDateString();
  if (s.lastResetDay !== today) { s.dailyTrades = 0; s.dailyPnL = 0; s.lastResetDay = today; }
}

function shouldStop(s, balance, start) {
  resetDay(s);
  if (!s.peakBalance || balance > s.peakBalance) s.peakBalance = balance;
  const r = [];
  if (s.consecutiveLosses >= 3)                              r.push('3 consecutive losses — Seykota');
  if ((s.dailyPnL / (start || 100)) * 100 < -3)             r.push('Daily loss >3% — PTJ stop');
  if (((balance - s.peakBalance) / s.peakBalance) * 100 < -20) r.push('Drawdown >20%');
  if (s.dailyTrades >= 10)                                   r.push('10 trades/day — Turtle rule');
  return { stop: r.length > 0, reasons: r };
}

function cooldown(s, minutes) {
  if (!s.lastLossAt) return 0;
  return Math.max(0, minutes - (Date.now() - s.lastLossAt) / 60000);
}

function recordTrade(s, win, pnl) {
  resetDay(s);
  s.dailyTrades++;
  s.dailyPnL += pnl;
  if (win) { s.consecutiveWins++; s.consecutiveLosses = 0; }
  else     { s.consecutiveLosses++; s.consecutiveWins = 0; s.lastLossAt = Date.now(); }
}

// ─── Position management ──────────────────────────────────────
function calcSLTP(side, price, cfg) {
  const sl = cfg.STOP_LOSS_PCT   || 0.016;
  const tp = cfg.TAKE_PROFIT_PCT || 0.032;
  return side === 'BUY'
    ? { stopLoss: price * (1 - sl), takeProfit: price * (1 + tp) }
    : { stopLoss: price * (1 + sl), takeProfit: price * (1 - tp) };
}

function checkExit(pos, price) {
  if (!pos) return null;
  if (pos.side === 'BUY'  && price <= pos.stopLoss)   return 'STOP_LOSS';
  if (pos.side === 'BUY'  && price >= pos.takeProfit) return 'TAKE_PROFIT';
  if (pos.side === 'SELL' && price >= pos.stopLoss)   return 'STOP_LOSS';
  if (pos.side === 'SELL' && price <= pos.takeProfit) return 'TAKE_PROFIT';
  return null;
}

// ─── Trade execution ──────────────────────────────────────────
async function openTrade(ctx, side, price, druckMult) {
  const { state, settings, exchange } = ctx;
  const symbol = settings.SYMBOL;
  const risk   = (settings.RISK_PER_TRADE || 0.05) * druckMult;
  const qty    = parseFloat(((state.paperBalance * risk) / price).toFixed(6));
  if (qty <= 0) return;

  const order    = await exchange.placeOrder(side, qty, symbol);
  const fill     = order?.avgPrice || price;
  const fillQty  = order?.executedQty || qty;
  const fee      = fill * fillQty * FEE_PCT;

  if (side === 'BUY') state.paperBalance -= fill * fillQty + fee;
  else                state.paperBalance += fill * fillQty - fee;

  const { stopLoss, takeProfit } = calcSLTP(side, fill, settings);
  state.openPosition = {
    symbol, side, entryPrice: fill, quantity: fillQty,
    stopLoss, takeProfit, openedAt: new Date().toISOString(), pnlPct: 0,
  };

  ctx.alertFn('trade_open', { side, symbol, price: fill, qty: fillQty, stopLoss, takeProfit, druckMult });
}

async function closeTrade(ctx, price, reason) {
  const { state, settings, exchange } = ctx;
  if (!state.openPosition) return;
  const { side, entryPrice, quantity, symbol } = state.openPosition;

  const order   = await exchange.placeOrder(side === 'BUY' ? 'SELL' : 'BUY', quantity, symbol);
  const fill    = order?.avgPrice || price;
  const feeBoth = (entryPrice + fill) * quantity * FEE_PCT;
  let   pnl     = (side === 'BUY' ? fill - entryPrice : entryPrice - fill) * quantity - feeBoth;

  if (side === 'BUY') state.paperBalance += fill * quantity * (1 - FEE_PCT);
  else                state.paperBalance -= fill * quantity * (1 + FEE_PCT);

  recordTrade(state.session, pnl > 0, pnl);

  // Increment usage trade counter
  try {
    const userStore = require('./userStore');
    const u2 = userStore.load(ctx.userId);
    if (!u2.usage) u2.usage = { totalTicks: 0, totalTrades: 0, lastActiveAt: null };
    u2.usage.totalTrades++;
    userStore.save(ctx.userId, u2);
  } catch {}

  state.trades.unshift({
    time: new Date().toLocaleString('en-US'), symbol, side,
    entry: entryPrice, exit: fill, qty: quantity,
    pnl:    parseFloat(pnl.toFixed(4)),
    pnlPct: parseFloat(((pnl / (entryPrice * quantity)) * 100).toFixed(2)),
    reason, win: pnl > 0,
  });
  if (state.trades.length > 50) state.trades.pop();
  state.openPosition = null;

  ctx.alertFn('trade_close', { side, symbol, entryPrice, exitPrice: fill, pnl, balance: state.paperBalance, reason });
}

// ─── Main tick ────────────────────────────────────────────────
async function tick(ctx) {
  if (ctx.ticking) return;
  ctx.ticking = true;
  ctx.state.tickCount = (ctx.state.tickCount || 0) + 1;

  // Usage tracking — evidence for Stripe dispute resolution
  const userStore = require('./userStore');
  const u = userStore.load(ctx.userId);
  if (!u.usage) u.usage = { totalTicks: 0, totalTrades: 0, lastActiveAt: null };
  u.usage.totalTicks++;
  u.usage.lastActiveAt = new Date().toISOString();
  userStore.save(ctx.userId, u);

  try {
    const { state, settings, exchange } = ctx;
    if (settings.PAUSED) return;

    const symbol = state.openPosition?.symbol ?? settings.SYMBOL;
    state.currentSymbol = symbol;

    const [candles, price] = await Promise.all([
      exchange.getCandles(symbol, TIMEFRAME, CANDLES),
      exchange.getPrice(symbol),
    ]);
    state.currentPrice = price;
    state.lastTick     = new Date().toLocaleString('en-US');

    if (state.openPosition) {
      const pnl = state.openPosition.side === 'BUY'
        ? (price - state.openPosition.entryPrice) * state.openPosition.quantity
        : (state.openPosition.entryPrice - price) * state.openPosition.quantity;
      state.openPosition.currentPnl = parseFloat(pnl.toFixed(4));
      state.openPosition.pnlPct     = parseFloat(((pnl / (state.openPosition.entryPrice * state.openPosition.quantity)) * 100).toFixed(2));
    }

    if (ctx.state.tickCount % 6 === 0) {
      ctx.alertFn('heartbeat', { tickCount: ctx.state.tickCount, balance: state.paperBalance, openPosition: state.openPosition, symbol });
    }

    const exit = checkExit(state.openPosition, price);
    if (exit) { await closeTrade(ctx, price, exit); return; }

    const stop = shouldStop(state.session, state.paperBalance, state.startBalance);
    if (stop.stop) { ctx.alertFn('strategy_stop', { reasons: stop.reasons }); return; }
    if (state.paperBalance < 1) return;

    const ind       = indicators.analyze(candles);
    ind.symbol      = symbol; // needed for per-symbol signal cache
    const stratData = strategies.analyze(candles);
    stratData.session = { ...state.session };

    const userGroqKey = ctx.userData?.groqKeyDec || null;
    let signal;
    try {
      signal = await ai.getSignal(ind, state.paperBalance, state.openPosition, stratData, userGroqKey);
    } catch (e) {
      if (e.userKey) {
        const msg = e.message === 'GROQ_KEY_INVALID'
          ? `⚠️ <b>Your Groq API key is invalid.</b>\nGet a new free key at <b>console.groq.com</b> → API Keys, then send /groq gsk_NEW_KEY`
          : `⚠️ <b>Your Groq API key hit the free limit.</b>\nGet a new free key at <b>console.groq.com</b> → API Keys, then send /groq gsk_NEW_KEY`;
        ctx.alertFn('groq_error', { msg });
        signal = ai.ruleBasedFallback(ind, state.openPosition);
      } else throw e;
    }
    state.lastSignal = {
      action: signal.action, confidence: signal.confidence,
      criteriaScore: signal.criteriaScore, reasoning: signal.reasoning,
      time: new Date().toLocaleTimeString('en-US'),
    };

    const confOk = signal.confidence >= (settings.MIN_CONFIDENCE ?? 62);
    const critOk = (signal.criteriaScore ?? 0) >= (settings.MIN_CRITERIA ?? 3);
    const volOk  = parseFloat(ind.volumeRatio) >= 0.7;

    const druckMult = !state.openPosition
      ? strategies.druckenmillerMultiplier(signal.confidence, signal.criteriaScore, stratData.livermore, stratData.turtle)
      : 1.0;

    const mode = settings.STRATEGY_MODE || 'auto';
    if (mode !== 'auto' && !state.openPosition && (signal.action === 'BUY' || signal.action === 'SELL')) {
      const blocked =
        (mode === 'turtle'       && !stratData.turtle.signal) ||
        (mode === 'livermore'    && !((stratData.livermore.trend === 'BULLISH' && signal.action === 'BUY') || (stratData.livermore.trend === 'BEARISH' && signal.action === 'SELL'))) ||
        (mode === 'soros'        && !((stratData.soros.direction === 'BULLISH' && signal.action === 'BUY') || (stratData.soros.direction === 'BEARISH' && signal.action === 'SELL'))) ||
        (mode === 'ptj'          && (signal.confidence < 85 || signal.criteriaScore < 4));
      if (blocked) signal.action = 'HOLD';
    }

    const ls = stratData.livermore.strength ?? 0;
    const lt = stratData.livermore.trend;
    const ts = stratData.turtle.signal;
    const contra = lt === 'BEARISH' && ts === 'SELL' ? 'BUY' : lt === 'BULLISH' && ts === 'BUY' ? 'SELL' : null;
    if (!state.openPosition && ls >= 0.8 && signal.action === contra) signal.action = 'HOLD';

    if (!state.openPosition && cooldown(state.session, 15) > 0 && (signal.action === 'BUY' || signal.action === 'SELL')) signal.action = 'HOLD';

    if (!confOk || !critOk || signal.action === 'HOLD') { /* hold */ }
    else if (signal.action === 'CLOSE' && state.openPosition) await closeTrade(ctx, price, 'AI_CLOSE');
    else if ((signal.action === 'BUY' || signal.action === 'SELL') && !state.openPosition && volOk) {
      await openTrade(ctx, signal.action, price, druckMult);
    }

  } catch (err) {
    console.error(`[Runner:${ctx.userId}] Tick error:`, err.message);
  } finally {
    ctx.ticking = false;
  }
}

function createContext(userId, userData, exchange, alertFn) {
  const userStore = require('./userStore');
  const groqKeyDec = userData.groqKey ? userStore.decrypt(userData.groqKey) : null;
  return {
    userId,
    exchange,
    settings: userData.settings,
    state:    userData.state,
    userData: { groqKeyDec },
    ticking:  false,
    alertFn,
  };
}

module.exports = { tick, createContext };
