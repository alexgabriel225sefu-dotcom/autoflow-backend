/**
 * Coinbase Advanced Trade connector
 * Auth: JWT (ES256) signed with the EC private key from your Coinbase CDP API key.
 *   COINBASE_API_KEY    = the key name, e.g. organizations/xxx/apiKeys/yyy
 *   COINBASE_API_SECRET = the EC PRIVATE KEY PEM (-----BEGIN EC PRIVATE KEY----- ...)
 * Interface: getPrice, getCandles, getBalance, placeOrder
 * ⚠️ Market data endpoints are public; trading/balance require the JWT key. Validate small first.
 */
const axios = require('axios');
const crypto = require('crypto');
const cfg = require('./config');

const HOST = 'api.coinbase.com';
const BASE = `https://${HOST}`;
const client = axios.create({ baseURL: BASE, timeout: 10000, headers: { 'User-Agent': 'ApexTradeBot/2.0' } });

const GRAN = { '1m':'ONE_MINUTE','3m':'FIVE_MINUTE','5m':'FIVE_MINUTE','15m':'FIFTEEN_MINUTE','30m':'THIRTY_MINUTE','1h':'ONE_HOUR','4h':'SIX_HOUR','1d':'ONE_DAY' };
const GRAN_SEC = { ONE_MINUTE:60, FIVE_MINUTE:300, FIFTEEN_MINUTE:900, THIRTY_MINUTE:1800, ONE_HOUR:3600, SIX_HOUR:21600, ONE_DAY:86400 };
const product = s => s.replace('USDT', '-USDT');
const b64url = b => b.toString('base64').replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');

// Build an ES256 JWT for a given request (method + path)
function jwt(method, path) {
  const key = (cfg.COINBASE_API_SECRET || '').replace(/\\n/g, '\n');
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: 'ES256', kid: cfg.COINBASE_API_KEY, typ: 'JWT', nonce: crypto.randomBytes(16).toString('hex') };
  const claims = { sub: cfg.COINBASE_API_KEY, iss: 'cdp', nbf: now, exp: now + 120, uri: `${method} ${HOST}${path}` };
  const signingInput = `${b64url(Buffer.from(JSON.stringify(header)))}.${b64url(Buffer.from(JSON.stringify(claims)))}`;
  const sig = crypto.sign('sha256', Buffer.from(signingInput), { key, dsaEncoding: 'ieee-p1363' });
  return `${signingInput}.${b64url(sig)}`;
}
const authHeaders = (method, path) => ({ Authorization: `Bearer ${jwt(method, path)}` });

async function getPrice(symbol = cfg.SYMBOL) {
  const path = `/api/v3/brokerage/market/products/${product(symbol)}`;
  const { data } = await client.get(path);
  return parseFloat(data.price);
}

async function getCandles(symbol = cfg.SYMBOL, interval = cfg.TIMEFRAME, limit = cfg.CANDLES) {
  const g = GRAN[interval] || 'FIVE_MINUTE';
  const end = Math.floor(Date.now() / 1000);
  const start = end - GRAN_SEC[g] * Math.min(limit, 300);
  const path = `/api/v3/brokerage/market/products/${product(symbol)}/candles`;
  const { data } = await client.get(path, { params: { start, end, granularity: g, limit: Math.min(limit, 300) } });
  return (data.candles || []).slice().reverse().map(c => ({
    time: parseInt(c.start) * 1000, open: parseFloat(c.open), high: parseFloat(c.high),
    low: parseFloat(c.low), close: parseFloat(c.close), volume: parseFloat(c.volume),
  }));
}

async function getBalance(asset = cfg.QUOTE_ASSET) {
  if (cfg.PAPER_TRADING) return cfg.PAPER_BALANCE;
  const path = '/api/v3/brokerage/accounts';
  const { data } = await client.get(path, { headers: authHeaders('GET', path) });
  const acc = (data.accounts || []).find(a => a.currency === asset || a.currency === 'USD');
  return acc ? parseFloat(acc.available_balance.value) : 0;
}

async function placeOrder(side, quantity, symbol = cfg.SYMBOL) {
  if (cfg.PAPER_TRADING) {
    console.log(`[PAPER][COINBASE] ${side} ${quantity} ${symbol}`);
    return { success: true, order_id: 'PAPER_' + Date.now() };
  }
  const path = '/api/v3/brokerage/orders';
  const bodyObj = {
    client_order_id: crypto.randomUUID(),
    product_id: product(symbol),
    side: side.toUpperCase(),
    order_configuration: { market_market_ioc: { base_size: String(quantity) } },
  };
  const { data } = await client.post(path, bodyObj, { headers: { ...authHeaders('POST', path), 'Content-Type': 'application/json' } });
  if (data.success === false) throw new Error('Coinbase order: ' + JSON.stringify(data.error_response || data));
  console.log(`[LIVE][COINBASE] ${side} ${quantity} ${symbol} → ${data.order_id || data.success_response?.order_id}`);
  return data;
}

module.exports = { getPrice, getCandles, getBalance, placeOrder };
