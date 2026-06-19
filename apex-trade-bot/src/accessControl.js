/**
 * Access Control — whitelist gate for paying clients.
 *
 * Model:
 *   - The FIRST person to message the bot auto-becomes ADMIN (bootstrap).
 *   - Extra admins can be set via ADMIN_CHAT_ID env (comma-separated).
 *   - Only admins + granted clients can use the bot.
 *   - Admin grants/revokes access by Telegram chat ID:  /grant <id> · /revoke <id>
 *
 * Payment itself is handled OFF-BOT by the owner (any method). Once a client
 * pays, the owner runs /grant <theirId>. This keeps zero payment liability
 * inside the bot and no card/crypto handling on the server.
 */
const fs   = require('fs');
const path = require('path');

const DIR  = process.env.USER_DATA_DIR || '/tmp/apex-users';
const FILE = path.join(DIR, '_access.json');

if (!fs.existsSync(DIR)) fs.mkdirSync(DIR, { recursive: true });

function _read() {
  try {
    const d = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    d.admins        = d.admins        || [];
    d.allowed       = d.allowed       || [];
    d.claimedTokens = d.claimedTokens || {};  // token → chatId (prevents reuse)
    return d;
  }
  catch { return { admins: [], allowed: [], claimedTokens: {} }; }
}

function _write(d) {
  try { fs.writeFileSync(FILE, JSON.stringify(d, null, 2)); }
  catch (e) { console.error('[Access] write error:', e.message); }
}

function _envAdmins() {
  return (process.env.ADMIN_CHAT_ID || '')
    .split(',').map(s => s.trim()).filter(Boolean);
}

function isAdmin(chatId) {
  chatId = String(chatId);
  if (_envAdmins().includes(chatId)) return true;
  return _read().admins.includes(chatId);
}

/** True once at least one admin exists (env or stored). */
function hasAnyAdmin() {
  return _envAdmins().length > 0 || _read().admins.length > 0;
}

/** First-user bootstrap: claim admin + auto-allow. */
function claimAdmin(chatId) {
  chatId = String(chatId);
  const d = _read();
  if (!d.admins.includes(chatId))  d.admins.push(chatId);
  if (!d.allowed.includes(chatId)) d.allowed.push(chatId);
  _write(d);
}

function isAllowed(chatId) {
  chatId = String(chatId);
  if (isAdmin(chatId)) return true;
  return _read().allowed.includes(chatId);
}

function grant(chatId) {
  chatId = String(chatId);
  const d = _read();
  if (d.allowed.includes(chatId)) return false;
  d.allowed.push(chatId);
  _write(d);
  return true;
}

function revoke(chatId) {
  chatId = String(chatId);
  const d = _read();
  const i = d.allowed.indexOf(chatId);
  if (i < 0) return false;
  d.allowed.splice(i, 1);
  // never strip an admin's own access
  if (!d.admins.includes(chatId)) _write(d);
  else { d.allowed.push(chatId); }
  return true;
}

function listAllowed() {
  // clients only (exclude admins from the "clients" view)
  const d = _read();
  return d.allowed.filter(id => !d.admins.includes(id) && !_envAdmins().includes(id));
}

function listAdmins() {
  return [..._envAdmins(), ..._read().admins];
}

// ── Paid-token claims (one activation link = one use) ──
function isTokenClaimed(token) {
  return Boolean(_read().claimedTokens[String(token)]);
}

function claimToken(token, chatId) {
  const d = _read();
  d.claimedTokens[String(token)] = String(chatId);
  _write(d);
}

module.exports = {
  isAdmin, isAllowed, hasAnyAdmin, claimAdmin,
  grant, revoke, listAllowed, listAdmins,
  isTokenClaimed, claimToken,
};
