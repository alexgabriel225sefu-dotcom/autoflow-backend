const fs  = require('fs');
const cfg = require('./config');

const FILE = '/tmp/apex-settings.json';

const DEFAULTS = {
  STRATEGY_MODE:   'auto',       // auto | turtle | livermore | soros | ptj | druckenmiller
  RISK_PER_TRADE:  cfg.RISK_PER_TRADE,
  STOP_LOSS_PCT:   cfg.STOP_LOSS_PCT,
  TAKE_PROFIT_PCT: cfg.TAKE_PROFIT_PCT,
  MIN_CONFIDENCE:  cfg.MIN_CONFIDENCE,
  SYMBOL:          cfg.SYMBOL,   // trading pair — changeable via /symbol
  PAUSED:          true,         // start PAUSED — client must press Start after setup
};

let _s = { ...DEFAULTS };
let _restoredFromFile = false;

try {
  const raw = fs.readFileSync(FILE, 'utf8');
  _s = { ...DEFAULTS, ...JSON.parse(raw) };
  _restoredFromFile = true;
  console.log('[SETTINGS] Runtime settings restored from', FILE);
} catch {}

// DEFAULTS above is snapshotted from cfg at require-time — before
// cfg.loadRemote() pulls the customer's configurator settings (risk,
// SL/TP, confidence, symbol) from the license server. Call this once
// in main(), right after loadRemote(), so those values actually apply.
// Skipped if a settings file was already restored (a prior deploy on
// this same container may already reflect customer /set overrides that
// should take precedence over a fresh remote-config pull).
function refreshFromConfig() {
  const fresh = {
    RISK_PER_TRADE:  cfg.RISK_PER_TRADE,
    STOP_LOSS_PCT:   cfg.STOP_LOSS_PCT,
    TAKE_PROFIT_PCT: cfg.TAKE_PROFIT_PCT,
    MIN_CONFIDENCE:  cfg.MIN_CONFIDENCE,
    SYMBOL:          cfg.SYMBOL,
  };
  for (const [key, value] of Object.entries(fresh)) {
    DEFAULTS[key] = value;
    if (!_restoredFromFile) _s[key] = value;
  }
}

function _save() {
  try { fs.writeFileSync(FILE, JSON.stringify(_s, null, 2)); } catch {}
}

function get(key) {
  return key in _s ? _s[key] : DEFAULTS[key];
}

function set(key, value) {
  _s[key] = value;
  _save();
}

function reset(key) {
  _s[key] = DEFAULTS[key];
  _save();
}

function snapshot() {
  return { ..._s };
}

module.exports = { get, set, reset, snapshot, refreshFromConfig, DEFAULTS };
