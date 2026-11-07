# `licenses` and `bot_configs`: row security

Production is already locked. This file records what was applied and what
must not be repeated. It does not connect to a database, and this
repository does not run it.

## Applied

**When:** 22:28:52 Europe/Amsterdam, 7 November 2026.

**Where:** Supabase project `ibvuibfzljhrgtsbvzsg`, tables
`public.licenses` and `public.bot_configs` only.

**Statement that was run:**

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';
ALTER TABLE public.licenses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bot_configs ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public.licenses, public.bot_configs
  FROM anon, authenticated, PUBLIC;
COMMIT;
```

That is the whole change. Do not run `sql/003_rls_server_tables.sql` against
this project as a follow-up. That file also alters affiliate tables and
their sequences, and it creates `service_role` policies. None of that was
part of this apply, and it is not required for the state below.

## What was verified

Catalog and privilege checks only. Do not SELECT customer rows from
`licenses` or `bot_configs`.

- Row security is on for both tables.
- `anon` and `authenticated` have no effective SELECT, INSERT, UPDATE, or
  DELETE on either table. `PUBLIC` was included in the revoke.
- `pg_policies` has no policy on either table. That is intentional. The
  server roles do not need a policy. Supabase advisors: the two errors are
  resolved; two info findings of "no policy" are expected.
- Explicit table grants for `postgres` and `service_role` are still
  `arwdDxtm` (INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES,
  TRIGGER, MAINTAIN). Both roles also have `BYPASSRLS`.
- A read-only `SELECT 1 ... LIMIT 0` as `service_role` succeeded on both
  tables. No row was returned and no row was read.
- Both platform health endpoints answered 200. The deployed API commit was
  still `d979ab73c3763b48752b960c95f94bc7ee458443`. This documentation
  change does not redeploy it.
- A full HTTP check that one tenant cannot read or write another tenant's
  business data has not been run.

## `BYPASSRLS` is not a table privilege

`BYPASSRLS` is a role attribute. It means row-security policies are not
applied to that role. It does not grant SELECT, INSERT, UPDATE, DELETE, or
any other table privilege.

`service_role` can read these tables because both of these are true: it
bypasses row security, and it still holds the explicit `arwdDxtm` grants.
Revoking those grants would lock the server out even though `BYPASSRLS`
remained. Keep the grants. Do not put the service key in the browser.

`anon` and `authenticated` do not bypass row security. With row security
on, no policy, and no table privileges, they cannot use the tables. The
missing policy is not a hole for those roles.

## `sql/003_rls_server_tables.sql`

The script in the repository is a broader template: it enables row
security, revokes `anon` and `authenticated`, and adds a `service_role`
policy, and it does that for affiliate tables and their sequences when
those objects exist. It was not the statement applied above. Do not apply
the whole file automatically to `ibvuibfzljhrgtsbvzsg`.

A policy for `service_role` is optional here. The role already bypasses
row security. Adding one later is a separate decision, not a repair of
this apply.

## Rollback — EMERGENCY, owner approval

Rollback is not a deploy step. Re-granting `anon`, `authenticated`, or
`PUBLIC`, or turning row security off, reopens the exposure that was
closed: the anon key shipped in the browser could read and write these
tables again. Do it only with an explicit owner decision that the legacy
server cannot run any other way.

This does not drop `service_role`, does not remove `BYPASSRLS`, and does
not delete rows. It also must not revoke the `postgres` or `service_role`
table grants.

```sql
-- EMERGENCY only, after the owner approves. Reopens the known exposure.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.licenses TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bot_configs TO anon, authenticated;
ALTER TABLE public.licenses DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.bot_configs DISABLE ROW LEVEL SECURITY;
```

## What this repository will not do

It will not run either statement against production, and it will not fill
in legal, tax, or company text.
