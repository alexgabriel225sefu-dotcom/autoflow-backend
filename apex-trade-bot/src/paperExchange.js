/**
 * Paper Exchange — public OKX market data + simulated order fills.
 * Used by the multi-tenant server: all users trade paper by default
 * without needing API keys. Same interface as real exchange connectors.
 */
const axios = require('axios');

const HEADERS = { 'User-Agent': 'ApexTradeBot/2.0' };
const TF      = { '1m':'1m','3m':'3m','5m':'5m','15m':'15m','30m':'30m','1h':'1H','4h':'4H','1d':'1D' };

function toOKX(sym) {
  return sym.endsWith('USDT') ? sym.replace('USDT', '-USDT') : sym;
}

async function getPrice(symbol) {
  const { data } = await axios.get('https://www.okx.com/api/v5/market/ticker', {
    params: { instId: toOKX(symbol) }, headers: HEADERS, timeout: 6000,
  });
  return parseFloat(data.data[0].last);
}

async function getCandles(symbol, interval = '5m', limit = 200) {
  const bar = TF[interval] || interval;
  const { data } = await axios.get('https://www.okx.com/api/v5/market/candles', {
    params: { instId: toOKX(symbol), bar, limit }, headers: HEADERS, timeout: 10000,
  });
  if (data.code !== '0') throw new Error(`OKX candles: ${data.msg}`);
  return data.data.slice().reverse().map(k => ({
    time:   parseInt(k[0]),
    open:   parseFloat(k[1]),
    high:   parseFloat(k[2]),
    low:    parseFloat(k[3]),
    close:  parseFloat(k[4]),
    volume: parseFloat(k[5]),
  }));
}

async function getBalance() { return 0; } // paper mode uses local balance

async function placeOrder(side, qty, symbol) {
  const price = await getPrice(symbol);
  return { avgPrice: price, executedQty: qty, quoteFee: qty * price * 0.001 };
}

module.exports = { getPrice, getCandles, getBalance, placeOrder, __name: 'paper-okx' };
