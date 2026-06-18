const fs     = require('fs');
const path   = require('path');
const crypto = require('crypto');

const DIR    = process.env.USER_DATA_DIR || '/tmp/apex-users';
const MASTER = Buffer.from(
  (process.env.MASTER_KEY || 'apex-server-default-key-change!!').padEnd(32).slice(0, 32)
);

if (!fs.existsSync(DIR)) fs.mkdirSync(DIR, { recursive: true });

function encrypt(text) {
  if (!text) return '';
  const iv = crypto.randomBytes(16);
  const c  = crypto.createCipheriv('aes-256-cbc', MASTER, iv);
  return iv.toString('hex') + ':' + Buffer.concat([c.update(text, 'utf8'), c.final()]).toString('hex');
}

function decrypt(enc) {
  if (!enc?.includes(':')) return '';
  try {
    const [ivH, data] = enc.split(':');
    const d = crypto.createDecipheriv('aes-256-cbc', MASTER, Buffer.from(ivH, 'hex'));
    return Buffer.concat([d.update(Buffer.from(data, 'hex')), d.final()]).toString('utf8');
  } catch { return ''; }
}

function fp(id) { return path.join(DIR, `${id}.json`); }

function make(userId) {
  return {
    userId:       String(userId),
    setupStep:    'start',  // start | exchange | apikey | apisecret | passphrase | done
    exchange:     null,
    apiKeyEnc:    '', apiSecretEnc: '', apiPassEnc: '',
    usePaper:     true,
    active:       false,
    settings: {
      SYMBOL:          'SOLUSDT',
      STRATEGY_MODE:   'auto',
      RISK_PER_TRADE:  0.05,
      STOP_LOSS_PCT:   0.016,
      TAKE_PROFIT_PCT: 0.032,
      MIN_CONFIDENCE:  62,
      MIN_CRITERIA:    3,
      PAUSED:          true,
    },
    state: {
      paperBalance:  100,
      startBalance:  100,
      openPosition:  null,
      trades:        [],
      lastTick:      null,
      lastSignal:    null,
      currentSymbol: 'SOLUSDT',
      currentPrice:  null,
      tickCount:     0,
      session: {
        consecutiveLosses: 0,
        consecutiveWins:   0,
        dailyTrades:       0,
        dailyPnL:          0,
        lastResetDay:      new Date().toDateString(),
        peakBalance:       100,
        lastLossAt:        0,
      },
    },
    createdAt: Date.now(),
  };
}

function merge(base, over) {
  if (!over) return base;
  const r = { ...base };
  for (const [k, v] of Object.entries(over)) {
    r[k] = (v && typeof v === 'object' && !Array.isArray(v) && base[k] && typeof base[k] === 'object')
      ? merge(base[k], v) : (v !== undefined ? v : base[k]);
  }
  return r;
}

function load(userId) {
  try { return merge(make(userId), JSON.parse(fs.readFileSync(fp(userId), 'utf8'))); }
  catch { return make(userId); }
}

function save(userId, data) {
  try { fs.writeFileSync(fp(userId), JSON.stringify(data, null, 2)); }
  catch (e) { console.error('[UserStore] Save error:', e.message); }
}

function list() {
  try { return fs.readdirSync(DIR).filter(f => f.endsWith('.json')).map(f => f.replace('.json', '')); }
  catch { return []; }
}

function setApiKeys(userId, keys) {
  const u = load(userId);
  u.apiKeyEnc    = encrypt(keys.apiKey    || '');
  u.apiSecretEnc = encrypt(keys.apiSecret || '');
  u.apiPassEnc   = encrypt(keys.apiPass   || '');
  save(userId, u);
}

function getApiKeys(userId) {
  const u = load(userId);
  return {
    apiKey:    decrypt(u.apiKeyEnc),
    apiSecret: decrypt(u.apiSecretEnc),
    apiPass:   decrypt(u.apiPassEnc),
  };
}

module.exports = { load, save, list, make, setApiKeys, getApiKeys, encrypt, decrypt };
