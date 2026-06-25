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

-- Affiliate terms acceptance (proof of consent for the affiliate program).
ALTER TABLE affiliates ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ;
ALTER TABLE affiliates ADD COLUMN IF NOT EXISTS terms_version TEXT;

-- Commission clawback: a refunded/charged-back sale cancels the commission.
ALTER TABLE referral_sales ADD COLUMN IF NOT EXISTS refunded BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE referral_sales ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMPTZ;

-- Where the affiliate wants to be paid (PayPal email / IBAN / crypto wallet).
ALTER TABLE affiliates ADD COLUMN IF NOT EXISTS payout_method TEXT;
ALTER TABLE affiliates ADD COLUMN IF NOT EXISTS payout_details TEXT;

-- Referral link clicks — one row per visit to aicashsystem.space/?ref=CODE.
-- Atomic inserts (no read-modify-write race), and gives a real click count +
-- conversion rate (sales / clicks) in the affiliate's /stats.
CREATE TABLE IF NOT EXISTS affiliate_clicks (
  id              BIGSERIAL PRIMARY KEY,
  affiliate_code  TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_code ON affiliate_clicks(affiliate_code);

-- Payout requests raised by affiliates, settled manually by the owner.
CREATE TABLE IF NOT EXISTS payout_requests (
  id              BIGSERIAL PRIMARY KEY,
  affiliate_code  TEXT NOT NULL REFERENCES affiliates(code),
  amount_cents    INTEGER NOT NULL,
  method          TEXT,
  details         TEXT,
  status          TEXT NOT NULL DEFAULT 'requested', -- requested | paid | rejected
  requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at    TIMESTAMPTZ,
  note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_payout_requests_affiliate ON payout_requests(affiliate_code);
CREATE INDEX IF NOT EXISTS idx_payout_requests_status ON payout_requests(status);
