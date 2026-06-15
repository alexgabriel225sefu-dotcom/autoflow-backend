/**
 * APEX TRADE BOT — Telegram Alerts + Interactive Bot Controls
 * Commands: /status /config /method /set /pause /resume /chart /help
 */
const axios    = require('axios');
const cfg      = require('./config');
const settings = require('./settings');

const TOKEN         = (process.env.TELEGRAM_BOT_TOKEN || '').trim();
const CHAT_ID       = (process.env.TELEGRAM_CHAT_ID   || '').trim();
const DASHBOARD_URL = (process.env.DASHBOARD_URL       || '').trim();

// ─── TradingView URL builder ──────────────────────────────
const TV_EXCHANGE = {
  binance: 'BINANCE', bybit: 'BYBIT', okx: 'OKX',
  kraken: 'KRAKEN', kucoin: 'KUCOIN', mexc: 'MEXC',
  coinbase: 'COINBASE', bitget: 'BITGET',
};
function tvUrl(symbol) {
  const ex = TV_EXCHANGE[cfg.EXCHANGE?.toLowerCase()] || 'BINANCE';
  return `https://www.tradingview.com/chart/?symbol=${ex}:${symbol}`;
}

// ─── Send helpers ─────────────────────────────────────────
async function send(text, extra = {}) {
  if (!TOKEN || !CHAT_ID) return;
  try {
    await axios.post(`https://api.telegram.org/bot${TOKEN}/sendMessage`, {
      chat_id: CHAT_ID, text, parse_mode: 'HTML', ...extra,
    }, { timeout: 6000 });
  } catch (err) { console.warn('[TELEGRAM] Send error:', err.message); }
}

async function sendTo(chatId, text, extra = {}) {
  if (!TOKEN) return;
  try {
    await axios.post(`https://api.telegram.org/bot${TOKEN}/sendMessage`, {
      chat_id: chatId, text, parse_mode: 'HTML', ...extra,
    }, { timeout: 6000 });
  } catch (err) { console.warn('[TELEGRAM] Send error:', err.message); }
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

function dashboardKeyboard(symbol) {
  const buttons = [];
  if (DASHBOARD_URL) buttons.push({ text: '📊 Live Dashboard', web_app: { url: DASHBOARD_URL } });
  if (symbol) buttons.push({ text: '📈 TradingView', url: tvUrl(symbol) });
  if (!buttons.length) return {};
  return { reply_markup: JSON.stringify({ inline_keyboard: [buttons] }) };
}

// ─── Status message builder ───────────────────────────────
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
  const mode    = settings.get('STRATEGY_MODE');
  const paused  = settings.get('PAUSED') ? '\n⏸️ <b>PAUSED</b> — /resume to restart' : '';

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
    `Method: <b>${mode.toUpperCase()}</b>${paused}\n` +
    `━━━━━━━━━━━━━━━━━━━━\n` +
    `💰 Balance: <b>$${(dash.balance || 0).toFixed(2)}</b>  (${pnlSign}${pnlPct}%)${chartLine}\n\n` +
    `${posLine}\n\n` +
    `📈 ${total} trades · ${wins}W/${total - wins}L · Win: ${winRate}\n` +
    `⏱️ Last tick: ${dash.lastTick || '—'}`
  );
}

