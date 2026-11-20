"""scripts/live_gate_drill.py keeps passing, and refuses to run near production.

The drill is only worth anything if it still works the day somebody needs it, so
the suite runs it. It also proves its safety rail: with any production setting
present it exits 2 before touching anything.

Run: python3 tests/test_live_gate_drill.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "live_gate_drill.py")
_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def run(extra_env=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("REDIS_URL", "A4T_LIVE_EXECUTION", "APEX_ALLOW_LIVE_ACCOUNTS",
                        "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN",
                        "SUPABASE_SERVICE_ROLE_KEY", "STRIPE_SECRET_KEY",
                        "A4T_EMERGENCY_HALT", "APP_ENV")}
    env.update(extra_env or {})
    return subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True,
                          env=env, timeout=120)


print("\n[1] the drill passes against the current gate code")
r = run()
check("exit code 0", r.returncode == 0, (r.stdout + r.stderr)[-600:])
check("it reports that every gate behaved as written",
      "Every gate behaved as written" in r.stdout, r.stdout[-300:])
check("no step failed", "❌" not in r.stdout, r.stdout[-300:])

print("\n[2] it refuses to run with production settings present")
for name, value in (("REDIS_URL", "redis://x"),
                    ("A4T_LIVE_EXECUTION", "enabled-i-accept-real-money-risk"),
                    ("STRIPE_SECRET_KEY", "sk_test_x"),
                    ("APP_ENV", "production")):
    r = run({name: value})
    check(f"{name} set: exits 2 and runs nothing",
          r.returncode == 2 and "LIVE GATE DRILL" not in r.stdout,
          f"{r.returncode} {r.stdout[-200:]}")

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("ALL LIVE GATE DRILL CHECKS PASSED")
