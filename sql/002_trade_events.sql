-- Trade decision events — §23 of the platform brief.
--
-- WHY THIS IS A MIGRATION AND NOT THE LIVE STORE
--
-- The decision log ships in Redis (apex/trade_events.py), because that is where
-- the trade journal already lives and §23 says not to create duplicate tables
-- for functionality that already exists. Redis is bounded at 2000 events per
-- account, which is roughly a fortnight of an active one.
--
-- This table is the durable half, for the two things Redis is the wrong shape
-- for: an audit trail that outlives a key eviction, and analytics across
-- accounts. It is OPTIONAL — nothing in the running platform requires it, and
-- the code does not write here yet. Applying it early means the archive exists
-- before anyone needs to reconstruct a year-old trade.
--
-- IMMUTABILITY IS ENFORCED, NOT REQUESTED
--
-- The whole value of a decision log is that a strategy change tomorrow cannot
-- alter last week's explanation. A comment saying "do not update" is not that
-- guarantee, so the trigger below refuses UPDATE and DELETE outright. If a row
-- is genuinely wrong, the correction is a new row that says so.
--
-- Apply with:  psql "$DATABASE_URL" -f sql/002_trade_events.sql
-- Safe to re-run.

CREATE TABLE IF NOT EXISTS trade_events (
    event_id         text        PRIMARY KEY,
    schema_version   text        NOT NULL,
    -- The owning account. Every user-scoped record has an explicit ownership
    -- column; there is no query in the platform that spans users, and this is
    -- what keeps that true here too.
    user_id          text        NOT NULL,
    account_id       text,
    -- LIVE / DEMO / SIMULATION / UNKNOWN. Stored, never inferred at read time:
    -- an event that mislabels its environment is read later as proof.
    environment      text        NOT NULL,
    event_type       text        NOT NULL,
    symbol           text,
    trade_id         text,
    position_id      text,
    -- The versions that were live when the decision was made. A strategy
    -- update must not change what an old event says it decided.
    strategy_id      text,
    strategy_version text,
    risk_version     text,
    occurred_at      timestamptz NOT NULL,
    payload          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- Indexes for the three questions actually asked: this account's recent
-- events, one trade's timeline, and one instrument's decisions. §23 says not
-- to over-index — there is no index on payload, environment or event_type
-- alone, because nothing reads by them.
CREATE INDEX IF NOT EXISTS trade_events_user_time_idx
    ON trade_events (user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS trade_events_position_idx
    ON trade_events (user_id, position_id)
    WHERE position_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS trade_events_symbol_idx
    ON trade_events (user_id, symbol, occurred_at DESC)
    WHERE symbol IS NOT NULL;

-- Append-only. Enforced rather than documented.
CREATE OR REPLACE FUNCTION trade_events_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'trade_events is append-only: % refused on event %',
        TG_OP, COALESCE(OLD.event_id, '(unknown)')
        USING HINT = 'Record a correcting event instead of editing history.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trade_events_no_update ON trade_events;
CREATE TRIGGER trade_events_no_update
    BEFORE UPDATE OR DELETE ON trade_events
    FOR EACH ROW EXECUTE FUNCTION trade_events_immutable();

-- Row-level security, so an account can only ever read its own events even if
-- a future service connects with a shared role and forgets the WHERE clause.
ALTER TABLE trade_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS trade_events_own_rows ON trade_events;
CREATE POLICY trade_events_own_rows ON trade_events
    FOR SELECT
    USING (user_id = current_setting('app.user_id', true));
