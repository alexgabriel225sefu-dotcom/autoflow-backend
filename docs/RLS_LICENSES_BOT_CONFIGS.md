# `licenses` and `bot_configs`: row security

`sql/003_rls_server_tables.sql` is the production fix. This file does not
apply it. Nothing here connects to a database. The owner runs it, on the
project the site already uses for sign-in, after reading it.

The browser ships that project's anon key. With row security off and
`anon` allowed to select, insert, update and delete, anyone who has the
key can read and write `public.licenses` and `public.bot_configs` through
the REST API. The platform app does not query those tables. The key being
public is enough.

`service_role` bypasses row security. `server.js` uses
`SUPABASE_SERVICE_KEY`, which is that role. The script keeps a
`service_role` policy and does not revoke that role, so the legacy server
can keep using the tables. Do not put the service key in the browser.

## Apply

From a machine that already has the database URL. Do not print the URL
and do not select rows.

```bash
psql "$DATABASE_URL" -f sql/003_rls_server_tables.sql
```

The script is idempotent. It skips a table that is not there. It enables
row security, revokes `anon` and `authenticated`, and adds one
`service_role` policy per table. Affiliate tables in the same file are
included when they exist. Sequences for those affiliate tables are revoked
from `anon` and `authenticated` too.

## Check, without reading customer data

```sql
SELECT c.relname, c.relrowsecurity
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('licenses', 'bot_configs');

SELECT table_name, grantee, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public'
  AND table_name IN ('licenses', 'bot_configs')
  AND grantee IN ('anon', 'authenticated', 'service_role')
ORDER BY table_name, grantee, privilege_type;

SELECT tablename, policyname, roles
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('licenses', 'bot_configs');
```

Do not SELECT from `licenses` or `bot_configs`. Expected after a successful
apply: `relrowsecurity` true, no privileges for `anon` or `authenticated`,
and a `service_role` policy still present. `service_role` may not appear in
`role_table_grants` as a separate grant; it bypasses row security either way.

## Rollback — EMERGENCY

Only if the legacy server can no longer read the tables and the cause is
this script. This puts the tables back to the unsafe state. It does not
drop `service_role` and it does not delete rows.

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.licenses TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bot_configs TO anon, authenticated;
ALTER TABLE public.licenses DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.bot_configs DISABLE ROW LEVEL SECURITY;
```

Leave the `service_role` policies in place. They do no harm while row
security is off, and they are what you want if you enable it again.

## What this repository will not do

It will not run the script against production, and it will not fill in
legal, tax or company text. Those stay owner decisions.
