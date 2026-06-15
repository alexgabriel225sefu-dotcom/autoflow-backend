/**
 * APEX TRADE BOT — Telegram Alerts + Interactive Dashboard
 * Send /status for live snapshot. Set DASHBOARD_URL for web link.
 */
const axios = require('axios');

const TOKEN        = process.env.TELEGRAM_BOT_TOKEN || '';
const CHAT_ID      = process.env.TELEGRAM_CHAT_ID   || '';
const DASHBOARD_URL = process.env.DASHBOARD_URL      || '';

// ─── Send helpers ─────────────────────────────────────────
async function send(text, extra = {}) {
  if (!TOKEN || !CHAT_ID) return;
  try {
    await axios.post(`https://api.telegram.org/bot${TOKEN}/sendMessage`, {
      chat_id: CHAT_ID, text, parse_mode: 'HTML', ...extra,
    }, { timeout: 6000 });
  } catch (err) {
    console.warn('[TELEGRAM] Send error:', err.message);
  }
}

async function sendTo(chatId, text, extra = {}) {
  if (!TOKEN) return;
  try {
    await axios.post(`https://api.telegram.org/bot${TOKEN}/sendMessage`, {
      chat_id: chatId, text, parse_mode: 'HTML', ...extra,
    }, { timeout: 6000 });
  } catch (err) {
    console.warn('[TELEGRAM] Send error:', err.message);
  }
}

// ─── Mini price chart (Unicode blocks) ───────────────────
function miniChart(closes) {
  const n = Math.min(closes.length, 24);
  const sl = closes.slice(-n);
  const min = Math.min(...sl), max = Math.max(...sl);
  const range = max - min || 1;
  const blocks = '▁▂▃▄▅▆▇█';
  return sl.map(c => blocks[Math.min(7, Math.floor(((c - min) / range) * 8))]).join('');
}

// ─── Dashboard button keyboard (Telegram Web App — opens inside Telegram) ───
function dashboardKeyboard() {
  if (!DASHBOARD_URL) return {};
  return {
    reply_markup: JSON.stringify({
      inline_keyboard: [[{ text: '📊 Live Dashboard', web_app: { url: DASHBOARD_URL } }]],
    }),
  };
}

// ─── Rich status message builder ─────────────────────────
function buildStatus(dash, chart = '') {
  const pnlPct  = dash.startBalance > 0
    ? ((dash.balance - dash.startBalance) / dash.startBalance * 100).toFixed(2) : '0.00';
  const pnlSign = parseFloat(pnlPct) >= 0 ? '+' : '';
  const wins    = (dash.trades || []).filter(t => t.win).length;
  const total   = (dash.trades || []).length;
  const winRate = total > 0 ? ((wins / total) * 100).toFixed(0) + '%' : '—';
  const chartLine = chart
    ? `\n<code>${chart}</code>  <b>$${dash.currentPrice?.toFixed(4) || '—'}</b>`
    : '';

  let posLine = '📭 No open position';
  if (dash.openPosition) {
    const dir  = dash.openPosition.side === 'BUY' ? '🟢 LONG' : '🔴 SHORT';
    const pnl  = dash.openPosition.currentPnl || 0;
    const sign = pnl >= 0 ? '+' : '';
    posLine =
      `${dir} <b>${dash.openPosition.symbol}</b>\n` +
      `  Entry: $${dash.openPosition.entryPrice}  ` +
      `SL: $${dash.openPosition.stopLoss?.toFixed(4)}\n` +
      `  PnL: <b>${sign}$${pnl.toFixed(4)}</b>`;
  }

  return (
    `⚡ <b>APEX TRADE BOT</b>  ${dash.mode || ''} · ${dash.exchange || ''}\n` +
    `━━━━━━━━━━━━━━━━━━━━\n` +
    `💰 Balance: <b>$${(dash.balance || 0).toFixed(2)}</b>  (${pnlSign}${pnlPct}%)${chartLine}\n\n` +
    `${posLine}\n\n` +
    `📈 ${total} trades · ${wins}W/${total - wins}L · Win: ${winRate}\n` +
    `⏱️ Last tick: ${dash.lastTick || '—'}`
  );
}

// ─── Command polling (runs in background) ────────────────
let _getDash   = () => null;
let _exchange  = null;
let _updateId  = 0;

async function _fetchUpdates() {
  const { data } = await axios.get(
    `https://api.telegram.org/bot${TOKEN}/getUpdates`,
    { params: { offset: _updateId, timeout: 10, allowed_updates: ['message'] }, timeout: 15000 }
  );
  return data.result || [];
}

async function _handleStatus(chatId) {
  const dash = _getDash();
  if (!dash || !dash.exchange) {
    return sendTo(chatId, '⏳ Bot is starting up, please wait...');
  }
  let chart = '';
  if (_exchange) {
    try {
      const candles = await _exchange.getCandles(dash.currentSymbol, '5m', 24);
      chart = miniChart(candles.map(c => c.close));
    } catch {}
  }
  await sendTo(chatId, buildStatus(dash, chart), dashboardKeyboard());
}

