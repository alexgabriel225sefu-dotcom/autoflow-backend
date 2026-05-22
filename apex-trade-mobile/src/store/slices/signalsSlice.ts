import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { signalsAPI } from '../../services/api';

export interface Signal {
  id: string;
  symbol: string;
  market: 'crypto' | 'stocks' | 'forex';
  action: 'BUY' | 'SELL' | 'HOLD';
  confidence: number; // 0-100
  entryPrice: number;
  targetPrice: number;
  stopLoss: number;
  riskRewardRatio: number;
  timeframe: string;
  reasoning: string;
  indicators: {
    rsi: number;
    macd: number;
    macdSignal: number;
    ema20: number;
    ema50: number;
    bb_upper: number;
    bb_lower: number;
    volume_ratio: number;
  };
  newssentiment: 'positive' | 'negative' | 'neutral';
  macroImpact: 'positive' | 'negative' | 'neutral';
  createdAt: string;
  expiresAt: string;
  status: 'active' | 'triggered' | 'expired';
}

interface SignalsState {
  signals: Signal[];
  loading: boolean;
  analyzing: boolean;
  error: string | null;
  activeMarket: string;
}

const initialState: SignalsState = {
  signals: [],
  loading: false,
  analyzing: false,
  error: null,
  activeMarket: 'all',
};

export const fetchSignals = createAsyncThunk(
  'signals/fetchSignals',
  async (market?: string) => {
    const res = await signalsAPI.getSignals(market);
    return res.data;
  }
);

export const runAnalysis = createAsyncThunk(
  'signals/runAnalysis',
  async ({ symbol, market }: { symbol: string; market: string }, { rejectWithValue }) => {
    try {
      const res = await signalsAPI.runAIAnalysis(symbol, market);
      return res.data;
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.message || 'Eroare la analiză');
    }
  }
);

const signalsSlice = createSlice({
  name: 'signals',
  initialState,
  reducers: {
    setActiveMarket: (state, action) => { state.activeMarket = action.payload; },
    addSignal: (state, action) => {
      state.signals.unshift(action.payload);
      if (state.signals.length > 50) state.signals.pop();
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchSignals.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchSignals.fulfilled, (state, action) => {
        state.loading = false;
        state.signals = action.payload;
      })
      .addCase(fetchSignals.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message || 'Eroare';
      })
      .addCase(runAnalysis.pending, (state) => { state.analyzing = true; })
      .addCase(runAnalysis.fulfilled, (state, action) => {
        state.analyzing = false;
        state.signals.unshift(action.payload);
      })
      .addCase(runAnalysis.rejected, (state, action) => {
        state.analyzing = false;
        state.error = action.payload as string;
      });
  },
});

export const { setActiveMarket, addSignal } = signalsSlice.actions;
export default signalsSlice.reducer;
