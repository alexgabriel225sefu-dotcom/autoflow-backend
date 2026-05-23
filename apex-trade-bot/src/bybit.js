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

// ─── Surse de date publice (cu fallback automat) ──────────

// Sursa 1: Bybit public klines
async function candlesBybit(symbol, interval, limit) {
  const ivMap = { '1m':'1','3m':'3','5m':'5','15m':'15','30m':'30','1h':'60','4h':'240','1d':'D' };
  const iv = ivMap[interval] || '15';
  const { data } = await axios.get(`${BASE}/v5/market/kline`, {
    params: { category:'spot', symbol, interval: iv, limit },
    headers: { 'User-Agent': 'ApexTradeBot/2.0' },
    timeout: 8000,
  });
  if (data.retCode !== 0) throw new Error('Bybit: ' + data.retMsg);
  return data.result.list.reverse().map(k => ({
    time: parseInt(k[0]), open: parseFloat(k[1]), high: parseFloat(k[2]),
    low: parseFloat(k[3]), close: parseFloat(k[4]), volume: parseFloat(k[5]),
  }));
}

// Sursa 2: Binance public klines
async function candlesBinance(symbol, interval, limit) {
  const { data } = await axios.get('https://api.binance.com/api/v3/klines', {
    params: { symbol, interval, limit },
    headers: { 'User-Agent': 'ApexTradeBot/2.0' },
    timeout: 8000,
  });
  return data.map(k => ({
    time: k[0], open: parseFloat(k[1]), high: parseFloat(k[2]),
    low: parseFloat(k[3]), close: parseFloat(k[4]), volume: parseFloat(k[5]),
  }));
}

// Sursa 3: OKX public candles (fallback final)
async function candlesOKX(symbol, interval, limit) {
  // OKX format: DOGE-USDT, interval: 15m
  const okxSym = symbol.replace('USDT', '-USDT');
  const okxBar = interval; // 1m, 5m, 15m, 1H, 4H, 1D
  const { data } = await axios.get('https://www.okx.com/api/v5/market/candles', {
    params: { instId: okxSym, bar: okxBar, limit },
    headers: { 'User-Agent': 'ApexTradeBot/2.0' },
    timeout: 8000,
  });
  if (data.code !== '0') throw new Error('OKX: ' + data.msg);
  return data.data.reverse().map(k => ({
    time: parseInt(k[0]), open: parseFloat(k[1]), high: parseFloat(k[2]),
    low: parseFloat(k[3]), close: parseFloat(k[4]), volume: parseFloat(k[5]),
  }));
}

// Preț curent — încearcă Bybit → Binance → OKX
async function getPrice(symbol = cfg.SYMBOL) {
  // Bybit
  try {
    const { data } = await axios.get(`${BASE}/v5/market/tickers`, {
      params: { category: 'spot', symbol },
      headers: { 'User-Agent': 'ApexTradeBot/2.0' },
      timeout: 6000,
    });
    const price = data.result?.list?.[0]?.lastPrice;
    if (price) return parseFloat(price);
  } catch {}

  // Binance fallback
  try {
    const { data } = await axios.get('https://api.binance.com/api/v3/ticker/price', {
      params: { symbol },
      headers: { 'User-Agent': 'ApexTradeBot/2.0' },
      timeout: 6000,
    });
    return parseFloat(data.price);
  } catch {}

  // OKX fallback
  const okxSym = symbol.replace('USDT', '-USDT');
  const { data } = await axios.get('https://www.okx.com/api/v5/market/ticker', {
    params: { instId: okxSym },
    headers: { 'User-Agent': 'ApexTradeBot/2.0' },
    timeout: 6000,
  });
  return parseFloat(data.data[0].last);
}

// Lumânări — încearcă Bybit → Binance → OKX
async function getCandles(symbol = cfg.SYMBOL, interval = cfg.TIMEFRAME, limit = cfg.CANDLES) {
  try { return await candlesBybit(symbol, interval, limit); } catch (e) {
    console.warn('[DATA] Bybit klines failed:', e.message, '→ Binance');
  }
  try { return await candlesBinance(symbol, interval, limit); } catch (e) {
    console.warn('[DATA] Binance klines failed:', e.message, '→ OKX');
  }
  return await candlesOKX(symbol, interval, limit);
}

// ─── Balanță (privat Bybit) ───────────────────────────────
async function getBalance(coin = 'USDT') {
  if (cfg.PAPER_TRADING) return cfg.PAPER_BALANCE;
  const params = { accountType: 'UNIFIED', coin };
  const { data } = await axios.get(`${BASE}/v5/account/wallet-balance`, {
    params, headers: authHeaders(params),
  });
  const bal = data.result.list[0]?.coin?.find(c => c.coin === coin);
  return bal ? parseFloat(bal.availableToWithdraw) : 0;
}

// ─── Plasare ordin MARKET (privat Bybit) ─────────────────
async function placeOrder(side, quantity, symbol = cfg.SYMBOL) {
  if (cfg.PAPER_TRADING) {
    console.log(`[PAPER] ${side} ${quantity} ${symbol}`);
    return { orderId: 'PAPER_' + Date.now(), orderStatus: 'Filled' };
  }
  const params = {
    category: 'spot', symbol,
    side: side === 'BUY' ? 'Buy' : 'Sell',
    orderType: 'Market', qty: String(quantity),
  };
  const { data } = await axios.post(`${BASE}/v5/order/create`, params, {
    headers: { ...authHeaders(params), 'Content-Type': 'application/json' },
  });
  return data.result;
}

module.exports = { getPrice, getCandles, getBalance, placeOrder };
