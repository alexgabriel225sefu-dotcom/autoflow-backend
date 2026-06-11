/**
 * AI signal sanitization + state persistence tests.
 */
process.env.PAPER_TRADING = 'true';
process.env.STATE_FILE = '/tmp/apex-test-state.json';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const { sanitize } = require('../src/ai');
const state = require('../src/state');

test('sanitize: confidence non-numeric → HOLD (nu trece de gate cu NaN)', () => {
  const r = sanitize({ action: 'BUY', confidence: 'high', criteriaScore: 4 });
  assert.strictEqual(r.action, 'HOLD');
  assert.strictEqual(r.confidence, 0);
});

test('sanitize: action inventată → HOLD', () => {
  assert.strictEqual(sanitize({ action: 'YOLO', confidence: 90, criteriaScore: 5 }).action, 'HOLD');
  assert.strictEqual(sanitize(null).action, 'HOLD');
  assert.strictEqual(sanitize({}).action, 'HOLD');
});

test('sanitize: semnal valid trece neschimbat, valorile sunt limitate', () => {
  const r = sanitize({ action: 'SELL', confidence: 150, criteriaScore: 9,
                       riskLevel: 'LOW', keyFactors: ['a', 'b'] });
  assert.strictEqual(r.action, 'SELL');
  assert.strictEqual(r.confidence, 100); // clamp
  assert.strictEqual(r.criteriaScore, 5); // clamp
  assert.deepStrictEqual(r.keyFactors, ['a', 'b']);
});

test('sanitize: riskLevel invalid → MEDIUM, keyFactors non-array → []', () => {
  const r = sanitize({ action: 'BUY', confidence: 70, criteriaScore: 3,
                       riskLevel: 'EXTREME', keyFactors: 'multe' });
  assert.strictEqual(r.riskLevel, 'MEDIUM');
  assert.deepStrictEqual(r.keyFactors, []);
});

test('state: roundtrip balanță + poziție + sesiune', () => {
  state.clear();
  const pos = { side: 'BUY', symbol: 'SOLUSDT', entryPrice: 150, quantity: 0.5,
                stopLoss: 148.8, takeProfit: 152.4 };
  const session = { consecutiveLosses: 2, dailyTrades: 3, lastResetDay: new Date().toDateString() };
  state.save(97.5, pos, session);
  const loaded = state.load(100);
  assert.strictEqual(loaded.paperBalance, 97.5);
  assert.strictEqual(loaded.openPosition.symbol, 'SOLUSDT');
  assert.strictEqual(loaded.session.consecutiveLosses, 2);
  state.clear();
});

test('state: starea mai veche de 24h e ignorată', () => {
  state.clear();
  fs.writeFileSync(process.env.STATE_FILE, JSON.stringify({
    paperBalance: 50, openPosition: null,
    savedAt: new Date(Date.now() - 25 * 3600 * 1000).toISOString(),
  }));
  assert.strictEqual(state.load(100), null);
  state.clear();
});

test('state: fișier corupt nu crapă botul', () => {
  fs.writeFileSync(process.env.STATE_FILE, '{nu e json');
  assert.strictEqual(state.load(100), null);
  state.clear();
});
