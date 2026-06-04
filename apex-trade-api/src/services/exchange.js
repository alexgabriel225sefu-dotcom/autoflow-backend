const axios = require('axios');
const crypto = require('crypto');

const BASE_URL = 'https://api.binance.com';
const TESTNET_URL = 'https://testnet.binance.vision';

class BinanceExchange {
  constructor(apiKey, apiSecret, testnet = false) {
    this.apiKey = apiKey;
    this.apiSecret = apiSecret;
    this.baseUrl = testnet ? TESTNET_URL : BASE_URL;
  }

  _sign(params) {
    const query = new URLSearchParams(params).toString();
    const sig = crypto.createHmac('sha256', this.apiSecret).update(query).digest('hex');
    return `${query}&signature=${sig}`;
  }

  async _get(path, params = {}, auth = false) {
    if (auth) {
      params.timestamp = Date.now();
      params.recvWindow = 5000;
    }
    const qs = auth ? this._sign(params) : new URLSearchParams(params).toString();
    const headers = auth ? { 'X-MBX-APIKEY': this.apiKey } : {};
    const res = await axios.get(`${this.baseUrl}${path}?${qs}`, { headers, timeout: 10000 });
    return res.data;
  }

  async _post(path, params = {}) {
    params.timestamp = Date.now();
    params.recvWindow = 5000;
    const qs = this._sign(params);
    const res = await axios.post(`${this.baseUrl}${path}?${qs}`, null, {
      headers: { 'X-MBX-APIKEY': this.apiKey },
      timeout: 10000,
    });
    return res.data;
  }

  async _delete(path, params = {}) {
    params.timestamp = Date.now();
    params.recvWindow = 5000;
    const qs = this._sign(params);
    const res = await axios.delete(`${this.baseUrl}${path}?${qs}`, {
      headers: { 'X-MBX-APIKEY': this.apiKey },
      timeout: 10000,
    });
    return res.data;
  }

  async getPrice(symbol) {
    const data = await this._get('/api/v3/ticker/price', { symbol });
    return parseFloat(data.price);
  }

  async get24hr(symbol) {
    return this._get('/api/v3/ticker/24hr', { symbol });
  }

  async getBalance() {
    const data = await this._get('/api/v3/account', {}, true);
    const out = {};
    for (const b of data.balances) {
      const total = parseFloat(b.free) + parseFloat(b.locked);
      if (total > 0) out[b.asset] = { free: parseFloat(b.free), locked: parseFloat(b.locked), total };
    }
    return out;
  }

  async getUSDTBalance() {
    const bal = await this.getBalance();
    return bal.USDT?.free || 0;
  }

  async getKlines(symbol, interval = '1h', limit = 100) {
    const data = await this._get('/api/v3/klines', { symbol, interval, limit });
    return data.map((k) => ({
      openTime: k[0],
      open: parseFloat(k[1]),
      high: parseFloat(k[2]),
      low: parseFloat(k[3]),
      close: parseFloat(k[4]),
      volume: parseFloat(k[5]),
    }));
  }

  async getLotSize(symbol) {
    const data = await this._get('/api/v3/exchangeInfo', { symbol });
    const info = data.symbols?.[0];
    const lot = info?.filters.find((f) => f.filterType === 'LOT_SIZE');
    const minNotional = info?.filters.find((f) => f.filterType === 'MIN_NOTIONAL' || f.filterType === 'NOTIONAL');
    return {
      stepSize: parseFloat(lot?.stepSize || '0.00001'),
      minQty: parseFloat(lot?.minQty || '0.00001'),
      minNotional: parseFloat(minNotional?.minNotional || minNotional?.notional || '5'),
    };
  }

  roundQty(qty, stepSize) {
    const decimals = stepSize.toString().split('.')[1]?.length || 0;
    return parseFloat((Math.floor(qty / stepSize) * stepSize).toFixed(decimals));
  }

  async buyMarket(symbol, quoteAmount) {
    return this._post('/api/v3/order', {
      symbol,
      side: 'BUY',
      type: 'MARKET',
      quoteOrderQty: quoteAmount.toFixed(2),
    });
  }

  async sellMarket(symbol, quantity) {
    return this._post('/api/v3/order', {
      symbol,
      side: 'SELL',
      type: 'MARKET',
      quantity: quantity.toString(),
    });
  }

  async cancelAllOrders(symbol) {
    try {
      return await this._delete('/api/v3/openOrders', { symbol });
    } catch {
      return [];
    }
  }

  async testConnection() {
    try {
      await this._get('/api/v3/account', {}, true);
      return true;
    } catch {
      return false;
    }
  }
}

module.exports = BinanceExchange;
