const axios = require('axios');
const crypto = require('crypto');
const cfg = require('./config');

const BASE = cfg.BYBIT_TESTNET
  ? 'https://api-testnet.bybit.com'
  : 'https://api.bybit.com';

function sign(params) {
  const ts = Date.now().toString();
  const query = Object.keys(params).sort().map(k => `${k}=${params[k]}`).join('&');
  const payload = ts + cfg.BYBIT_API_KEY + '5000' + query;
  const sig = crypto.createHmac('sha256', cfg.BYBIT_API_SECRET).update(payload).digest('hex');
  return { sig, ts };
}

function authHeaders(params) {
  const { sig, ts } = sign(params);
  return {
    'X-BAPI-API-KEY': cfg.BYBIT_API_KEY,
    'X-BAPI-TIMESTAMP': ts,
    'X-BAPI-SIGN': sig,
    'X-BAPI-RECV-WINDOW': '5000',
  };
}

// Preț curent — Binance public API (funcționează din Railway)
async function getPrice(symbol = cfg.SYMBOL) {
  const { data } = await axios.get('https://api.binance.com/api/v3/ticker/price', {
    params: { symbol },
    headers: { 'User-Agent': 'ApexTradeBot/2.0' },
    timeout: 10000,
  });
  return parseFloat(data.price);
}

// Lumânări OHLCV — Binance public API (funcționează din Railway)
async function getCandles(symbol = cfg.SYMBOL, interval = cfg.TIMEFRAME, limit = cfg.CANDLES) {
  const validIntervals = { '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1h', '4h': '4h', '1d': '1d' };
  const binanceInterval = validIntervals[interval] || '15m';
  const { data } = await axios.get('https://api.binance.com/api/v3/klines', {
    params: { symbol, interval: binanceInterval, limit },
    headers: { 'User-Agent': 'ApexTradeBot/2.0' },
    timeout: 10000,
  });
  return data.map(k => ({
    time:   k[0],
    open:   parseFloat(k[1]),
    high:   parseFloat(k[2]),
    low:    parseFloat(k[3]),
    close:  parseFloat(k[4]),
    volume: parseFloat(k[5]),
  }));
}

// Balanță (privat)
async function getBalance(coin = 'USDT') {
  if (cfg.PAPER_TRADING) return cfg.PAPER_BALANCE;
  const params = { accountType: 'UNIFIED', coin };
  const { data } = await axios.get(`${BASE}/v5/account/wallet-balance`, {
    params,
    headers: authHeaders(params),
  });
  const bal = data.result.list[0]?.coin?.find(c => c.coin === coin);
  return bal ? parseFloat(bal.availableToWithdraw) : 0;
}

// Plasare ordin MARKET (privat)
async function placeOrder(side, quantity) {
  if (cfg.PAPER_TRADING) {
    console.log(`[PAPER] ${side} ${quantity} ${cfg.SYMBOL}`);
    return { orderId: 'PAPER_' + Date.now(), orderStatus: 'Filled', side, qty: quantity };
  }
  const params = {
    category: 'spot',
    symbol: cfg.SYMBOL,
    side: side === 'BUY' ? 'Buy' : 'Sell',
    orderType: 'Market',
    qty: String(quantity),
  };
  const { data } = await axios.post(`${BASE}/v5/order/create`, params, {
    headers: { ...authHeaders(params), 'Content-Type': 'application/json' },
  });
  return data.result;
}

module.exports = { getPrice, getCandles, getBalance, placeOrder };
