"""The deployment blueprint must describe the service that actually runs.

An audit flagged the build filter as possibly wrong for the repository
layout. It is not: `apex-forex-bot/**` is correct, because buildFilter paths
are relative to the REPOSITORY ROOT and this is a monorepo — the bot is one
folder inside it, alongside apex-crypto-bot/, ruflo-mcp/ and the website.

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
for sibling in ("apex-crypto-bot", "ruflo-mcp", "web", "public"):
    if not os.path.isdir(os.path.join(REPO_ROOT, sibling)):
        continue
    hit = any(f"{sibling}/x.py".startswith(p.rstrip("*")) for p in paths)
    check(f"{sibling} does not trigger a restart", not hit,
          "an unrelated commit restarting the loop can orphan an open position")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the blueprint matches the repository.")
