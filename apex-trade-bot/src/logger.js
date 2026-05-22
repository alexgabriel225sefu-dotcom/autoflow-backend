const cfg = require('./config');

let stats = { trades: 0, wins: 0, losses: 0, totalPnL: 0, startBalance: 0, currentBalance: 0 };

function setStartBalance(b) { stats.startBalance = b; stats.currentBalance = b; }
function updateBalance(b)   { stats.currentBalance = b; }

function log(msg)   { console.log(`[${new Date().toISOString()}] ${msg}`); }
function info(msg)  { console.log(`\x1b[36m[INFO]\x1b[0m  ${msg}`); }
function warn(msg)  { console.log(`\x1b[33m[WARN]\x1b[0m  ${msg}`); }
function error(msg) { console.log(`\x1b[31m[ERROR]\x1b[0m ${msg}`); }
function good(msg)  { console.log(`\x1b[32m[WIN]\x1b[0m   ${msg}`); }
function bad(msg)   { console.log(`\x1b[31m[LOSS]\x1b[0m  ${msg}`); }

function printSignal(signal, ind) {
  const emoji = signal.action === 'BUY' ? '📈' : signal.action === 'SELL' ? '📉' : signal.action === 'CLOSE' ? '🔄' : '⏸️';
  console.log('\n' + '─'.repeat(60));
  console.log(`${emoji}  AI SIGNAL: \x1b[1m${signal.action}\x1b[0m  (${signal.confidence}% confidence | ${signal.riskLevel} risk | criterii: ${signal.criteriaScore ?? '?'}/5)`);
  console.log(`💭 ${signal.reasoning}`);
  console.log(`📊 RSI: ${ind.rsi} | StochRSI K: ${ind.stochRsiK} | MACD Hist: ${ind.macdHist}`);
  console.log(`📈 Trend: ${ind.emaTrend} | Structura: ${ind.marketStructure} | Divergenta: ${ind.divergence}`);
  console.log(`💰 Preț: $${ind.price} | ATR: ${ind.atrPct}% | Volum: ${ind.volumeRatio}× avg`);
  console.log(`📉 BB Pos: ${ind.bb_position}% | BB Width: ${ind.bb_bandwidth}%`);
  if (signal.keyFactors?.length) console.log(`🔑 Factori: ${signal.keyFactors.join(' • ')}`);
  console.log('─'.repeat(60));
}

function printTrade(type, symbol, price, quantity, pnl = null) {
  if (pnl !== null) {
    stats.trades++;
    stats.totalPnL += pnl;
    if (pnl > 0) { stats.wins++; good(`PROFIT: +$${pnl.toFixed(4)} | ${symbol} ${type} @ $${price}`); }
    else { stats.losses++; bad(`LOSS: -$${Math.abs(pnl).toFixed(4)} | ${symbol} ${type} @ $${price}`); }
  } else {
    info(`TRADE: ${type} ${quantity} ${symbol} @ $${price}`);
  }
}

// openPosition passat din index.js pentru a calcula valoarea totală corect
function printStats(balance, openPosition = null, currentPrice = null) {
  // Valoarea totală = USDT liber + valoarea DOGE deținut
  let totalValue = balance;
  let positionNote = '';
  if (openPosition && currentPrice) {
    const posValue = openPosition.quantity * currentPrice;
    totalValue = balance + posValue;
    const unrealizedPnl = openPosition.side === 'BUY'
      ? (currentPrice - openPosition.entryPrice) * openPosition.quantity
      : (openPosition.entryPrice - currentPrice) * openPosition.quantity;
    positionNote = ` | Poziție: ${openPosition.side} ${openPosition.quantity} @ $${openPosition.entryPrice} | PnL nerealizat: ${unrealizedPnl >= 0 ? '+' : ''}$${unrealizedPnl.toFixed(4)}`;
  }

  const pnlPct = stats.startBalance > 0 ? ((totalValue - stats.startBalance) / stats.startBalance * 100).toFixed(2) : 0;
  const winRate = stats.trades > 0 ? (stats.wins / stats.trades * 100).toFixed(0) : 0;
  console.log('\n📊 STATISTICI:');
  console.log(`   Portofoliu total: $${totalValue.toFixed(4)} (${pnlPct >= 0 ? '+' : ''}${pnlPct}%)${positionNote}`);
  console.log(`   USDT liber: $${balance.toFixed(4)}${openPosition ? ' (restul e în poziție deschisă)' : ''}`);
  console.log(`   Tranzacții închise: ${stats.trades} | ✅ ${stats.wins} | ❌ ${stats.losses} | Win Rate: ${winRate}%`);
  console.log(`   Profit realizat: ${stats.totalPnL >= 0 ? '+' : ''}$${stats.totalPnL.toFixed(4)}`);
  console.log(`   Mod: ${cfg.PAPER_TRADING ? '📝 PAPER TRADING' : cfg.TESTNET ? '🧪 TESTNET' : '🔴 LIVE'}\n`);
}

function printBanner(balance) {
  console.log('\n' + '═'.repeat(60));
  console.log('  🚀 APEX TRADE BOT — AI Powered Trading');
  console.log(`  Symbol: ${cfg.SYMBOL} | Timeframe: ${cfg.TIMEFRAME}`);
  console.log(`  Mod: ${cfg.PAPER_TRADING ? '📝 PAPER TRADING (fără risc real)' : cfg.TESTNET ? '🧪 TESTNET' : '🔴 LIVE TRADING'}`);
  console.log(`  Balanță start: $${balance.toFixed(4)}`);
  console.log(`  Interval analiză: ${cfg.LOOP_INTERVAL_MS / 60000} minute`);
  console.log(`  Stop Loss: ${cfg.STOP_LOSS_PCT * 100}% | Take Profit: ${cfg.TAKE_PROFIT_PCT * 100}%`);
  console.log('═'.repeat(60) + '\n');
}

module.exports = { log, info, warn, error, good, bad, printSignal, printTrade, printStats, printBanner, setStartBalance, updateBalance };
