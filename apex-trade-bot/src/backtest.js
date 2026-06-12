// ─── Backtest pe STRATEGIA REALĂ (nu un proxy diferit) ───────────────────────
// Rulare:  node src/backtest.js
//          BT_SYMBOL=XRPUSDT BT_TIMEFRAME=5m BT_CANDLES=1000 node src/backtest.js
//          BT_SYNTHETIC=true node src/backtest.js   (fără internet — doar validare motor)
//
// Ce simulează FIDEL:  rubrica de criterii din promptul AI (calculată mecanic),
//   gate-urile MIN_CRITERIA/MIN_VOLUME_RATIO, filtrul de trend 1h, veto-ul
//   Livermore+Turtle, cooldown după pierdere, sizing Druckenmiller, și exiturile
//   REALE din src/position.js (SL/TP/breakeven/trailing/runner) evaluate la close
//   de lumânare — exact cum face botul live la fiecare tick. Comisioane 0.1%/parte
//   + slippage pe intrare/ieșire.
// Ce NU simulează:  judecata LLM-ului. AI-ul poate respinge trade-uri pe care
//   rubrica le-ar lua (e un filtru în plus), deci live-ul ia DE REGULĂ mai puține
//   trade-uri decât acest backtest. Rezultatele NU sunt o promisiune de profit.

require('dotenv').config();
const indicators = require('./indicators');
const strategies = require('./strategies');
const logger     = require('./logger');
const cfg        = require('./config');
const { calcSLTP, checkPosition } = require('./position');

const SYMBOL    = process.env.BT_SYMBOL    || cfg.SYMBOL;
const TIMEFRAME = process.env.BT_TIMEFRAME || cfg.TIMEFRAME;
const CANDLES   = parseInt(process.env.BT_CANDLES || '1000');
const START_BAL = parseFloat(process.env.BT_BALANCE || '100');
const SLIPPAGE  = parseFloat(process.env.BT_SLIPPAGE || '0.0005'); // 0.05%/parte
const SYNTHETIC = process.env.BT_SYNTHETIC === 'true';

logger.info = () => {}; // fără spam de breakeven/runner pe mii de lumânări

// ─── Rubrica de criterii — identică cu cea cerută AI-ului în prompt ──────────
function criteriaSignal(ind, strat) {
  const rsi = parseFloat(ind.rsi), macdH = parseFloat(ind.macdHist);
  const volR = parseFloat(ind.volumeRatio), price = parseFloat(ind.price);
  const ema20 = parseFloat(ind.ema20);
  const bonus = (dir) =>
    (strat.turtle.breakoutStr === 'STRONG' && strat.turtle.signal === dir) ||
    (strat.livermore.trend === (dir === 'BUY' ? 'BULLISH' : 'BEARISH') && strat.livermore.strength >= 0.5) ||
    (strat.soros.direction === (dir === 'BUY' ? 'BULLISH' : 'BEARISH')) ? 1 : 0;

  let buy = 0;
  if (ind.emaTrend === 'BULLISH') buy++;
  if (rsi < 50 || ind.divergence === 'BULLISH') buy++;
  if (macdH > 0) buy++;
  if (volR > 1.2) buy++;
  if (price < ema20) buy++;
  buy += bonus('BUY');

  let sell = 0;
  if (ind.emaTrend === 'BEARISH') sell++;
  if (rsi > 50 || ind.divergence === 'BEARISH') sell++;
  if (macdH < 0) sell++;
  if (volR > 1.2) sell++;
  if (price > ema20) sell++;
  sell += bonus('SELL');

  const minC = parseInt(process.env.MIN_CRITERIA || '5');
  if (buy >= minC && buy > sell) return { action: 'BUY', criteriaScore: Math.min(5, buy) };
  if (sell >= minC && sell > buy) return { action: 'SELL', criteriaScore: Math.min(5, sell) };
  return { action: 'HOLD', criteriaScore: 0 };
}

// 5m → 1h pentru filtrul HTF (12 lumânări de 5m = 1h)
function resample1h(candles, ratio = 12) {
  const out = [];
  for (let i = 0; i + ratio <= candles.length; i += ratio) {
    const grp = candles.slice(i, i + ratio);
    out.push({
      time: grp[0].time, open: grp[0].open, close: grp[grp.length - 1].close,
      high: Math.max(...grp.map(c => c.high)), low: Math.min(...grp.map(c => c.low)),
      volume: grp.reduce((a, c) => a + c.volume, 0),
    });
  }
  return out;
}

