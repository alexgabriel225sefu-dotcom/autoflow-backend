"""Remote configuration must not be a write primitive onto the environment.

`bot._apply_config` used to be, in full:

    for k, v in data.items():
        os.environ[k] = str(v)

and `load_remote()` fed it whatever answered for the licence server. Whoever
controls that response — the server, anyone who can write the `bot_configs`
row, anyone who can answer for that hostname — could set ANY environment
variable in a process that places trades with real money.

That is not a configuration bug, it is remote code execution:

    PATH        decides which binary the next subprocess runs
    LD_PRELOAD  maps a shared object into every child process
    PYTHONPATH  decides which module `import` finds first

and it could equally overwrite TOKEN_ENCRYPTION_KEY (every stored credential),
LICENSE_SERVER (where the NEXT config comes from — self-perpetuating), or
CTRADER_REDIRECT_URI (where an OAuth code is delivered).

No denylist fixes this, because the dangerous key is always the one nobody
listed. These checks assert the allowlist: a key that is not named in
apex/settings_policy is refused, whatever it is called.

Run: python tests/test_remote_config_allowlist.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-remotecfg-")

from apex import settings_policy as sp  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


def refused(key, value="x"):
    try:
        sp.validate_remote(key, value)
        return False
    except sp.SettingRejected:
        return True


def _why(key, value="x"):
    """The refusal message for a key, or '' if it was accepted."""
    try:
        sp.validate_remote(key, value)
        return ""
    except sp.SettingRejected as e:
        return str(e)


print("\n🔒 REMOTE CONFIG — allowlist, not denylist\n")

print("1. Process-control variables — the execution vector")
for k in ("PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONSTARTUP",
          "BASH_ENV", "IFS", "SHELL", "HOME", "TMPDIR", "NODE_OPTIONS"):
    check(f"{k} refused", refused(k, "/tmp/evil"))

print("\n2. Secrets and signing keys")
for k in ("TOKEN_ENCRYPTION_KEY", "STRIPE_WEBHOOK_SECRET", "MCP_SIGNING_SECRET",
          "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN", "CTRADER_REFRESH_TOKEN",
          "ADMIN_CHAT_ID", "SUPABASE_SERVICE_KEY", "DATABASE_URL"):
    check(f"{k} refused", refused(k, "stolen"))

print("\n3. Network destinations — SSRF and self-perpetuation")
for k in ("LICENSE_SERVER", "LICENSE_KEY", "DASHBOARD_URL", "AI_GATEWAY_URL",
          "VOICE_SHORTCUT_URL", "CTRADER_REDIRECT_URI"):
    check(f"{k} refused", refused(k, "http://169.254.169.254/"))

print("\n4. EV_GATE_MODE stays an operator decision")
check("EV_GATE_MODE refused from remote", refused("EV_GATE_MODE", "enforce"))

print("\n5. Nonsense keys and lookalikes")
for k in ("", "  ", "__class__", "risk_per_trade", "RISK_PER_TRADE_",
          "X" * 200, "RISK\nPER\nTRADE"):
    check(f"{k!r:24} refused", refused(k, "1"))

print("\n6. …while the settings that ARE remote-configurable still work")
for k, v, want in (
    ("PAPER_TRADING",   "false",   False),
    ("RISK_PER_TRADE",  "0.02",    0.02),
    ("STOP_LOSS_PIPS",  "35",      35.0),
    ("TRADE_SYMBOL",    "eur_usd", "EURUSD"),
    ("SCAN_SYMBOLS",    "EURUSD,XAUUSD", "EURUSD,XAUUSD"),
    ("CTRADER_ENV",     "demo",    "demo"),
    ("MIN_CONFIDENCE",  "62",      62),
    ("HTF_FILTER",      "true",    True),
):
    try:
        gk, gv = sp.validate_remote(k, v)
        check(f"{k}={v} accepted as {want!r}", (gk, gv) == (k, want), f"got {gv!r}")
    except sp.SettingRejected as e:
        check(f"{k}={v} accepted", False, str(e))

print("\n7. Allowed keys still get their VALUES validated")
for k, bad in (("RISK_PER_TRADE", "50"),        # 5000% per trade
               ("RISK_PER_TRADE", "-1"),
               ("STOP_LOSS_PIPS", "0"),
               ("MIN_CONFIDENCE", "500"),
               ("CTRADER_ENV", "prod"),
               ("BROKER", "; rm -rf /"),
               ("TRADE_SYMBOL", "../../etc/passwd"),
               ("SCAN_SYMBOLS", ",".join(["EURUSD"] * 500)),
               ("PAPER_TRADING", "maybe")):
    check(f"{k}={bad[:24]!r} refused", refused(k, bad))

print("\n8. Remote is strictly weaker than operator")
only_operator = set(sp.OPERATOR_SETTABLE) - set(sp.REMOTE_SETTABLE)
check("CTRADER_CLIENT_SECRET is operator-only", "CTRADER_CLIENT_SECRET" in only_operator)
check("every remote-settable secret is marked secret",
      all(sp.is_secret_key(k) for k in sp.REMOTE_SETTABLE
          if "TOKEN" in k or "KEY" in k or "SECRET" in k))

print("\n9. A refusal names the KEY and never the VALUE")
SECRET = "sk-live-THIS-MUST-NOT-APPEAR-9f3a2b"
try:
    sp.validate_remote("TOTALLY_UNKNOWN_KEY", SECRET)
    check("unknown key raised", False)
except sp.SettingRejected as e:
    check("unknown key raised", True)
    check("the message names the key", "TOTALLY_UNKNOWN_KEY" in str(e), str(e))
    check("the message does NOT carry the value", SECRET not in str(e), str(e))

# Secrets are validated on the PROVISIONING path now — the runtime path
# refuses them by category before a validator ever sees the value, which is
# itself the stronger answer. Both refusals must stay value-free.
try:
    sp.validate_remote("DASHBOARD_TOKEN", "tiny-9f3a2b")
    check("the runtime path refuses a credential", False)
except sp.SettingRejected as e:
    check("the runtime path refuses a credential", True)
    check("without echoing it", "tiny-9f3a2b" not in str(e), str(e))
    check("and says it is the wrong path, not an unknown key",
          "provisioning credential" in str(e), str(e))

try:
    sp.validate_provisioning("DASHBOARD_TOKEN", "tiny-9f3a2b")
    check("a too-short credential is refused on the provisioning path", False)
except sp.SettingRejected as e:
    check("a too-short credential is refused on the provisioning path", True)
    check("and does not echo the rejected secret", "tiny-9f3a2b" not in str(e), str(e))
    check("it says the value was withheld", "withheld" in str(e), str(e))

print("\n10. …and _apply_config actually enforces it end to end")
from apex import bot  # noqa: E402

os.environ.pop("LD_PRELOAD", None)
before_risk = os.environ.get("RISK_PER_TRADE")
applied = bot._apply_config(
    {"LD_PRELOAD": "/tmp/evil.so",
     "PATH": "/tmp/evil",
     "TOKEN_ENCRYPTION_KEY": "attacker-key",
     "LICENSE_SERVER": "http://evil.invalid",
     "RISK_PER_TRADE": "0.01"},
    source="test-remote",
    validate=sp.validate_remote,
)
check("only the one legitimate setting was applied", applied == 1, f"applied={applied}")
check("LD_PRELOAD never reached the environment", "LD_PRELOAD" not in os.environ)
check("PATH was not overwritten", os.environ.get("PATH") != "/tmp/evil")
check("TOKEN_ENCRYPTION_KEY was not overwritten",
      os.environ.get("TOKEN_ENCRYPTION_KEY") != "attacker-key")
check("LICENSE_SERVER was not overwritten",
      os.environ.get("LICENSE_SERVER") != "http://evil.invalid")
check("the legitimate setting DID apply", os.environ.get("RISK_PER_TRADE") == "0.01")
if before_risk is not None:
    os.environ["RISK_PER_TRADE"] = before_risk

print("\n11. The remote loader is wired to the REMOTE allowlist")
import inspect  # noqa: E402
src = inspect.getsource(bot.load_remote)
check("load_remote passes validate_remote", "validate_remote" in src, src[-400:])

print("\n12. Everything runtime.json can carry is still settable")
# A regression here would silently drop an operator's saved setting at startup.
import re  # noqa: E402
tg_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "apex", "telegram.py"), encoding="utf-8").read()
saved = set()
for m in re.finditer(r"_save_runtime\(\{(.*?)\}", tg_src, re.S):
    saved |= set(re.findall(r'"([A-Z_0-9]+)"', m.group(1)))
missing = sorted(k for k in saved if k not in sp.OPERATOR_SETTABLE)
check(f"all {len(saved)} runtime.json keys survive the operator allowlist",
      not missing, f"would be dropped at startup: {missing}")

print("\n13. Provisioning credentials are a SEPARATE trust class")
# Before the split, REMOTE_SETTABLE was {**trading, **provisioning} and every
# startup fetch applied the lot. The allowlist stopped arbitrary environment
# injection, but any response from the licence server could still ROTATE the
# bot's Telegram token, dashboard token or AI key as a side effect of a routine
# configuration update. Whoever controls that response then controls the bot.
# MT_BRIDGE_SECRET and TWELVE_DATA_KEY are absent from BOTH tables now: their
# brokers cannot run, so a credential for them is dead configuration surface.
# They are covered by the unknown-key checks above instead.
for k in ("TELEGRAM_BOT_TOKEN", "DASHBOARD_TOKEN", "GROQ_API_KEY",
          "GEMINI_API_KEY", "METAAPI_TOKEN", "AI_GATEWAY_KEY"):
    check(f"{k} is refused by the RUNTIME path", refused(k, "x" * 40))
    check(f"…and the refusal says why, not just 'unknown'",
          "provisioning credential" in _why(k, "x" * 40), _why(k, "x" * 40))

check("trading settings are NOT in the provisioning table",
      not (set(sp.REMOTE_SETTABLE) & set(sp.REMOTE_PROVISIONING)),
      "the two classes overlap, so the split means nothing")
check("the runtime table is trading settings only",
      all(not sp.is_secret_key(k) for k in sp.REMOTE_SETTABLE),
      "a credential is still runtime-settable")

print("\n14. …delivered once, never replaced")
_before = os.environ.get("DASHBOARD_TOKEN")
os.environ.pop("DASHBOARD_TOKEN", None)
n1 = bot._apply_provisioning({"DASHBOARD_TOKEN": "first-value-0123456789abcdef"})
check("a fresh container receives the credential", n1 == 1, f"applied={n1}")
check("and it is actually set",
      os.environ.get("DASHBOARD_TOKEN") == "first-value-0123456789abcdef")

n2 = bot._apply_provisioning({"DASHBOARD_TOKEN": "attacker-value-0123456789ab"})
check("a later response cannot replace it", n2 == 0, f"applied={n2}")
check("the original value is untouched",
      os.environ.get("DASHBOARD_TOKEN") == "first-value-0123456789abcdef",
      "a config fetch rotated the bot's dashboard credential")

check("provisioning_allowed says no once a value exists",
      sp.provisioning_allowed("DASHBOARD_TOKEN", "already-set") is False)
check("…and yes when nothing is set",
      sp.provisioning_allowed("DASHBOARD_TOKEN", "") is True)
check("…and no for a key that is not a provisioning credential",
      sp.provisioning_allowed("RISK_PER_TRADE", "") is False)

if _before is None:
    os.environ.pop("DASHBOARD_TOKEN", None)
else:
    os.environ["DASHBOARD_TOKEN"] = _before

print("\n15. Provisioning still refuses everything outside its own table")
for k in ("PATH", "LD_PRELOAD", "TOKEN_ENCRYPTION_KEY", "LICENSE_SERVER",
          "CTRADER_CLIENT_SECRET", "RISK_PER_TRADE", "JWT_SECRET",
          "COOKIE_SECRET", "STRIPE_WEBHOOK_SECRET"):
    try:
        sp.validate_provisioning(k, "x" * 40)
        check(f"{k} refused by the provisioning path", False, "accepted")
    except sp.SettingRejected:
        check(f"{k} refused by the provisioning path", True)

check("load_remote routes both classes",
      "validate_remote" in src and "_apply_provisioning" in src,
      "the loader does not use the split")

print("\n16. The generated field allowlist still matches these tables")
# server.js filters GET /api/bot-config down to config/bot-config-fields.json.
# That file is generated from the tables above rather than hand-written in JS,
# because a second copy is the one that drifts — and the failure is silent: add
# a setting here only, and the bot quietly stops receiving it.
import json  # noqa: E402
_FIELDS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "config", "bot-config-fields.json")
check("the generated file exists", os.path.exists(_FIELDS), _FIELDS)
if os.path.exists(_FIELDS):
    doc = json.load(open(_FIELDS, encoding="utf-8"))
    check("runtime keys match REMOTE_SETTABLE",
          sorted(doc.get("runtime", [])) == sorted(sp.REMOTE_SETTABLE),
          "run scripts/gen_bot_config_fields.py — the two have drifted")
    check("provisioning keys match REMOTE_PROVISIONING",
          sorted(doc.get("provisioning", [])) == sorted(sp.REMOTE_PROVISIONING),
          "run scripts/gen_bot_config_fields.py — the two have drifted")
    every = set(doc.get("runtime", [])) | set(doc.get("provisioning", []))
    for dangerous in ("PATH", "PYTHONPATH", "LD_PRELOAD", "TOKEN_ENCRYPTION_KEY",
                      "JWT_SECRET", "COOKIE_SECRET", "STRIPE_WEBHOOK_SECRET",
                      "LICENSE_SERVER", "CTRADER_CLIENT_SECRET",
                      "CTRADER_ACCESS_TOKEN", "MT_BRIDGE_SECRET", "EV_GATE_MODE"):
        check(f"{dangerous} is absent from the shipped allowlist",
              dangerous not in every)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} FAILED: {', '.join(failures[:10])}")
    sys.exit(1)
print("✅ ALL REMOTE-CONFIG CHECKS PASSED — remote config cannot write the environment.")
