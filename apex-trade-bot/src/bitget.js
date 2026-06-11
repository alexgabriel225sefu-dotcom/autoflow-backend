/**
 * Bitget Spot connector (API v2)
 * Auth: ACCESS-SIGN = base64(HMAC-SHA256(secret, ts+method+requestPath+body)), ms timestamp, passphrase.
 * Interface: getPrice, getCandles, getBalance, placeOrder
 * ⚠️ Note: Bitget market-buy sizing can be quote-denominated on some accounts — validate on small live amount.
 */
const axios = require('axios');
const crypto = require('crypto');
const cfg = require('./config');

const BASE = 'https://api.bitget.com';
const client = axios.create({ baseURL: BASE, timeout: 10000, headers: { 'User-Agent': 'ApexTradeBot/2.0', 'locale': 'en-US' } });

// Bitget granularity: 1min,5min,15min,30min,1h,4h,1day
const IV = { '1m':'1min','3m':'5min','5m':'5min','15m':'15min','30m':'30min','1h':'1h','4h':'4h','1d':'1day' };

function authHeaders(method, requestPath, body = '') {
  const ts = Date.now().toString();
  const prehash = ts + method.toUpperCase() + requestPath + body;
  const sign = crypto.createHmac('sha256', cfg.BITGET_API_SECRET).update(prehash).digest('base64');
  return {
    'ACCESS-KEY': cfg.BITGET_API_KEY,
    'ACCESS-SIGN': sign,
    'ACCESS-TIMESTAMP': ts,
    'ACCESS-PASSPHRASE': cfg.BITGET_API_PASSPHRASE,
    'Content-Type': 'application/json',
  };
}

async function getPrice(symbol = cfg.SYMBOL) {
  const { data } = await client.get('/api/v2/spot/market/tickers', { params: { symbol } });
  return parseFloat(data.data[0].lastPr);
}

async function getCandles(symbol = cfg.SYMBOL, interval = cfg.TIMEFRAME, limit = cfg.CANDLES) {
  const { data } = await client.get('/api/v2/spot/market/candles', { params: { symbol, granularity: IV[interval] || '5min', limit } });
  if (data.code !== '00000') throw new Error('Bitget candles: ' + data.msg);
  // Sortare explicită ascendentă — indicatorii presupun vechi → nou,
  // iar Bitget nu garantează aceeași ordine ca celelalte exchange-uri
  return data.data.map(k => ({
    time: parseInt(k[0]), open: parseFloat(k[1]), high: parseFloat(k[2]),
    low: parseFloat(k[3]), close: parseFloat(k[4]), volume: parseFloat(k[5]),
  })).sort((a, b) => a.time - b.time);
}

async function getBalance(coin = cfg.QUOTE_ASSET) {
  if (cfg.PAPER_TRADING) return cfg.PAPER_BALANCE;
  const path = `/api/v2/spot/account/assets?coin=${coin}`;
  const { data } = await client.get(path, { headers: authHeaders('GET', path) });
  if (data.code !== '00000') throw new Error('Bitget balance: ' + data.msg);
  const a = data.data?.[0];
  return a ? parseFloat(a.available) : 0;
}

async function placeOrder(side, quantity, symbol = cfg.SYMBOL) {
  if (cfg.PAPER_TRADING) {
    console.log(`[PAPER][BITGET] ${side} ${quantity} ${symbol}`);
    return { orderId: 'PAPER_' + Date.now() };
  }
  const path = '/api/v2/spot/trade/place-order';
  const bodyObj = { symbol, side: side.toLowerCase(), orderType: 'market', force: 'gtc', size: String(quantity) };
  const body = JSON.stringify(bodyObj);
  const { data } = await client.post(path, body, { headers: authHeaders('POST', path, body) });
  if (data.code !== '00000') throw new Error(`Bitget order: ${data.msg}`);
  console.log(`[LIVE][BITGET] ${side} ${quantity} ${symbol} → ${data.data?.orderId}`);
  return data.data;
}

module.exports = { getPrice, getCandles, getBalance, placeOrder };
