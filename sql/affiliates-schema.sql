-- Affiliate / referral system for Apex Bot sales.
-- Run this once in the Supabase SQL editor (same project used for `licenses`, `purchases`, etc).

CREATE TABLE IF NOT EXISTS affiliates (
  code                TEXT PRIMARY KEY,
  email               TEXT NOT NULL,
  name                TEXT,
  tiktok_handle       TEXT,
  commission_percent  INTEGER NOT NULL DEFAULT 20,
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
