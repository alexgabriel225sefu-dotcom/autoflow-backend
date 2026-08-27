"""The deployment blueprint must describe the service that actually runs.

An audit flagged the build filter as possibly wrong for the repository
layout. It is not: `apex-forex-bot/**` is correct, because buildFilter paths
are relative to the REPOSITORY ROOT and this is a monorepo — the bot is one
folder inside it, alongside ruflo-mcp/ and the website.

What the audit did surface, by making us look, is a different and real defect:
the blueprint had no `rootDir`. Its buildCommand (`pip install -r
requirements.txt`) and startCommand (`python -u main.py`) both resolve from
the repository root, where neither file exists. The live service works only
because it was created by hand with rootDir set — so the RUNNING deployment
was fine and the blueprint could not reproduce it. That surfaces the day
somebody rebuilds from it, which is the day it matters most.

These checks are static: they read the blueprint and the repository and
assert the two agree. Nothing here talks to Render.

Run: python tests/test_deploy_config.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICE_DIR = os.path.dirname(HERE)                 # apex-forex-bot/
REPO_ROOT = os.path.dirname(SERVICE_DIR)            # monorepo root
BLUEPRINT = os.path.join(SERVICE_DIR, "render.yaml")

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


def field(text, key):
    """The scalar value of `key:` in the first service block.

    Deliberately not PyYAML: it is not in requirements.txt, and a deployment
    check that only runs where an undeclared package happens to be installed
    is a check that silently stops running.
    """
    m = re.search(rf"^\s*{re.escape(key)}:\s*(\S.*?)\s*$", text, re.M)
    return m.group(1) if m else None


def filter_paths(text):
    block = re.search(r"^\s*buildFilter:\s*$\n\s*paths:\s*$\n((?:\s*-\s*\S+\s*$\n?)+)",
                      text, re.M)
    if not block:
        return []
    return re.findall(r"^\s*-\s*(\S+)\s*$", block.group(1), re.M)


SRC = open(BLUEPRINT, encoding="utf-8").read()

print("\n🚀 DEPLOY CONFIG — the blueprint must describe what actually runs\n")

print("1. The service builds and starts from the right directory")
root_dir = field(SRC, "rootDir")
check("rootDir is declared", bool(root_dir),
      "without it the blueprint cannot recreate the running service")
check("rootDir points at this service", root_dir == os.path.basename(SERVICE_DIR),
      f"got {root_dir!r}, expected {os.path.basename(SERVICE_DIR)!r}")

print("\n2. The commands resolve inside that directory")
build_cmd = field(SRC, "buildCommand") or ""
start_cmd = field(SRC, "startCommand") or ""
req = re.search(r"-r\s+(\S+)", build_cmd)
check("buildCommand names a requirements file", bool(req), build_cmd)
if req:
    check(f"{req.group(1)} exists under rootDir",
          os.path.isfile(os.path.join(SERVICE_DIR, req.group(1))),
          "the build would fail on a fresh deploy")
entry = re.search(r"(\S+\.py)", start_cmd)
check("startCommand names an entrypoint", bool(entry), start_cmd)
if entry:
    check(f"{entry.group(1)} exists under rootDir",
          os.path.isfile(os.path.join(SERVICE_DIR, entry.group(1))),
          "the service would build and then fail to start")
    check("and NOT at the repository root",
          not os.path.isfile(os.path.join(REPO_ROOT, entry.group(1))),
          "if it existed at the root, rootDir would be silently optional")

print("\n3. Every relevant change triggers a deploy")
paths = filter_paths(SRC)
check("a build filter is declared", bool(paths),
      "no filter means every commit in the monorepo restarts the trading loop")
prefix = os.path.basename(SERVICE_DIR) + "/"
check("the filter is repository-root relative",
      all(p.startswith(prefix) for p in paths), paths)
check("it is not shortened to match rootDir", "**" not in paths and "./**" not in paths,
      "a bare ** matches the whole monorepo, not this service")
# The directories a change to which MUST redeploy the bot.
for needed in ("apex", "tests", "main.py", "requirements.txt", "render.yaml"):
    on_disk = os.path.join(SERVICE_DIR, needed)
    if not os.path.exists(on_disk):
        continue
    covered = any(p == f"{prefix}**" or p.startswith(f"{prefix}{needed}")
                  for p in paths)
    check(f"a change to {needed}/ redeploys", covered,
          f"{needed} is not matched by {paths}")

print("\n4. Sibling projects must NOT redeploy this trading loop")
for sibling in ("ruflo-mcp", "web", "public", "scripts"):
    if not os.path.isdir(os.path.join(REPO_ROOT, sibling)):
        continue
    hit = any(f"{sibling}/x.py".startswith(p.rstrip("*")) for p in paths)
    check(f"{sibling} does not trigger a restart", not hit,
          "an unrelated commit restarting the loop can orphan an open position")


# ─────────────────────────────────────────────────────────
# ONE production trading deployment path.
#
# The repository carried a second one: .github/workflows/deploy-forex-bot.yml
# SSH'd into an Oracle Cloud VM, wrote an .env containing
#
#     BYPASS_LICENSE=true
#     BROKER=oanda
#     OANDA_ENV=practice
#
# installed a systemd unit and started the bot — with real production secrets
# (FOREX_TELEGRAM_BOT_TOKEN, GROQ_API_KEY) handed to that VM.
#
# Two problems, and the second is why deleting it beat fixing it: it disabled
# the entitlement gate, and it could not work anyway, because the engine's
# SUPPORTED_BROKERS is ["ctrader"] so BROKER=oanda is refused at startup. A
# dead path that still carried live credentials.
#
# Production is Render, deploying from the branch on every commit. These
# checks fail if a second path reappears.
import re  # noqa: E402

WORKFLOWS = os.path.join(REPO_ROOT, ".github", "workflows")

# Each of these is a control being switched off, not a preference.
FORBIDDEN_IN_DEPLOY = (
    r"BYPASS_LICENSE\s*=\s*true",     # removes the entitlement gate entirely
    r"BROKER\s*=\s*oanda",            # brokers the engine no longer has, so
    r"BROKER\s*=\s*mt\b",             # naming one is either dead config or a
    r"BROKER\s*=\s*td\b",             # path around the cTrader-only layer
    r"BROKER\s*=\s*metaapi",
    r"OANDA_ENV",
    r"REQUIRE_LICENSE\s*=\s*false",
)

print("\n🚀  ONE PRODUCTION PATH — no second way to start a trading process")

check("the legacy VM workflow is gone",
      not os.path.exists(os.path.join(WORKFLOWS, "deploy-forex-bot.yml")),
      "the second production trading path is back")

if os.path.isdir(WORKFLOWS):
    wf = sorted(f for f in os.listdir(WORKFLOWS) if f.endswith((".yml", ".yaml")))
    check(f"{len(wf)} workflow(s) scanned", bool(wf))
    for fn in wf:
        text = open(os.path.join(WORKFLOWS, fn), encoding="utf-8").read()
        hits = [p for p in FORBIDDEN_IN_DEPLOY if re.search(p, text, re.I)]
        check(f"{fn} switches nothing off", not hits, f"contains {hits}")

# Deployment-shaped files only. A scan over the whole tree would match this
# file's own list of what it forbids — the prose-assertion trap.
deploy_files = []
for dirpath, dirs, files in os.walk(REPO_ROOT):
    dirs[:] = [d for d in dirs
               if d not in ("node_modules", ".git", "tests", ".agents", ".claude")]
    for fn in files:
        if fn == "Dockerfile" or fn.endswith((".yml", ".yaml", ".sh")):
            deploy_files.append(os.path.join(dirpath, fn))

offenders = []
for path in deploy_files:
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    for pat in (r"BYPASS_LICENSE\s*=\s*true", r"BROKER\s*=\s*oanda", r"OANDA_ENV\s*="):
        if re.search(pat, text, re.I):
            offenders.append(os.path.relpath(path, REPO_ROOT))
check(f"{len(deploy_files)} deployment file(s) carry no disabled control",
      not offenders, f"offenders: {sorted(set(offenders))}")

print("\n🔒  THE BROKER ALLOWLIST IS ENFORCED, NOT JUST DECLARED")
# SUPPORTED_BROKERS said ["ctrader"] and one Telegram command checked it, but
# nothing stopped the environment from naming another — the engine just took a
# different branch. An unsupported broker is not a degraded mode; it is a
# configuration that cannot place a correct order.
import importlib  # noqa: E402
# This file's original checks are purely static, so it never needed the package
# on the path. The broker allowlist is a runtime property, so it does.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-oauth-signing-secret")
import apex.config as _cfg  # noqa: E402

_saved = os.environ.get("BROKER")
try:
    for bad in ("mt", "td", "oanda", "metaapi", "binance", "nonsense"):
        os.environ["BROKER"] = bad
        try:
            importlib.reload(_cfg)
            check(f"BROKER={bad} is refused", False, f"accepted as {_cfg.BROKER!r}")
        except _cfg.UnsupportedBroker:
            check(f"BROKER={bad} is refused", True)
    for good in ("ctrader", "CTRADER", "  ctrader  "):
        os.environ["BROKER"] = good
        importlib.reload(_cfg)
        check(f"BROKER={good!r} is accepted", _cfg.BROKER == "ctrader", _cfg.BROKER)
    os.environ.pop("BROKER", None)
    importlib.reload(_cfg)
    check("an unset BROKER defaults to ctrader", _cfg.BROKER == "ctrader", _cfg.BROKER)
finally:
    if _saved is None:
        os.environ.pop("BROKER", None)
    else:
        os.environ["BROKER"] = _saved
    importlib.reload(_cfg)


print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the blueprint matches the repository.")
