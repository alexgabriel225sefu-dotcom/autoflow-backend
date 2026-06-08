/**
 * MEXC Spot connector (API v3 — Binance-compatible signing)
 * Interface: getPrice, getCandles, getBalance, placeOrder
 * ⚠️ Validate on a small live amount before trusting live orders.
 */
const axios = require('axios');
const crypto = require('crypto');
const cfg = require('./config');

const BASE = 'https://api.mexc.com';
const client = axios.create({ baseURL: BASE, timeout: 10000, headers: { 'User-Agent': 'ApexTradeBot/2.0' } });

// MEXC kline intervals: 1m,5m,15m,30m,60m,4h,1d
const IV = { '1m':'1m','3m':'5m','5m':'5m','15m':'15m','30m':'30m','1h':'60m','4h':'4h','1d':'1d' };

function sign(params) {
  const qs = new URLSearchParams(params).toString();
  const sig = crypto.createHmac('sha256', cfg.MEXC_API_SECRET).update(qs).digest('hex');
  return `${qs}&signature=${sig}`;
}
const headers = () => ({ 'X-MEXC-APIKEY': cfg.MEXC_API_KEY });

async function getPrice(symbol = cfg.SYMBOL) {
  const { data } = await client.get('/api/v3/ticker/price', { params: { symbol } });
  return parseFloat(data.price);
}

async function getCandles(symbol = cfg.SYMBOL, interval = cfg.TIMEFRAME, limit = cfg.CANDLES) {
  const { data } = await client.get('/api/v3/klines', { params: { symbol, interval: IV[interval] || '5m', limit } });
  return data.map(k => ({
    time: k[0], open: parseFloat(k[1]), high: parseFloat(k[2]),
    low: parseFloat(k[3]), close: parseFloat(k[4]), volume: parseFloat(k[5]),
  }));
}

async function getBalance(asset = cfg.QUOTE_ASSET) {
  if (cfg.PAPER_TRADING) return cfg.PAPER_BALANCE;
  const params = { timestamp: Date.now(), recvWindow: 5000 };
  const { data } = await client.get(`/api/v3/account?${sign(params)}`, { headers: headers() });
  const bal = (data.balances || []).find(b => b.asset === asset);
  return bal ? parseFloat(bal.free) : 0;
}

async function placeOrder(side, quantity, symbol = cfg.SYMBOL) {
  if (cfg.PAPER_TRADING) {
    console.log(`[PAPER][MEXC] ${side} ${quantity} ${symbol}`);
    return { orderId: 'PAPER_' + Date.now(), status: 'FILLED' };
  }
  const params = { symbol, side, type: 'MARKET', quantity: String(quantity), timestamp: Date.now(), recvWindow: 5000 };
  const { data } = await client.post(`/api/v3/order?${sign(params)}`, null, { headers: headers() });
  console.log(`[LIVE][MEXC] ${side} ${quantity} ${symbol} → ${data.orderId}`);
  return data;
}

module.exports = { getPrice, getCandles, getBalance, placeOrder };
