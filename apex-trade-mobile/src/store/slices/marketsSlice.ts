import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { marketsAPI } from '../../services/api';

export interface Asset {
  symbol: string;
  name: string;
  price: number;
  change24h: number;
  changePercent24h: number;
  volume24h: number;
  marketCap?: number;
  high24h: number;
  low24h: number;
  market: 'crypto' | 'stocks' | 'forex';
  logo?: string;
}

export interface NewsItem {
  id: string;
  title: string;
  summary: string;
  source: string;
  url: string;
  publishedAt: string;
  sentiment: 'positive' | 'negative' | 'neutral';
  relatedSymbols: string[];
}

export interface MacroEvent {
  id: string;
  title: string;
  date: string;
  importance: 'high' | 'medium' | 'low';
  actual?: string;
  forecast?: string;
  previous?: string;
  currency: string;
}

interface MarketsState {
  crypto: Asset[];
  stocks: Asset[];
  forex: Asset[];
  news: NewsItem[];
  macroEvents: MacroEvent[];
  klines: Record<string, any[]>;
  loading: boolean;
  error: string | null;
  activeMarket: 'crypto' | 'stocks' | 'forex';
}

const initialState: MarketsState = {
  crypto: [],
  stocks: [],
  forex: [],
  news: [],
  macroEvents: [],
  klines: {},
  loading: false,
  error: null,
  activeMarket: 'crypto',
};

export const fetchCrypto = createAsyncThunk('markets/fetchCrypto', async () => {
  const res = await marketsAPI.getCrypto();
  return res.data;
});

export const fetchStocks = createAsyncThunk('markets/fetchStocks', async () => {
  const res = await marketsAPI.getStocks();
  return res.data;
});

export const fetchForex = createAsyncThunk('markets/fetchForex', async () => {
  const res = await marketsAPI.getForex();
  return res.data;
});

export const fetchKlines = createAsyncThunk(
  'markets/fetchKlines',
  async ({ symbol, interval, market }: { symbol: string; interval: string; market: string }) => {
    const res = await marketsAPI.getKlines(symbol, interval, market);
    return { key: `${symbol}_${interval}`, data: res.data };
  }
);

export const fetchNews = createAsyncThunk('markets/fetchNews', async (query?: string) => {
  const res = await marketsAPI.getNews(query);
  return res.data;
});

export const fetchMacroEvents = createAsyncThunk('markets/fetchMacroEvents', async () => {
  const res = await marketsAPI.getMacroEvents();
  return res.data;
});

const marketsSlice = createSlice({
  name: 'markets',
  initialState,
  reducers: {
    setActiveMarket: (state, action) => { state.activeMarket = action.payload; },
    updatePrice: (state, action) => {
      const { symbol, price, change24h, changePercent24h, market } = action.payload;
      const list = state[market as 'crypto' | 'stocks' | 'forex'];
      const idx = list.findIndex((a) => a.symbol === symbol);
      if (idx !== -1) {
        list[idx].price = price;
        list[idx].change24h = change24h;
        list[idx].changePercent24h = changePercent24h;
      }
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchCrypto.pending, (state) => { state.loading = true; })
      .addCase(fetchCrypto.fulfilled, (state, action) => {
        state.loading = false;
        state.crypto = action.payload;
      })
      .addCase(fetchStocks.fulfilled, (state, action) => {
        state.stocks = action.payload;
      })
      .addCase(fetchForex.fulfilled, (state, action) => {
        state.forex = action.payload;
      })
      .addCase(fetchKlines.fulfilled, (state, action) => {
        state.klines[action.payload.key] = action.payload.data;
      })
      .addCase(fetchNews.fulfilled, (state, action) => {
        state.news = action.payload;
      })
      .addCase(fetchMacroEvents.fulfilled, (state, action) => {
        state.macroEvents = action.payload;
      });
  },
});

export const { setActiveMarket, updatePrice } = marketsSlice.actions;
export default marketsSlice.reducer;
