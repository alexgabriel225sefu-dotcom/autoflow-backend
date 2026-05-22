import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit';
import * as SecureStore from 'expo-secure-store';
import { authAPI } from '../../services/api';

interface User {
  id: string;
  email: string;
  name: string;
  plan: 'free' | 'pro' | 'enterprise';
  brokerConnected: boolean;
}

interface AuthState {
  user: User | null;
  token: string | null;
  loading: boolean;
  error: string | null;
}

const initialState: AuthState = {
  user: null,
  token: null,
  loading: false,
  error: null,
};

export const loginThunk = createAsyncThunk(
  'auth/login',
  async ({ email, password }: { email: string; password: string }, { rejectWithValue }) => {
    try {
      const res = await authAPI.login(email, password);
      await SecureStore.setItemAsync('apextrade_token', res.data.token);
      return res.data;
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.message || 'Eroare la autentificare');
    }
  }
);

export const registerThunk = createAsyncThunk(
  'auth/register',
  async (
    { email, password, name }: { email: string; password: string; name: string },
    { rejectWithValue }
  ) => {
    try {
      const res = await authAPI.register(email, password, name);
      await SecureStore.setItemAsync('apextrade_token', res.data.token);
      return res.data;
    } catch (err: any) {
      return rejectWithValue(err.response?.data?.message || 'Eroare la înregistrare');
    }
  }
);

export const logoutThunk = createAsyncThunk('auth/logout', async () => {
  await SecureStore.deleteItemAsync('apextrade_token');
  await authAPI.logout().catch(() => {});
});

export const loadUserThunk = createAsyncThunk('auth/loadUser', async (_, { rejectWithValue }) => {
  try {
    const token = await SecureStore.getItemAsync('apextrade_token');
    if (!token) return rejectWithValue('No token');
    const res = await authAPI.me();
    return { user: res.data, token };
  } catch {
    await SecureStore.deleteItemAsync('apextrade_token');
    return rejectWithValue('Session expired');
  }
});

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    clearError: (state) => { state.error = null; },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loginThunk.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(loginThunk.fulfilled, (state, action) => {
        state.loading = false;
        state.user = action.payload.user;
        state.token = action.payload.token;
      })
      .addCase(loginThunk.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload as string;
      })
      .addCase(registerThunk.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(registerThunk.fulfilled, (state, action) => {
        state.loading = false;
        state.user = action.payload.user;
        state.token = action.payload.token;
      })
      .addCase(registerThunk.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload as string;
      })
      .addCase(logoutThunk.fulfilled, (state) => {
        state.user = null;
        state.token = null;
      })
      .addCase(loadUserThunk.fulfilled, (state, action) => {
        state.user = action.payload.user;
        state.token = action.payload.token;
      })
      .addCase(loadUserThunk.rejected, (state) => {
        state.user = null;
        state.token = null;
      });
  },
});

export const { clearError } = authSlice.actions;
export default authSlice.reducer;
