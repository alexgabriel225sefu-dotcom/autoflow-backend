/**
 * APEX TRADE BOT — Telegram Alerts
 * Sends notifications on every important event.
 * If TELEGRAM_BOT_TOKEN is missing → silent (bot runs normally).
 */
const axios = require('axios');

const TOKEN   = process.env.TELEGRAM_BOT_TOKEN || '';
const CHAT_ID = process.env.TELEGRAM_CHAT_ID   || '';

async function send(text) {
  if (!TOKEN || !CHAT_ID) return; // Telegram not configured — skip
  try {
    await axios.post(`https://api.telegram.org/bot${TOKEN}/sendMessage`, {
      chat_id:    CHAT_ID,
      text,
      parse_mode: 'HTML',
    }, { timeout: 6000 });
  } catch (err) {
    console.warn('[TELEGRAM] Send error:', err.message);
  }
}

// ─── Alert: Position opened ──────────────────────────────
function alertOpen(side, symbol, price, quantity, stopLoss, takeProfit, druckMult) {
  const emoji = side === 'BUY' ? '🟢' : '🔴';
  const dir   = side === 'BUY' ? 'LONG' : 'SHORT';
  const mult  = druckMult !== 1.0 ? `\n📐 <b>Druckenmiller:</b> ×${druckMult.toFixed(2)}` : '';
  send(
    `${emoji} <b>APEX BOT — ${dir} OPENED</b>\n` +
    `💰 <b>${symbol}</b> @ $${price}\n` +
    `📦 Quantity: ${quantity}\n` +
    `🛡 SL: $${stopLoss.toFixed(5)}\n` +
    `🎯 TP: $${takeProfit.toFixed(5)}` +
    mult
  );
}

// ─── Alert: Position closed ──────────────────────────────
function alertClose(reason, symbol, side, entryPrice, closePrice, pnl, balance) {
  const won   = pnl > 0;
  const emoji = won ? '✅' : '❌';
  const icons = { TAKE_PROFIT: '🎯 TAKE PROFIT', STOP_LOSS: '🛑 STOP LOSS', AI_CLOSE: '🤖 AI CLOSE' };
  const label = icons[reason] || reason;
  const dir   = side === 'BUY' ? 'LONG' : 'SHORT';
  send(
    `${emoji} <b>APEX BOT — ${label}</b>\n` +
    `📊 <b>${symbol}</b> ${dir}\n` +
    `📈 Entry: $${entryPrice} → Exit: $${closePrice}\n` +
    `💵 PnL: <b>${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)}</b>\n` +
    `💼 Balance: $${balance.toFixed(4)}`
  );
}

// ─── Alert: Strategy Stop (PTJ / Seykota) ───────────────
function alertStop(reasons) {
  send(
    `🚨 <b>APEX BOT — STRATEGY STOP</b>\n` +
    `Trading paused:\n` +
    reasons.map(r => `• ${r}`).join('\n')
  );
}

// ─── Alert: Signal filtered (Livermore counter-trend) ───
function alertFiltered(action, livermore, turtle) {
  send(
    `⚡ <b>APEX BOT — SIGNAL FILTERED</b>\n` +
    `AI: ${action} | Livermore: ${livermore} | Turtle: ${turtle}\n` +
    `<i>PTJ: Play defense — no counter-trend entries</i>`
  );
}

// ─── Alert: Bot started ──────────────────────────────────
function alertStart(symbol, timeframe, balance, mode) {
  send(
    `🚀 <b>APEX TRADE BOT STARTED</b>\n` +
    `📊 ${symbol} | ${timeframe}\n` +
    `💰 Starting balance: $${balance.toFixed(4)}\n` +
    `⚙️ Mode: ${mode}`
  );
}

// ─── Heartbeat every 30 min ──────────────────────────────
function alertHeartbeat(tickCount, balance, openPosition, currentPrice) {
  let posLine = '📭 No open position';
  if (openPosition && currentPrice) {
    const dir = openPosition.side === 'BUY' ? 'LONG' : 'SHORT';
    const pnl = openPosition.side === 'BUY'
      ? (currentPrice - openPosition.entryPrice) * openPosition.quantity
      : (openPosition.entryPrice - currentPrice) * openPosition.quantity;
    const pnlPct = openPosition.side === 'BUY'
      ? (currentPrice - openPosition.entryPrice) / openPosition.entryPrice * 100
      : (openPosition.entryPrice - currentPrice) / openPosition.entryPrice * 100;
    posLine =
      `📊 ${dir} <b>${openPosition.symbol}</b> @ $${openPosition.entryPrice}\n` +
      `💹 Current: $${currentPrice} | PnL: <b>${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)} (${pnlPct.toFixed(2)}%)</b>\n` +
      `🛡 SL: $${openPosition.stopLoss.toFixed(5)} | 🎯 TP: $${openPosition.takeProfit.toFixed(5)}`;
  }
  send(
    `💓 <b>APEX BOT — ACTIVE</b> (tick #${tickCount})\n` +
    `💼 Balance: $${balance.toFixed(4)}\n` +
    posLine
  );
}

module.exports = { alertOpen, alertClose, alertStop, alertFiltered, alertStart, alertHeartbeat };
