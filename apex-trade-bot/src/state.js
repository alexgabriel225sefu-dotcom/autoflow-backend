/**
 * State persistence — survives Railway restarts
 * Saves openPosition + paperBalance to /tmp/apex-state.json
 */
const fs   = require('fs');
const path = require('path');

const STATE_FILE = process.env.STATE_FILE || '/tmp/apex-state.json';

function save(paperBalance, openPosition, session = null) {
  try {
    fs.writeFileSync(STATE_FILE, JSON.stringify({
      paperBalance,
      openPosition,
      session,
      savedAt: new Date().toISOString(),
    }, null, 2));
  } catch (err) {
    console.warn('[STATE] Cannot save state:', err.message);
  }
}

function load(defaultBalance) {
  try {
    if (!fs.existsSync(STATE_FILE)) return null;
    const raw  = fs.readFileSync(STATE_FILE, 'utf8');
    const data = JSON.parse(raw);
    const age  = Date.now() - new Date(data.savedAt).getTime();
    if (age > 24 * 60 * 60 * 1000) {
      console.log('[STATE] State too old (>24h) — ignored, clean start.');
      return null;
    }
    console.log(`[STATE] ♻️  State restored from ${data.savedAt}`);
    if (data.openPosition) {
      console.log(`[STATE] 📌 Position recovered: ${data.openPosition.side} ${data.openPosition.symbol} @ $${data.openPosition.entryPrice}`);
    }
    return data;
  } catch (err) {
    console.warn('[STATE] Cannot read state:', err.message);
    return null;
  }
}

function clear() {
  try { fs.unlinkSync(STATE_FILE); } catch {}
}

module.exports = { save, load, clear };
