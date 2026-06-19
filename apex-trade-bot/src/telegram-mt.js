/**
 * Telegram Multi-Tenant Handler
 * One bot token → many users. Each user has isolated settings + state.
 * No CHAT_ID restriction — any Telegram user can /start the bot.
 */
const axios     = require('axios');
const userStore = require('./userStore');
const botMgr    = require('./botManager');
const access    = require('./accessControl');
const payments  = require('./payments');

const TOKEN = (process.env.TELEGRAM_BOT_TOKEN || '').trim();
const NEEDS_PASS = new Set(['okx', 'kucoin', 'bitget', 'coinbase']);

// ─── HTTP ──────────────────────────────────────────────────────
async function send(chatId, text, extra = {}) {
  if (!TOKEN) return;
  try {
    await axios.post(`https://api.telegram.org/bot${TOKEN}/sendMessage`,
      { chat_id: chatId, text, parse_mode: 'HTML', ...extra }, { timeout: 6000 });
  } catch (e) { console.warn(`[TG-MT:${chatId}]`, e.message); }
}

async function answerCb(id) {
  try { await axios.post(`https://api.telegram.org/bot${TOKEN}/answerCallbackQuery`, { callback_query_id: id }, { timeout: 5000 }); } catch {}
}

// Shown to anyone not on the whitelist.
async function sendNoAccess(chatId) {
  return send(chatId,
    `🔒 <b>Private Trading Bot</b>\n\nThis bot is for paying members only.\n\n` +
    `Your ID: <code>${chatId}</code>\n\n` +
    `Send this ID to the owner to get access. 💎`
  );
}

// ─── Keyboards ─────────────────────────────────────────────────
const KB_START = { reply_markup: JSON.stringify({ inline_keyboard: [[
  { text: '📝 Paper Trading (no risk)', callback_data: 'setup:paper' },
  { text: '🔴 Real Exchange',           callback_data: 'setup:live'  },
]] }) };

const KB_EXCHANGE = { reply_markup: JSON.stringify({ inline_keyboard: [
  [{ text: '⚡ Binance',  callback_data: 'ex:binance' }, { text: '⚡ Bybit',   callback_data: 'ex:bybit'   }],
  [{ text: '⚡ OKX',     callback_data: 'ex:okx'     }, { text: '⚡ Kraken',  callback_data: 'ex:kraken'  }],
  [{ text: '⚡ KuCoin',  callback_data: 'ex:kucoin'  }, { text: '⚡ Bitget',  callback_data: 'ex:bitget'  }],
] }) };

const KB_SYMBOLS = { reply_markup: JSON.stringify({ inline_keyboard: [
  [{ text: '₿ BTC',  callback_data: 'sym:BTCUSDT'  }, { text: '⟠ ETH',  callback_data: 'sym:ETHUSDT'  }],
  [{ text: '◎ SOL',  callback_data: 'sym:SOLUSDT'  }, { text: '✕ XRP',  callback_data: 'sym:XRPUSDT'  }],
  [{ text: 'Ð DOGE', callback_data: 'sym:DOGEUSDT' }, { text: '△ ADA',  callback_data: 'sym:ADAUSDT'  }],
  [{ text: '⬡ BNB',  callback_data: 'sym:BNBUSDT'  }, { text: '☀ AVAX', callback_data: 'sym:AVAXUSDT' }],
] }) };

const SITE_URL = process.env.SITE_URL || 'https://aicashsystem.space';

function kbMenu(paused, symbol = 'BTCUSDT') {
  const chartUrl = `${SITE_URL}/chart?s=${encodeURIComponent(symbol)}`;
  return { reply_markup: JSON.stringify({ inline_keyboard: [
    [{ text: '📊 Status',  callback_data: 'c:status' }, { text: '📋 Trades', callback_data: 'c:trades' }],
    [{ text: '💎 Symbol',  callback_data: 'c:symbol' }, { text: '⚙️ Config', callback_data: 'c:config' }],
    [{ text: '🎯 Method',  callback_data: 'c:method' }, { text: '❓ Help',   callback_data: 'c:help'   }],
    [{ text: '📈 Live Chart', web_app: { url: chartUrl } }],
    [paused
      ? { text: '▶️ Start Trading', callback_data: 'c:resume' }
      : { text: '⏸ Pause Bot',     callback_data: 'c:pause'  }],
  ] }) };
}