// ─── Config summary ───────────────────────────────────────
function buildConfig() {
  const s = settings.snapshot();
  const METHOD_DESC = {
    auto:           '🤖 Auto — all strategies',
    turtle:         '🐢 Turtle breakout (R. Dennis)',
    livermore:      '📐 Livermore pivot structure',
    soros:          '💡 Soros momentum / reflexivity',
    ptj:            '🛡️  PTJ — defensive, high confidence only',
    druckenmiller:  '📊 Druckenmiller — high-conviction sizing',
  };
  return (
    `⚙️ <b>CURRENT CONFIGURATION</b>\n` +
    `━━━━━━━━━━━━━━━━━━━━\n` +
    `🎯 Method: <b>${(METHOD_DESC[s.STRATEGY_MODE] || s.STRATEGY_MODE)}</b>\n` +
    `💸 Risk/trade: <b>${(s.RISK_PER_TRADE * 100).toFixed(1)}%</b>\n` +
    `🛡 Stop Loss: <b>${(s.STOP_LOSS_PCT * 100).toFixed(1)}%</b>\n` +
    `🎯 Take Profit: <b>${(s.TAKE_PROFIT_PCT * 100).toFixed(1)}%</b>\n` +
    `🧠 Min confidence: <b>${s.MIN_CONFIDENCE}%</b>\n` +
    `⏸️ Paused: <b>${s.PAUSED ? 'YES' : 'NO'}</b>\n\n` +
    `<i>Edit with /set or /method — changes apply instantly</i>`
  );
}

// ─── Command handlers ────────────────────────────────────
async function _handleStatus(chatId) {
  const dash = _getDash();
  if (!dash || !dash.exchange) return sendTo(chatId, '⏳ Bot is starting up...');
  let chart = '';
  if (_exchange) {
    try {
      const candles = await _exchange.getCandles(dash.currentSymbol, '5m', 24);
      chart = miniChart(candles.map(c => c.close));
    } catch {}
  }
  await sendTo(chatId, buildStatus(dash, chart), dashboardKeyboard(dash.currentSymbol));
}

async function _handleMethod(chatId, arg) {
  const VALID = ['auto', 'turtle', 'livermore', 'soros', 'ptj', 'druckenmiller'];
  if (!arg || !VALID.includes(arg)) {
    return sendTo(chatId,
      `🎯 <b>Choose a trading method:</b>\n\n` +
      `/method auto — 🤖 All strategies (default)\n` +
      `/method turtle — 🐢 Turtle Breakout (R. Dennis)\n` +
      `/method livermore — 📐 Livermore Pivot Structure\n` +
      `/method soros — 💡 Soros Momentum / Reflexivity\n` +
      `/method ptj — 🛡️  PTJ Defense (high confidence only)\n` +
      `/method druckenmiller — 📊 Druckenmiller Sizing\n\n` +
      `<i>Current: <b>${settings.get('STRATEGY_MODE').toUpperCase()}</b></i>`
    );
  }
  settings.set('STRATEGY_MODE', arg);
  const EMOJI = { auto:'🤖', turtle:'🐢', livermore:'📐', soros:'💡', ptj:'🛡️', druckenmiller:'📊' };
  await sendTo(chatId, `${EMOJI[arg]} Method set to <b>${arg.toUpperCase()}</b> — active from next tick.`);
}

