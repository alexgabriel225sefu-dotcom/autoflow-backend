/**
 * APEX TRADE BOT — Telegram Alerts + Interactive Bot Controls
 * Commands: /menu /status /trades /chart /config /method /set /pause /resume /app /help
 */
const axios    = require('axios');
const cfg      = require('./config');
const settings = require('./settings');

const TOKEN         = (process.env.TELEGRAM_BOT_TOKEN || '').trim();
const CHAT_ID       = (process.env.TELEGRAM_CHAT_ID   || '').trim();
const DASHBOARD_URL = (process.env.DASHBOARD_URL       || '').trim();

// ─── TradingView URL ──────────────────────────────────────
const TV_EX = { binance:'BINANCE', bybit:'BYBIT', okx:'OKX', kraken:'KRAKEN', kucoin:'KUCOIN', mexc:'MEXC', coinbase:'COINBASE', bitget:'BITGET' };
function tvUrl(sym) { return `https://www.tradingview.com/chart/?symbol=${TV_EX[cfg.EXCHANGE?.toLowerCase()]||'BINANCE'}:${sym}`; }

// ─── Send helpers ─────────────────────────────────────────
async function send(text, extra = {}) {
  if (!TOKEN || !CHAT_ID) return;
  try { await axios.post(`https://api.telegram.org/bot${TOKEN}/sendMessage`, { chat_id: CHAT_ID, text, parse_mode: 'HTML', ...extra }, { timeout: 6000 }); }
  catch (e) { console.warn('[TG] Send error:', e.message, e.response?.data?.description || ''); }
}
async function sendTo(chatId, text, extra = {}) {
  if (!TOKEN) return;
  try { await axios.post(`https://api.telegram.org/bot${TOKEN}/sendMessage`, { chat_id: chatId, text, parse_mode: 'HTML', ...extra }, { timeout: 6000 }); }
  catch (e) { console.warn('[TG] Send error:', e.message, e.response?.data?.description || ''); }
}
async function answerCb(id) {
  try { await axios.post(`https://api.telegram.org/bot${TOKEN}/answerCallbackQuery`, { callback_query_id: id }, { timeout: 5000 }); } catch {}
}

// ─── Mini chart (Unicode blocks) ─────────────────────────
function miniChart(closes) {
  const sl = closes.slice(-Math.min(closes.length, 24));
  const min = Math.min(...sl), range = Math.max(...sl) - min || 1;
  return sl.map(c => '▁▂▃▄▅▆▇█'[Math.min(7, Math.floor(((c - min) / range) * 8))]).join('');
}

// ─── Keyboards ────────────────────────────────────────────
function dashboardKeyboard(symbol) {
  const btns = [];
  if (DASHBOARD_URL) btns.push({ text: '🚀 Open App', web_app: { url: DASHBOARD_URL } });
  if (symbol)        btns.push({ text: '📈 TradingView', url: tvUrl(symbol) });
  return btns.length ? { reply_markup: JSON.stringify({ inline_keyboard: [btns] }) } : {};
}
function menuKeyboard() {
  const rows = [
    [{ text: '📊 Status',  callback_data: 'menu:status'  }, { text: '⚙️ Config',  callback_data: 'menu:config'  }],
    [{ text: '📋 Trades',  callback_data: 'menu:trades'  }, { text: '📈 Chart',   callback_data: 'menu:chart'   }],
    [{ text: '💎 Symbol',  callback_data: 'menu:symbol'  }, { text: '🎯 Method',  callback_data: 'menu:method'  }],
    [{ text: '⏸ Pause',   callback_data: 'menu:pause'   }, { text: '▶️ Start',   callback_data: 'menu:resume'  }],
  ];
  if (DASHBOARD_URL) rows.push([{ text: '🚀 Open App', web_app: { url: DASHBOARD_URL } }]);
  return { reply_markup: JSON.stringify({ inline_keyboard: rows }) };
}

function symbolKeyboard() {
  return {
    reply_markup: JSON.stringify({
      inline_keyboard: [
        [{ text: '₿ BTCUSDT',  callback_data: 'symbol:BTCUSDT'  }, { text: '⟠ ETHUSDT',  callback_data: 'symbol:ETHUSDT'  }],
        [{ text: '◎ SOLUSDT',  callback_data: 'symbol:SOLUSDT'  }, { text: '⬡ BNBUSDT',  callback_data: 'symbol:BNBUSDT'  }],
        [{ text: '✕ XRPUSDT',  callback_data: 'symbol:XRPUSDT'  }, { text: 'Ð DOGEUSDT', callback_data: 'symbol:DOGEUSDT' }],
        [{ text: '△ AVAXUSDT', callback_data: 'symbol:AVAXUSDT' }, { text: '◈ ADAUSDT',  callback_data: 'symbol:ADAUSDT'  }],
      ],
    }),
  };
}

