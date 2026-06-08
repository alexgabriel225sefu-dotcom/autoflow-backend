/**
 * OKX Spot connector (API v5)
 * Auth: OK-ACCESS-SIGN = base64(HMAC-SHA256(secret, ts+method+path+body)), ISO timestamp, passphrase.
 * Interface: getPrice, getCandles, getBalance, placeOrder
 * ⚠️ Validate on demo trading before live.
 */
const axios = require('axios');
const crypto = require('crypto');
const cfg = require('./config');

const BASE = 'https://www.okx.com';
const client = axios.create({ baseURL: BASE, timeout: 10000, headers: { 'User-Agent': 'ApexTradeBot/2.0' } });

// OKX bars: 1m,5m,15m,30m,1H,4H,1D
const IV = { '1m':'1m','3m':'5m','5m':'5m','15m':'15m','30m':'30m','1h':'1H','4h':'4H','1d':'1D' };
const inst = s => s.replace('USDT', '-USDT');

function authHeaders(method, path, body = '') {
  const ts = new Date().toISOString();
  const prehash = ts + method.toUpperCase() + path + body;
  const sign = crypto.createHmac('sha256', cfg.OKX_API_SECRET).update(prehash).digest('base64');
  return {
    'OK-ACCESS-KEY': cfg.OKX_API_KEY,
    'OK-ACCESS-SIGN': sign,
    'OK-ACCESS-TIMESTAMP': ts,
    'OK-ACCESS-PASSPHRASE': cfg.OKX_API_PASSPHRASE,
    'Content-Type': 'application/json',
  };
}

async function getPrice(symbol = cfg.SYMBOL) {
  const { data } = await client.get('/api/v5/market/ticker', { params: { instId: inst(symbol) } });
  return parseFloat(data.data[0].last);
}

async function getCandles(symbol = cfg.SYMBOL, interval = cfg.TIMEFRAME, limit = cfg.CANDLES) {
  const { data } = await client.get('/api/v5/market/candles', { params: { instId: inst(symbol), bar: IV[interval] || '5m', limit } });
  if (data.code !== '0') throw new Error('OKX candles: ' + data.msg);
  return data.data.reverse().map(k => ({
    time: parseInt(k[0]), open: parseFloat(k[1]), high: parseFloat(k[2]),
    low: parseFloat(k[3]), close: parseFloat(k[4]), volume: parseFloat(k[5]),
  }));
}

async function getBalance(ccy = cfg.QUOTE_ASSET) {
  if (cfg.PAPER_TRADING) return cfg.PAPER_BALANCE;
  const path = `/api/v5/account/balance?ccy=${ccy}`;
  const { data } = await client.get(path, { headers: authHeaders('GET', path) });
  if (data.code !== '0') throw new Error('OKX balance: ' + data.msg);
  const det = data.data?.[0]?.details?.find(d => d.ccy === ccy);
  return det ? parseFloat(det.availBal) : 0;
}

async function placeOrder(side, quantity, symbol = cfg.SYMBOL) {
  if (cfg.PAPER_TRADING) {
    console.log(`[PAPER][OKX] ${side} ${quantity} ${symbol}`);
    return { ordId: 'PAPER_' + Date.now(), state: 'filled' };
  }
  const path = '/api/v5/trade/order';
  // tgtCcy:'base_ccy' → sz is interpreted as base quantity for market orders
  const bodyObj = { instId: inst(symbol), tdMode: 'cash', side: side.toLowerCase(), ordType: 'market', sz: String(quantity), tgtCcy: 'base_ccy' };
  const body = JSON.stringify(bodyObj);
  const { data } = await client.post(path, body, { headers: authHeaders('POST', path, body) });
  if (data.code !== '0') throw new Error(`OKX order: ${data.msg} ${JSON.stringify(data.data)}`);
  console.log(`[LIVE][OKX] ${side} ${quantity} ${symbol} → ${data.data[0]?.ordId}`);
  return data.data[0];
}

module.exports = { getPrice, getCandles, getBalance, placeOrder };