// ─── Alert dispatcher ──────────────────────────────────────────
function makeAlertFn(chatId) {
  return async (type, data) => {
    if (type === 'trade_open') {
      const dir = data.side === 'BUY' ? '🟢 LONG' : '🔴 SHORT';
      const mult = data.druckMult !== 1.0 ? `\n📐 Druckenmiller: ×${data.druckMult.toFixed(2)}` : '';
      await send(chatId,
        `${dir} <b>OPENED — ${data.symbol}</b>\n` +
        `💰 Entry: $${data.price.toFixed(4)}  Qty: ${data.qty}\n` +
        `🛡 SL: $${data.stopLoss.toFixed(4)}  🎯 TP: $${data.takeProfit.toFixed(4)}${mult}`
      );
    } else if (type === 'trade_close') {
      const pnlStr  = `${data.pnl >= 0 ? '+' : ''}$${data.pnl.toFixed(4)}`;
      const icons   = { TAKE_PROFIT: '🎯 TAKE PROFIT', STOP_LOSS: '🛑 STOP LOSS', AI_CLOSE: '🤖 AI CLOSE' };
      await send(chatId,
        `${data.pnl > 0 ? '✅' : '❌'} <b>${icons[data.reason] || data.reason} — ${data.symbol}</b>\n` +
        `$${data.entryPrice.toFixed(4)} → $${data.exitPrice.toFixed(4)}\n` +
        `PnL: <b>${pnlStr}</b>  💼 Balance: $${data.balance.toFixed(2)}`
      );
    } else if (type === 'heartbeat') {
      const p = data.openPosition;
      const pos = p
        ? `${p.side === 'BUY' ? '🟢' : '🔴'} ${p.symbol} @ $${p.entryPrice}  PnL: ${p.currentPnl >= 0 ? '+' : ''}$${p.currentPnl?.toFixed(4)}`
        : '📭 No position';
      await send(chatId, `💓 Tick #${data.tickCount}  💼 $${data.balance.toFixed(2)}\n${pos}\n<i>/menu for controls</i>`);
    } else if (type === 'strategy_stop') {
      await send(chatId,
        `🚨 <b>STRATEGY STOP</b>\n${data.reasons.map(r => `• ${r}`).join('\n')}\n\n<i>/resume when conditions improve.</i>`
      );
    } else if (type === 'groq_error') {
      await send(chatId, data.msg);
    }
  };
}

// ─── Status / config builders ──────────────────────────────────
function buildStatus(user, ctx) {
  const s    = ctx?.state || user.state;
  const set  = ctx?.settings || user.settings;
  const pct  = s.startBalance > 0 ? ((s.paperBalance - s.startBalance) / s.startBalance * 100).toFixed(2) : '0.00';
  const wins = (s.trades || []).filter(t => t.win).length;
  const tot  = (s.trades || []).length;
  const wr   = tot > 0 ? ((wins / tot) * 100).toFixed(0) + '%' : '—';
  const paused = set.PAUSED ? '⏸️ <b>PAUSED</b>' : '▶️ <b>ACTIVE</b>';
  let pos = '📭 No open position';
  if (s.openPosition) {
    const p = s.openPosition;
    pos = `${p.side === 'BUY' ? '🟢' : '🔴'} ${p.side} <b>${p.symbol}</b>\n  Entry: $${p.entryPrice}  PnL: <b>${p.currentPnl >= 0 ? '+' : ''}$${p.currentPnl?.toFixed(4) ?? '—'}</b>`;
  }
  const sig = s.lastSignal;
  const sigLine = sig
    ? `🤖 Last AI signal: <b>${sig.action}</b>  ${sig.confidence}% conf  ${sig.criteriaScore}/5 criteria\n   <i>${sig.reasoning?.slice(0, 90) || '—'}</i>\n`
    : `🤖 AI signal: <i>waiting for first tick…</i>\n`;
  return (
    `⚡ <b>APEX TRADE BOT</b>  📝 PAPER  ${paused}\n━━━━━━━━━━━━━━━━━━━━\n` +
    `💰 Balance: <b>$${s.paperBalance.toFixed(2)}</b>  (${parseFloat(pct) >= 0 ? '+' : ''}${pct}%)\n\n` +
    `${pos}\n\n` +
    `${sigLine}\n` +
    `📈 ${tot} trades · ${wins}W/${tot - wins}L · WR: ${wr}\n` +
    `🎯 Symbol: <b>${set.SYMBOL}</b>  ⏱️ Last tick: ${s.lastTick || 'never'}`
  );
}

