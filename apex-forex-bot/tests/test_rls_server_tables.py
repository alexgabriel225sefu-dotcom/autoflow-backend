"""The server-table RLS script denies the browser roles and keeps service_role.

This does not connect to a database. It checks the script that an operator
runs by hand, and a synthetic grant matrix of what that script is for.
No production project is contacted and no row is read.

Run: python3 tests/test_rls_server_tables.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)

SQL = open(os.path.join(REPO, "sql", "003_rls_server_tables.sql"),
           encoding="utf-8").read()
DOC = open(os.path.join(REPO, "docs", "RLS_LICENSES_BOT_CONFIGS.md"),
           encoding="utf-8").read()

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name if not detail else f"{name} — {detail}")
        print(f"  FAIL {name} {detail}")


TABLES = ("licenses", "bot_configs")

print("\n[1] the script locks the browser roles and keeps the server role")
check("row security is enabled", "ENABLE ROW LEVEL SECURITY" in SQL)
check("anon is revoked", "REVOKE ALL ON TABLE public.%I FROM anon" in SQL)
check("authenticated is revoked",
      "REVOKE ALL ON TABLE public.%I FROM authenticated" in SQL)
check("service_role may use the rows",
      "TO service_role USING (true) WITH CHECK (true)" in SQL)
check("it does not grant anything to anon", "GRANT " not in SQL.upper()
      or "TO anon" not in SQL.lower())
for table in TABLES:
    check(f"{table} is in the list", f"'{table}'" in SQL)


def allowed(role, *, rls_on, revoked):
    """What a request may do after the script, with no user rows involved.

    service_role bypasses RLS. anon and authenticated lose table privileges,
    so RLS being on is not the only lock.
    """
    if role == "service_role":
        return True
    if role in ("anon", "authenticated") and revoked:
        return False
    if role in ("anon", "authenticated") and not rls_on:
        return True
    return False


print("\n[2] synthetic roles, no database")
check("anon is denied once the script has been applied",
      allowed("anon", rls_on=True, revoked=True) is False)
check("authenticated is denied",
      allowed("authenticated", rls_on=True, revoked=True) is False)
check("service_role still can",
      allowed("service_role", rls_on=True, revoked=True) is True)
check("anon could before the script",
      allowed("anon", rls_on=False, revoked=False) is True)

print("\n[3] the operator note names the apply and the rollback")
check("it points at the script", "sql/003_rls_server_tables.sql" in DOC)
check("rollback is marked emergency", "EMERGENCY" in DOC)
check("rollback does not drop service_role",
      "service_role" in DOC and "DROP ROLE" not in DOC.upper())
check("verification does not select table rows",
      "Do not SELECT" in DOC or "do not select" in DOC.lower())

if _fails:
    print(f"\nFAILED ({len(_fails)}):")
    for item in _fails:
        print(f"  - {item}")
    sys.exit(1)
print("\nALL OK")
