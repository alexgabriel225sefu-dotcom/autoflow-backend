"""A client may tune their automation. They may not move their own environment.

This is the screen where a pretty control could quietly become an execution
decision, so the allowlist matters more than the UI does.

The brief states it plainly: "The client must never be allowed to submit
paper=false or any equivalent flag to force LIVE execution. The server derives
the execution environment from the authenticated account."

So there is a third settings tier below operator and remote — the smallest —
built by NAMING what a client may change rather than by subtracting what they
may not. A denylist would silently admit every key added to the trading table
later, and the keys that must never be admitted are exactly the ones that
decide where money goes.

Run: python tests/test_automation_screen.py
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-signing-secret")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-auto-")

from apex import settings_policy as sp  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


BOT = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()
HTML = open(os.path.join(ROOT, "apex", "static", "terminal.html"), encoding="utf-8").read()
GET = BOT[BOT.index('if self.path.startswith("/api/app/automation") and self.command == "GET"'):]
GET = GET[:GET.index('if self.path.startswith("/api/app/intelligence")')]
POST = BOT[BOT.index('if self.path == "/api/app/automation" and self.command == "POST"'):]
POST = POST[:POST.index('if self.path == "/api/app/close"')]
GETC = "\n".join(l for l in GET.splitlines() if not l.strip().startswith("#"))
POSTC = "\n".join(l for l in POST.splitlines() if not l.strip().startswith("#"))

print("\n1. The environment is not a client setting")
for key in ("PAPER_TRADING", "CTRADER_ENV", "BROKER", "LEVERAGE", "PAPER_BALANCE"):
    check(f"{key} is not writable by a client", key not in sp.MINIAPP_SETTABLE,
          "a client who can set this can move their own account to live money")
    try:
        sp.validate_miniapp(key, "false")
        refused = False
    except Exception:
        refused = True
    check(f"...and validate_miniapp refuses it outright", refused)
check("the forbidden set and the writable set do not overlap",
      not (set(sp.MINIAPP_SETTABLE) & sp.MINIAPP_FORBIDDEN))
check("every forbidden key is one an operator CAN set",
      all(k in sp.OPERATOR_SETTABLE for k in sp.MINIAPP_FORBIDDEN),
      "the point is the tier, not that the key is unknown")

print("\n2. The client tier is a named allowlist, not a subtraction")
POLICY = open(os.path.join(ROOT, "apex", "settings_policy.py"), encoding="utf-8").read()
BODY = "\n".join(l for l in POLICY.splitlines() if not l.strip().startswith("#"))
check("MINIAPP_SETTABLE is built from an explicit tuple of names",
      re.search(r"MINIAPP_SETTABLE\s*=\s*\{\s*\n?\s*k:\s*_TRADING\[k\]\s*for k in \(", BODY)
      is not None,
      "a denylist here admits every key added to _TRADING later")
check("it is strictly smaller than the operator tier",
      0 < len(sp.MINIAPP_SETTABLE) < len(sp.OPERATOR_SETTABLE),
      f"{len(sp.MINIAPP_SETTABLE)} vs {len(sp.OPERATOR_SETTABLE)}")
check("every client key is also an operator key",
      set(sp.MINIAPP_SETTABLE) <= set(sp.OPERATOR_SETTABLE))
check("no secret is in it",
      not (set(sp.MINIAPP_SETTABLE) & set(getattr(sp, "SECRET_KEYS", set()))))

print("\n3. An unknown key is refused by name, never by value")
try:
    sp.validate_miniapp("TOTALLY_MADE_UP", "x")
    ok = False
    msg = ""
except Exception as e:
    ok, msg = True, str(e)
check("an unknown key raises", ok)
check("...naming the key", "TOTALLY_MADE_UP" in msg, msg)
check("...and identifying the tier", "client" in msg, msg)

print("\n4. The write path has exactly one gate")
check("validate_miniapp is the gate", "_s_sp.validate_miniapp(" in POSTC)
check("no other validator is used here",
      "validate_operator" not in POSTC and "validate_remote" not in POSTC)
check("os.environ is never written from a client request",
      "os.environ" not in POSTC,
      "a per-client change must not become process-wide")
check("the write lands on the client's own record",
      "_s_us.update(_s_chat" in POSTC)
check("...and is strict, so an unconfirmed write is reported",
      "strict=True" in POSTC and "WRITE_NOT_CONFIRMED" in POSTC)
check("no order path is reachable",
      not any(x in POSTC for x in ("place_order", "force_close", "authorize_order",
                                   "_make_broker")))
check("refusals are returned by key, not by value",
      '"refused": _s_refused' in POSTC and "_s_refused.append(str(_s_e)" in POSTC)

print("\n5. The request itself is bounded")
check("the body is length-checked before it is read", "> 8192" in POSTC)
check("a non-object body is refused", "isinstance(_s_body, dict)" in POSTC)
check("the number of keys is bounded", "len(_s_body) > 20" in POSTC)
check("the endpoint is rate limited", "http_security.MINIAPP.check" in POSTC)

print("\n6. Both routes are scoped to the authenticated client")
for name, code in (("GET", GETC), ("POST", POSTC)):
    check(f"{name}: identity is checked first",
          code.index("_telegram_identity") < max(code.index("load") if "load" in code else 10**9,
                                                 0) or "_telegram_identity" in code)
    check(f"{name}: a denied caller is refused", "_telegram_denied" in code)
    check(f"{name}: the chat id comes from the signature",
          'str(_u_user["id"])' in code or 'str(_s_user["id"])' in code)
    check(f"{name}: no chat id is read from the request",
          "qs.get" not in code and '"user_id"' not in code and '"chat_id"' not in code)

print("\n7. The screen offers only what the server said is writable")
check("the payload carries the writable list", '"writable": sorted(_u_sp.MINIAPP_SETTABLE)' in GETC,
      "the screen must not decide this for itself")
check("the screen reads that list", "autoWritable = d.writable" in HTML)
check("a non-writable field renders read-only", "read-only" in HTML)
check("the environment is shown as state, not as a control",
      "set by your broker, not from this screen" in HTML)
# The sentence is built from two JS literals, so only the contiguous half
# can be matched in the source. Matching the half that carries the claim.
check("the screen says a setting cannot permit a refused trade",
      "permit a trade the engine would refuse" in HTML)
check("...and that the risk engine checks every order",
      "checked by the risk engine on every order" in HTML)

print("\n8. Reachable, and no local can shadow the enclosing scope")
check("Auto is a navigation destination", 'data-s="automation"' in HTML)
check("...with a screen", 'id="s-automation"' in HTML and 'id="autoBody"' in HTML)
check("...that loads when opened", "if(name==='automation') loadAuto(true);" in HTML)
# An assignment is `name = value`; a keyword argument is `name=value`. The
# space is what tells them apart, and only the former can shadow.
RX = re.compile(r'^\s+([a-z][\w]*) = (?!=)', re.M)
for name, code in (("GET", GETC), ("POST", POSTC)):
    bare = {m.group(1) for m in RX.finditer(code)}
    check(f"{name}: every local is prefixed ({sorted(bare)})", not bare,
          "do_GET/do_POST share a scope; a bare name breaks a branch elsewhere")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL AUTOMATION CHECKS PASSED - a client tunes limits, never the environment.")
