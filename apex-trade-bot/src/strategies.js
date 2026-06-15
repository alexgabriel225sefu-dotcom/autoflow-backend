/**
 * APEX TRADE BOT — Legendary Traders Strategy Engine
 */

const session = {
  consecutiveLosses: 0,
  consecutiveWins:   0,
  dailyTrades:       0,
  dailyPnL:          0,
  dailyPnLPct:       0,
  lastResetDay:      new Date().toDateString(),
  peakBalance:       null,
  totalTrades:       0,
  lastLossAt:        0,
};

function resetDailyIfNeeded() {
  const today = new Date().toDateString();
  if (session.lastResetDay !== today) {
    session.dailyTrades = 0;
    session.dailyPnL    = 0;
    session.dailyPnLPct = 0;
    session.lastResetDay = today;
    console.log('[STRATEGY] 🌅 New day — counters reset.');
  }
}

function shouldStop(balance, startBalance) {
  resetDailyIfNeeded();
  const reasons = [];

  if (!session.peakBalance || balance > session.peakBalance) {
    session.peakBalance = balance;
  }

  if (session.consecutiveLosses >= 3) {
    reasons.push(`3 consecutive losses — unfavorable conditions (Seykota rule)`);
  }

  const dailyDrawdownPct = (session.dailyPnL / startBalance) * 100;
  if (dailyDrawdownPct < -3) {
    reasons.push(`Daily loss exceeded -3% ($${Math.abs(session.dailyPnL).toFixed(2)}) — PTJ daily stop`);
  }

  const peakDrawdown = ((balance - session.peakBalance) / session.peakBalance) * 100;
  if (peakDrawdown < -20) {
    reasons.push(`Drawdown from peak: ${peakDrawdown.toFixed(1)}% — capital protection stop`);
  }

  if (session.dailyTrades >= 10) {
    reasons.push(`Daily trade limit of 10 reached — Turtle rule`);
  }

  if (balance < 1) {
    reasons.push(`Balance below $1 — cannot trade`);
  }

  return { stop: reasons.length > 0, reasons };
}

function turtleBreakout(candles) {
  const PERIOD = 20;
  if (candles.length < PERIOD + 2) return { signal: null, high20: null, low20: null };

  const lookback  = candles.slice(-(PERIOD + 1), -1);
  const current   = candles[candles.length - 1];
  const prev      = candles[candles.length - 2];

  const high20    = Math.max(...lookback.map(c => c.high));
  const low20     = Math.min(...lookback.map(c => c.low));
  const range     = high20 - low20;

  const buyBreakout  = current.close > high20 && prev.close <= high20;
  const sellBreakout = current.close < low20  && prev.close >= low20;

  const nearHigh  = current.close > high20 * 0.995 && !buyBreakout;
  const nearLow   = current.close < low20  * 1.005 && !sellBreakout;

  return {
    signal:     buyBreakout ? 'BUY' : sellBreakout ? 'SELL' : null,
    nearSignal: nearHigh    ? 'BUY' : nearLow      ? 'SELL' : null,
    high20:     parseFloat(high20.toFixed(6)),
    low20:      parseFloat(low20.toFixed(6)),
    range:      parseFloat(range.toFixed(6)),
    breakoutStr: buyBreakout || sellBreakout ? 'STRONG' : nearHigh || nearLow ? 'NEAR' : 'NONE',
  };
}

function livermoreStructure(candles) {
  if (candles.length < 12) return { trend: 'NEUTRAL', strength: 0 };

  const last12 = candles.slice(-12);
  const half1  = last12.slice(0, 6);
  const half2  = last12.slice(6);

  const h1High = Math.max(...half1.map(c => c.high));
  const h2High = Math.max(...half2.map(c => c.high));
  const h1Low  = Math.min(...half1.map(c => c.low));
  const h2Low  = Math.min(...half2.map(c => c.low));

  const higherHighs = h2High > h1High;
  const higherLows  = h2Low  > h1Low;
  const lowerHighs  = h2High < h1High;
  const lowerLows   = h2Low  < h1Low;

  const closes  = last12.map(c => c.close);
  const slope   = (closes[closes.length - 1] - closes[0]) / closes[0] * 100;

  if (higherHighs && higherLows && slope > 0)  return { trend: 'BULLISH', strength: 0.85, reason: 'HH+HL structure' };
  if (lowerHighs  && lowerLows  && slope < 0)  return { trend: 'BEARISH', strength: 0.85, reason: 'LH+LL structure' };
  if (higherHighs && !higherLows)              return { trend: 'BULLISH', strength: 0.55, reason: 'HH only' };
  if (lowerLows   && !lowerHighs)              return { trend: 'BEARISH', strength: 0.55, reason: 'LL only' };

  return { trend: 'NEUTRAL', strength: 0.2, reason: 'Mixed structure' };
}