function buildConfig(user, ctx) {
  const s = ctx?.settings || user.settings;
  return (
    `⚙️ <b>CONFIGURATION</b>\n━━━━━━━━━━━━━━━━━━━━\n` +
    `💎 Symbol: <b>${s.SYMBOL}</b>\n` +
    `🎯 Method: <b>${s.STRATEGY_MODE}</b>\n` +
    `💸 Risk/trade: <b>${(s.RISK_PER_TRADE * 100).toFixed(1)}%</b>\n` +
    `🛡 SL: <b>${(s.STOP_LOSS_PCT * 100).toFixed(1)}%</b>  🎯 TP: <b>${(s.TAKE_PROFIT_PCT * 100).toFixed(1)}%</b>\n` +
    `🧠 Min confidence: <b>${s.MIN_CONFIDENCE}%</b>  Criteria: <b>${s.MIN_CRITERIA}/5</b>\n\n` +
    `<i>Change with: /symbol /risk /sl /tp /confidence /method</i>`
  );
}

// ─── Completes setup after all steps (including optional Groq key) ─
async function finishSetup(chatId) {
  const u = userStore.load(chatId);
  u.setupStep = 'done'; u.active = false;
  userStore.save(chatId, u);
  if (u.pendingMode === 'paper') {
    return send(chatId,
      `✅ <b>Paper Account Ready!</b>\n💰 Virtual balance: <b>$100</b>\n📊 Symbol: <b>${u.settings.SYMBOL}</b>\n\n` +
      `Press <b>▶️ Start Trading</b> when ready.\n<i>Paper mode = real market data, zero real money risk.</i>`,
      kbMenu(true, u.settings.SYMBOL)
    );
  }
  return send(chatId,
    `✅ <b>Setup Complete!</b>\n\nExchange: <b>${u.exchange?.toUpperCase()}</b>\n` +
    `<i>Press ▶️ Start Trading when ready!</i>`,
    kbMenu(true, u.settings.SYMBOL)
  );
}

// ─── Setup flow ────────────────────────────────────────────────
async function handleSetupCb(chatId, data) {
  const u = userStore.load(chatId);

  if (data === 'setup:paper') {
    u.usePaper = true; u.state.startBalance = 100; u.state.paperBalance = 100;
    u.pendingMode = 'paper'; u.setupStep = 'groq';
    userStore.save(chatId, u);
    return send(chatId,
      `✅ Paper mode selected!\n\n` +
      `🤖 <b>Last step — AI Key (free)</b>\n\n` +
      `The bot uses Groq AI to analyze the market.\n` +
      `Get your <b>free key</b> at <b>console.groq.com</b> → API Keys → Create Key\n\n` +
      `Then paste it here, or tap Skip to use basic signals.`,
      { reply_markup: JSON.stringify({ inline_keyboard: [[{ text: '⏭ Skip for now', callback_data: 'setup:skipgroq' }]] }) }
    );
  }

  if (data === 'setup:live') {
    u.setupStep = 'exchange'; userStore.save(chatId, u);
    return send(chatId, `🔴 <b>Real Trading Setup</b>\n\nWhich exchange do you use?`, KB_EXCHANGE);
  }

  if (data === 'setup:skipgroq') {
    return finishSetup(chatId);
  }

  if (data.startsWith('ex:')) {
    const ex = data.replace('ex:', '');
    u.exchange = ex; u.setupStep = 'apikey'; userStore.save(chatId, u);
    return send(chatId,
      `✅ Exchange: <b>${ex.toUpperCase()}</b>\n\n` +
      `Now send me your <b>API Key</b>.\n\n` +
      `<i>⚠️ Enable Read + Spot Trading only.\nNEVER enable Withdrawals.</i>`
    );
  }
}

