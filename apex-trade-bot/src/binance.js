const axios = require('axios');
const crypto = require('crypto');
const cfg = require('./config');

// Default to TESTNET unless BINANCE_TESTNET is explicitly set to 'false'
// (live api.binance.com is geo-blocked from cloud servers in EU)
const _bnTest = (process.env.BINANCE_TESTNET || '').toLowerCase().trim();
const TESTNET = _bnTest !== 'false'; // default: true (testnet)
const BASE_URL = TESTNET
  ? 'https://testnet.binance.vision/api/v3'
  : 'https://api.binance.com/api/v3';

console.log(`[BINANCE] Mode: ${TESTNET ? '🧪 TESTNET (testnet.binance.vision)' : '🔴 LIVE (api.binance.com)'} | BINANCE_TESTNET="${process.env.BINANCE_TESTNET || '(not set — defaulting to testnet)'}"`);


const client = axios.create({ baseURL: BASE_URL, timeout: 10000 });

function sign(params) {
  const qs = new URLSearchParams(params).toString();
  const sig = crypto.createHmac('sha256', cfg.BINANCE_API_SECRET).update(qs).digest('hex');
  return `${qs}&signature=${sig}`;
}

function headers() {
  return { 'X-MBX-APIKEY': cfg.BINANCE_API_KEY };
}

// OKX fallback (geo-unrestricted public API)
async function _priceOKX(symbol) {
  const { data } = await axios.get('https://www.okx.com/api/v5/market/ticker', {
    params: { instId: symbol.replace('USDT', '-USDT') },
    headers: { 'User-Agent': 'ApexTradeBot/2.0' }, timeout: 6000,
  });
  return parseFloat(data.data[0].last);
}
async function _candlesOKX(symbol, interval, limit) {
  const { data } = await axios.get('https://www.okx.com/api/v5/market/candles', {
    params: { instId: symbol.replace('USDT', '-USDT'), bar: interval, limit },
    headers: { 'User-Agent': 'ApexTradeBot/2.0' }, timeout: 8000,
  });
  if (data.code !== '0') throw new Error('OKX: ' + data.msg);
  return data.data.reverse().map(k => ({
    time: parseInt(k[0]), open: parseFloat(k[1]), high: parseFloat(k[2]),
    low: parseFloat(k[3]), close: parseFloat(k[4]), volume: parseFloat(k[5]),
  }));
}

// Preț curent — Binance → OKX fallback
async function getPrice(symbol = cfg.SYMBOL) {
  try {
    const { data } = await client.get('/ticker/price', { params: { symbol } });
    return parseFloat(data.price);
  } catch (e) {
    console.warn('[DATA] Binance price blocked (' + e.message + ') → OKX');
    return _priceOKX(symbol);
  }
}

// Lumânări (OHLCV) — Binance → OKX fallback
async function getCandles(symbol = cfg.SYMBOL, interval = cfg.TIMEFRAME, limit = cfg.CANDLES) {
  try {
    const { data } = await client.get('/klines', { params: { symbol, interval, limit } });
    return data.map(k => ({
      open:   parseFloat(k[1]),
      high:   parseFloat(k[2]),
      low:    parseFloat(k[3]),
      close:  parseFloat(k[4]),
      volume: parseFloat(k[5]),
      time:   k[0],
    }));
  } catch (e) {
    console.warn('[DATA] Binance klines blocked (' + e.message + ') → OKX');
    return _candlesOKX(symbol, interval, limit);
  }
}

// Balanță USDT
async function getBalance(asset = cfg.QUOTE_ASSET) {
  const params = { timestamp: Date.now() };
  const { data } = await client.get(`/account?${sign(params)}`, { headers: headers() });
  const bal = data.balances.find(b => b.asset === asset);
  return bal ? parseFloat(bal.free) : 0;
}

// Info simbol (lot size etc.) — cache per simbol, filtrele nu se schimbă des
const _filterCache = {};
async function getSymbolInfo(symbol = cfg.SYMBOL) {
  if (_filterCache[symbol]) return _filterCache[symbol];
  const { data } = await client.get('/exchangeInfo', { params: { symbol } });
  const info = data.symbols.find(s => s.symbol === symbol);
  if (info) _filterCache[symbol] = info;
  return info;
}

