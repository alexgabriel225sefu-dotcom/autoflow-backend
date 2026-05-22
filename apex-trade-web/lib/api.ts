import axios from 'axios';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://autoflow-backend-production-9b95.up.railway.app';

export const api = axios.create({
  baseURL: API_URL,
  timeout: 10000,
  headers: { 'Content-Type': 'application/json' },
});

// Auto-attach JWT token
api.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('apex_token');
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-logout on 401
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && typeof window !== 'undefined') {
      localStorage.removeItem('apex_token');
      localStorage.removeItem('apex_user');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

// Auth
export const authApi = {
  login: (email: string, password: string) =>
    api.post('/auth/login', { email, password }),
  register: (email: string, password: string, name: string) =>
    api.post('/auth/register', { email, password, name }),
  me: () => api.get('/auth/me'),
};

// Markets
export const marketsApi = {
  getCrypto: () => api.get('/markets/crypto'),
  getStocks: () => api.get('/markets/stocks'),
  getForex: () => api.get('/markets/forex'),
};

// Signals
export const signalsApi = {
  getAll: (market?: string) => api.get('/signals', { params: { market } }),
  analyze: (symbol: string, market: string) =>
    api.post('/signals/analyze', { symbol, market }),
};

// Portfolio
export const portfolioApi = {
  getSummary: () => api.get('/portfolio'),
  getPositions: () => api.get('/portfolio/positions'),
  getPnL: (period: string) => api.get('/portfolio/pnl', { params: { period } }),
};

// Backtest
export const backtestApi = {
  getStrategies: () => api.get('/backtest/strategies'),
  run: (params: object) => api.post('/backtest/run', params),
};
