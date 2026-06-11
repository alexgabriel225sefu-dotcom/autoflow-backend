/**
 * Exchange order math — Binance LOT_SIZE/minNotional filters (pure, no network)
 * + paper P&L accounting (the formulas used in index.js).
 */
process.env.PAPER_TRADING = 'true';
const { test } = require('node:test');
const assert = require('node:assert');
const { applyFilters } = require('../src/binance');
const ind = require('../src/indicators');

// Filtre reale de pe Binance pentru SOLUSDT (stepSize 0.001, minNotional 5)
const SOL_INFO = {
  filters: [
    { filterType: 'LOT_SIZE', stepSize: '0.00100000', minQty: '0.00100000' },
    { filterType: 'NOTIONAL', minNotional: '5.00000000' },
  ],
};

test('applyFilters: 0.13456 SOL → 0.134 (stepSize 0.001, nu toFixed(0))', () => {
  const { qty, qtyStr } = applyFilters(SOL_INFO, 0.13456, 150);
  assert.strictEqual(qtyStr, '0.134');
  assert.ok(Math.abs(qty - 0.134) < 1e-9);
});

test('applyFilters: sub minQty → eroare clară, nu ordin de 0', () => {
  assert.throws(() => applyFilters(SOL_INFO, 0.0004, 150), /minQty/);
});

test('applyFilters: sub minNotional → eroare, nu respingere criptică de la exchange', () => {
  // 0.02 SOL × $150 = $3 < $5 minNotional
  assert.throws(() => applyFilters(SOL_INFO, 0.02, 150), /minim/);
});

test('applyFilters: DOGE cu stepSize 1 → unități întregi', () => {
  const DOGE_INFO = {
    filters: [
      { filterType: 'LOT_SIZE', stepSize: '1.00000000', minQty: '1.00000000' },
      { filterType: 'MIN_NOTIONAL', minNotional: '5.0' },
    ],
  };
  const { qtyStr } = applyFilters(DOGE_INFO, 123.789, 0.2);
  assert.strictEqual(qtyStr, '123');
});

// ─── Paper P&L: aceleași formule ca index.js — algebra trebuie să fie corectă ──
const FEE = 0.001;

test('paper BUY win: PnL net = mișcare − comisioane pe ambele părți', () => {
  let bal = 100;
  const entry = 100, exit = 102, qty = 0.5;
  bal -= entry * qty + entry * qty * FEE;          // open
  bal += exit * qty - exit * qty * FEE;            // close
  const pnl = (exit - entry) * qty - (entry + exit) * qty * FEE;
  assert.ok(Math.abs((bal - 100) - pnl) < 1e-9, `balanța (${bal - 100}) ≠ pnl (${pnl})`);
  assert.ok(pnl < (exit - entry) * qty, 'PnL net < PnL brut (comisioanele se simt)');
});

test('paper SELL win: short profită la scădere, net de comisioane', () => {
  let bal = 100;
  const entry = 100, exit = 98, qty = 0.5;
  bal += entry * qty - entry * qty * FEE;          // short: încasare
  bal -= exit * qty + exit * qty * FEE;            // răscumpărare
  const pnl = (entry - exit) * qty - (entry + exit) * qty * FEE;
  assert.ok(Math.abs((bal - 100) - pnl) < 1e-9);
  assert.ok(pnl > 0);
});

test('round-trip pe loc (entry = exit) pierde exact comisioanele', () => {
  const entry = 100, qty = 1;
  const pnl = 0 - (entry + entry) * qty * FEE;
  assert.ok(Math.abs(pnl - (-0.2)) < 1e-9, '0.1% × 2 părți pe $100 = -$0.20');
});

// ─── Indicatori: valori sanity pe date sintetice ───────────
function mkCandles(closes) {
  return closes.map((c, i) => ({
    time: i, open: c * 0.999, high: c * 1.002, low: c * 0.997, close: c, volume: 1000 + i,
  }));
}

test('indicators.analyze: RSI în [0,100], ATR > 0, EMA-urile ordonate pe uptrend', () => {
  const up = Array.from({ length: 250 }, (_, i) => 100 * Math.pow(1.001, i));
  const r = ind.analyze(mkCandles(up));
  const rsi = parseFloat(r.rsi);
  assert.ok(rsi >= 0 && rsi <= 100, `RSI=${rsi}`);
  assert.ok(parseFloat(r.atr) > 0);
  assert.ok(parseFloat(r.ema20) > parseFloat(r.ema50), 'uptrend: EMA20 > EMA50');
  assert.strictEqual(r.emaTrend, 'BULLISH');
});

test('indicators.analyze: downtrend → emaTrend BEARISH, RSI scăzut', () => {
  const down = Array.from({ length: 250 }, (_, i) => 200 * Math.pow(0.999, i));
  const r = ind.analyze(mkCandles(down));
  assert.strictEqual(r.emaTrend, 'BEARISH');
  assert.ok(parseFloat(r.rsi) < 50);
});
