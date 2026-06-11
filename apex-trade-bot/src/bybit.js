const axios = require('axios');
const crypto = require('crypto');
const cfg = require('./config');

const BASE = cfg.BYBIT_TESTNET
  ? 'https://api-testnet.bybit.com'
  : 'https://api.bybit.com';

const RECV_WINDOW = '5000';

// ─── Bybit v5 sign: GET uses queryString, POST uses raw JSON body ──────────
function signGet(params) {
  const ts = Date.now().toString();
  const query = Object.keys(params).sort().map(k => `${k}=${params[k]}`).join('&');
  const payload = ts + cfg.BYBIT_API_KEY + RECV_WINDOW + query;
  const sig = crypto.createHmac('sha256', cfg.BYBIT_API_SECRET).update(payload).digest('hex');
  return { sig, ts };
}

function signPost(body) {
  const ts = Date.now().toString();
  // POST: sign the raw JSON string, NOT a query string
  const payload = ts + cfg.BYBIT_API_KEY + RECV_WINDOW + JSON.stringify(body);
  const sig = crypto.createHmac('sha256', cfg.BYBIT_API_SECRET).update(payload).digest('hex');
  return { sig, ts };
}

function authHeadersGet(params) {
  const { sig, ts } = signGet(params);
  return {
    'X-BAPI-API-KEY':     cfg.BYBIT_API_KEY,
    'X-BAPI-TIMESTAMP':   ts,
    'X-BAPI-SIGN':        sig,
    'X-BAPI-RECV-WINDOW': RECV_WINDOW,
  };
}

function authHeadersPost(body) {
  const { sig, ts } = signPost(body);
  return {
    'X-BAPI-API-KEY':     cfg.BYBIT_API_KEY,
    'X-BAPI-TIMESTAMP':   ts,
    'X-BAPI-SIGN':        sig,
    'X-BAPI-RECV-WINDOW': RECV_WINDOW,
    'Content-Type':       'application/json',
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
  const okxSym = symbol.replace('USDT', '-USDT');
  const { data } = await axios.get('https://www.okx.com/api/v5/market/candles', {
    params: { instId: okxSym, bar: interval, limit },
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
  try {
    const { data } = await axios.get(`${BASE}/v5/market/tickers`, {
      params: { category: 'spot', symbol },
      headers: { 'User-Agent': 'ApexTradeBot/2.0' },
      timeout: 6000,
    });
    const price = data.result?.list?.[0]?.lastPrice;
    if (price) return parseFloat(price);
  } catch {}

  try {
    const { data } = await axios.get('https://api.binance.com/api/v3/ticker/price', {
      params: { symbol },
      headers: { 'User-Agent': 'ApexTradeBot/2.0' },
      timeout: 6000,
    });
    return parseFloat(data.price);
  } catch {}

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

// ─── Balanță (privat Bybit) — GET ────────────────────────
async function getBalance(coin = 'USDT') {
  if (cfg.PAPER_TRADING) return cfg.PAPER_BALANCE;
  const params = { accountType: 'UNIFIED', coin };
  const { data } = await axios.get(`${BASE}/v5/account/wallet-balance`, {
    params, headers: authHeadersGet(params),
    timeout: 8000,
  });
  if (data.retCode !== 0) throw new Error('Bybit balance: ' + data.retMsg);
  const bal = data.result.list[0]?.coin?.find(c => c.coin === coin);
  return bal ? parseFloat(bal.availableToWithdraw) : 0;
}

// ─── Plasare ordin MARKET (privat Bybit) — POST ──────────
async function placeOrder(side, quantity, symbol = cfg.SYMBOL) {
  if (cfg.PAPER_TRADING) {
    console.log(`[PAPER] ${side} ${quantity} ${symbol}`);
    return { orderId: 'PAPER_' + Date.now(), orderStatus: 'Filled' };
  }

  const body = {
    category:  'spot',
    symbol,
    side:      side === 'BUY' ? 'Buy' : 'Sell',
    orderType: 'Market',
    qty:       String(quantity),
    // Fără asta, Bybit interpretează qty la market BUY ca monedă QUOTE (USDT),
    // nu ca monedă de bază — ordinul ar fi greșit cu un factor de ~preț
    marketUnit: 'baseCoin',
  };

  const { data } = await axios.post(
    `${BASE}/v5/order/create`,
    body,
    { headers: authHeadersPost(body), timeout: 10000 }
  );

  if (data.retCode !== 0) {
    throw new Error(`Bybit order failed (${data.retCode}): ${data.retMsg}`);
  }
  console.log(`[LIVE] Order placed: ${side} ${quantity} ${symbol} → orderId: ${data.result?.orderId}`);
  return data.result;
}

module.exports = { getPrice, getCandles, getBalance, placeOrder };