// Rotunjire la regulile perechii — funcție pură, testabilă fără rețea
function applyFilters(info, quantity, price, symbol = '?') {
  const lot = info.filters.find(f => f.filterType === 'LOT_SIZE');
  const notional = info.filters.find(f => f.filterType === 'NOTIONAL' || f.filterType === 'MIN_NOTIONAL');
  const step = parseFloat(lot.stepSize);
  const qty = Math.floor(quantity / step) * step;
  // toFixed cu nr. de zecimale din stepSize (ex. "0.00100000" → 3)
  const decimals = Math.max(0, (lot.stepSize.split('.')[1] || '').replace(/0+$/, '').length);
  const qtyStr = qty.toFixed(decimals);
  if (qty < parseFloat(lot.minQty)) throw new Error(`Binance: qty ${qtyStr} sub minQty ${lot.minQty} pentru ${symbol}`);
  const minNotional = parseFloat(notional?.minNotional ?? '0');
  if (price && qty * price < minNotional) {
    throw new Error(`Binance: valoare ordin $${(qty * price).toFixed(2)} sub minimul $${minNotional} pentru ${symbol}`);
  }
  return { qty, qtyStr, decimals };
}

// Rotunjește cantitatea la stepSize-ul perechii (LOT_SIZE) și validează minNotional
async function normalizeQty(symbol, quantity, price) {
  const info = await getSymbolInfo(symbol);
  if (!info) throw new Error(`Binance: unknown symbol ${symbol}`);
  return applyFilters(info, quantity, price, symbol);
}

// Plasare ordin MARKET — rotunjit la LOT_SIZE, returnează fill-ul real
async function placeOrder(side, quantity, symbol = cfg.SYMBOL) {
  if (cfg.PAPER_TRADING) {
    console.log(`[PAPER] ${side} ${quantity} ${symbol}`);
    return { orderId: 'PAPER_' + Date.now(), status: 'FILLED', side, quantity };
  }
  const price = await getPrice(symbol).catch(() => null);
  const { qtyStr } = await normalizeQty(symbol, quantity, price);
  const params = {
    symbol, side, type: 'MARKET',
    quantity: qtyStr,
    newOrderRespType: 'FULL', // include fills[] în răspuns
    timestamp: Date.now(),
  };
  const { data } = await client.post(`/order?${sign(params)}`, null, { headers: headers() });
  // Fill-ul real (preț mediu ponderat + comision), nu prețul de ticker
  if (Array.isArray(data.fills) && data.fills.length) {
    let cost = 0, qty = 0, fee = 0;
    for (const f of data.fills) {
      cost += parseFloat(f.price) * parseFloat(f.qty);
      qty  += parseFloat(f.qty);
      if (f.commissionAsset === cfg.QUOTE_ASSET) fee += parseFloat(f.commission);
    }
    data.avgPrice    = qty > 0 ? cost / qty : null;
    data.executedQty = qty;
    data.quoteFee    = fee;
  }
  return data;
}

// ─── Protecție server-side: OCO SELL (TP limit + SL stop) pentru poziții BUY ──
// Dacă botul moare, exchange-ul execută oricum SL/TP.
async function placeProtection(symbol, qty, stopLoss, takeProfit) {
  if (cfg.PAPER_TRADING) return null;
  const info = await getSymbolInfo(symbol);
  const tickSize = parseFloat(info.filters.find(f => f.filterType === 'PRICE_FILTER').tickSize);
  const pDec = Math.max(0, (String(tickSize).split('.')[1] || '').length);
  const round = p => (Math.round(p / tickSize) * tickSize).toFixed(pDec);
  const { qtyStr } = await normalizeQty(symbol, qty, null);
  const params = {
    symbol, side: 'SELL', quantity: qtyStr,
    aboveType: 'LIMIT_MAKER',          abovePrice: round(takeProfit),
    belowType: 'STOP_LOSS_LIMIT',      belowStopPrice: round(stopLoss),
    belowPrice: round(stopLoss * 0.997), // limit puțin sub stop ca să se execute sigur
    belowTimeInForce: 'GTC',
    timestamp: Date.now(),
  };
  const { data } = await client.post(`/orderList/oco?${sign(params)}`, null, { headers: headers() });
  console.log(`[LIVE] 🛡️ OCO plasat la exchange: TP ${params.abovePrice} / SL ${params.belowStopPrice} (${symbol})`);
  return data;
}

async function cancelAllOrders(symbol = cfg.SYMBOL) {
  if (cfg.PAPER_TRADING) return null;
  const params = { symbol, timestamp: Date.now() };
  try {
    const { data } = await client.delete(`/openOrders?${sign(params)}`, { headers: headers() });
    return data;
  } catch (e) {
    // -2011 = no open orders — not an error
    if (e.response?.data?.code === -2011) return null;
    throw e;
  }
}

async function getOpenOrders(symbol = cfg.SYMBOL) {
  const params = { symbol, timestamp: Date.now() };
  const { data } = await client.get(`/openOrders?${sign(params)}`, { headers: headers() });
  return data;
}

// Ticker 24h
async function getTicker24h(symbol = cfg.SYMBOL) {
  const { data } = await client.get('/ticker/24hr', { params: { symbol } });
  return data;
}

module.exports = {
  getPrice, getCandles, getBalance, placeOrder, getSymbolInfo, getTicker24h,
  placeProtection, cancelAllOrders, getOpenOrders, applyFilters,
};