// ─── Fear & Greed Index ───────────────────────────────────
async function fetchFearGreed() {
  try {
    const { data } = await axios.get('https://api.alternative.me/fng/', { timeout: 5000 });
    const d   = data.data[0];
    const val = parseInt(d.value);
    const icon = val >= 75 ? '🔥' : val >= 55 ? '😊' : val >= 45 ? '😐' : val >= 25 ? '😨' : '❄️';
    return `${icon} ${d.value_classification} (${val}/100)`;
  } catch { return null; }
}

// ─── Message builders ─────────────────────────────────────
function buildStatus(dash, chart = '') {
  const pnlPct  = dash.startBalance > 0 ? ((dash.balance - dash.startBalance) / dash.startBalance * 100).toFixed(2) : '0.00';
  const pnlSign = parseFloat(pnlPct) >= 0 ? '+' : '';
  const wins    = (dash.trades||[]).filter(t=>t.win).length;
  const total   = (dash.trades||[]).length;
  const winRate = total > 0 ? ((wins/total)*100).toFixed(0)+'%' : '—';
  const chartLine = chart ? `\n<code>${chart}</code>  <b>$${dash.currentPrice?.toFixed(4)||'—'}</b>` : '';
  const mode   = settings.get('STRATEGY_MODE');
  const paused = settings.get('PAUSED') ? '\n⏸️ <b>PAUSED</b> — /resume to restart' : '';
  let posLine = '📭 No open position';
  if (dash.openPosition) {
    const dir = dash.openPosition.side === 'BUY' ? '🟢 LONG' : '🔴 SHORT';
    const pnl = dash.openPosition.currentPnl || 0;
    posLine = `${dir} <b>${dash.openPosition.symbol}</b>\n  Entry: $${dash.openPosition.entryPrice}  SL: $${dash.openPosition.stopLoss?.toFixed(4)}\n  PnL: <b>${pnl>=0?'+':''}$${pnl.toFixed(4)}</b>`;
  }
  return (
    `⚡ <b>APEX TRADE BOT</b>  ${dash.mode||''} · ${dash.exchange||''}\n` +
    `Method: <b>${mode.toUpperCase()}</b>${paused}\n━━━━━━━━━━━━━━━━━━━━\n` +
    `💰 Balance: <b>$${(dash.balance||0).toFixed(2)}</b>  (${pnlSign}${pnlPct}%)${chartLine}\n\n` +
    `${posLine}\n\n` +
    `📈 ${total} trades · ${wins}W/${total-wins}L · Win: ${winRate}\n⏱️ Last tick: ${dash.lastTick||'—'}`
  );
}

function buildConfig() {
  const s = settings.snapshot();
  const DESC = { auto:'🤖 Auto — all strategies', turtle:'🐢 Turtle breakout', livermore:'📐 Livermore pivot', soros:'💡 Soros momentum', ptj:'🛡️ PTJ defense', druckenmiller:'📊 Druckenmiller sizing' };
  return (
    `⚙️ <b>CURRENT CONFIGURATION</b>\n━━━━━━━━━━━━━━━━━━━━\n` +
    `🎯 Method: <b>${DESC[s.STRATEGY_MODE]||s.STRATEGY_MODE}</b>\n` +
    `💸 Risk/trade: <b>${(s.RISK_PER_TRADE*100).toFixed(1)}%</b>\n` +
    `🛡 Stop Loss: <b>${(s.STOP_LOSS_PCT*100).toFixed(1)}%</b>\n` +
    `🎯 Take Profit: <b>${(s.TAKE_PROFIT_PCT*100).toFixed(1)}%</b>\n` +
    `🧠 Min confidence: <b>${s.MIN_CONFIDENCE}%</b>\n` +
    `⏸️ Paused: <b>${s.PAUSED?'YES':'NO'}</b>\n\n<i>Edit with /set or /method — instant effect</i>`
  );
}

