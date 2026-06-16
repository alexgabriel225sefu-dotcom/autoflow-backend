-- Affiliate / referral system for Apex Bot sales.
-- Run this once in the Supabase SQL editor (same project used for `licenses`, `purchases`, etc).

CREATE TABLE IF NOT EXISTS affiliates (
  code                TEXT PRIMARY KEY,
  email               TEXT NOT NULL,
  name                TEXT,
  tiktok_handle       TEXT,
  commission_percent  INTEGER NOT NULL DEFAULT 30,
  status              TEXT NOT NULL DEFAULT 'active', -- active | suspended
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS referral_sales (
  id                  BIGSERIAL PRIMARY KEY,
  affiliate_code      TEXT NOT NULL REFERENCES affiliates(code),
  license_key         TEXT,
  payment_intent_id   TEXT UNIQUE,
  product             TEXT,
  amount              INTEGER NOT NULL,           -- cents, full sale price
  commission_amount   INTEGER NOT NULL,           -- cents, affiliate's cut
  paid                BOOLEAN NOT NULL DEFAULT false,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_referral_sales_affiliate_code ON referral_sales(affiliate_code);

-- Run this if the tables already existed with the old 20% default —
-- CREATE TABLE IF NOT EXISTS does not alter an existing table.
ALTER TABLE affiliates ALTER COLUMN commission_percent SET DEFAULT 30;
UPDATE affiliates SET commission_percent = 30 WHERE commission_percent = 20;

-- Affiliate login: password (scrypt salt:hash, set on signup or account claim).
ALTER TABLE affiliates ADD COLUMN IF NOT EXISTS password_hash TEXT;
