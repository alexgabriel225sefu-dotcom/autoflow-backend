// ─── Backtest rapid pe date istorice ─────────────────────────────────────────
// Rulare: node src/backtest.js
//         BT_SYMBOL=XRPUSDT BT_TIMEFRAME=15m BT_CANDLES=500 node src/backtest.js
// Testează strategia fără AI (doar indicatori tehnici) pe ultimele N lumânări

require('dotenv').config();
const indicators = require('./indicators');
const cfg        = require('./config');
const exchange   = cfg.EXCHANGE === 'binance' ? require('./binance') : require('./bybit');

const SYMBOL     = process.env.BT_SYMBOL    || cfg.SYMBOL;
const TIMEFRAME  = process.env.BT_TIMEFRAME || cfg.TIMEFRAME;
const CANDLES    = parseInt(process.env.BT_CANDLES || '500');
const START_BAL  = parseFloat(process.env.BT_BALANCE || '10');

// ─── Semnal simplu bazat pe indicatori (fără AI = rapid) ──────────────────
function simpleSignal(ind) {
  const rsi    = parseFloat(ind.rsi);
  const macdH  = parseFloat(ind.macdHist);
  const srsiK  = parseFloat(ind.stochRsiK);
  const srsiD  = parseFloat(ind.stochRsiD);
  const bbPos  = parseFloat(ind.bb_position);
  const volR   = parseFloat(ind.volumeRatio);
  const trend  = ind.emaTrend;

  let buyScore  = 0;
  let sellScore = 0;

  // Criterii BUY
  if (trend === 'BULLISH')                         buyScore++;
  if (rsi < 45)                                    buyScore++;
  if (macdH > 0)                                   buyScore++;
  if (srsiK < 30 || (srsiK > srsiD && srsiK < 50)) buyScore++;
  if (bbPos < 30)                                  buyScore++;
  if (ind.divergence === 'BULLISH')                buyScore++;
  if (volR > 1.2)                                  buyScore++;

  // Criterii SELL
  if (trend === 'BEARISH')                          sellScore++;
  if (rsi > 55)                                     sellScore++;
  if (macdH < 0)                                    sellScore++;
  if (srsiK > 70 || (srsiK < srsiD && srsiK > 50))  sellScore++;
  if (bbPos > 70)                                    sellScore++;
  if (ind.divergence === 'BEARISH')                  sellScore++;
  if (volR > 1.2)                                    sellScore++;

  if (buyScore  >= 4 && buyScore  > sellScore) return { action: 'BUY',  score: buyScore };
  if (sellScore >= 4 && sellScore > buyScore)  return { action: 'SELL', score: sellScore };
  return { action: 'HOLD', score: 0 };
}

// ─── Fetch date istorice prin modulul exchange ────────────
async function fetchCandles(symbol, interval, limit) {
  // exchange.getCandles folosește Binance public API (accesibil din Railway)
  return await exchange.getCandles(symbol, interval, limit);
}