async function handleSetupInput(chatId, text) {
  const u = userStore.load(chatId);

  if (u.setupStep === 'groq') {
    const key = text.trim();
    if (key.startsWith('gsk_') && key.length > 20) {
      u.groqKey = userStore.encrypt(key);
      userStore.save(chatId, u);
      await send(chatId, `✅ <b>Groq key saved!</b> AI-powered signals activated.`);
    } else {
      await send(chatId, `⚠️ That doesn't look like a valid Groq key (should start with <code>gsk_</code>). Skipping for now — you can add it later with /groq`);
    }
    return finishSetup(chatId);
  }

  if (u.setupStep === 'apikey') {
    u.apiKeyEnc = userStore.encrypt(text.trim());
    u.setupStep = 'apisecret';
    userStore.save(chatId, u);
    return send(chatId, `✅ API Key saved.\n\nNow send your <b>API Secret</b>:`);
  }

  if (u.setupStep === 'apisecret') {
    u.apiSecretEnc = userStore.encrypt(text.trim());
    if (NEEDS_PASS.has(u.exchange)) {
      u.setupStep = 'passphrase'; userStore.save(chatId, u);
      return send(chatId, `✅ API Secret saved.\n\nNow send your <b>Passphrase</b> (required for ${u.exchange.toUpperCase()}):`);
    }
    u.pendingMode = 'live'; u.setupStep = 'groq'; userStore.save(chatId, u);
    return send(chatId,
      `✅ Exchange keys saved!\n\n` +
      `🤖 <b>Last step — AI Key (free)</b>\n\n` +
      `Get your free key at <b>console.groq.com</b> → API Keys → Create Key\n\nPaste it here or tap Skip.`,
      { reply_markup: JSON.stringify({ inline_keyboard: [[{ text: '⏭ Skip for now', callback_data: 'setup:skipgroq' }]] }) }
    );
  }

  if (u.setupStep === 'passphrase') {
    u.apiPassEnc = userStore.encrypt(text.trim());
    u.pendingMode = 'live'; u.setupStep = 'groq'; userStore.save(chatId, u);
    return send(chatId,
      `✅ Passphrase saved!\n\n` +
      `🤖 <b>Last step — AI Key (free)</b>\n\n` +
      `Get your free key at <b>console.groq.com</b> → API Keys → Create Key\n\nPaste it here or tap Skip.`,
      { reply_markup: JSON.stringify({ inline_keyboard: [[{ text: '⏭ Skip for now', callback_data: 'setup:skipgroq' }]] }) }
    );
  }
}

// ─── Admin commands (whitelist control) ───────────────────────
async function handleAdminCmd(chatId, cmd, args) {
  if (cmd === '/users') {
    const clients = access.listAllowed();
    const admins  = access.listAdmins();
    return send(chatId,
      `👥 <b>ACCESS LIST</b>\n━━━━━━━━━━━━━━━━━━━━\n` +
      `👑 Admins: ${admins.map(a => `<code>${a}</code>`).join(', ') || '—'}\n\n` +
      `✅ Paying clients (${clients.length}):\n` +
      (clients.map(a => `• <code>${a}</code>`).join('\n') || '— none yet —') +
      `\n\n<i>/grant ID — give access\n/revoke ID — remove access</i>`
    );
  }

  if (cmd === '/grant') {
    if (!args[0]) return send(chatId, `Usage: <code>/grant 123456789</code>\n(the client's ID, shown when they message the bot)`);
    const id = args[0].trim();
    const ok = access.grant(id);
    if (ok) { try { await send(id, `✅ <b>Access granted!</b>\n\nSend /start to set up your trading bot. 🚀`); } catch {} }
    return send(chatId, ok ? `✅ Granted access to <code>${id}</code>` : `ℹ️ <code>${id}</code> already has access.`);
  }

  if (cmd === '/revoke') {
    if (!args[0]) return send(chatId, `Usage: <code>/revoke 123456789</code>`);
    const id = args[0].trim();
    const ok = access.revoke(id);
    if (ok) { try { await botMgr.stop(id); } catch {} try { await send(id, `🚫 Your access has been removed. Contact the owner to renew.`); } catch {} }
    return send(chatId, ok ? `🚫 Revoked <code>${id}</code> (bot stopped).` : `ℹ️ <code>${id}</code> was not in the list.`);
  }

  if (cmd === '/admin') {
    return send(chatId, `👑 <b>ADMIN PANEL</b>\n\n/users — list access\n/grant ID — add paying client\n/revoke ID — remove client`);
  }
}

