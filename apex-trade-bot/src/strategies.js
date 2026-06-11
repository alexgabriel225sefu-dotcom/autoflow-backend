/**
 * APEX TRADE BOT — Legendary Traders Strategy Engine
 *
 * Implements rules from the world's most successful traders:
 *  - Paul Tudor Jones   → defense first, daily loss limits, 5:1 R:R
 *  - Jesse Livermore    → pivot points, trade with the tape, trend structure
 *  - Turtle Trading     → breakout system (Richard Dennis / William Eckhardt)
 *  - Ed Seykota         → cut losses short, let profits run, systematic rules
 *  - Stan Druckenmiller → scale position size with conviction level
 *  - George Soros       → reflexivity — momentum feeds momentum
 */

// ─── Session tracking ────────────────────────────────────────
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
    console.log('[STRATEGY] 🌅 Zi nouă — contoare reset.');
  }
}

// ─── Paul Tudor Jones + Ed Seykota: WHEN TO STOP ────────────
// "Play great defense. If you have a bad day, stop." — PTJ
// "The market is never wrong. Stop when it tells you to." — ES
function shouldStop(balance, startBalance) {
  resetDailyIfNeeded();
  const reasons = [];

  // Update peak balance
  if (!session.peakBalance || balance > session.peakBalance) {
    session.peakBalance = balance;
  }

  // Rule 1 — Ed Seykota: Stop after 3 consecutive losses
  // "A loss is a loss. Three in a row = wrong market condition. Wait."
  if (session.consecutiveLosses >= 3) {
    reasons.push(`3 pierderi consecutive — condiții nefavorabile (regula Seykota)`);
  }

  // Rule 2 — Paul Tudor Jones: Max 3% daily loss
  // "I'm always thinking about losing money rather than making money."
  const dailyDrawdownPct = (session.dailyPnL / startBalance) * 100;
  if (dailyDrawdownPct < -3) {
    reasons.push(`Pierdere zilnică depășit -3% ($${Math.abs(session.dailyPnL).toFixed(2)}) — PTJ daily stop`);
  }

  // Rule 3: Max drawdown from peak -20%
  const peakDrawdown = ((balance - session.peakBalance) / session.peakBalance) * 100;
  if (peakDrawdown < -20) {
    reasons.push(`Drawdown de la peak: ${peakDrawdown.toFixed(1)}% — stop protecție capital`);
  }

  // Rule 4 — Turtle: Max 10 trades per day (avoid overtrading)
  // "More trades ≠ more profit. Quality over quantity." — Dennis
  if (session.dailyTrades >= 10) {
    reasons.push(`Limita de 10 tranzacții/zi atinsă — Turtle rule`);
  }

  // Rule 5: Balance too low to be meaningful
  if (balance < 1) {
    reasons.push(`Balanță sub $1 — imposibil de tranzacționat`);
  }

  return { stop: reasons.length > 0, reasons };
}

// ─── Turtle Trading: BREAKOUT DETECTION ──────────────────────
// Richard Dennis: "Buy when price breaks out above 20-period high."
// William Eckhardt: "A breakout with volume is a gift."
function turtleBreakout(candles) {
  const PERIOD = 20;
  if (candles.length < PERIOD + 2) return { signal: null, high20: null, low20: null };

  const lookback  = candles.slice(-(PERIOD + 1), -1); // last N candles (not current)
  const current   = candles[candles.length - 1];
  const prev      = candles[candles.length - 2];

  const high20    = Math.max(...lookback.map(c => c.high));
  const low20     = Math.min(...lookback.map(c => c.low));
  const range     = high20 - low20;

  // Strong breakout: close above 20-period high (Turtle Long Entry)
  const buyBreakout  = current.close > high20 && prev.close <= high20;
  // Strong breakdown: close below 20-period low (Turtle Short Entry)
  const sellBreakout = current.close < low20  && prev.close >= low20;

  // Near breakout (within 0.5% of level — anticipate)
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

// ─── Jesse Livermore: MARKET STRUCTURE (Pivots) ──────────────
// "Never fight the tape. The tape tells the truth."
// "Higher highs + higher lows = buy. Lower highs + lower lows = sell."
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

  // Confirm with price velocity (last 3 closes trending)
  const closes  = last12.map(c => c.close);
  const slope   = (closes[closes.length - 1] - closes[0]) / closes[0] * 100;

  if (higherHighs && higherLows && slope > 0)  return { trend: 'BULLISH', strength: 0.85, reason: 'HH+HL structure' };
  if (lowerHighs  && lowerLows  && slope < 0)  return { trend: 'BEARISH', strength: 0.85, reason: 'LH+LL structure' };
  if (higherHighs && !higherLows)              return { trend: 'BULLISH', strength: 0.55, reason: 'HH only' };
  if (lowerLows   && !lowerHighs)              return { trend: 'BEARISH', strength: 0.55, reason: 'LL only' };

  return { trend: 'NEUTRAL', strength: 0.2, reason: 'Mixed structure' };
}