function buildTrades(trades) {
  if (!trades?.length) return '📭 No trades recorded yet.';
  const rows = trades.slice(0, 10).map(t => {
    const pnlStr = t.pnl >= 0 ? `+$${t.pnl.toFixed(2)}` : `-$${Math.abs(t.pnl).toFixed(2)}`;
    return `${t.win?'✅':'❌'} ${t.side} <b>${t.symbol}</b>  $${t.entry}→$${t.exit}  <b>${pnlStr}</b>`;
  });
  return `📋 <b>LAST ${Math.min(trades.length,10)} TRADES</b>\n━━━━━━━━━━━━━━━━━━━━\n` + rows.join('\n');
}

// ─── Daily report ─────────────────────────────────────────
async function sendDailyReport(dash) {
  if (!dash) return;
  const trades  = dash.trades || [];
  const wins    = trades.filter(t => t.win).length;
  const total   = trades.reduce((s, t) => s + t.pnl, 0);
  const best    = trades.reduce((b, t) => t.pnl > (b?.pnl ?? -Infinity) ? t : b, null);
  const worst   = trades.reduce((w, t) => t.pnl < (w?.pnl ?? Infinity)  ? t : w, null);
  const fg      = await fetchFearGreed();
  const totalStr = total >= 0 ? `+$${total.toFixed(2)}` : `-$${Math.abs(total).toFixed(2)}`;
  const date    = new Date().toLocaleDateString('en-US', { weekday:'short', month:'short', day:'numeric' });
  send(
    `📅 <b>DAILY REPORT — ${date}</b>\n━━━━━━━━━━━━━━━━━━━━\n` +
    `📊 Trades: ${trades.length}  ·  ${wins}W/${trades.length-wins}L\n` +
    `📈 Win rate: ${trades.length>0?((wins/trades.length)*100).toFixed(0)+'%':'—'}\n` +
    `💵 Total PnL: <b>${totalStr}</b>\n` +
    `💼 Balance: <b>$${(dash.balance||0).toFixed(2)}</b>\n` +
    (best  ? `🏆 Best: <b>+$${best.pnl.toFixed(2)}</b> (${best.symbol})\n`  : '') +
    (worst ? `💀 Worst: <b>$${worst.pnl.toFixed(2)}</b> (${worst.symbol})\n` : '') +
    (fg    ? `🧠 Market: ${fg}\n` : '') +
    `\n<i>Tomorrow is a new day — trade smart.</i>`,
    dashboardKeyboard(dash.currentSymbol)
  );
}

// ─── Command handlers ─────────────────────────────────────
async function _handleStatus(chatId) {
  const dash = _getDash();
  if (!dash?.exchange) return sendTo(chatId, '⏳ Bot is starting up...');
  let chart = '';
  try { if (_exchange) chart = miniChart((await _exchange.getCandles(dash.currentSymbol,'5m',24)).map(c=>c.close)); } catch {}
  await sendTo(chatId, buildStatus(dash, chart), dashboardKeyboard(dash.currentSymbol));
}

async function _handleMethod(chatId, arg) {
  const VALID = ['auto','turtle','livermore','soros','ptj','druckenmiller'];
  if (!arg || !VALID.includes(arg)) {
    return sendTo(chatId,
      `🎯 <b>Choose a trading method:</b>\n\n` +
      `/method auto — 🤖 All strategies (default)\n` +
      `/method turtle — 🐢 Turtle Breakout (R. Dennis)\n` +
      `/method livermore — 📐 Livermore Pivot Structure\n` +
      `/method soros — 💡 Soros Momentum / Reflexivity\n` +
      `/method ptj — 🛡️ PTJ Defense (high confidence only)\n` +
      `/method druckenmiller — 📊 Druckenmiller Sizing\n\n` +
      `<i>Current: <b>${settings.get('STRATEGY_MODE').toUpperCase()}</b></i>`
    );
  }
  settings.set('STRATEGY_MODE', arg);
  const EMOJI = { auto:'🤖', turtle:'🐢', livermore:'📐', soros:'💡', ptj:'🛡️', druckenmiller:'📊' };
  await sendTo(chatId, `${EMOJI[arg]} Method set to <b>${arg.toUpperCase()}</b> — active from next tick.`);
}

