/**
 * Strategy + risk circuit-breaker tests.
 */
process.env.PAPER_TRADING = 'true';
const { test } = require('node:test');
const assert = require('node:assert');
const s = require('../src/strategies');

function candles(closes) {
  return closes.map((c, i) => ({
    time: i, open: c * 0.999, high: c * 1.001, low: c * 0.998, close: c, volume: 1000,
  }));
}

function resetSession() {
  Object.assign(s.session, {
    consecutiveLosses: 0, consecutiveWins: 0, dailyTrades: 0, dailyPnL: 0,
    dailyPnLPct: 0, lastResetDay: new Date().toDateString(),
    peakBalance: null, totalTrades: 0, lastLossAt: 0,
  });
}

test('htfTrend: uptrend susținut → BULLISH', () => {
  const up = Array.from({ length: 80 }, (_, i) => 100 + i * 0.5);
  assert.strictEqual(s.htfTrend(candles(up)), 'BULLISH');
});

test('htfTrend: downtrend susținut → BEARISH', () => {
  const down = Array.from({ length: 80 }, (_, i) => 200 - i * 0.5);
  assert.strictEqual(s.htfTrend(candles(down)), 'BEARISH');
});

test('htfTrend: date insuficiente sau lipsă → NEUTRAL (nu blochează)', () => {
  assert.strictEqual(s.htfTrend(null), 'NEUTRAL');
  assert.strictEqual(s.htfTrend(candles([1, 2, 3])), 'NEUTRAL');
});

test('cooldown: activ după pierdere reală, expiră în timp', () => {
  resetSession();
  s.recordTrade(false, -5, 1000);
  assert.ok(s.cooldownRemaining(15) > 0, 'cooldown pornit');
  s.session.lastLossAt = Date.now() - 16 * 60000;
  assert.strictEqual(s.cooldownRemaining(15), 0, 'cooldown expirat');
});

test('cooldown: breakeven (PnL=0) NU declanșează cooldown', () => {
  resetSession();
  s.recordTrade(false, 0, 1000);
  assert.strictEqual(s.cooldownRemaining(15), 0);
});

test('druckenmiller: multiplicatorul stă în [0.4, 2.0]', () => {
  const lo = s.druckenmillerMultiplier(0, 0, { strength: 0 }, { signal: null });
  const hi = s.druckenmillerMultiplier(100, 5, { strength: 1, trend: 'BULLISH' },
                                       { signal: 'BUY', breakoutStr: 'STRONG' });
  assert.ok(lo >= 0.4 && lo <= 2.0, `lo=${lo}`);
  assert.ok(hi >= 0.4 && hi <= 2.0, `hi=${hi}`);
  assert.ok(hi > lo, 'convingere mare → poziție mai mare');
});

test('shouldStop: 3 pierderi consecutive opresc trading-ul (Seykota)', () => {
  resetSession();
  for (let i = 0; i < 3; i++) s.recordTrade(false, -2, 1000);
  const r = s.shouldStop(994, 1000);
  assert.strictEqual(r.stop, true);
});

test('shouldStop: pierdere zilnică > 3% oprește (PTJ)', () => {
  resetSession();
  s.recordTrade(false, -35, 1000); // -3.5% într-un singur trade
  const r = s.shouldStop(965, 1000);
  assert.strictEqual(r.stop, true);
});

test('shouldStop: zi normală nu oprește', () => {
  resetSession();
  s.recordTrade(true, 5, 1000);
  const r = s.shouldStop(1005, 1000);
  assert.strictEqual(r.stop, false);
});

test('sesiunea se salvează și se restaurează (protecții peste restart)', () => {
  resetSession();
  s.recordTrade(false, -3, 1000);
  s.recordTrade(false, -3, 1000);
  const snap = s.sessionSnapshot();
  resetSession();
  s.restoreSession(snap);
  assert.strictEqual(s.session.consecutiveLosses, 2);
  assert.strictEqual(s.session.dailyTrades, 2);
});

test('restoreSession ignoră sesiunile din altă zi', () => {
  resetSession();
  s.restoreSession({ lastResetDay: 'Mon Jan 01 1990', consecutiveLosses: 99 });
  assert.strictEqual(s.session.consecutiveLosses, 0);
});

test('turtle: breakout peste high-ul de 20 → semnal BUY', () => {
  const flat = Array.from({ length: 25 }, () => 100);
  flat.push(103); // breakout clar
  const r = s.turtleBreakout(candles(flat));
  assert.strictEqual(r.signal, 'BUY');
});

test('analyze returnează toate componentele', () => {
  const r = s.analyze(candles(Array.from({ length: 60 }, (_, i) => 100 + Math.sin(i / 5))));
  assert.ok(r.turtle && r.livermore && r.soros && r.session);
});
