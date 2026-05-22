import axios from 'axios';
import * as SecureStore from 'expo-secure-store';

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL || 'https://apextrade-api.railway.app';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// Attach JWT token to every request
api.interceptors.request.use(async (config) => {
  const token = await SecureStore.getItemAsync('apextrade_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Auto-refresh on 401
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status === 401) {
      await SecureStore.deleteItemAsync('apextrade_token');
    }
    return Promise.reject(error);
  }
);

// ─── Auth ────────────────────────────────────────────────
export const authAPI = {
  login: (email: string, password: string) =>
    api.post('/auth/login', { email, password }),
  register: (email: string, password: string, name: string) =>
    api.post('/auth/register', { email, password, name }),
  logout: () => api.post('/auth/logout'),
  me: () => api.get('/auth/me'),
};

// ─── Markets ─────────────────────────────────────────────
export const marketsAPI = {
  getCrypto: (symbols?: string[]) =>
    api.get('/markets/crypto', { params: { symbols: symbols?.join(',') } }),
  getStocks: (symbols?: string[]) =>
    api.get('/markets/stocks', { params: { symbols: symbols?.join(',') } }),
  getForex: (pairs?: string[]) =>
    api.get('/markets/forex', { params: { pairs: pairs?.join(',') } }),
  getKlines: (symbol: string, interval: string, market: string) =>
    api.get('/markets/klines', { params: { symbol, interval, market } }),
  getNews: (query?: string) =>
    api.get('/markets/news', { params: { query } }),
  getMacroEvents: () => api.get('/markets/macro'),
};

// ─── Signals ─────────────────────────────────────────────
export const signalsAPI = {
  getSignals: (market?: string) =>
    api.get('/signals', { params: { market } }),
  getSignalDetail: (id: string) => api.get(`/signals/${id}`),
  runAIAnalysis: (symbol: string, market: string) =>
    api.post('/signals/analyze', { symbol, market }),
};

// ─── Backtest ────────────────────────────────────────────
export const backtestAPI = {
  run: (params: BacktestParams) => api.post('/backtest/run', params),
  getHistory: () => api.get('/backtest/history'),
  getResult: (id: string) => api.get(`/backtest/${id}`),
  getStrategies: () => api.get('/backtest/strategies'),
};

// ─── Portfolio ───────────────────────────────────────────
export const portfolioAPI = {
  getPortfolio: () => api.get('/portfolio'),
  getPositions: () => api.get('/portfolio/positions'),
  getPnL: (period: string) => api.get('/portfolio/pnl', { params: { period } }),
  getHistory: () => api.get('/portfolio/history'),
};

// ─── Broker ──────────────────────────────────────────────
export const brokerAPI = {
  connect: (broker: string, apiKey: string, apiSecret: string, sandbox?: boolean) =>
    api.post('/broker/connect', { broker, apiKey, apiSecret, sandbox }),
  disconnect: () => api.delete('/broker/disconnect'),
  getStatus: () => api.get('/broker/status'),
  placeOrder: (order: OrderParams) => api.post('/broker/order', order),
  cancelOrder: (orderId: string) => api.delete(`/broker/order/${orderId}`),
  getOrders: () => api.get('/broker/orders'),
};

// ─── Types ───────────────────────────────────────────────
export interface BacktestParams {
  strategy: string;
  symbol: string;
  market: string;
  startDate: string;
  endDate: string;
  initialCapital: number;
  params?: Record<string, number>;
}

export interface OrderParams {
  symbol: string;
  side: 'buy' | 'sell';
  type: 'market' | 'limit';
  quantity: number;
  price?: number;
  market: string;
}

export default api;