// Date sintetice cu seed — DOAR pentru validarea motorului, nu pentru concluzii
function syntheticCandles(n) {
  let seed = 42;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31;
  const out = []; let p = 100, drift = 0;
  for (let i = 0; i < n; i++) {
    if (i % 200 === 0) drift = (rnd() - 0.5) * 0.0015; // regimuri de trend
    const ret = drift + (rnd() - 0.5) * 0.006;
    const o = p; p = Math.max(1, p * (1 + ret));
    out.push({ time: i, open: o, close: p,
               high: Math.max(o, p) * (1 + rnd() * 0.002),
               low: Math.min(o, p) * (1 - rnd() * 0.002),
               volume: 800 + rnd() * 600 });
  }
  return out;
}

// OKX public, paginat — singura sursă publică ne-geo-blocată care dă istoric lung
// (Binance răspunde 451 din cloud US/EU; OKX /candles max 300, /history-candles max 100)
async function fetchOKXPaginated(symbol, bar, total) {
  const axios = require('axios');
  const instId = symbol.replace('USDT', '-USDT');
  const opts = { headers: { 'User-Agent': 'ApexTradeBot/2.0' }, timeout: 10000 };
  const parse = rows => rows.map(k => ({
    time: parseInt(k[0]), open: parseFloat(k[1]), high: parseFloat(k[2]),
    low: parseFloat(k[3]), close: parseFloat(k[4]), volume: parseFloat(k[5]),
  }));
  const { data } = await axios.get('https://www.okx.com/api/v5/market/candles',
    { ...opts, params: { instId, bar, limit: 300 } });
  if (data.code !== '0') throw new Error('OKX: ' + data.msg);
  let candles = parse(data.data); // newest-first
  while (candles.length < total) {
    const oldest = candles[candles.length - 1].time;
    const { data: h } = await axios.get('https://www.okx.com/api/v5/market/history-candles',
      { ...opts, params: { instId, bar, after: oldest, limit: 100 } });
    if (h.code !== '0' || !h.data?.length) break;
    candles = candles.concat(parse(h.data));
    await new Promise(r => setTimeout(r, 250)); // rate limit OKX: 10 req/2s
  }
  return candles.reverse(); // vechi → nou, cum așteaptă indicatorii
}

async function fetchCandles() {
  if (SYNTHETIC) return syntheticCandles(CANDLES + 200);
  const want = CANDLES + 250;
  const exchange = require('./exchange');
  let candles = [];
  try { candles = await exchange.getCandles(SYMBOL, TIMEFRAME, Math.min(want, 1000)); } catch {}
  if (candles.length < Math.min(want, 600)) {
    console.log(`[DATA] Doar ${candles.length} lumânări de la exchange — paginez OKX pentru istoric complet...`);
    candles = await fetchOKXPaginated(SYMBOL, TIMEFRAME, want);
  }
  console.log(`[DATA] ${candles.length} lumânări reale încărcate`);
  return candles;
}