async function _handleSet(chatId, parts) {
  const key = parts[0], rawVal = parts[1];
  if (!key || !rawVal) {
    return sendTo(chatId,
      `⚙️ <b>Settings usage:</b>\n\n` +
      `/set risk 1.5 — risk per trade (%)\n` +
      `/set sl 2 — stop loss (%)\n` +
      `/set tp 4 — take profit (%)\n` +
      `/set confidence 70 — min AI confidence (0-100)\n` +
      `/set paper on — enable paper trading\n` +
      `/set paper off — disable paper (⚠️ real money!)`
    );
  }

  if (key === 'risk') {
    const v = parseFloat(rawVal);
    if (isNaN(v) || v <= 0 || v > 10) return sendTo(chatId, '❌ risk must be 0.1–10 (percent per trade)');
    settings.set('RISK_PER_TRADE', v / 100);
    return sendTo(chatId, `✅ Risk/trade set to <b>${v}%</b>`);
  }
  if (key === 'sl') {
    const v = parseFloat(rawVal);
    if (isNaN(v) || v <= 0 || v > 20) return sendTo(chatId, '❌ sl must be 0.1–20 (percent)');
    settings.set('STOP_LOSS_PCT', v / 100);
    return sendTo(chatId, `✅ Stop Loss set to <b>${v}%</b>`);
  }
  if (key === 'tp') {
    const v = parseFloat(rawVal);
    if (isNaN(v) || v <= 0 || v > 50) return sendTo(chatId, '❌ tp must be 0.1–50 (percent)');
    settings.set('TAKE_PROFIT_PCT', v / 100);
    return sendTo(chatId, `✅ Take Profit set to <b>${v}%</b>`);
  }
  if (key === 'confidence') {
    const v = parseInt(rawVal);
    if (isNaN(v) || v < 0 || v > 100) return sendTo(chatId, '❌ confidence must be 0–100');
    settings.set('MIN_CONFIDENCE', v);
    return sendTo(chatId, `✅ Min confidence set to <b>${v}%</b>`);
  }
  if (key === 'paper') {
    if (rawVal === 'on') {
      settings.set('PAPER_TRADING', true);
      return sendTo(chatId, '✅ Paper trading <b>ON</b> — no real orders');
    }
    if (rawVal === 'off') {
      settings.set('PAPER_TRADING', false);
      return sendTo(chatId, '⚠️ Paper trading <b>OFF</b> — bot will place REAL orders!');
    }
    return sendTo(chatId, '❌ Use: /set paper on  or  /set paper off');
  }
  return sendTo(chatId, `❌ Unknown setting: <code>${key}</code>\nUse /set without args to see options.`);
}

// ─── Polling loop ─────────────────────────────────────────
let _getDash  = () => null;
let _exchange = null;
let _updateId = 0;

async function _fetchUpdates() {
  const { data } = await axios.get(
    `https://api.telegram.org/bot${TOKEN}/getUpdates`,
    { params: { offset: _updateId, timeout: 10, allowed_updates: ['message'] }, timeout: 15000 }
  );
  return data.result || [];
}