function sorosMomentum(candles) {
  if (candles.length < 8) return { momentum: 0, direction: 'NEUTRAL' };

  const recent = candles.slice(-8);
  const wins   = recent.filter(c => c.close > c.open).length;
  const bullPct = wins / recent.length;

  const closes = recent.map(c => c.close);
  const velocity = (closes[closes.length - 1] - closes[0]) / closes[0] * 100;

  if (bullPct >= 0.75 && velocity > 0.3) return { momentum: bullPct, direction: 'BULLISH', velocity };
  if (bullPct <= 0.25 && velocity < -0.3) return { momentum: 1 - bullPct, direction: 'BEARISH', velocity };
  return { momentum: 0.5, direction: 'NEUTRAL', velocity };
}

function druckenmillerMultiplier(confidence, criteriaScore, livermore, turtle) {
  let mult = 1.0;

  if (confidence >= 85 && criteriaScore >= 5) mult *= 1.5;
  else if (confidence >= 80 && criteriaScore >= 4) mult *= 1.2;
  else if (confidence < 75 || criteriaScore < 3)   mult *= 0.6;

  if (turtle?.breakoutStr === 'STRONG') mult *= 1.3;
  if (livermore?.strength >= 0.8) mult *= 1.1;

  return Math.min(2.0, Math.max(0.4, mult));
}

function recordTrade(won, pnlAmount, startBalance) {
  session.totalTrades++;
  session.dailyTrades++;
  session.dailyPnL += pnlAmount;
  session.dailyPnLPct = (session.dailyPnL / startBalance) * 100;

  if (won) {
    session.consecutiveWins++;
    session.consecutiveLosses = 0;
  } else {
    session.consecutiveLosses++;
    session.consecutiveWins = 0;
    if (pnlAmount < 0) session.lastLossAt = Date.now();
  }

  const icon = won ? '✅' : '❌';
  console.log(`[STRATEGY] ${icon} Streak: ${session.consecutiveLosses} losses / ${session.consecutiveWins} wins consecutive | Today: ${session.dailyTrades} trades | Daily PnL: ${session.dailyPnL >= 0 ? '+' : ''}$${session.dailyPnL.toFixed(4)}`);
}

function cooldownRemaining(cooldownMin) {
  if (!session.lastLossAt || cooldownMin <= 0) return 0;
  const elapsed = (Date.now() - session.lastLossAt) / 60000;
  return elapsed >= cooldownMin ? 0 : Math.ceil(cooldownMin - elapsed);
}

function htfTrend(candles) {
  if (!candles || candles.length < 55) return 'NEUTRAL';
  const closes = candles.map(c => c.close);
  const k = 2 / (50 + 1);
  let ema = closes.slice(0, 50).reduce((a, b) => a + b, 0) / 50;
  let emaPrev = ema;
  for (let i = 50; i < closes.length; i++) {
    emaPrev = ema;
    ema = closes[i] * k + ema * (1 - k);
  }
  const price = closes[closes.length - 1];
  if (price > ema && ema >= emaPrev) return 'BULLISH';
  if (price < ema && ema <= emaPrev) return 'BEARISH';
  return 'NEUTRAL';
}

function analyze(candles) {
  const turtle    = turtleBreakout(candles);
  const livermore = livermoreStructure(candles);
  const soros     = sorosMomentum(candles);
  return { turtle, livermore, soros, session: { ...session } };
}

function sessionSnapshot() {
  return { ...session };
}

function restoreSession(saved) {
  if (!saved || typeof saved !== 'object') return;
  if (saved.lastResetDay !== new Date().toDateString()) return;
  Object.assign(session, saved);
  console.log(`[STRATEGY] ♻️ Session restored: ${session.consecutiveLosses} consecutive losses, ${session.dailyTrades} trades today`);
}

module.exports = { shouldStop, analyze, druckenmillerMultiplier, recordTrade, turtleBreakout, livermoreStructure, sorosMomentum, cooldownRemaining, htfTrend, session, sessionSnapshot, restoreSession };
