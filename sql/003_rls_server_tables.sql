-- Row-level security for the server-only tables. Deny by default.
--
-- WHY: `licenses`, `bot_configs` (001_licences_and_bot_configs.sql) and the
-- affiliate tables (affiliates-schema.sql) were created without row-level
-- security. In Supabase every table in `public` is reachable through the REST
-- API with the project's ANON key, which ships in every browser bundle. With
-- RLS off, that key can read every licence key and e-mail, every encrypted
-- bot config, every affiliate's password hash and payout details.
--
-- WHAT THIS DOES
--
--   * Enables RLS on each table. With RLS on and no policy granting a role,
--     that role sees no rows and can write none: deny by default.
--   * Grants the `service_role` an explicit policy. server.js talks to these
--     tables with SUPABASE_SERVICE_KEY (the service role), which bypasses RLS
--     anyway; the policy states that intent instead of relying on it.
--   * Revokes table privileges from `anon` and `authenticated`, so the deny
--     does not rest on RLS alone.
--
-- NO PER-USER POLICY, ON PURPOSE. None of these tables has a column holding a
-- Supabase auth user id (`auth.uid()`): licences are keyed by licence key and
-- e-mail, affiliates log in with their own password hash checked by the
-- server, and the rest hang off an affiliate code. A "select your own rows"
-- policy needs an owner column to compare against, and matching on e-mail
-- would let anybody who registers an address read the rows filed under it.
-- `trade_events` (002) is the one user-owned table and already has its own
-- per-user policy.
--
-- Idempotent: every statement can be re-run, and tables that do not exist in
-- a given project are skipped. NOT applied anywhere by this commit — run it
-- deliberately, per project, after checking that nothing reads these tables
-- with the anon key:
--
--     psql "$DATABASE_URL" -f sql/003_rls_server_tables.sql

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'licenses', 'bot_configs',
        'affiliates', 'referral_sales', 'affiliate_clicks', 'payout_requests'
    ]
    LOOP
        IF to_regclass('public.' || t) IS NULL THEN
            RAISE NOTICE 'skipping %, which does not exist here', t;
            CONTINUE;
        END IF;

        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I',
                       t || '_service_role_all', t);
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format(
                'CREATE POLICY %I ON public.%I AS PERMISSIVE FOR ALL '
                'TO service_role USING (true) WITH CHECK (true)',
                t || '_service_role_all', t);
        END IF;

        -- Belt and braces: no table privilege for the browser-facing roles.
        -- Guarded because a self-hosted Postgres may not have them.
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon', t);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE format('REVOKE ALL ON TABLE public.%I FROM authenticated', t);
        END IF;
    END LOOP;
END
$$;

-- The BIGSERIAL sequences behind referral_sales, affiliate_clicks and
-- payout_requests: an anon caller must not be able to advance them either.
DO $$
DECLARE
    s text;
BEGIN
    FOREACH s IN ARRAY ARRAY[
        'referral_sales_id_seq', 'affiliate_clicks_id_seq',
        'payout_requests_id_seq'
    ]
    LOOP
        IF to_regclass('public.' || s) IS NULL THEN
            CONTINUE;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE format('REVOKE ALL ON SEQUENCE public.%I FROM anon', s);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE format('REVOKE ALL ON SEQUENCE public.%I FROM authenticated', s);
        END IF;
    END LOOP;
END
$$;
