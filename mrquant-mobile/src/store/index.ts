import { configureStore } from '@reduxjs/toolkit';
import authReducer from './slices/authSlice';
import marketsReducer from './slices/marketsSlice';
import portfolioReducer from './slices/portfolioSlice';
import signalsReducer from './slices/signalsSlice';

export const store = configureStore({
  reducer: {
    auth: authReducer,
    markets: marketsReducer,
    portfolio: portfolioReducer,
    signals: signalsReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