// ─── Commands ──────────────────────────────────────────────────
async function handleCmd(chatId, cmd, args) {
  const u   = userStore.load(chatId);
  const ctx = botMgr.getCtx(chatId);

  if (cmd === '/start' || cmd === '/setup') {
    if (u.setupStep === 'done') return send(chatId, `⚡ <b>APEX TRADE BOT</b> — your bot is ready!`, kbMenu(u.settings.PAUSED, u.settings.SYMBOL));
    userStore.save(chatId, { ...u, setupStep: 'start' });
    return send(chatId,
      `⚡ <b>Welcome to APEX TRADE BOT!</b>\n\nAI + legendary trader strategies. Automatic crypto trading.\n\nHow do you want to start?`,
      KB_START
    );
  }

  if (u.setupStep !== 'done') return send(chatId, `⏳ Setup not complete. Send /start to begin.`);

  const upd = (key, val) => {
    u.settings[key] = val;
    if (ctx) ctx.settings[key] = val;
    userStore.save(chatId, u);
  };

  switch (cmd) {
    case '/groq': {
      const key = args[0]?.trim();
      if (!key || !key.startsWith('gsk_')) {
        return send(chatId,
          `🤖 <b>Set your Groq API Key</b>\n\n` +
          `Get a free key at <b>console.groq.com</b> → API Keys → Create Key\n\n` +
          `Then send: <code>/groq gsk_YOUR_KEY_HERE</code>\n\n` +
          `<i>Your key is stored encrypted and used only for YOUR trades.</i>`
        );
      }
      u.groqKey = userStore.encrypt(key);
      userStore.save(chatId, u);
      if (ctx) ctx.userData.groqKeyDec = key;
      return send(chatId, `✅ <b>Groq key saved!</b> AI signals are now powered by your personal key.`);
    }
    case '/menu': case '/m':
      return send(chatId, `📲 <b>APEX BOT — Control Panel</b>`, kbMenu(u.settings.PAUSED, u.settings.SYMBOL));
    case '/status': case '/s':
      return send(chatId, buildStatus(u, ctx));
    case '/config': case '/c':
      return send(chatId, buildConfig(u, ctx));
    case '/trades': case '/t': {
      const list = (ctx?.state.trades || u.state.trades).slice(0, 10);
      if (!list.length) return send(chatId, '📭 No trades yet — /resume to start trading.');
      const rows = list.map(t => `${t.win ? '✅' : '❌'} ${t.side} <b>${t.symbol}</b>  $${t.entry}→$${t.exit}  <b>${t.pnl >= 0 ? '+' : ''}$${t.pnl}</b>`);
      return send(chatId, `📋 <b>LAST ${list.length} TRADES</b>\n━━━━━━━━━━━━━━━━━━━━\n` + rows.join('\n'));
    }
    case '/symbol':
      if (!args[0]) return send(chatId, `💎 <b>Choose trading pair:</b>\nCurrent: <b>${u.settings.SYMBOL}</b>`, KB_SYMBOLS);
      upd('SYMBOL', args[0].toUpperCase());
      return send(chatId, `💎 Symbol → <b>${args[0].toUpperCase()}</b>`);
    case '/method': {
      const VALID = ['auto','turtle','livermore','soros','ptj','druckenmiller'];
      if (!args[0] || !VALID.includes(args[0])) return send(chatId,
        `🎯 <b>Method</b> (current: ${u.settings.STRATEGY_MODE})\n\n` +
        `/method auto · turtle · livermore · soros · ptj · druckenmiller`
      );
      upd('STRATEGY_MODE', args[0]);
      return send(chatId, `🎯 Method → <b>${args[0].toUpperCase()}</b>`);
    }
    case '/risk': { const v = parseFloat(args[0]); if (isNaN(v)||v<=0||v>10) return send(chatId,'❌ /risk 5  (0.1–10%)'); upd('RISK_PER_TRADE', v/100); return send(chatId, `💸 Risk/trade → <b>${v}%</b>`); }
    case '/sl':   { const v = parseFloat(args[0]); if (isNaN(v)||v<=0||v>20) return send(chatId,'❌ /sl 1.6  (0.1–20%)'); upd('STOP_LOSS_PCT', v/100); return send(chatId, `🛡 Stop Loss → <b>${v}%</b>`); }
    case '/tp':   { const v = parseFloat(args[0]); if (isNaN(v)||v<=0||v>50) return send(chatId,'❌ /tp 3.2  (0.1–50%)'); upd('TAKE_PROFIT_PCT', v/100); return send(chatId, `🎯 Take Profit → <b>${v}%</b>`); }
    case '/confidence': { const v = parseInt(args[0]); if (isNaN(v)||v<50||v>99) return send(chatId,'❌ /confidence 70  (50–99)'); upd('MIN_CONFIDENCE', v); return send(chatId, `🧠 Min confidence → <b>${v}%</b>`); }
    case '/pause':
      upd('PAUSED', true);
      return send(chatId, `⏸️ <b>Bot PAUSED</b> — /resume to restart.`);
    case '/resume': {
      upd('PAUSED', false);
      if (!botMgr.isRunning(chatId)) {
        u.active = true; userStore.save(chatId, u);
        await botMgr.start(chatId, makeAlertFn(chatId));
      }
      return send(chatId, `▶️ <b>Bot ACTIVE</b> — trading every minute! 🚀`, kbMenu(false, u.settings.SYMBOL));
    }
    case '/help':
      return send(chatId,
        `📋 <b>APEX BOT COMMANDS</b>\n\n` +
        `<b>Navigation:</b>\n/menu · /status · /config · /trades\n\n` +
        `<b>Symbol & Strategy:</b>\n/symbol BTCUSDT\n/method auto|turtle|livermore|soros|ptj|druckenmiller\n\n` +
        `<b>Risk Settings:</b>\n/risk 5 — % per trade\n/sl 1.6 — stop loss %\n/tp 3.2 — take profit %\n/confidence 70 — min AI confidence\n\n` +
        `<b>Control:</b>\n/pause · /resume\n\n` +
        `<b>AI Key (free):</b>\n/groq gsk_YOUR_KEY — set personal Groq key\nGet free key: console.groq.com`
      );
    default:
      return send(chatId, `❓ Unknown command. Use /menu or /help.`);
  }
}

