"""The platform's Render blueprint describes something that exists.

WHY THIS IS TESTED

`apex-forex-bot/render.yaml` carries a comment worth reading: the live service
was created by hand with `rootDir` set, the blueprint did not have it, and so
the blueprint could not reproduce the running service. "That only shows up the
day someone rebuilds from it, which is the day it matters most."

The same failure is available to `docs/deploy/render-apex4traders.yaml`, which
describes two services that do not exist yet — so nothing at all would notice a
wrong path, a command that cannot resolve, or a secret value pasted in. This
checks it against the repository instead of trusting it.

It also checks the two things that would be actively dangerous: a health check
pointed at `/readyz`, and a secret with a value.

Run: python3 tests/test_platform_blueprint.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICE_DIR = os.path.dirname(HERE)              # apex-forex-bot/
REPO_ROOT = os.path.dirname(SERVICE_DIR)
BLUEPRINT = os.path.join(REPO_ROOT, "docs", "deploy", "render-apex4traders.yaml")

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


check("the blueprint exists", os.path.exists(BLUEPRINT), BLUEPRINT)
if not os.path.exists(BLUEPRINT):
    sys.exit(1)

with open(BLUEPRINT, encoding="utf-8") as fh:
    RAW = fh.read()

# Parsed without PyYAML deliberately: it is not in requirements.txt, and a test
# that needs a dependency the deployment does not have is a test that will be
# skipped. The structure here is flat enough to read directly.
def services(text):
    """[{key: value}] for each `- type:` block, values as strings."""
    out, cur = [], None
    for line in text.splitlines():
        if re.match(r"^\s*-\s+type:\s*\S+", line):
            cur = {"type": line.split("type:")[1].strip()}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"^\s{4}([A-Za-z][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            cur[m.group(1)] = m.group(2).strip()
    return out


SVCS = {s.get("name"): s for s in services(RAW) if s.get("name")}

# ── 1. both services, named as asked ────────────────────────────────────────
print("\n[1] the two platform services are declared")
for name in ("apex4traders-api", "apex4traders-web"):
    check(f"{name} is declared", name in SVCS, str(sorted(SVCS)))

# ── 2. the paths and commands resolve in this repository ────────────────────
# The failure the bot's blueprint already suffered: a command that resolves
# from the repository root, where the file does not exist.
print("\n[2] every rootDir exists and every command resolves inside it")
EXPECT = {
    "apex4traders-api": ("apex-forex-bot", ["requirements.txt", "main.py"]),
    "apex4traders-web": ("web", ["package.json", "package-lock.json"]),
}
for name, (root, needed) in EXPECT.items():
    svc = SVCS.get(name, {})
    check(f"{name} sets rootDir to {root}", svc.get("rootDir") == root,
          str(svc.get("rootDir")))
    full = os.path.join(REPO_ROOT, root)
    check(f"{root}/ exists", os.path.isdir(full))
    for f in needed:
        check(f"{root}/{f} exists, so the command can resolve",
              os.path.exists(os.path.join(full, f)))

api, web = SVCS.get("apex4traders-api", {}), SVCS.get("apex4traders-web", {})
check("the API installs from requirements.txt",
      "requirements.txt" in api.get("buildCommand", ""), api.get("buildCommand"))
check("the API starts main.py unbuffered",
      "main.py" in api.get("startCommand", "") and "-u" in api.get("startCommand", ""),
      api.get("startCommand"))
# `npm ci` and not `npm install`: the lockfile is the reviewed dependency set,
# and the framework pin exists because a range would let a deploy install a
# version nobody read.
check("the web service uses `npm ci`, not `npm install`",
      "npm ci" in web.get("buildCommand", "")
      and "npm install" not in web.get("buildCommand", ""),
      web.get("buildCommand"))
check("the web service builds before starting",
      "npm run build" in web.get("buildCommand", ""))
check("and starts with npm run start",
      web.get("startCommand") == "npm run start", web.get("startCommand"))
for name in EXPECT:
    scripts = os.path.join(REPO_ROOT, EXPECT[name][0], "package.json")
    if os.path.exists(scripts):
        body = open(scripts, encoding="utf-8").read()
        check("the web package.json defines build and start",
              '"build"' in body and '"start"' in body)

# ── 3. the health check is /healthz and NOT /readyz ─────────────────────────
# Readiness touches dependencies. A restart probe pointed at it turns one
# backend degradation into every container restarting at once.
print("\n[3] the restart probe cannot take the fleet down")
check("the API health check is /healthz", api.get("healthCheckPath") == "/healthz",
      str(api.get("healthCheckPath")))
check("it is NOT /readyz", api.get("healthCheckPath") != "/readyz",
      "a readiness probe as a restart probe converts degradation into outage")
check("the web health check is /", web.get("healthCheckPath") == "/",
      str(web.get("healthCheckPath")))
# And the endpoint the blueprint names has to exist in the code.
health_src = open(os.path.join(SERVICE_DIR, "apex", "bot.py"),
                  encoding="utf-8").read()
check("/healthz is actually served by the transport", '"/healthz"' in health_src)

# ── 4. no secret has a value, anywhere ──────────────────────────────────────
print("\n[4] every secret is `sync: false` and no value is present")
MUST_BE_SYNC_FALSE = (
    "TOKEN_ENCRYPTION_KEY", "SUPABASE_ANON_KEY", "SUPABASE_URL",
    "CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_REDIRECT_URI",
    "REDIS_URL", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN",
    "NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "NEXT_PUBLIC_API_BASE_URL",
)
for key in MUST_BE_SYNC_FALSE:
    m = re.search(rf"- key: {re.escape(key)}\s*\n\s*(\S+):", RAW)
    check(f"{key} is sync: false", bool(m) and m.group(1) == "sync",
          f"declared as {m.group(1) if m else 'absent'}")
# Nothing that looks like a real credential.
for pat, what in ((r"gAAAAA[A-Za-z0-9_-]{20,}", "a Fernet value"),
                  (r"whsec_[A-Za-z0-9]{10,}", "a webhook secret"),
                  (r"sk_(?:live|test)_[A-Za-z0-9]{10,}", "a Stripe key"),
                  (r"eyJ[A-Za-z0-9_-]{20,}\.", "a JWT"),
                  (r"https://[a-z0-9]{16,}\.supabase\.co", "a real Supabase URL")):
    check(f"no {what} in the blueprint", not re.search(pat, RAW))

# ── 5. the dangerous variables are absent, not set to false ────────────────
# Absent is stronger. A variable set to "false" is one dashboard edit from
# being "true"; a variable nobody declared has to be added deliberately.
print("\n[5] the live-trading and payment flags are absent, not defaulted")
for key in ("LIVE_TRADING_ENABLED", "APEX_ALLOW_LIVE_ACCOUNTS",
            "A4T_CHECKOUT_ENABLED", "ALLOW_LOCAL_BACKEND_DEV",
            "ALLOW_PLAINTEXT_DEV_STORAGE"):
    check(f"{key} is not declared as an envVar",
          not re.search(rf"- key: {re.escape(key)}\b", RAW),
          "absent is stronger than false")
    check(f"…and {key} is named in a comment, so the omission reads as chosen",
          key in RAW, "an unexplained absence looks like an oversight")

# ── 6. it does not touch the legacy services ────────────────────────────────
print("\n[6] the legacy services are not redefined or redeployed")
for legacy in ("apex-forex-bot", "autoflow-backend", "aicashsystem"):
    check(f"the blueprint does not declare a service named {legacy}",
          f"name: {legacy}" not in RAW)
check("it is NOT the root render.yaml, so Render does not auto-apply it",
      os.path.basename(BLUEPRINT) != "render.yaml")
check("and the root render.yaml still describes only the sales site",
      "autoflow-backend" in open(os.path.join(REPO_ROOT, "render.yaml"),
                                 encoding="utf-8").read())
# The platform branch, not the bot's deploy branch — a commit here must never
# restart the live trading loop.
for name, svc in (("api", api), ("web", web)):
    check(f"the {name} service deploys the platform branch",
          svc.get("branch") == "claude/apex4traders-platform-v1",
          str(svc.get("branch")))
    check(f"the {name} service does not auto-deploy",
          svc.get("autoDeploy") == "false", str(svc.get("autoDeploy")))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("The platform blueprint matches the repository and carries no secret.")
