"""scripts/check_runtime_env.py: names and OK/MISSING/UNSAFE, never values.

Run: python3 tests/test_check_runtime_env.py
"""
import importlib.util
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
spec = importlib.util.spec_from_file_location(
    "check_runtime_env", os.path.join(ROOT, "scripts", "check_runtime_env.py"))
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name} {detail}")


GOOD = {
    "APP_ENV": "production", "PRODUCT": "forex",
    "TOKEN_ENCRYPTION_KEY": "k" * 44,
    "REDIS_URL": "redis://:hunter2hunter2@host:6379/0",
    "SUPABASE_URL": "https://abc.supabase.co",
    "SUPABASE_ANON_KEY": "anon-key-value-123456",
    "CTRADER_CLIENT_ID": "cid-value-123", "CTRADER_CLIENT_SECRET": "csecret-value-123",
    "CTRADER_REDIRECT_URI": "https://api.example.com/cb",
    "A4T_ALLOWED_ORIGIN": "https://app.example.com",
}


def run(env):
    return C.evaluate(env)


def status(rows, name):
    return {r[0]: r[1] for r in rows}.get(name)


print("\n[1] a complete production environment passes")
rows = run(GOOD)
check("no row is MISSING or UNSAFE",
      all(r[1] == "OK" or r[1] == "SKIPPED" for r in rows), str(rows))
check("exit code is 0", C.exit_code(rows) == 0)

print("\n[2] missing variables are named")
for name in ("TOKEN_ENCRYPTION_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY",
             "CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_REDIRECT_URI",
             "A4T_ALLOWED_ORIGIN", "APP_ENV", "PRODUCT"):
    env = dict(GOOD)
    env.pop(name)
    check(f"{name} missing is MISSING", status(run(env), name) == "MISSING")
    check(f"{name} missing exits non-zero", C.exit_code(run(env)) != 0)
env = dict(GOOD)
env.pop("REDIS_URL")
check("no shared backend is MISSING", status(run(env), "REDIS_URL|UPSTASH") == "MISSING")
env["UPSTASH_REDIS_REST_URL"] = "https://x.upstash.io"
check("Upstash URL without token is still MISSING",
      status(run(env), "REDIS_URL|UPSTASH") == "MISSING")
env["UPSTASH_REDIS_REST_TOKEN"] = "tok-123456789"
check("Upstash URL + token satisfies it", status(run(env), "REDIS_URL|UPSTASH") == "OK")
env = dict(GOOD, SUPABASE_URL="   ")
check("whitespace-only counts as missing", status(run(env), "SUPABASE_URL") == "MISSING")

print("\n[3] unsafe settings are flagged")
for name, value in (("ALLOW_LOCAL_BACKEND_DEV", "true"),
                    ("ALLOW_PLAINTEXT_DEV_STORAGE", "1"),
                    ("LIVE_TRADING_ENABLED", "true"),
                    ("A4T_LIVE_EXECUTION", "enabled-i-accept-real-money-risk"),
                    ("SUPABASE_SERVICE_KEY", "service-key-value-123"),
                    ("RATE_LIMIT_STORE", "memory"),
                    ("A4T_CHECKOUT_ENABLED", "true")):
    rows = run(dict(GOOD, **{name: value}))
    check(f"{name} is UNSAFE", status(rows, name) == "UNSAFE", str(rows))
    check(f"{name} exits non-zero", C.exit_code(rows) != 0)
check("APP_ENV=dev is UNSAFE",
      status(run(dict(GOOD, APP_ENV="dev")), "APP_ENV") == "UNSAFE")
check("a wildcard origin is UNSAFE",
      status(run(dict(GOOD, A4T_ALLOWED_ORIGIN="*")), "A4T_ALLOWED_ORIGIN") == "UNSAFE")
check("a plain-http origin is UNSAFE",
      status(run(dict(GOOD, A4T_ALLOWED_ORIGIN="http://app.example.com")),
             "A4T_ALLOWED_ORIGIN") == "UNSAFE")
check("localhost origin is UNSAFE",
      status(run(dict(GOOD, A4T_ALLOWED_ORIGIN="https://localhost:3000")),
             "A4T_ALLOWED_ORIGIN") == "UNSAFE")
check("a non-https redirect URI is UNSAFE",
      status(run(dict(GOOD, CTRADER_REDIRECT_URI="http://x/cb")),
             "CTRADER_REDIRECT_URI") == "UNSAFE")
check("unset flags are not reported as problems",
      status(run(GOOD), "ALLOW_LOCAL_BACKEND_DEV") in ("OK", None))

print("\n[4] output never contains a value")
secretish = dict(GOOD)
buf = io.StringIO()
with redirect_stdout(buf):
    C.report(C.evaluate(dict(secretish, ALLOW_LOCAL_BACKEND_DEV="true",
                             SUPABASE_SERVICE_KEY="service-key-value-123")))
out = buf.getvalue()
for name, value in secretish.items():
    if name in ("APP_ENV", "PRODUCT"):
        continue
    check(f"value of {name} is not printed", value not in out)
check("service key value is not printed", "service-key-value-123" not in out)
check("names are printed", "TOKEN_ENCRYPTION_KEY" in out and "SUPABASE_URL" in out)

print("\n[5] an env file is parsed without exporting it")
with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
    f.write("# comment\n\nexport APP_ENV=production\nPRODUCT='forex'\n"
            'SUPABASE_URL="https://abc.supabase.co"\nBAD LINE\nEMPTY=\n')
    path = f.name
parsed = C.parse_env_file(path)
os.unlink(path)
check("comments, blanks and bad lines are skipped",
      parsed == {"APP_ENV": "production", "PRODUCT": "forex",
                 "SUPABASE_URL": "https://abc.supabase.co", "EMPTY": ""}, str(parsed))

print("\n[6] the required list is derived from the readiness code, not invented")
sys.path.insert(0, ROOT)
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
from apex.platform import health as H                       # noqa: E402
src = open(os.path.join(ROOT, "apex", "platform", "health.py"), encoding="utf-8").read()
for name in C.REQUIRED_NAMES:
    if name in ("APP_ENV", "PRODUCT", "A4T_ALLOWED_ORIGIN"):
        continue                         # not read by a readiness check
    check(f"{name} is read by health.py or user_store", name in src
          or name in open(os.path.join(ROOT, "apex", "user_store.py"),
                          encoding="utf-8").read())
check("every dev-only flag health.py knows is covered",
      all(n in C.UNSAFE_IF_SET for n in H.DEV_ONLY_FLAGS))

print()
if _fails:
    print(f"FAILED {len(_fails)}: {_fails}")
    sys.exit(1)
print("ALL RUNTIME ENV CHECKS PASSED")
