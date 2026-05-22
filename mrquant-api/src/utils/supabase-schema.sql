-- MrQuant Database Schema
-- Rulează în Supabase SQL Editor

-- Users
CREATE TABLE IF NOT EXISTS users (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  plan TEXT DEFAULT 'free' CHECK (plan IN ('free', 'pro', 'enterprise')),
  broker_connected BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Broker Connections (encrypted API keys)
CREATE TABLE IF NOT EXISTS broker_connections (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  broker TEXT NOT NULL,
  api_key_encrypted TEXT NOT NULL,
  api_secret_encrypted TEXT NOT NULL,
  sandbox BOOLEAN DEFAULT true,
  status TEXT DEFAULT 'active',
  connected_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id)
);

-- Signals History
CREATE TABLE IF NOT EXISTS signals (
  id TEXT PRIMARY KEY,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('BUY', 'SELL', 'HOLD')),
  confidence INTEGER,
  entry_price DECIMAL,
  target_price DECIMAL,
  stop_loss DECIMAL,
  risk_reward_ratio DECIMAL,
  timeframe TEXT,
  reasoning TEXT,
  indicators JSONB,
  status TEXT DEFAULT 'active',
  created_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ
);

-- Backtest History
CREATE TABLE IF NOT EXISTS backtests (
  id TEXT PRIMARY KEY,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  strategy TEXT NOT NULL,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  initial_capital DECIMAL,
  final_capital DECIMAL,
  total_return DECIMAL,
  sharpe_ratio DECIMAL,
  max_drawdown DECIMAL,
  win_rate DECIMAL,
  total_trades INTEGER,
  params JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Portfolio Positions
CREATE TABLE IF NOT EXISTS positions (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('long', 'short')),
  quantity DECIMAL NOT NULL,
  entry_price DECIMAL NOT NULL,
  current_price DECIMAL,
  pnl DECIMAL DEFAULT 0,
  pnl_percent DECIMAL DEFAULT 0,
  opened_at TIMESTAMPTZ DEFAULT now(),
  closed_at TIMESTAMPTZ,
  status TEXT DEFAULT 'open'
);

-- Orders History
CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  side TEXT NOT NULL,
  type TEXT NOT NULL,
  quantity DECIMAL,
  price DECIMAL,
  filled_price DECIMAL,
  status TEXT DEFAULT 'pending',
  broker TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Row Level Security
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE broker_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE backtests ENABLE ROW LEVEL SECURITY;
ALTER TABLE positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

-- Policies (Service role bypasses RLS — API uses service key)
CREATE POLICY "Service role full access" ON users FOR ALL USING (true);
CREATE POLICY "Service role full access" ON broker_connections FOR ALL USING (true);
CREATE POLICY "Service role full access" ON signals FOR ALL USING (true);
CREATE POLICY "Service role full access" ON backtests FOR ALL USING (true);
CREATE POLICY "Service role full access" ON positions FOR ALL USING (true);
CREATE POLICY "Service role full access" ON orders FOR ALL USING (true);
