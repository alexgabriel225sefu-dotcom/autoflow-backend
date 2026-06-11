/**
 * Exit engine tests — SL/TP, breakeven, trailing, runner mode.
 * Run: node --test tests/
 */
process.env.PAPER_TRADING = 'true';
const { test } = require('node:test');
const assert = require('node:assert');
const { calcSLTP, checkPosition } = require('../src/position');
const cfg = require('../src/config');

function freshPos(side = 'BUY', entry = 100) {
  const { stopLoss, takeProfit } = calcSLTP(side, entry, 0);
  return {
    side, entryPrice: entry, quantity: 1, stopLoss, takeProfit,
    initialStop: stopLoss,
    trailHigh: side === 'BUY' ? entry : null,
    trailLow: side === 'SELL' ? entry : null,
  };
}

test('calcSLTP: BUY are SL sub și TP peste entry, R:R = 2', () => {
  const { stopLoss, takeProfit } = calcSLTP('BUY', 100, 0);
  assert.ok(stopLoss < 100 && takeProfit > 100);
  const rr = (takeProfit - 100) / (100 - stopLoss);
  assert.ok(Math.abs(rr - cfg.TAKE_PROFIT_PCT / cfg.STOP_LOSS_PCT) < 0.01, `R:R = ${rr}`);
});

test('calcSLTP: SELL e oglindit', () => {
  const { stopLoss, takeProfit } = calcSLTP('SELL', 100, 0);
  assert.ok(stopLoss > 100 && takeProfit < 100);
});

test('calcSLTP: ATR-based folosește multiplii configurați', () => {
  const old = cfg.ATR_BASED_SL;
  cfg.ATR_BASED_SL = true;
  const { stopLoss, takeProfit } = calcSLTP('BUY', 100, 2);
  assert.strictEqual(stopLoss, 100 - 2 * cfg.ATR_SL_MULT);
  assert.strictEqual(takeProfit, 100 + 2 * cfg.ATR_TP_MULT);
  cfg.ATR_BASED_SL = old;
});

test('SL hit pe BUY închide cu STOP_LOSS', () => {
  const pos = freshPos('BUY');
  assert.strictEqual(checkPosition(pos, pos.stopLoss - 0.01), 'STOP_LOSS');
});

test('breakeven: la +1R SL se mută peste entry', () => {
  const pos = freshPos('BUY', 100);
  const oneR = 100 - pos.initialStop;
  checkPosition(pos, 100 + oneR * 1.05);
  assert.strictEqual(pos.beDone, true);
  assert.ok(pos.stopLoss >= 100, `SL ${pos.stopLoss} trebuie >= entry`);
});

test('breakeven nu se mută înainte de +1R', () => {
  const pos = freshPos('BUY', 100);
  const oneR = 100 - pos.initialStop;
  checkPosition(pos, 100 + oneR * 0.5);
  assert.ok(!pos.beDone);
});

test('runner mode: la TP pe paper nu închide, trecere pe trail strâns', () => {
  const pos = freshPos('BUY', 100);
  const trigger = checkPosition(pos, pos.takeProfit + 0.01);
  assert.strictEqual(trigger, null);
  assert.strictEqual(pos.runner, true);
});

test('runner: trail hit returnează TRAIL_PROFIT (profit, nu pierdere)', () => {
  const pos = freshPos('BUY', 100);
  checkPosition(pos, pos.takeProfit + 0.5);     // intră în runner
  const peak = pos.takeProfit + 2;
  checkPosition(pos, peak);                     // trail urcă după preț
  const trigger = checkPosition(pos, peak * (1 - cfg.RUNNER_TRAIL_DIST) - 0.01);
  assert.strictEqual(trigger, 'TRAIL_PROFIT');
  assert.ok(pos.stopLoss > pos.entryPrice, 'iese pe profit');
});

test('trailing pe BUY nu coboară niciodată SL-ul', () => {
  const pos = freshPos('BUY', 100);
  checkPosition(pos, 101);
  const sl1 = pos.stopLoss;
  checkPosition(pos, 100.2); // preț scade
  assert.ok(pos.stopLoss >= sl1, 'SL nu are voie să coboare');
});

test('trailing pe SELL nu urcă niciodată SL-ul', () => {
  const pos = freshPos('SELL', 100);
  checkPosition(pos, 99);
  const sl1 = pos.stopLoss;
  checkPosition(pos, 99.8);
  assert.ok(pos.stopLoss <= sl1);
});

test('pnlPct se calculează corect pe ambele direcții', () => {
  const buy = freshPos('BUY', 100);
  checkPosition(buy, 101);
  assert.ok(Math.abs(buy.pnlPct - 1) < 0.01);
  const sell = freshPos('SELL', 100);
  checkPosition(sell, 99);
  assert.ok(Math.abs(sell.pnlPct - 1) < 0.01);
});