async function _pollLoop() {
  while (true) {
    try {
      const updates = await _fetchUpdates();
      for (const u of updates) {
        _updateId = u.update_id + 1;
        const raw    = (u.message?.text || '').trim();
        const chatId = u.message?.chat?.id;
        if (!raw || !chatId) continue;
        if (chatId.toString() !== CHAT_ID) continue;

        const lower  = raw.toLowerCase();
        const parts  = lower.split(/\s+/);
        const cmd    = parts[0];
        const args   = parts.slice(1);

        if (cmd === '/status' || cmd === '/s') {
          await _handleStatus(chatId);
        } else if (cmd === '/config' || cmd === '/c') {
          await sendTo(chatId, buildConfig());
        } else if (cmd === '/method') {
          await _handleMethod(chatId, args[0]);
        } else if (cmd === '/set') {
          await _handleSet(chatId, args);
        } else if (cmd === '/chart') {
          const d = _getDash();
          const sym = d?.currentSymbol || cfg.SYMBOL;
          await sendTo(chatId,
            `📈 <b>${sym} — Live Chart</b>\n<i>Opens TradingView in your browser</i>`,
            { reply_markup: JSON.stringify({ inline_keyboard: [[{ text: `📈 Open ${sym} on TradingView`, url: tvUrl(sym) }]] }) }
          );
        } else if (cmd === '/pause') {
          settings.set('PAUSED', true);
          await sendTo(chatId, '⏸️ <b>Bot PAUSED</b> — no new trades until /resume');
        } else if (cmd === '/resume') {
          settings.set('PAUSED', false);
          await sendTo(chatId, '▶️ <b>Bot RESUMED</b> — trading active again');
        } else if (cmd === '/help') {
          await sendTo(chatId,
            `📋 <b>APEX BOT COMMANDS</b>\n\n` +
            `<b>Info:</b>\n` +
            `/status  — live snapshot\n` +
            `/config  — current settings\n` +
            `/chart   — open TradingView chart\n\n` +
            `<b>Strategy:</b>\n` +
            `/method  — choose legendary trader method\n` +
            `/method auto | turtle | livermore | soros | ptj | druckenmiller\n\n` +
            `<b>Settings:</b>\n` +
            `/set risk 1.5  — risk per trade (%)\n` +
            `/set sl 2      — stop loss (%)\n` +
            `/set tp 4      — take profit (%)\n` +
            `/set confidence 70  — min AI confidence\n` +
            `/set paper on/off   — toggle paper mode\n\n` +
            `<b>Control:</b>\n` +
            `/pause   — pause new trades\n` +
            `/resume  — resume trading`
          );
        }
      }
    } catch (e) {
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
  console.log('[TELEGRAM] Polling started. Commands: /help /status /config /chart /method /set /pause /resume');
}

// ─── Alerts ───────────────────────────────────────────────
function alertOpen(side, symbol, price, quantity, stopLoss, takeProfit, druckMult) {
  const dir  = side === 'BUY' ? '🟢 LONG' : '🔴 SHORT';
  const mult = druckMult !== 1.0 ? `\n📐 <b>Druckenmiller:</b> ×${druckMult.toFixed(2)}` : '';
  const mode = settings.get('STRATEGY_MODE');
  const modeTag = mode !== 'auto' ? `\n🎯 Method: ${mode.toUpperCase()}` : '';
  send(
    `${dir} <b>OPENED — ${symbol}</b>\n` +
    `💰 @ $${price}  Qty: ${quantity}\n` +
    `🛡 SL: $${stopLoss.toFixed(5)}\n` +
    `🎯 TP: $${takeProfit.toFixed(5)}` + mult + modeTag,
    dashboardKeyboard(symbol)
  );
}

function alertClose(reason, symbol, side, entryPrice, closePrice, pnl, balance) {
  const icons = { TAKE_PROFIT: '🎯 TAKE PROFIT', STOP_LOSS: '🛑 STOP LOSS', AI_CLOSE: '🤖 AI CLOSE' };
  const dir   = side === 'BUY' ? 'LONG' : 'SHORT';
  send(
    `${pnl > 0 ? '✅' : '❌'} <b>${icons[reason] || reason} — ${symbol}</b>\n` +
    `📊 ${dir}  $${entryPrice} → $${closePrice}\n` +
    `💵 PnL: <b>${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)}</b>\n` +
    `💼 Balance: $${balance.toFixed(4)}`,
    dashboardKeyboard(symbol)
  );
}

function alertStop(reasons) {
  send(`🚨 <b>STRATEGY STOP</b>\n` + reasons.map(r => `• ${r}`).join('\n'));
}

function alertFiltered(action, livermore, turtle) {
  send(
    `⚡ <b>SIGNAL FILTERED</b>\n` +
    `AI: ${action} | Livermore: ${livermore} | Turtle: ${turtle}\n` +
    `<i>PTJ: Play defense</i>`
  );
}

function alertStart(symbol, timeframe, balance, mode) {
  send(
    `🚀 <b>APEX TRADE BOT STARTED</b>\n` +
    `📊 ${symbol} | ${timeframe} | $${balance.toFixed(2)}\n` +
    `⚙️ ${mode}\n` +
    (DASHBOARD_URL ? `🌐 Dashboard: ${DASHBOARD_URL}\n` : '') +
    `<i>Try /help for all commands</i>`,
    dashboardKeyboard(symbol)
  );
}

function alertHeartbeat(tickCount, balance, openPosition, currentPrice) {
  const paused = settings.get('PAUSED') ? ' ⏸️ PAUSED' : '';
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
  const hbSymbol = openPosition?.symbol || cfg.SYMBOL;
  send(
    `💓 <b>ACTIVE</b>  tick #${tickCount}${paused}\n` +
    `💼 Balance: $${balance.toFixed(4)}\n` +
    `${posLine}\n<i>/status for details · /chart for TradingView</i>`,
    dashboardKeyboard(hbSymbol)
  );
}

module.exports = {
  alertOpen, alertClose, alertStop, alertFiltered, alertStart, alertHeartbeat,
  startPolling, miniChart,
};