async function _handleSet(chatId, parts) {
  const [key, rawVal] = parts;
  if (!key || !rawVal) return sendTo(chatId,
    `⚙️ <b>Settings usage:</b>\n/set risk 1.5 · /set sl 2 · /set tp 4\n/set confidence 70 · /set paper on/off`
  );
  const setters = {
    risk:       v => { if (v<=0||v>10) throw '0.1–10'; settings.set('RISK_PER_TRADE',v/100); return `✅ Risk/trade → <b>${v}%</b>`; },
    sl:         v => { if (v<=0||v>20) throw '0.1–20'; settings.set('STOP_LOSS_PCT',v/100);  return `✅ Stop Loss → <b>${v}%</b>`; },
    tp:         v => { if (v<=0||v>50) throw '0.1–50'; settings.set('TAKE_PROFIT_PCT',v/100);return `✅ Take Profit → <b>${v}%</b>`; },
    confidence: v => { if (v<0||v>100) throw '0–100';  settings.set('MIN_CONFIDENCE',v);     return `✅ Min confidence → <b>${v}%</b>`; },
  };
  if (key === 'paper') {
    if (rawVal==='on')  { settings.set('PAPER_TRADING',true);  return sendTo(chatId,'✅ Paper trading <b>ON</b>'); }
    if (rawVal==='off') { settings.set('PAPER_TRADING',false); return sendTo(chatId,'⚠️ Paper trading <b>OFF</b> — REAL orders!'); }
    return sendTo(chatId,'❌ Use: /set paper on  or  /set paper off');
  }
  if (!setters[key]) return sendTo(chatId, `❌ Unknown: <code>${key}</code>. Use /set without args.`);
  try { const v = parseFloat(rawVal); if (isNaN(v)) throw 'number'; return sendTo(chatId, setters[key](v)); }
  catch (range) { return sendTo(chatId, `❌ ${key} must be ${range}`); }
}

// ─── Polling loop ─────────────────────────────────────────
let _getDash  = () => null;
let _exchange = null;
let _updateId = 0;

async function _fetchUpdates() {
  const { data } = await axios.get(
    `https://api.telegram.org/bot${TOKEN}/getUpdates`,
    { params: { offset: _updateId, timeout: 10, allowed_updates: ['message','callback_query'] }, timeout: 15000 }
  );
  return data.result || [];
}

async function _handleCallback(cb) {
  const chatId = cb.message?.chat?.id;
  await answerCb(cb.id);
  if (!chatId) return;
  const d   = cb.data;
  const sym = _getDash()?.currentSymbol || settings.get('SYMBOL');

  if (d === 'menu:status')  return _handleStatus(chatId);
  if (d === 'menu:config')  return sendTo(chatId, buildConfig());
  if (d === 'menu:trades')  return sendTo(chatId, buildTrades(_getDash()?.trades));
  if (d === 'menu:symbol')  return sendTo(chatId, `💎 <b>Choose trading pair:</b>\n<i>Current: <b>${settings.get('SYMBOL')}</b></i>`, symbolKeyboard());
  if (d === 'menu:method')  return _handleMethod(chatId, null);
  if (d === 'menu:chart')   return sendTo(chatId, `📈 <b>${sym}</b>`, { reply_markup: JSON.stringify({ inline_keyboard: [[{ text:`📈 Open ${sym} on TradingView`, url: tvUrl(sym) }]] }) });
  if (d === 'menu:pause')   { settings.set('PAUSED',true);  return sendTo(chatId,'⏸️ <b>Bot PAUSED</b> — no new trades until you press Start'); }
  if (d === 'menu:resume')  { settings.set('PAUSED',false); return sendTo(chatId,'▶️ <b>Bot STARTED</b> — trading active! Good luck 🚀'); }

  // Symbol selection buttons
  if (d.startsWith('symbol:')) {
    const newSym = d.replace('symbol:', '');
    settings.set('SYMBOL', newSym);
    return sendTo(chatId,
      `💎 Symbol set to <b>${newSym}</b> — active from next tick.\n\n` +
      `Now press <b>▶️ Start</b> in /menu when ready to trade.`,
      menuKeyboard()
    );
  }
}

