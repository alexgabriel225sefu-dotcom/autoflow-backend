/**
 * APEX TRADE BOT — Telegram Alerts
 * Trimite notificări pe Telegram la fiecare eveniment important.
 * Dacă TELEGRAM_BOT_TOKEN lipsește → tace silențios (botul funcționează normal).
 */
const axios = require('axios');

const TOKEN   = process.env.TELEGRAM_BOT_TOKEN || '';
const CHAT_ID = process.env.TELEGRAM_CHAT_ID   || '';

async function send(text) {
  if (!TOKEN || !CHAT_ID) return; // Telegram neconfigurat — skip
  try {
    await axios.post(`https://api.telegram.org/bot${TOKEN}/sendMessage`, {
      chat_id:    CHAT_ID,
      text,
      parse_mode: 'HTML',
    }, { timeout: 6000 });
  } catch (err) {
    console.warn('[TELEGRAM] Eroare trimitere:', err.message);
  }
}

// ─── Alertă: Poziție deschisă ────────────────────────────
function alertOpen(side, symbol, price, quantity, stopLoss, takeProfit, druckMult) {
  const emoji = side === 'BUY' ? '🟢' : '🔴';
  const dir   = side === 'BUY' ? 'LONG' : 'SHORT';
  const mult  = druckMult !== 1.0 ? `\n📐 <b>Druckenmiller:</b> ×${druckMult.toFixed(2)}` : '';
  send(
    `${emoji} <b>APEX BOT — ${dir} DESCHIS</b>\n` +
    `💰 <b>${symbol}</b> @ $${price}\n` +
    `📦 Cantitate: ${quantity}\n` +
    `🛡 SL: $${stopLoss.toFixed(5)}\n` +
    `🎯 TP: $${takeProfit.toFixed(5)}` +
    mult
  );
}

// ─── Alertă: Poziție închisă ─────────────────────────────
function alertClose(reason, symbol, side, entryPrice, closePrice, pnl, balance) {
  const won   = pnl > 0;
  const emoji = won ? '✅' : '❌';
  const icons = { TAKE_PROFIT: '🎯 TAKE PROFIT', STOP_LOSS: '🛑 STOP LOSS', AI_CLOSE: '🤖 AI CLOSE' };
  const label = icons[reason] || reason;
  const dir   = side === 'BUY' ? 'LONG' : 'SHORT';
  send(
    `${emoji} <b>APEX BOT — ${label}</b>\n` +
    `📊 <b>${symbol}</b> ${dir}\n` +
    `📈 Intrare: $${entryPrice} → Ieșire: $${closePrice}\n` +
    `💵 PnL: <b>${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)}</b>\n` +
    `💼 Balanță: $${balance.toFixed(4)}`
  );
}

// ─── Alertă: Strategy Stop (PTJ / Seykota) ──────────────
function alertStop(reasons) {
  send(
    `🚨 <b>APEX BOT — STRATEGY STOP</b>\n` +
    `Botul a oprit tranzacțiile:\n` +
    reasons.map(r => `• ${r}`).join('\n')
  );
}

// ─── Alertă: Signal filtrat (Livermore contra-trend) ────
function alertFiltered(action, livermore, turtle) {
  send(
    `⚡ <b>APEX BOT — SIGNAL FILTRAT</b>\n` +
    `AI: ${action} | Livermore: ${livermore} | Turtle: ${turtle}\n` +
    `<i>PTJ: Play defense — nu intrăm contra trendului</i>`
  );
}

// ─── Alertă: Bot pornit ──────────────────────────────────
function alertStart(symbol, timeframe, balance, mode) {
  send(
    `🚀 <b>APEX TRADE BOT PORNIT</b>\n` +
    `📊 ${symbol} | ${timeframe}\n` +
    `💰 Balanță start: $${balance.toFixed(4)}\n` +
    `⚙️ Mod: ${mode}`
  );
}

module.exports = { alertOpen, alertClose, alertStop, alertFiltered, alertStart };