async function runBacktest() {
  const FEE = cfg.FEE_PCT;
  console.log('\n' + '═'.repeat(64));
  console.log('  📊 APEX BACKTEST — strategia reală (rubrică AI + filtre + exituri live)');
  console.log(`  ${SYNTHETIC ? '⚠️  DATE SINTETICE — validare motor, NU concluzii de profit' : `Symbol: ${SYMBOL} | TF: ${TIMEFRAME}`}`);
  console.log(`  Balanță: $${START_BAL} | SL ${cfg.STOP_LOSS_PCT * 100}% | TP ${cfg.TAKE_PROFIT_PCT * 100}% | fee ${FEE * 100}%/parte | slippage ${SLIPPAGE * 100}%/parte`);
  console.log('═'.repeat(64));

  const all = await fetchCandles();
  if (all.length < 300) throw new Error(`Doar ${all.length} lumânări — minim 300`);

  let balance = START_BAL, position = null, lastLossIdx = -1e9;
  const trades = [];
  const cooldownBars = Math.ceil(cfg.COOLDOWN_AFTER_LOSS_MIN / 5);
  let equityPeak = START_BAL, maxDD = 0, feesPaid = 0;

  const close = (exitRaw, reason, i) => {
    const dir = position.side === 'BUY' ? 1 : -1;
    const exit = exitRaw * (1 - dir * SLIPPAGE);
    const fee = (position.entryPrice + exit) * position.quantity * FEE;
    const pnl = dir * (exit - position.entryPrice) * position.quantity - fee;
    feesPaid += fee;
    balance += pnl;
    trades.push({ side: position.side, entry: position.entryPrice, exit, pnl, reason, bars: i - position.openedAt });
    if (pnl < 0) lastLossIdx = i;
    position = null;
    equityPeak = Math.max(equityPeak, balance);
    maxDD = Math.max(maxDD, (equityPeak - balance) / equityPeak);
  };

  for (let i = 250; i < all.length; i++) {
    const window = all.slice(0, i + 1);
    const price = all[i].close;

    if (position) {
      const trigger = checkPosition(position, price);
      if (trigger) { close(price, trigger, i); continue; }
    }
    if (position || balance < 1) continue;
    if (i - lastLossIdx < cooldownBars) continue;            // cooldown după pierdere

    const ind = indicators.analyze(window);
    const strat = strategies.analyze(window);
    const sig = criteriaSignal(ind, strat);
    if (sig.action === 'HOLD') continue;
    if (parseFloat(ind.volumeRatio) < parseFloat(process.env.MIN_VOLUME_RATIO || '0.7')) continue;

    // Veto Livermore+Turtle (identic cu live)
    const contra = strat.livermore.trend === 'BEARISH' && strat.turtle.signal === 'SELL' ? 'BUY'
                 : strat.livermore.trend === 'BULLISH' && strat.turtle.signal === 'BUY' ? 'SELL' : null;
    if ((strat.livermore.strength ?? 0) >= 0.8 && sig.action === contra) continue;

    // Filtru HTF 1h (identic cu live). BT_HTF_STRICT: intră DOAR pe direcția
    // trendului mare (NEUTRAL = stai pe mâini), nu doar blochează contra-trend.
    if (cfg.HTF_FILTER) {
      const ratio = TIMEFRAME === '15m' ? 4 : TIMEFRAME === '1h' ? 1 : 12;
      const htf = ratio === 1 ? strategies.htfTrend(window.slice(-80))
                              : strategies.htfTrend(resample1h(window.slice(-60 * ratio), ratio));
      if (process.env.BT_HTF_STRICT === 'true') {
        if (htf !== (sig.action === 'BUY' ? 'BULLISH' : 'BEARISH')) continue;
      } else if ((sig.action === 'BUY' && htf === 'BEARISH') || (sig.action === 'SELL' && htf === 'BULLISH')) {
        continue;
      }
    }

    const mult = strategies.druckenmillerMultiplier(70, sig.criteriaScore, strat.livermore, strat.turtle);
    const dir = sig.action === 'BUY' ? 1 : -1;
    const entry = price * (1 + dir * SLIPPAGE);
    const quantity = (balance * cfg.RISK_PER_TRADE * mult) / entry;
    const { stopLoss, takeProfit } = calcSLTP(sig.action, entry, parseFloat(ind.atr));
    position = { side: sig.action, entryPrice: entry, quantity, stopLoss, takeProfit,
                 initialStop: stopLoss, openedAt: i,
                 trailHigh: sig.action === 'BUY' ? entry : null,
                 trailLow: sig.action === 'SELL' ? entry : null };
  }
  if (position) close(all[all.length - 1].close, 'END', all.length - 1);

  // ─── Raport ────────────────────────────────────────────
  const wins = trades.filter(t => t.pnl > 0), losses = trades.filter(t => t.pnl <= 0);
  const gw = wins.reduce((a, t) => a + t.pnl, 0), gl = Math.abs(losses.reduce((a, t) => a + t.pnl, 0));
  const pf = gl > 0 ? (gw / gl).toFixed(2) : '∞';
  const ret = ((balance - START_BAL) / START_BAL * 100).toFixed(2);
  const barsDays = ((all.length - 250) * (TIMEFRAME === '5m' ? 5 : 15) / 1440).toFixed(1);

  console.log(`\n  Perioadă: ~${barsDays} zile (${all.length - 250} lumânări) | Trades: ${trades.length} (✅ ${wins.length} / ❌ ${losses.length})`);
  console.log(`  Win rate: ${trades.length ? (wins.length / trades.length * 100).toFixed(1) : 0}% | Profit factor: ${pf}`);
  console.log(`  Rezultat net: ${ret >= 0 ? '+' : ''}${ret}% ($${balance.toFixed(2)}) | Comisioane+slippage plătite: $${feesPaid.toFixed(2)}`);
  console.log(`  Max drawdown: -${(maxDD * 100).toFixed(1)}%`);
  if (trades.length) {
    const exp = trades.reduce((a, t) => a + t.pnl, 0) / trades.length;
    console.log(`  Expectancy: ${exp >= 0 ? '+' : ''}$${exp.toFixed(4)}/trade`);
    const byReason = {};
    trades.forEach(t => byReason[t.reason] = (byReason[t.reason] || 0) + 1);
    console.log(`  Exituri: ${Object.entries(byReason).map(([r, n]) => `${r}×${n}`).join(' | ')}`);
  }
  console.log('\n  ⚠️  Stratul AI nu e simulat (filtrează în plus la live). Rezultatele');
  console.log('      trecute nu garantează nimic. Testează pe paper înainte de live.');
  console.log('═'.repeat(64) + '\n');
  return { balance, trades: trades.length, pf };
}

runBacktest().catch(err => { console.error('Backtest error:', err.message); process.exit(1); });