async function _pollLoop() {
  // Clear any stale webhook so polling works cleanly after redeploy
  try {
    await axios.post(`https://api.telegram.org/bot${TOKEN}/deleteWebhook`, { drop_pending_updates: true }, { timeout: 5000 });
  } catch {}

  while (true) {
    try {
      const updates = await _fetchUpdates();
      for (const u of updates) {
        _updateId = u.update_id + 1;
        if (u.callback_query) {
          if (u.callback_query.message?.chat?.id?.toString() === CHAT_ID) await _handleCallback(u.callback_query);
          continue;
        }
        const raw    = (u.message?.text || '').trim();
        const chatId = u.message?.chat?.id;
        if (!raw || !chatId || chatId.toString() !== CHAT_ID) continue;
        const parts = raw.toLowerCase().split(/\s+/);
        const cmd   = parts[0];
        const args  = parts.slice(1);
        const sym   = _getDash()?.currentSymbol || cfg.SYMBOL;

        if      (cmd==='/status'||cmd==='/s')   await _handleStatus(chatId);
        else if (cmd==='/config'||cmd==='/c')   await sendTo(chatId, buildConfig());
        else if (cmd==='/trades'||cmd==='/t')   await sendTo(chatId, buildTrades(_getDash()?.trades));
        else if (cmd==='/menu'  ||cmd==='/m')   await sendTo(chatId, '📲 <b>APEX BOT — Control Panel</b>', menuKeyboard());
        else if (cmd==='/app') {
          if (!DASHBOARD_URL) { await sendTo(chatId,'❌ DASHBOARD_URL not set in Railway Variables.'); continue; }
          await sendTo(chatId,'🚀 <b>Apex Trade Bot</b>', { reply_markup: JSON.stringify({ inline_keyboard: [[{ text:'🚀 Open App', web_app:{ url: DASHBOARD_URL } }]] }) });
        }
        else if (cmd==='/chart')  await sendTo(chatId, `📈 <b>${sym}</b>`, { reply_markup: JSON.stringify({ inline_keyboard: [[{ text:`📈 Open ${sym} on TradingView`, url: tvUrl(sym) }]] }) });
        else if (cmd==='/symbol') {
          if (args[0]) {
            const newSym = args[0].toUpperCase();
            settings.set('SYMBOL', newSym);
            await sendTo(chatId, `💎 Symbol set to <b>${newSym}</b> — active from next tick.`);
          } else {
            await sendTo(chatId, `💎 <b>Choose trading pair:</b>\n<i>Current: <b>${settings.get('SYMBOL')}</b></i>`, symbolKeyboard());
          }
        }
        else if (cmd==='/method') await _handleMethod(chatId, args[0]);
        else if (cmd==='/set')    await _handleSet(chatId, args);
        else if (cmd==='/pause')  { settings.set('PAUSED',true);  await sendTo(chatId,'⏸️ <b>Bot PAUSED</b> — no new trades until /resume'); }
        else if (cmd==='/resume') { settings.set('PAUSED',false); await sendTo(chatId,'▶️ <b>Bot RESUMED</b> — trading active again'); }
        else if (cmd==='/help')   await sendTo(chatId,
          `📋 <b>APEX BOT COMMANDS</b>\n\n` +
          `<b>Quick access:</b>\n/menu · /app · /chart\n\n` +
          `<b>Info:</b>\n/status · /config · /trades\n\n` +
          `<b>Strategy:</b>\n/symbol — choose trading pair\n/method auto|turtle|livermore|soros|ptj|druckenmiller\n\n` +
          `<b>Settings:</b>\n/set risk 1.5 · sl 2 · tp 4 · confidence 70 · paper on/off\n\n` +
          `<b>Control:</b>\n/pause · /resume`
        );
      }
    } catch (e) {
      const status = e.response?.status;
      if (status === 409) {
        // Another instance is polling — wait for it to stop (Railway deploy overlap)
        console.warn('[TG] Poll 409 — previous instance still running, waiting 30s...');
        await new Promise(r => setTimeout(r, 30000));
      } else {
        console.warn('[TG] Poll error:', e.message, e.response?.data?.description || '');
        await new Promise(r => setTimeout(r, 5000));
      }
    }
    await new Promise(r => setTimeout(r, 2000));
  }
}

// ─── Daily report scheduler ───────────────────────────────
let _lastReportDate = '';
function _scheduleDailyReport(getDash) {
  setInterval(() => {
    const now = new Date();
    if (now.getHours() === 0 && now.getMinutes() === 0) {
      const dateStr = now.toDateString();
      if (dateStr !== _lastReportDate) { _lastReportDate = dateStr; sendDailyReport(getDash()); }
    }
  }, 60000);
}

function startPolling(getDash, exchange) {
  if (!TOKEN || !CHAT_ID) return;
  _getDash  = getDash;
  _exchange = exchange;
  _pollLoop();
  _scheduleDailyReport(getDash);
  console.log('[TELEGRAM] Polling started — /menu /status /trades /chart /config /method /set /pause /resume /app /help');
}