// ─── Callbacks ─────────────────────────────────────────────────
async function handleCb(chatId, data) {
  const u   = userStore.load(chatId);
  const ctx = botMgr.getCtx(chatId);

  if (data.startsWith('setup:') || data.startsWith('ex:')) return handleSetupCb(chatId, data);

  if (data.startsWith('sym:')) {
    const sym = data.replace('sym:', '');
    u.settings.SYMBOL = sym;
    if (ctx) ctx.settings.SYMBOL = sym;
    userStore.save(chatId, u);
    return send(chatId, `💎 Symbol → <b>${sym}</b>`, kbMenu(u.settings.PAUSED, u.settings.SYMBOL));
  }

  const upd = (key, val) => { u.settings[key] = val; if (ctx) ctx.settings[key] = val; userStore.save(chatId, u); };

  switch (data) {
    case 'c:status': return send(chatId, buildStatus(u, ctx));
    case 'c:config': return send(chatId, buildConfig(u, ctx));
    case 'c:symbol': return send(chatId, `💎 Choose trading pair:\nCurrent: <b>${u.settings.SYMBOL}</b>`, KB_SYMBOLS);
    case 'c:trades': {
      const list = (ctx?.state.trades || u.state.trades).slice(0, 10);
      if (!list.length) return send(chatId, '📭 No trades yet.');
      return send(chatId, `📋 <b>TRADES</b>\n` + list.map(t => `${t.win ? '✅' : '❌'} ${t.side} <b>${t.symbol}</b>  <b>${t.pnl >= 0 ? '+' : ''}$${t.pnl}</b>`).join('\n'));
    }
    case 'c:method':
      return send(chatId, `🎯 Method (current: <b>${u.settings.STRATEGY_MODE}</b>)\n\n/method auto · turtle · livermore · soros · ptj · druckenmiller`);
    case 'c:help':
      return handleCmd(chatId, '/help', []);
    case 'c:pause':
      upd('PAUSED', true);
      return send(chatId, `⏸️ <b>Bot PAUSED</b>`, kbMenu(true, u.settings.SYMBOL));
    case 'c:resume':
      upd('PAUSED', false);
      if (!botMgr.isRunning(chatId)) { u.active = true; userStore.save(chatId, u); await botMgr.start(chatId, makeAlertFn(chatId)); }
      return send(chatId, `▶️ <b>Bot ACTIVE</b> — trading every minute! 🚀`, kbMenu(false, u.settings.SYMBOL));
  }
}

// ─── Polling ────────────────────────────────────────────────────
let _id = 0;

