/**
 * Kraken Spot connector (REST)
 * Auth: API-Sign = base64(HMAC-SHA512(base64decode(secret), path + SHA256(nonce + postdata)))
 * Interface: getPrice, getCandles, getBalance, placeOrder
 * ⚠️ Kraken pair naming differs (BTC→XBT). Validate on a small live amount first.
 */
const axios = require('axios');
const crypto = require('crypto');
const qs = require('querystring');
const cfg = require('./config');

const BASE = 'https://api.kraken.com';
const client = axios.create({ baseURL: BASE, timeout: 10000, headers: { 'User-Agent': 'ApexTradeBot/2.0' } });

// Kraken OHLC interval in minutes
const IV = { '1m':1,'3m':5,'5m':5,'15m':15,'30m':30,'1h':60,'4h':240,'1d':1440 };
// Kraken uses XBT for Bitcoin
const pair = s => s.replace(/^BTC/, 'XBT');

function sign(path, params, nonce) {
  const postdata = qs.stringify(params);
  const sha = crypto.createHash('sha256').update(nonce + postdata).digest();
  const hmac = crypto.createHmac('sha512', Buffer.from(cfg.KRAKEN_API_SECRET, 'base64'));
  hmac.update(path, 'latin1').update(sha);
  return hmac.digest('base64');
}

async function _private(method, params = {}) {
  const path = `/0/private/${method}`;
  const nonce = Date.now() * 1000;
  const body = { nonce, ...params };
  const signature = sign(path, body, nonce);
  const { data } = await client.post(path, qs.stringify(body), {
    headers: { 'API-Key': cfg.KRAKEN_API_KEY, 'API-Sign': signature, 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  if (data.error && data.error.length) throw new Error('Kraken: ' + data.error.join(', '));
  return data.result;
}

async function getPrice(symbol = cfg.SYMBOL) {
  const { data } = await client.get('/0/public/Ticker', { params: { pair: pair(symbol) } });
  if (data.error && data.error.length) throw new Error('Kraken price: ' + data.error.join(', '));
  const r = Object.values(data.result)[0];
  return parseFloat(r.c[0]);
}

async function getCandles(symbol = cfg.SYMBOL, interval = cfg.TIMEFRAME, limit = cfg.CANDLES) {
  const { data } = await client.get('/0/public/OHLC', { params: { pair: pair(symbol), interval: IV[interval] || 5 } });
  if (data.error && data.error.length) throw new Error('Kraken candles: ' + data.error.join(', '));
  const rows = Object.values(data.result)[0] || [];
  // [time, open, high, low, close, vwap, volume, count]
  return rows.slice(-limit).map(k => ({
    time: parseInt(k[0]) * 1000, open: parseFloat(k[1]), high: parseFloat(k[2]),
    low: parseFloat(k[3]), close: parseFloat(k[4]), volume: parseFloat(k[6]),
  }));
}

async function getBalance(asset = cfg.QUOTE_ASSET) {
  if (cfg.PAPER_TRADING) return cfg.PAPER_BALANCE;
  const res = await _private('Balance');
  // Kraken keys USDT as 'USDT', USD as 'ZUSD'
  const key = res[asset] !== undefined ? asset : (asset === 'USD' ? 'ZUSD' : asset);
  return res[key] ? parseFloat(res[key]) : 0;
}

async function placeOrder(side, quantity, symbol = cfg.SYMBOL) {
  if (cfg.PAPER_TRADING) {
    console.log(`[PAPER][KRAKEN] ${side} ${quantity} ${symbol}`);
    return { txid: ['PAPER_' + Date.now()] };
  }
  const res = await _private('AddOrder', {
    pair: pair(symbol), type: side.toLowerCase(), ordertype: 'market', volume: String(quantity),
  });
  console.log(`[LIVE][KRAKEN] ${side} ${quantity} ${symbol} → ${res.txid}`);
  return res;
}

module.exports = { getPrice, getCandles, getBalance, placeOrder };
