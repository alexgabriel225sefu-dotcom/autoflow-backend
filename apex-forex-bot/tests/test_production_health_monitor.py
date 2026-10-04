"""Production monitor contract tests.

Run: python tests/test_production_health_monitor.py
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "check_production_health.py")
spec = importlib.util.spec_from_file_location("check_production_health", SCRIPT)
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)

fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        fails.append(name)
        print(f"  FAIL {name} {detail}")


print("\n[1] readiness alerts name the failing checks")
M.fetch = lambda url: (503, '{"ok": false, "status": "fail", "release": {"commit": "abc123"}, "checks": [{"name": "supabase", "status": "fail", "message": "missing"}, {"name": "billing", "status": "skipped", "message": "off"}]}', None)
r = M.check_readyz()
check("readyz failure is not flattened", r.ok is False)
check("the alert names supabase", "supabase" in r.message, r.message)
check("the failing check detail is carried", r.detail["failedChecks"][0]["name"] == "supabase", r.detail)

print("\n[2] release commit drift fails the API checks")
M.EXPECTED_API_COMMIT = "wanted"
M.fetch = lambda url: (200, '{"ok": true, "status": "ok", "release": {"commit": "other123"}, "checks": []}', None)
r = M.check_readyz()
check("readyz detects the wrong deployed commit", r.ok is False and "expected wanted" in r.message, r.message)

print("\n[3] liveness requires release.commit")
M.EXPECTED_API_COMMIT = ""
M.fetch = lambda url: (200, '{"ok": true, "status": "ok"}', None)
r = M.check_healthz()
check("healthz without release.commit fails", r.ok is False and "release.commit" in r.message, r.message)

print("\n[4] the web check is read-only and accepts the Apex home page")
M.fetch = lambda url: (200, '<html><title>Apex4Traders</title></html>', None)
r = M.check_web()
check("web home passes on HTTP 200 with Apex copy", r.ok is True, r.message)

print("\n[5] the script has no service write verbs")
src = open(SCRIPT, encoding="utf-8").read().lower()
check("no POST/PUT/PATCH/DELETE request method is configured",
      all(verb not in src for verb in ('method="post"', 'method="put"', 'method="patch"', 'method="delete"')),
      "write verb found")

if fails:
    print("FAILED:")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("All production monitor checks passed.")
