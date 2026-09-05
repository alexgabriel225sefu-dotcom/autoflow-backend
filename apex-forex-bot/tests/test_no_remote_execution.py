"""Nothing a Telegram message can reach may execute a command on the host.

`/deploy` used to shell out on the production host — fetch the branch,
hard-reset the working tree, reinstall requirements, restart the service unit
— as one string handed to a shell, behind nothing but an admin check.

Three separate problems, and removing it fixes all three:

  * it could not work. Production is Render, deploying from GitHub on every
    commit. There is no checkout on disk and no service unit on that host;
    the paths it drove belonged to a machine this service left;
  * it was a SECOND way to change what code is live, inside a process that
    trades real money, so the running code could disagree with the branch
    everyone reads;
  * `is_admin` was the only thing between a Telegram message and a shell on
    the trading host. No second factor, no confirmation.

These checks are static and behavioural: the source must contain no execution
primitive, and the command must answer without running anything.

Run: python tests/test_no_remote_execution.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-nox-")

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APEX = os.path.join(ROOT, "apex")


def code_of(path):
    """Source with comments and docstrings removed.

    Scanning raw text finds the words in the comment that EXPLAINS the
    removal, which is how a check like this quietly starts passing on prose.
    """
    src = open(path, encoding="utf-8").read()
    src = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', '""', src)
    src = re.sub(r"#.*$", "", src, flags=re.M)
    return src


PY = []
for base, _dirs, files in os.walk(APEX):
    if "__pycache__" in base:
        continue
    PY += [os.path.join(base, f) for f in files if f.endswith(".py")]
PY.append(os.path.join(ROOT, "main.py"))

print("\n🔒 NO REMOTE EXECUTION — a message must not reach a shell\n")

print("1. The production package contains no execution primitive")
BANNED = ("subprocess", "os.system", "os.popen", "shell=True",
          "systemctl", "pty.spawn", "os.execv", "commands.getoutput")
for token in BANNED:
    guilty = [os.path.relpath(p, ROOT) for p in PY if token in code_of(p)]
    check(f"no {token}", not guilty, guilty)

print("\n2. …and no git command against the host filesystem")
for token in ("git reset", "git fetch", "git pull", "git checkout"):
    guilty = [os.path.relpath(p, ROOT) for p in PY if token in code_of(p)]
    check(f"no {token!r}", not guilty, guilty)

print("\n3. /deploy answers, and only reads")
from apex import telegram  # noqa: E402

sent = []
_real = telegram.send_to
try:
    telegram.send_to = lambda cid, text, *a, **k: sent.append(text)
    os.environ["RENDER_SERVICE_NAME"] = "svc-under-test"
    os.environ["RENDER_GIT_BRANCH"] = "a-branch"
    os.environ["RENDER_GIT_COMMIT"] = "0123456789abcdef"
    telegram._handle_deploy("1")
finally:
    telegram.send_to = _real
    for k in ("RENDER_SERVICE_NAME", "RENDER_GIT_BRANCH", "RENDER_GIT_COMMIT"):
        os.environ.pop(k, None)

out = sent[-1] if sent else ""
check("it replies", bool(out))
check("it names the running service", "svc-under-test" in out, out[:120])
check("it names the branch deploys come from", "a-branch" in out, out[:160])
check("it shows the running commit, shortened", "01234567" in out, out[:200])
check("it says deploys are automatic", "automatic" in out.lower(), out[:240])
check("it says it cannot change anything", "read-only" in out.lower(), out[-160:])

print("\n4. The handler itself runs nothing")
import inspect  # noqa: E402

body = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', '""',
              inspect.getsource(telegram._handle_deploy))
for token in ("subprocess", "Popen", "system(", "shell", "systemctl", "git "):
    check(f"the handler body has no {token!r}", token not in body)
check("it does not spawn a thread to do work later", "Thread" not in body,
      "the old one deployed on a background thread so the reply arrived first")

print("\n5. It stays out of reach of the operator message channel")
# _MSG_DENY is a local inside the handler factory, so it is not a module
# attribute — read the block itself rather than the whole file, which would
# also match the comment above it.
CA = open(os.path.join(APEX, "control_actions.py"), encoding="utf-8").read()
deny_block = CA.split("_MSG_DENY = {")[1].split("}")[0]
check("/deploy cannot be sent as a client message", '"/deploy"' in deny_block,
      "MCP must not be able to type it on somebody's behalf")
check("and neither can the other money-moving commands",
      all(f'"{c}"' in deny_block for c in ("/paper", "/reset", "/buy", "/sell",
                                           "/close", "/grant", "/revoke")),
      deny_block)

print("\n6. Non-admins never reach it")
ROUTER = code_of(os.path.join(APEX, "telegram.py"))
m = re.search(r'cmd_l\s*==\s*"/deploy"\s*and\s*is_adm', ROUTER)
check("the route still requires an admin", bool(m),
      "read-only or not, deployment detail is operator information")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — no Telegram path can execute anything.")
