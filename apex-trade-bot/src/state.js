/**
 * State persistence — supraviețuiește restart-urilor Railway
 * Salvează openPosition + paperBalance în /tmp/apex-state.json
 */
const fs   = require('fs');
const path = require('path');

const STATE_FILE = process.env.STATE_FILE || '/tmp/apex-state.json';

function save(paperBalance, openPosition, session = null) {
  try {
    fs.writeFileSync(STATE_FILE, JSON.stringify({
      paperBalance,
      openPosition,
      session, // streak-uri/daily-stop — protecțiile nu se resetează la restart
      savedAt: new Date().toISOString(),
    }, null, 2));
  } catch (err) {
    console.warn('[STATE] Nu pot salva starea:', err.message);
  }
}

function load(defaultBalance) {
  try {
    if (!fs.existsSync(STATE_FILE)) return null;
    const raw  = fs.readFileSync(STATE_FILE, 'utf8');
    const data = JSON.parse(raw);
    const age  = Date.now() - new Date(data.savedAt).getTime();
    // Ignoră starea dacă e mai veche de 24h (poziția ar fi expirat oricum)
    if (age > 24 * 60 * 60 * 1000) {
      console.log('[STATE] Stare veche (>24h) — ignorată, start curat.');
      return null;
    }
    console.log(`[STATE] ♻️  Stare restaurată din ${data.savedAt}`);
    if (data.openPosition) {
      console.log(`[STATE] 📌 Poziție recuperată: ${data.openPosition.side} ${data.openPosition.symbol} @ $${data.openPosition.entryPrice}`);
    }
    return data;
  } catch (err) {
    console.warn('[STATE] Nu pot citi starea:', err.message);
    return null;
  }
}

function clear() {
  try { fs.unlinkSync(STATE_FILE); } catch {}
}

module.exports = { save, load, clear };