// ─── Alerts ───────────────────────────────────────────────
function alertOpen(side, symbol, price, quantity, stopLoss, takeProfit, druckMult) {
  const dir     = side === 'BUY' ? '🟢 LONG' : '🔴 SHORT';
  const mult    = druckMult !== 1.0 ? `\n📐 <b>Druckenmiller:</b> ×${druckMult.toFixed(2)}` : '';
  const mode    = settings.get('STRATEGY_MODE');
  const modeTag = mode !== 'auto' ? `\n🎯 Method: ${mode.toUpperCase()}` : '';
  send(`${dir} <b>OPENED — ${symbol}</b>\n💰 @ $${price}  Qty: ${quantity}\n🛡 SL: $${stopLoss.toFixed(5)}\n🎯 TP: $${takeProfit.toFixed(5)}${mult}${modeTag}`, dashboardKeyboard(symbol));
}

function alertClose(reason, symbol, side, entryPrice, closePrice, pnl, balance) {
  const icons = { TAKE_PROFIT:'🎯 TAKE PROFIT', STOP_LOSS:'🛑 STOP LOSS', AI_CLOSE:'🤖 AI CLOSE' };
  send(
    `${pnl>0?'✅':'❌'} <b>${icons[reason]||reason} — ${symbol}</b>\n` +
    `📊 ${side==='BUY'?'LONG':'SHORT'}  $${entryPrice} → $${closePrice}\n` +
    `💵 PnL: <b>${pnl>=0?'+':''}$${pnl.toFixed(4)}</b>\n💼 Balance: $${balance.toFixed(4)}`,
    dashboardKeyboard(symbol)
  );
}

function alertStop(reasons) {
  send(`🚨 <b>STRATEGY STOP</b>\n` + reasons.map(r=>`• ${r}`).join('\n'));
}

function alertFiltered(action, livermore, turtle) {
  send(`⚡ <b>SIGNAL FILTERED</b>\nAI: ${action} | Livermore: ${livermore} | Turtle: ${turtle}\n<i>PTJ: Play defense</i>`);
}

function alertStart(symbol, timeframe, balance, mode) {
  const s = settings.snapshot();
  send(
    `⚡ <b>APEX TRADE BOT — READY</b>\n` +
    `━━━━━━━━━━━━━━━━━━━━\n` +
    `⏸️ <b>Bot is PAUSED</b> — configure before trading!\n\n` +
    `<b>Step 1:</b> Choose your coin → /symbol\n` +
    `<b>Step 2:</b> Choose strategy → /method\n` +
    `<b>Step 3:</b> Review settings → /config\n` +
    `<b>Step 4:</b> Press ▶️ Start in /menu\n\n` +
    `━━━━━━━━━━━━━━━━━━━━\n` +
    `💎 Symbol: <b>${symbol}</b>  |  ⚙️ ${mode}\n` +
    `💸 Risk: <b>${(s.RISK_PER_TRADE*100).toFixed(1)}%</b>  ·  🛡 SL: <b>${(s.STOP_LOSS_PCT*100).toFixed(1)}%</b>  ·  🎯 TP: <b>${(s.TAKE_PROFIT_PCT*100).toFixed(1)}%</b>\n` +
    `💼 Balance: <b>$${balance.toFixed(2)}</b>\n\n` +
    `<i>When ready → /menu then press ▶️ Start</i>`,
    menuKeyboard()
  );
}

async function alertHeartbeat(tickCount, balance, openPosition, currentPrice) {
  const paused = settings.get('PAUSED') ? ' ⏸️ PAUSED' : '';
  const fg     = await fetchFearGreed();
  let posLine  = '📭 No open position';
  if (openPosition && currentPrice) {
    const dir = openPosition.side === 'BUY' ? 'LONG' : 'SHORT';
    const pnl = openPosition.side === 'BUY'
      ? (currentPrice - openPosition.entryPrice) * openPosition.quantity
      : (openPosition.entryPrice - currentPrice) * openPosition.quantity;
    posLine = `${openPosition.side==='BUY'?'🟢':'🔴'} ${dir} <b>${openPosition.symbol}</b> @ $${openPosition.entryPrice}\nPnL: <b>${pnl>=0?'+':''}$${pnl.toFixed(4)}</b>`;
  }
  send(
    `💓 <b>ACTIVE</b>  tick #${tickCount}${paused}\n` +
    `💼 Balance: $${balance.toFixed(4)}\n` +
    (fg ? `🧠 Sentiment: ${fg}\n` : '') +
    `${posLine}\n<i>/menu · /chart · /trades</i>`,
    dashboardKeyboard(openPosition?.symbol || cfg.SYMBOL)
  );
}

module.exports = {
  alertOpen, alertClose, alertStop, alertFiltered, alertStart, alertHeartbeat,
  startPolling, miniChart,
};