// ─── George Soros: MOMENTUM / REFLEXIVITY ────────────────────
// "Markets are reflexive — momentum feeds momentum until it collapses."
// Strong momentum in one direction = trade with it, not against it.
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

// ─── Stan Druckenmiller: POSITION SIZE MULTIPLIER ────────────
// "When you have conviction, bet big. Small positions won't change your life."
// "The key is not being right. The key is making maximum profit when right."
function druckenmillerMultiplier(confidence, criteriaScore, livermore, turtle) {
  let mult = 1.0;

  // High AI confidence + criteria
  if (confidence >= 85 && criteriaScore >= 5) mult *= 1.5;
  else if (confidence >= 80 && criteriaScore >= 4) mult *= 1.2;
  else if (confidence < 75 || criteriaScore < 3)   mult *= 0.6;

  // Turtle breakout confirmation → scale up
  if (turtle?.breakoutStr === 'STRONG') mult *= 1.3;

  // Livermore strong structure → scale up
  if (livermore?.strength >= 0.8) mult *= 1.1;

  // Cap: never exceed 2x, never below 0.4x
  return Math.min(2.0, Math.max(0.4, mult));
}

// ─── Record trade result ─────────────────────────────────────
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
    // Cooldown doar pe pierdere reală — breakeven (PnL=0) nu e revenge-trade material
    if (pnlAmount < 0) session.lastLossAt = Date.now();
  }

  const icon = won ? '✅' : '❌';
  console.log(`[STRATEGY] ${icon} Streak: ${session.consecutiveLosses} pierderi / ${session.consecutiveWins} câștiguri consecutive | Azi: ${session.dailyTrades} tranzacții | PnL zilnic: ${session.dailyPnL >= 0 ? '+' : ''}$${session.dailyPnL.toFixed(4)}`);
}

// ─── Ed Seykota: cooldown after a loss ───────────────────────
// "After a loss, the worst trade is the revenge trade."
// Returns minutes left until entries are allowed again (0 = clear).
function cooldownRemaining(cooldownMin) {
  if (!session.lastLossAt || cooldownMin <= 0) return 0;
  const elapsed = (Date.now() - session.lastLossAt) / 60000;
  return elapsed >= cooldownMin ? 0 : Math.ceil(cooldownMin - elapsed);
}

// ─── Higher-timeframe trend filter (Livermore: trade WITH the tape) ──
// EMA50 on the big timeframe: price above + EMA rising = BULLISH,
// price below + EMA falling = BEARISH, otherwise NEUTRAL (allow both).
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

// ─── Full analysis (all strategies combined) ─────────────────
function analyze(candles) {
  const turtle    = turtleBreakout(candles);
  const livermore = livermoreStructure(candles);
  const soros     = sorosMomentum(candles);
  return { turtle, livermore, soros, session: { ...session } };
}

// ─── Persistență sesiune (supraviețuiește restart-urilor) ────
// Fără asta, daily-stop / loss-streak / drawdown se resetează la fiecare
// redeploy Railway — adică exact protecțiile dispar când e instabilitate.
function sessionSnapshot() {
  return { ...session };
}

function restoreSession(saved) {
  if (!saved || typeof saved !== 'object') return;
  // Restaurează doar dacă e din aceeași zi — peste zi se resetează oricum
  if (saved.lastResetDay !== new Date().toDateString()) return;
  Object.assign(session, saved);
  console.log(`[STRATEGY] ♻️ Sesiune restaurată: ${session.consecutiveLosses} pierderi consecutive, ${session.dailyTrades} tranzacții azi`);
}

module.exports = { shouldStop, analyze, druckenmillerMultiplier, recordTrade, turtleBreakout, livermoreStructure, sorosMomentum, cooldownRemaining, htfTrend, session, sessionSnapshot, restoreSession };