// ─── Rulează backtest ─────────────────────────────────────
async function runBacktest() {
  console.log('\n' + '═'.repeat(60));
  console.log('  📊 APEX BACKTEST ENGINE');
  console.log(`  Symbol: ${SYMBOL} | Timeframe: ${TIMEFRAME} | Lumânări: ${CANDLES}`);
  console.log(`  Start balance: $${START_BAL} | SL: ${cfg.STOP_LOSS_PCT*100}% | TP: ${cfg.TAKE_PROFIT_PCT*100}%`);
  console.log('═'.repeat(60));

  const allCandles = await fetchCandles(SYMBOL, TIMEFRAME, CANDLES + 200);

  let balance     = START_BAL;
  let position    = null;
  let trades      = [];
  let wins = 0, losses = 0;

  // Simulăm iterând prin fiecare lumânare
  for (let i = 100; i < allCandles.length; i++) {
    const window  = allCandles.slice(0, i + 1);
    const ind     = indicators.analyze(window);
    const price   = allCandles[i].close;
    const candle  = allCandles[i];

    // Verifică SL/TP pe poziție deschisă
    if (position) {
      const { side, entryPrice, quantity, stopLoss, takeProfit } = position;
      let closed = false;
      let closePrice = null;
      let reason = '';

      // Verifică dacă SL sau TP a fost atins în această lumânare
      if (side === 'BUY') {
        if (candle.low <= stopLoss) { closePrice = stopLoss; reason = 'SL'; closed = true; }
        else if (candle.high >= takeProfit) { closePrice = takeProfit; reason = 'TP'; closed = true; }
      } else {
        if (candle.high >= stopLoss) { closePrice = stopLoss; reason = 'SL'; closed = true; }
        else if (candle.low <= takeProfit) { closePrice = takeProfit; reason = 'TP'; closed = true; }
      }

      if (closed) {
        const pnl = side === 'BUY'
          ? (closePrice - entryPrice) * quantity
          : (entryPrice - closePrice) * quantity;
        balance += entryPrice * quantity + pnl;
        if (pnl > 0) wins++; else losses++;
        trades.push({ i, side, entry: entryPrice, exit: closePrice, pnl, reason });
        position = null;
      }
    }

    // Deschide poziție nouă dacă nu avem una
    if (!position && balance > 1) {
      const signal = simpleSignal(ind);
      if (signal.action !== 'HOLD') {
        const riskAmt  = balance * cfg.RISK_PER_TRADE;
        const quantity = signal.action === 'BUY' || signal.action === 'SELL'
          ? riskAmt / price
          : 0;

        if (quantity > 0) {
          const sl = signal.action === 'BUY' ? price * (1 - cfg.STOP_LOSS_PCT) : price * (1 + cfg.STOP_LOSS_PCT);
          const tp = signal.action === 'BUY' ? price * (1 + cfg.TAKE_PROFIT_PCT) : price * (1 - cfg.TAKE_PROFIT_PCT);
          balance -= riskAmt;
          position = { side: signal.action, entryPrice: price, quantity, stopLoss: sl, takeProfit: tp, openedAt: i };
        }
      }
    }
  }

  // Închide poziție deschisă la final
  if (position) {
    const lastPrice = allCandles[allCandles.length - 1].close;
    const pnl = position.side === 'BUY'
      ? (lastPrice - position.entryPrice) * position.quantity
      : (position.entryPrice - lastPrice) * position.quantity;
    balance += position.entryPrice * position.quantity + pnl;
    trades.push({ side: position.side, entry: position.entryPrice, exit: lastPrice, pnl, reason: 'END' });
    if (pnl > 0) wins++; else losses++;
  }

  // ─── Raport ─────────────────────────────────────────────
  const totalTrades = wins + losses;
  const winRate     = totalTrades > 0 ? (wins / totalTrades * 100).toFixed(1) : 0;
  const pnlTotal    = balance - START_BAL;
  const pnlPct      = (pnlTotal / START_BAL * 100).toFixed(2);
  const avgWin      = trades.filter(t => t.pnl > 0).reduce((a, t) => a + t.pnl, 0) / (wins || 1);
  const avgLoss     = trades.filter(t => t.pnl < 0).reduce((a, t) => a + t.pnl, 0) / (losses || 1);
  const profitFactor = losses > 0 && avgLoss !== 0 ? (wins * avgWin / (losses * Math.abs(avgLoss))).toFixed(2) : '∞';

  console.log('\n📊 REZULTATE BACKTEST:');
  console.log(`   Balanță finală:   $${balance.toFixed(4)} (${pnlPct >= 0 ? '+' : ''}${pnlPct}%)`);
  console.log(`   Total trades:     ${totalTrades} | ✅ ${wins} | ❌ ${losses}`);
  console.log(`   Win Rate:         ${winRate}%`);
  console.log(`   Profit Factor:    ${profitFactor} (>1.5 = bun, >2 = excelent)`);
  console.log(`   Avg Win:         +$${avgWin.toFixed(4)}`);
  console.log(`   Avg Loss:        -$${Math.abs(avgLoss).toFixed(4)}`);
  console.log(`   Profit total:     ${pnlTotal >= 0 ? '+' : ''}$${pnlTotal.toFixed(4)}`);

  console.log('\n📈 Ultimele 10 trades:');
  trades.slice(-10).forEach((t, i) => {
    const sign = t.pnl >= 0 ? '✅' : '❌';
    console.log(`   ${sign} ${t.side} | Entry: $${t.entry?.toFixed(5)} | Exit: $${t.exit?.toFixed(5)} | PnL: ${t.pnl >= 0 ? '+' : ''}$${t.pnl?.toFixed(4)} | ${t.reason}`);
  });

  // Recomandare
  console.log('\n💡 CONCLUZIE:');
  if (parseFloat(winRate) >= 55 && parseFloat(profitFactor) >= 1.5) {
    console.log('   ✅ STRATEGIE PROFITABILĂ — poți testa live cu capital mic');
  } else if (parseFloat(winRate) >= 45 && parseFloat(profitFactor) >= 1.2) {
    console.log('   ⚠️  STRATEGIE MARGINALĂ — testează mai mult înainte de live');
  } else {
    console.log('   ❌ STRATEGIE NEPROFITABILĂ — ajustează SL/TP sau timeframe');
  }
  console.log('═'.repeat(60) + '\n');

  return { balance, winRate, profitFactor, totalTrades };
}

runBacktest().catch(err => { console.error('Backtest error:', err.message); process.exit(1); });
