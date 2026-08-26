-- Apex — the two tables server.js cannot work without.
--
-- WHY THIS EXISTS: all three Supabase projects on this account were found to
-- contain ZERO tables. The licence system had therefore never had a database
-- behind it — which is exactly why /api/verify-license used to grant on an
-- HMAC signature alone, and why removing that fail-open would have refused
-- every activation. A signature proves the key was minted here; only this
-- table knows whether it was PAID FOR, refunded, or an expired trial.
--
-- Columns are derived from server.js, not invented: every one below is read
-- or written by code in that file.
--
-- Idempotent. Safe to run against a project that already has them.

CREATE TABLE IF NOT EXISTS licenses (
    key               TEXT PRIMARY KEY,
    email             TEXT,
    name              TEXT,
    product           TEXT        NOT NULL DEFAULT 'apex-forex',
    -- active is written ONLY by the payment webhook (_fulfillOrder) and the
    -- admin grant path. Verification never sets it: that is what made a valid
    -- signature stop being proof of payment.
    active            BOOLEAN     NOT NULL DEFAULT FALSE,
    activated_at      TIMESTAMPTZ,
    payment_intent_id TEXT,
    refunded          BOOLEAN     NOT NULL DEFAULT FALSE,
    refunded_at       TIMESTAMPTZ,
    trial             BOOLEAN     NOT NULL DEFAULT FALSE,
    expires_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fulfilment looks a payment up by its intent id to stay idempotent across
-- webhook redeliveries; without this that is a full scan, and Stripe retries.
CREATE UNIQUE INDEX IF NOT EXISTS licenses_payment_intent_id_key
    ON licenses (payment_intent_id)
    WHERE payment_intent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS licenses_email_idx ON licenses (email);

-- Client bot configuration, encrypted at rest with the key derived from
-- JWT_SECRET (server.js::_botConfigKey). The ciphertext is stored here; the
-- key never is.
CREATE TABLE IF NOT EXISTS bot_configs (
    license_key TEXT PRIMARY KEY,
    config      TEXT        NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
