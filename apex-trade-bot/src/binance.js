const axios = require('axios');
const crypto = require('crypto');
const cfg = require('./config');

const client = axios.create({ baseURL: cfg.BINANCE_BASE, timeout: 10000 });

function sign(params) {
  const qs = new URLSearchParams(params).toString();
  const sig = crypto.createHmac('sha256', cfg.BINANCE_API_SECRET).update(qs).digest('hex');
  return `${qs}&signature=${sig}`;
}

function headers() {
  return { 'X-MBX-APIKEY': cfg.BINANCE_API_KEY };
}

// Preț curent
async function getPrice(symbol = cfg.SYMBOL) {
  const { data } = await client.get('/ticker/price', { params: { symbol } });
  return parseFloat(data.price);
}

// Lumânări (OHLCV)
async function getCandles(symbol = cfg.SYMBOL, interval = cfg.TIMEFRAME, limit = cfg.CANDLES) {
  const { data } = await client.get('/klines', { params: { symbol, interval, limit } });
  return data.map(k => ({
    open:   parseFloat(k[1]),
    high:   parseFloat(k[2]),
    low:    parseFloat(k[3]),
    close:  parseFloat(k[4]),
    volume: parseFloat(k[5]),
    time:   k[0],
  }));
}

// Balanță USDT
async function getBalance(asset = cfg.QUOTE_ASSET) {
  const params = { timestamp: Date.now() };
  const { data } = await client.get(`/account?${sign(params)}`, { headers: headers() });
  const bal = data.balances.find(b => b.asset === asset);
  return bal ? parseFloat(bal.free) : 0;
}

// Plasare ordin MARKET
async function placeOrder(side, quantity) {
  if (cfg.PAPER_TRADING) {
    console.log(`[PAPER] ${side} ${quantity} ${cfg.SYMBOL}`);
    return { orderId: 'PAPER_' + Date.now(), status: 'FILLED', side, quantity };
  }
  const params = {
    symbol: cfg.SYMBOL, side, type: 'MARKET',
    quantity: quantity.toFixed(0), // DOGE = întregi
    timestamp: Date.now(),
  };
  const { data } = await client.post(`/order?${sign(params)}`, null, { headers: headers() });
  return data;
}

// Info simbol (lot size etc.)
async function getSymbolInfo(symbol = cfg.SYMBOL) {
  const { data } = await axios.get(`${cfg.BINANCE_BASE.replace('/api/v3', '')}/api/v3/exchangeInfo`);
  return data.symbols.find(s => s.symbol === symbol);
}

// Ticker 24h
async function getTicker24h(symbol = cfg.SYMBOL) {
  const { data } = await client.get('/ticker/24hr', { params: { symbol } });
  return data;
}

module.exports = { getPrice, getCandles, getBalance, placeOrder, getSymbolInfo, getTicker24h };
