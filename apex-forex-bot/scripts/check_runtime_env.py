"""Config-drift check: are the production variables present and safe?

Prints variable NAMES and a status, never a value. Safe to paste into a chat.

    python3 scripts/check_runtime_env.py                 # the current environment
    python3 scripts/check_runtime_env.py --env-file prod.env

Statuses
    OK       present and acceptable
    MISSING  required and absent or blank
    UNSAFE   set to something a production deployment must not have
    SKIPPED  optional and not set

Exit code 0 only when nothing is MISSING or UNSAFE.

WHERE THE LIST COMES FROM (so it can be audited, not trusted)
  health.py            supabase, encryption, shared_store, ctrader_oauth,
                       dev_flags, live_trading, rate_limit_store, billing
  user_store.py        REDIS_URL / UPSTASH_REDIS_REST_URL + _TOKEN, PRODUCT, APP_ENV
  platform_server.py   A4T_ALLOWED_ORIGIN (CORS; unset blocks every web call)
  entitlement.py       A4T_LIVE_EXECUTION is the live switch
  live_gate.py         A4T_OPERATOR_USER_IDS (optional: who is an operator)
The env file is parsed here and never exported or executed.
"""
import argparse
import os
import re
import sys

OK, MISSING, UNSAFE, SKIPPED = "OK", "MISSING", "UNSAFE", "SKIPPED"

REQUIRED_NAMES = (
    "APP_ENV", "PRODUCT", "TOKEN_ENCRYPTION_KEY",
    "SUPABASE_URL", "SUPABASE_ANON_KEY",
    "CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_REDIRECT_URI",
    "A4T_ALLOWED_ORIGIN",
)
SHARED_STORE = "REDIS_URL|UPSTASH"

# name -> predicate(value) that is True when the (set) value is unsafe.
_TRUTHY = ("1", "true", "yes", "on")


def _truthy(v):
    return v.strip().lower() in _TRUTHY


UNSAFE_IF_SET = {
    "ALLOW_LOCAL_BACKEND_DEV": _truthy,           # health.DEV_ONLY_FLAGS
    "ALLOW_PLAINTEXT_DEV_STORAGE": _truthy,       # health.DEV_ONLY_FLAGS
    "LIVE_TRADING_ENABLED": _truthy,              # fails /readyz; not the switch
    "A4T_LIVE_EXECUTION": lambda v: v.strip() != "",   # owner decision, not config
    "SUPABASE_SERVICE_KEY": lambda v: v.strip() != "",  # bypasses row-level security
    "RATE_LIMIT_STORE": lambda v: v.strip().lower() == "memory",
    "A4T_CHECKOUT_ENABLED": _truthy,              # no checkout path in this build
}


OPERATOR_NAME = "A4T_OPERATOR_USER_IDS"
# A Supabase user id. An e-mail address or text with spaces in the list never
# matches anyone, and the owner would believe they were an operator.
_OPERATOR_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _val(env, name):
    return (env.get(name) or "").strip()


def _origin_unsafe(value):
    for o in (x.strip() for x in value.split(",") if x.strip()):
        low = o.lower()
        if o == "*" or not low.startswith("https://"):
            return True
        host = low[len("https://"):].split("/")[0].split(":")[0]
        if host in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]"):
            return True
    return False


def evaluate(env):
    """Return [(name, status, note)] for a mapping of environment variables."""
    rows = []
    for name in REQUIRED_NAMES:
        v = _val(env, name)
        if not v:
            rows.append((name, MISSING, "required"))
            continue
        low = v.lower()
        if name == "APP_ENV" and low in ("dev", "development", "local", "test"):
            rows.append((name, UNSAFE, "non-production APP_ENV"))
        elif name == "A4T_ALLOWED_ORIGIN" and _origin_unsafe(v):
            rows.append((name, UNSAFE, "must be https origin(s), no wildcard or localhost"))
        elif name == "CTRADER_REDIRECT_URI" and not low.startswith("https://"):
            rows.append((name, UNSAFE, "must be https"))
        else:
            rows.append((name, OK, ""))
    shared = bool(_val(env, "REDIS_URL")) or (
        bool(_val(env, "UPSTASH_REDIS_REST_URL"))
        and bool(_val(env, "UPSTASH_REDIS_REST_TOKEN")))
    rows.append((SHARED_STORE, OK if shared else MISSING,
                 "REDIS_URL, or UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN"))
    for name, bad in UNSAFE_IF_SET.items():
        v = _val(env, name)
        if v and bad(v):
            rows.append((name, UNSAFE, "must not be set in production"))
        else:
            rows.append((name, OK, "not set" if not v else "acceptable"))
    # Optional. An empty list is the normal state and never an error. A list is
    # reported by how many entries it has, never by what they are.
    ids = [x.strip() for x in _val(env, OPERATOR_NAME).split(",") if x.strip()]
    if not ids:
        rows.append((OPERATOR_NAME, SKIPPED, "optional: no operator is set"))
    elif any(not _OPERATOR_ID.match(i) for i in ids):
        rows.append((OPERATOR_NAME, UNSAFE,
                     "an entry is not a Supabase user id and will never match"))
    else:
        rows.append((OPERATOR_NAME, OK, f"{len(ids)} operator id(s)"))
    return rows


def exit_code(rows):
    return 1 if any(r[1] in (MISSING, UNSAFE) for r in rows) else 0


def report(rows, out=None):
    out = out or sys.stdout
    width = max(len(r[0]) for r in rows)
    for name, st, note in rows:
        line = f"{st:<8} {name:<{width}}"
        if st in (MISSING, UNSAFE) and note:
            line += f"  ({note})"
        print(line, file=out)
    bad = [r[0] for r in rows if r[1] in (MISSING, UNSAFE)]
    print("\n" + (f"NOT READY: {len(bad)} problem(s): {', '.join(bad)}"
                  if bad else "READY: no missing or unsafe variables."), file=out)


def parse_env_file(path):
    """KEY=VALUE lines. No shell, no expansion, nothing exported."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or " " in key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            out[key] = value
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--env-file", help="check this file instead of the environment")
    args = ap.parse_args(argv)
    env = parse_env_file(args.env_file) if args.env_file else dict(os.environ)
    rows = evaluate(env)
    report(rows)
    return exit_code(rows)


if __name__ == "__main__":
    sys.exit(main())
