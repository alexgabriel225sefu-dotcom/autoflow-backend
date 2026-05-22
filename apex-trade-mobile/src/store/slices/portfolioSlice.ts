import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { portfolioAPI } from '../../services/api';

export interface Position {
  id: string;
  symbol: string;
  market: 'crypto' | 'stocks' | 'forex';
  side: 'long' | 'short';
  quantity: number;
  entryPrice: number;
  currentPrice: number;
  pnl: number;
  pnlPercent: number;
  openedAt: string;
}

export interface PortfolioSummary {
  totalValue: number;
  totalPnL: number;
  totalPnLPercent: number;
  dailyPnL: number;
  dailyPnLPercent: number;
  winRate: number;
  totalTrades: number;
  currency: string;
}

interface PortfolioState {
  summary: PortfolioSummary | null;
  positions: Position[];
  pnlHistory: { date: string; value: number }[];
  loading: boolean;
  error: string | null;
}

const initialState: PortfolioState = {
  summary: null,
  positions: [],
  pnlHistory: [],
  loading: false,
  error: null,
};

export const fetchPortfolio = createAsyncThunk('portfolio/fetch', async () => {
  const [portfolioRes, positionsRes] = await Promise.all([
    portfolioAPI.getPortfolio(),
    portfolioAPI.getPositions(),
  ]);
  return {
    summary: portfolioRes.data,
    positions: positionsRes.data,
  };
});

export const fetchPnLHistory = createAsyncThunk(
  'portfolio/pnlHistory',
  async (period: string) => {
    const res = await portfolioAPI.getPnL(period);
    return res.data;
  }
);

const portfolioSlice = createSlice({
  name: 'portfolio',
  initialState,
  reducers: {
    updatePosition: (state, action) => {
      const idx = state.positions.findIndex((p) => p.id === action.payload.id);
      if (idx !== -1) state.positions[idx] = { ...state.positions[idx], ...action.payload };
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchPortfolio.pending, (state) => { state.loading = true; })
      .addCase(fetchPortfolio.fulfilled, (state, action) => {
        state.loading = false;
        state.summary = action.payload.summary;
        state.positions = action.payload.positions;
      })
      .addCase(fetchPortfolio.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message || 'Eroare';
      })
      .addCase(fetchPnLHistory.fulfilled, (state, action) => {
        state.pnlHistory = action.payload;
      });
  },
});

export const { updatePosition } = portfolioSlice.actions;
export default portfolioSlice.reducer;