async function _pollLoop() {
  while (true) {
    try {
      const updates = await _fetchUpdates();
      for (const u of updates) {
        _updateId = u.update_id + 1;
        const text   = (u.message?.text || '').trim().toLowerCase();
        const chatId = u.message?.chat?.id;
        if (!text || !chatId) continue;
        if (chatId.toString() !== CHAT_ID) continue; // authorized only
        if (text === '/status' || text === '/s')
          await _handleStatus(chatId);
        else if (text === '/help')
          await sendTo(chatId,
            '📋 <b>Available commands:</b>\n' +
            '/status — live snapshot\n' +
            '/help — this list'
          );
      }
    } catch (e) {
      // token invalid / network down — log + backoff
      console.warn('[TG] Poll error:', e.message);
      await new Promise(r => setTimeout(r, 28000));
    }
    await new Promise(r => setTimeout(r, 2000));
  }
}

function startPolling(getDash, exchange) {
  if (!TOKEN || !CHAT_ID) return;
  _getDash  = getDash;
  _exchange = exchange;
  _pollLoop();
  console.log('[TELEGRAM] Command polling started. Try /status in your chat.');
}

// ─── Alert: Position opened ───────────────────────────────
function alertOpen(side, symbol, price, quantity, stopLoss, takeProfit, druckMult) {
  const dir  = side === 'BUY' ? '🟢 LONG' : '🔴 SHORT';
  const mult = druckMult !== 1.0 ? `\n📐 <b>Druckenmiller:</b> ×${druckMult.toFixed(2)}` : '';
  send(
    `${dir} <b>OPENED — ${symbol}</b>\n` +
    `💰 @ $${price}  Qty: ${quantity}\n` +
    `🛡 SL: $${stopLoss.toFixed(5)}\n` +
    `🎯 TP: $${takeProfit.toFixed(5)}` + mult,
    dashboardKeyboard()
  );
}

// ─── Alert: Position closed ───────────────────────────────
function alertClose(reason, symbol, side, entryPrice, closePrice, pnl, balance) {
  const icons = { TAKE_PROFIT: '🎯 TAKE PROFIT', STOP_LOSS: '🛑 STOP LOSS', AI_CLOSE: '🤖 AI CLOSE' };
  const dir   = side === 'BUY' ? 'LONG' : 'SHORT';
  send(
    `${pnl > 0 ? '✅' : '❌'} <b>${icons[reason] || reason} — ${symbol}</b>\n` +
    `📊 ${dir}  $${entryPrice} → $${closePrice}\n` +
    `💵 PnL: <b>${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)}</b>\n` +
    `💼 Balance: $${balance.toFixed(4)}`,
    dashboardKeyboard()
  );
}

// ─── Alert: Strategy Stop ────────────────────────────────
function alertStop(reasons) {
  send(`🚨 <b>STRATEGY STOP</b>\n` + reasons.map(r => `• ${r}`).join('\n'));
}

// ─── Alert: Signal filtered ──────────────────────────────
function alertFiltered(action, livermore, turtle) {
  send(
    `⚡ <b>SIGNAL FILTERED</b>\n` +
    `AI: ${action} | Livermore: ${livermore} | Turtle: ${turtle}\n` +
    `<i>PTJ: Play defense</i>`
  );
}

// ─── Alert: Bot started ──────────────────────────────────
function alertStart(symbol, timeframe, balance, mode) {
  send(
    `🚀 <b>APEX TRADE BOT STARTED</b>\n` +
    `📊 ${symbol} | ${timeframe} | $${balance.toFixed(2)}\n` +
    `⚙️ ${mode}\n` +
    (DASHBOARD_URL ? `🌐 Dashboard: ${DASHBOARD_URL}\n` : '') +
    `<i>Send /status for a live snapshot</i>`,
    dashboardKeyboard()
  );
}

// ─── Heartbeat (every 30 min) ────────────────────────────
function alertHeartbeat(tickCount, balance, openPosition, currentPrice) {
  let posLine = '📭 No open position';
  if (openPosition && currentPrice) {
    const dir = openPosition.side === 'BUY' ? 'LONG' : 'SHORT';
    const pnl = openPosition.side === 'BUY'
      ? (currentPrice - openPosition.entryPrice) * openPosition.quantity
      : (openPosition.entryPrice - currentPrice) * openPosition.quantity;
    posLine =
      `${openPosition.side === 'BUY' ? '🟢' : '🔴'} ${dir} <b>${openPosition.symbol}</b> @ $${openPosition.entryPrice}\n` +
      `PnL: <b>${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)}</b>`;
  }
  send(
    `💓 <b>ACTIVE</b>  tick #${tickCount}\n` +
    `💼 Balance: $${balance.toFixed(4)}\n` +
    `${posLine}\n<i>/status for details</i>`,
    dashboardKeyboard()
  );
}

module.exports = {
  alertOpen, alertClose, alertStop, alertFiltered, alertStart, alertHeartbeat,
  startPolling, miniChart,
};