async function _poll() {
  const { data } = await axios.get(`https://api.telegram.org/bot${TOKEN}/getUpdates`, {
    params: { offset: _id, timeout: 10, allowed_updates: ['message', 'callback_query'] },
    timeout: 15000,
  });
  return data.result || [];
}

async function _handle(u) {
  _id = u.update_id + 1;

  if (u.callback_query) {
    const chatId = String(u.callback_query.message?.chat?.id || '');
    await answerCb(u.callback_query.id);
    if (!chatId) return;
    if (!access.isAllowed(chatId)) return sendNoAccess(chatId);
    await handleCb(chatId, u.callback_query.data || '');
    return;
  }

  const raw    = (u.message?.text || '').trim();
  const chatId = String(u.message?.chat?.id || '');
  if (!raw || !chatId) return;

  const parts = raw.split(/\s+/);
  const cmd   = parts[0].toLowerCase();

  // ── Access control gate ──
  // Bootstrap: the very first user to message becomes the admin/owner.
  if (!access.hasAnyAdmin()) {
    access.claimAdmin(chatId);
    await send(chatId,
      `👑 <b>You are now the OWNER of this bot.</b>\nYour ID: <code>${chatId}</code>\n\n` +
      `Give clients access with <code>/grant THEIR_ID</code>\nList them with /users · remove with /revoke ID`
    );
  }

  // Admin-only whitelist commands
  if (access.isAdmin(chatId) && ['/grant', '/revoke', '/users', '/admin'].includes(cmd)) {
    return handleAdminCmd(chatId, cmd, parts.slice(1));
  }

  // Auto-activation: client arrives via paid deep-link  /start <token>
  if (!access.isAllowed(chatId) && cmd === '/start' && parts[1] && payments.enabled()) {
    const token = parts[1].trim();
    if (access.isTokenClaimed(token)) {
      return send(chatId, `⚠️ This activation link was already used on another account. Contact the owner if this is a mistake.`);
    }
    await send(chatId, `⏳ Verifying your payment…`);
    const paid = await payments.verifyPaidToken(token);
    if (paid) {
      access.grant(chatId);
      access.claimToken(token, chatId);
      await send(chatId, `✅ <b>Payment confirmed — access activated!</b>\n\nWelcome aboard. 🚀`);
      // fall through to normal /start setup below
    } else {
      return send(chatId,
        `❌ <b>Couldn't confirm payment yet.</b>\n\n` +
        `If you just paid, wait ~1 minute and tap the activation link again.\n\n` +
        `If the problem persists, send this ID to the owner: <code>${chatId}</code>`
      );
    }
  }

  // Block everyone not on the whitelist
  if (!access.isAllowed(chatId)) return sendNoAccess(chatId);

  const user = userStore.load(chatId);

  // During setup, route free text to setup input handler
  if (user.setupStep !== 'done' && user.setupStep !== 'start' && !raw.startsWith('/')) {
    await handleSetupInput(chatId, raw);
    return;
  }

  await handleCmd(chatId, cmd, parts.slice(1));
}

async function startPolling() {
  if (!TOKEN) { console.warn('[TG-MT] No TELEGRAM_BOT_TOKEN — polling disabled.'); return; }

  try { await axios.post(`https://api.telegram.org/bot${TOKEN}/deleteWebhook`, { drop_pending_updates: true }, { timeout: 5000 }); } catch {}

  // Restore previously active users
  for (const uid of userStore.list()) {
    const u = userStore.load(uid);
    if (u.active && u.setupStep === 'done') {
      console.log(`[TG-MT] Restoring bot for ${uid}`);
      await botMgr.start(uid, makeAlertFn(uid));
    }
  }

  console.log('[TG-MT] Polling started. Send your bot /start to begin!');

  while (true) {
    try {
      const updates = await _poll();
      for (const u of updates) await _handle(u);
    } catch (e) {
      if (e.response?.status === 409) {
        console.warn('[TG-MT] 409 — another instance polling, waiting 30s...');
        await new Promise(r => setTimeout(r, 30000));
      } else {
        console.warn('[TG-MT] Poll error:', e.message);
        await new Promise(r => setTimeout(r, 5000));
      }
    }
    await new Promise(r => setTimeout(r, 1000));
  }
}

module.exports = { startPolling, makeAlertFn, send };
