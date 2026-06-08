/**
 * KuCoin Spot connector (API v2 auth)
 * Auth: KC-API-SIGN = base64(HMAC-SHA256(secret, ts+method+endpoint+body)),
 *       KC-API-PASSPHRASE = base64(HMAC-SHA256(secret, passphrase)), KC-API-KEY-VERSION: 2
 * Interface: getPrice, getCandles, getBalance, placeOrder
 * ⚠️ Validate on a small live amount before trusting live orders.
 */
const axios = require('axios');
const crypto = require('crypto');
const cfg = require('./config');

const BASE = 'https://api.kucoin.com';
const client = axios.create({ baseURL: BASE, timeout: 10000, headers: { 'User-Agent': 'ApexTradeBot/2.0' } });

// KuCoin candle types: 1min,5min,15min,30min,1hour,4hour,1day
const IV = { '1m':'1min','3m':'5min','5m':'5min','15m':'15min','30m':'30min','1h':'1hour','4h':'4hour','1d':'1day' };
const sym = s => s.replace('USDT', '-USDT');

function authHeaders(method, endpoint, body = '') {
  const ts = Date.now().toString();
  const strToSign = ts + method.toUpperCase() + endpoint + body;
  const sign = crypto.createHmac('sha256', cfg.KUCOIN_API_SECRET).update(strToSign).digest('base64');
  const passphrase = crypto.createHmac('sha256', cfg.KUCOIN_API_SECRET).update(cfg.KUCOIN_API_PASSPHRASE).digest('base64');
  return {
    'KC-API-KEY': cfg.KUCOIN_API_KEY,
    'KC-API-SIGN': sign,
    'KC-API-TIMESTAMP': ts,
    'KC-API-PASSPHRASE': passphrase,
    'KC-API-KEY-VERSION': '2',
    'Content-Type': 'application/json',
  };
}

async function getPrice(symbol = cfg.SYMBOL) {
  const { data } = await client.get('/api/v1/market/orderbook/level1', { params: { symbol: sym(symbol) } });
  return parseFloat(data.data.price);
}

async function getCandles(symbol = cfg.SYMBOL, interval = cfg.TIMEFRAME, limit = cfg.CANDLES) {
  const { data } = await client.get('/api/v1/market/candles', { params: { type: IV[interval] || '5min', symbol: sym(symbol) } });
  if (data.code !== '200000') throw new Error('KuCoin candles: ' + data.msg);
  // KuCoin returns newest-first: [time, open, close, high, low, volume, turnover]
  return data.data.slice(0, limit).reverse().map(k => ({
    time: parseInt(k[0]) * 1000, open: parseFloat(k[1]), close: parseFloat(k[2]),
    high: parseFloat(k[3]), low: parseFloat(k[4]), volume: parseFloat(k[5]),
  }));
}

async function getBalance(currency = cfg.QUOTE_ASSET) {
  if (cfg.PAPER_TRADING) return cfg.PAPER_BALANCE;
  const endpoint = `/api/v1/accounts?currency=${currency}&type=trade`;
  const { data } = await client.get(endpoint, { headers: authHeaders('GET', endpoint) });
  if (data.code !== '200000') throw new Error('KuCoin balance: ' + data.msg);
  const acc = (data.data || [])[0];
  return acc ? parseFloat(acc.available) : 0;
}

async function placeOrder(side, quantity, symbol = cfg.SYMBOL) {
  if (cfg.PAPER_TRADING) {
    console.log(`[PAPER][KUCOIN] ${side} ${quantity} ${symbol}`);
    return { orderId: 'PAPER_' + Date.now() };
  }
  const endpoint = '/api/v1/orders';
  const bodyObj = { clientOid: crypto.randomUUID(), side: side.toLowerCase(), symbol: sym(symbol), type: 'market', size: String(quantity) };
  const body = JSON.stringify(bodyObj);
  const { data } = await client.post(endpoint, body, { headers: authHeaders('POST', endpoint, body) });
  if (data.code !== '200000') throw new Error(`KuCoin order: ${data.msg}`);
  console.log(`[LIVE][KUCOIN] ${side} ${quantity} ${symbol} → ${data.data?.orderId}`);
  return data.data;
}

module.exports = { getPrice, getCandles, getBalance, placeOrder };
