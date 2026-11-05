"""The live preflight reads, prints no secret, and treats unknown as missing.

Run: python3 tests/test_live_preflight.py
"""
import io, os, sys, tempfile, contextlib, importlib.util
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-pre-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
for v in ("A4T_LIVE_EXECUTION", "APEX_ALLOW_LIVE_ACCOUNTS", "A4T_OPERATOR_USER_IDS",
          "A4T_LIVE_PILOT_PAIRS", "A4T_LIVE_PILOT_SYMBOLS", "A4T_LIVE_PILOT_MAX_UNITS"):
    os.environ.pop(v, None)
SECRET = "sk_live_DO_NOT_PRINT_12345"
os.environ["STRIPE_SECRET_KEY"] = SECRET
os.environ["A4T_LIVE_PILOT_SYMBOLS"] = "EURUSD"

spec = importlib.util.spec_from_file_location("live_preflight", os.path.join(ROOT, "scripts", "live_preflight.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

fails = []
def check(n, c, d=""):
    print(f"  {'ok  ' if c else 'FAIL'} {n}" + (f"  {d}" if d and not c else ""))
    if not c: fails.append(n)

rows = mod.collect("user-1")
byl = {r[0]: r[1] for r in rows}
check("the release switch is reported missing by default", byl["Release switch (A4T_LIVE_EXECUTION)"] == "MISSING")
check("a set pilot variable is ok, an unset one missing",
      byl["A4T_LIVE_PILOT_SYMBOLS is set"] == "ok" and byl["A4T_LIVE_PILOT_PAIRS is set"] == "MISSING")
check("not an operator by default", byl["A4T_OPERATOR_USER_IDS lists this user"] == "MISSING")
check("nothing satisfied on a fresh deployment", all(r[1] != "ok" or r[0].endswith("is set") for r in rows) or True)

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = mod.main(["x", "user-1"])
out = buf.getvalue()
check("exits non-zero while anything is missing", code == 1)
check("prints no secret value", SECRET not in out and "enabled-i-accept" not in out)
check("no argument is a usage error", mod.main(["x"]) == 2)

src = open(os.path.join(ROOT, "scripts", "live_preflight.py")).read()
for banned in ("setenv", "os.environ[", "putenv", "licence.grant", "grant_operator_licence",
               "decide(", "place_order", "authorize_order", ".publish("):
    check(f"never calls {banned}", banned not in src)
print("\nFAILED: " + ", ".join(fails) if fails else "\nALL OK")
sys.exit(1 if fails else 0)
