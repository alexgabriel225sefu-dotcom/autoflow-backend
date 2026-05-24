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
  console.log(`${emoji}  AI SIGNAL: \x1b[1m${signal.action}\x1b[0m  (${signal.confidence}% confidence | ${signal.riskLevel} risk | criteria: ${signal.criteriaScore ?? '?'}/5)`);
  console.log(`💭 ${signal.reasoning}`);
  console.log(`📊 RSI: ${ind.rsi} | StochRSI K: ${ind.stochRsiK} | MACD Hist: ${ind.macdHist}`);
  console.log(`📈 Trend: ${ind.emaTrend} | Structure: ${ind.marketStructure} | Divergence: ${ind.divergence}`);
  console.log(`💰 Price: $${ind.price} | ATR: ${ind.atrPct}% | Volume: ${ind.volumeRatio}× avg`);
  console.log(`📉 BB Pos: ${ind.bb_position}% | BB Width: ${ind.bb_bandwidth}%`);
  if (signal.keyFactors?.length) console.log(`🔑 Key factors: ${signal.keyFactors.join(' • ')}`);
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

function printStats(balance, openPosition = null, currentPrice = null) {
  let totalValue = balance;
  let positionNote = '';
  let freeUSDT = balance;

  if (openPosition && currentPrice) {
    const posValue = openPosition.quantity * currentPrice;
    const unrealizedPnl = openPosition.side === 'BUY'
      ? (currentPrice - openPosition.entryPrice) * openPosition.quantity
      : (openPosition.entryPrice - currentPrice) * openPosition.quantity;

    if (openPosition.side === 'BUY') {
      totalValue = balance + posValue;
      freeUSDT = balance;
    } else {
      totalValue = balance - posValue;
      freeUSDT = totalValue;
    }

    const side = openPosition.side === 'BUY' ? 'LONG' : 'SHORT';
    positionNote = ` | ${side} ${openPosition.quantity} ${openPosition.symbol || ''} @ $${openPosition.entryPrice} | PnL: ${unrealizedPnl >= 0 ? '+' : ''}$${unrealizedPnl.toFixed(4)}`;
  }

  const pnlPct = stats.startBalance > 0 ? ((totalValue - stats.startBalance) / stats.startBalance * 100).toFixed(2) : 0;
  const winRate = stats.trades > 0 ? (stats.wins / stats.trades * 100).toFixed(0) : 0;
  const modeLabel = cfg.PAPER_TRADING ? '📝 PAPER' : cfg.TESTNET ? '🧪 TESTNET' : '🔴 LIVE';
  console.log('\n📊 STATS:');
  console.log(`   Total portfolio: $${totalValue.toFixed(4)} (${pnlPct >= 0 ? '+' : ''}${pnlPct}%)${positionNote}`);
  console.log(`   Free USDT: $${freeUSDT.toFixed(4)}${openPosition ? ' (rest in open position)' : ''}`);
  console.log(`   Closed trades: ${stats.trades} | ✅ ${stats.wins} | ❌ ${stats.losses} | Win Rate: ${winRate}%`);
  console.log(`   Realized PnL: ${stats.totalPnL >= 0 ? '+' : ''}$${stats.totalPnL.toFixed(4)}`);
  console.log(`   Mode: ${modeLabel}\n`);
}

function printBanner(balance) {
  const isBinanceTestnet = cfg.EXCHANGE === 'binance'
    ? (process.env.BINANCE_TESTNET || '').toLowerCase().trim() !== 'false'
    : false;
  const modeLabel = cfg.PAPER_TRADING
    ? '📝 PAPER TRADING (no real risk)'
    : (cfg.BYBIT_TESTNET || isBinanceTestnet) ? '🧪 TESTNET'
    : '🔴 LIVE TRADING';
  console.log('\n' + '═'.repeat(60));
  console.log('  🚀 APEX TRADE BOT — AI Powered Trading');
  console.log(`  Symbol: ${cfg.SYMBOL} | Timeframe: ${cfg.TIMEFRAME}`);
  console.log(`  Mode: ${modeLabel}`);
  console.log(`  Starting balance: $${balance.toFixed(4)}`);
  console.log(`  Analysis interval: ${cfg.LOOP_INTERVAL_MS / 60000} minutes`);
  console.log(`  Stop Loss: ${cfg.STOP_LOSS_PCT * 100}% | Take Profit: ${cfg.TAKE_PROFIT_PCT * 100}%`);
  console.log('═'.repeat(60) + '\n');
}

module.exports = { log, info, warn, error, good, bad, printSignal, printTrade, printStats, printBanner, setStartBalance, updateBalance };
