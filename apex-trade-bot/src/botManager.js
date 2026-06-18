/**
 * BotManager — manages per-user trading loops.
 * Each active user gets their own interval + context; isolated state.
 */
const userStore = require('./userStore');
const runner    = require('./runner');
const paper     = require('./paperExchange');

const _loops = new Map(); // userId → { intervalId, ctx }

function _save(ctx) {
  const u     = userStore.load(ctx.userId);
  u.state     = ctx.state;
  userStore.save(ctx.userId, u);
}

async function start(userId, alertFn) {
  if (_loops.has(userId)) return;

  const user = userStore.load(userId);
  if (!user.active) return;

  const ctx = runner.createContext(userId, user, paper, alertFn);

  await runner.tick(ctx);
  _save(ctx);

  const id = setInterval(async () => {
    try   { await runner.tick(ctx); _save(ctx); }
    catch (e) { console.error(`[BotMgr:${userId}]`, e.message); }
  }, 60 * 1000); // 1 min ticks for paper trading

  _loops.set(userId, { id, ctx });
  console.log(`[BotMgr] Started bot for user ${userId}`);
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

function isRunning(userId) { return _loops.has(userId); }

function getCtx(userId) { return _loops.get(userId)?.ctx ?? null; }

function allRunning() { return [..._loops.keys()]; }

module.exports = { start, stop, restart, isRunning, getCtx, allRunning };
