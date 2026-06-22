/**
 * BotManager — manages per-user trading loops.
 * Each active user gets their own interval + context; isolated state.
 * Routes to real exchange (testnet/live) or paper based on user setup.
 */
const userStore = require('./userStore');
const runner    = require('./runner');
const paper     = require('./paperExchange');

const _loops = new Map(); // userId → { intervalId, ctx }

function _save(ctx) {
  const u = userStore.load(ctx.userId);
  u.state = ctx.state;
  userStore.save(ctx.userId, u);
}

// Returns the right exchange connector for this user.
// Paper mode → internal simulator. Real mode → live API with user's own keys.
function _makeExchange(user) {
  if (user.usePaper !== false) return paper;
  if (!user.exchange || !user.apiKeyEnc) return paper;
  const { apiKey, apiSecret } = userStore.getApiKeys(user.userId);
  if (!apiKey || !apiSecret) return paper;
  try {
    if (user.exchange === 'binance') {
      return require('./binance').createConnector(apiKey, apiSecret);
    }
  } catch (e) {
    console.warn(`[BotMgr:${user.userId}] Exchange init failed:`, e.message);
  }
  return paper;
}

async function start(userId, alertFn) {
  if (_loops.has(userId)) return;

  const user = userStore.load(userId);
  if (!user.active) return;

  const exchange = _makeExchange(user);
  const ctx = runner.createContext(userId, user, exchange, alertFn);

  // Sync real balance for live/testnet trading on first start
  if (user.usePaper === false && exchange !== paper) {
    try {
      const realBal = await exchange.getBalance('USDT');
      if (realBal > 0) {
        ctx.state.paperBalance = realBal;
        if (!ctx.state.startBalance || ctx.state.startBalance <= 100) ctx.state.startBalance = realBal;
        console.log(`[BotMgr:${userId}] 💰 Balance synced from exchange: $${realBal.toFixed(2)} USDT`);
      }
    } catch (e) {
      console.warn(`[BotMgr:${userId}] Balance sync failed (using stored):`, e.message);
    }
  }

  await runner.tick(ctx);
  _save(ctx);

  const id = setInterval(async () => {
    try   { await runner.tick(ctx); _save(ctx); }
    catch (e) { console.error(`[BotMgr:${userId}]`, e.message); }
  }, 60 * 1000);

  _loops.set(userId, { id, ctx });
  console.log(`[BotMgr] Started bot for user ${userId} on ${user.usePaper ? 'paper' : user.exchange}`);
}

async function stop(userId) {
  const loop = _loops.get(userId);
  if (!loop) return;
  clearInterval(loop.id);
  _loops.delete(userId);
  const u = userStore.load(userId);
  u.active = false;
  userStore.save(userId, u);
  console.log(`[BotMgr] Stopped bot for user ${userId}`);
}

async function restart(userId, alertFn) {
  await stop(userId);
  const u = userStore.load(userId);
  u.active = true;
  userStore.save(userId, u);
  await start(userId, alertFn);
}

// Clear all strategy-stop conditions so a manual /resume restarts trading.
// Without this, 3 consecutive losses (or a daily-loss / drawdown / trade-cap
// stop) latches forever: the tick returns before trading, so the bot never
// gets a win to reset the counter and spams "STRATEGY STOP" every minute.
function resetSession(userId) {
  const fresh = {
    consecutiveLosses: 0, consecutiveWins: 0,
    dailyTrades: 0, dailyPnL: 0,
    lastLossAt: 0, lastResetDay: new Date().toDateString(),
    stopAlertedAt: 0, stopStartedAt: 0,
  };
  const loop = _loops.get(userId);
  if (loop) {
    const s = loop.ctx.state;
    s.session = { ...s.session, ...fresh, peakBalance: s.paperBalance };
    _save(loop.ctx);
  } else {
    const u = userStore.load(userId);
    if (u.state && u.state.session) {
      u.state.session = { ...u.state.session, ...fresh, peakBalance: u.state.paperBalance };
      userStore.save(userId, u);
    }
  }
}

function isRunning(userId) { return _loops.has(userId); }

function getCtx(userId) { return _loops.get(userId)?.ctx ?? null; }

function allRunning() { return [..._loops.keys()]; }

module.exports = { start, stop, restart, resetSession, isRunning, getCtx, allRunning };
