"""The operations layer: authorization, isolation, and refusing to guess.

APEX is the authority; the ops API is a window. These tests pin the three
properties that make that true rather than aspirational:

  * AUTHORIZATION — read is always available, controlled operations need an
    explicit switch AND a confirmation, and financial actions need a separate
    switch of their own. An action nobody classified is treated as financial,
    so a new handler cannot become remotely callable by being forgotten.
  * ISOLATION — no tool reaches another user's data, and nothing
    credential-shaped leaves the process.
  * SAFE FAILURE — an unreadable subsystem reports UNKNOWN. It is never
    rounded to HEALTHY, and UNKNOWN blocks rather than authorizes.

Run: python tests/test_ops_api.py
"""
import os
import sys

os.environ.setdefault("PAPER_TRADING", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import control, ops_api, ownership, user_loop, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def env(**kw):
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


print("\n🧪 OPS API — authorization, isolation, safe failure\n")

# ─────────────────────────────────────────────────────────────
print("1. Capability levels")
env(MCP_CONTROL_ENABLED=None, MCP_FINANCIAL_ENABLED=None)
check("reads work with everything switched off",
      control.authorize("ops_user_health", {"user_id": "1"})[0] is True)
check("a controlled op is refused", control.authorize("restart_loop", {})[0] is False)
check("and says why",
      "LEVEL_2_DISABLED" in control.authorize("restart_loop", {})[1])
check("a financial action is refused",
      control.authorize("force_trade", {})[0] is False)

env(MCP_CONTROL_ENABLED="true")
ok, why = control.authorize("restart_loop", {})
check("with ops enabled it still needs confirmation",
      ok is False and "CONFIRMATION_REQUIRED" in why, why)
check("confirmed, it passes",
      control.authorize("restart_loop", {"confirm": True})[0] is True)

# The point of the whole level split: enabling operations must not enable money.
ok, why = control.authorize("force_trade", {"confirm": True})
check("enabling LEVEL 2 does NOT enable LEVEL 3",
      ok is False and "FINANCIAL_DISABLED" in why, why)
check("closing a position is financial too",
      control.authorize("force_close", {"confirm": True})[0] is False)

env(MCP_FINANCIAL_ENABLED="true")
check("financial needs its own switch AND a confirmation",
      control.authorize("force_trade", {})[0] is False)
check("both present → allowed",
      control.authorize("force_trade", {"confirm": True})[0] is True)
env(MCP_CONTROL_ENABLED=None, MCP_FINANCIAL_ENABLED=None)

print("\n   an unclassified action is treated as the dangerous kind")
check("an unknown action is level 3", control.level_of("ops_delete_everything") == 3)
check("and is therefore refused by default",
      control.authorize("ops_delete_everything", {"confirm": True})[0] is False)
check("every registered read tool is level 1",
      all(control.level_of(a) == 1 for a in control.LEVEL_1_READ))
check("no action is in two levels at once",
      not (control.LEVEL_1_READ & control.LEVEL_2_CONTROLLED)
      and not (control.LEVEL_1_READ & control.LEVEL_3_FINANCIAL)
      and not (control.LEVEL_2_CONTROLLED & control.LEVEL_3_FINANCIAL))

# ─────────────────────────────────────────────────────────────
print("\n2. No generic escape hatches exist")
from apex import control_actions  # noqa: E402

CA = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "apex", "control_actions.py"), encoding="utf-8").read()
OPS = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "ops_api.py"), encoding="utf-8").read()
for bad in ("execute_sql", "execute_action", "run_shell", "eval(", "exec("):
    check(f"no {bad!r} in the ops surface", bad not in OPS and bad not in CA)
check("no arbitrary redis command is exposed",
      "def redis_command" not in OPS and "_cmd(" not in OPS.split("recent_errors")[0])

# ─────────────────────────────────────────────────────────────
print("\n3. Isolation — user ids are validated, secrets never leave")
for bad in ("", None, "../../etc", "1 OR 1=1", "abc", "*", "9" * 40):
    r = ops_api.user_health(bad)
    check(f"{bad!r} is refused", "error" in r, r)
check("a valid-looking id is accepted as far as existence",
      "error" in ops_api.user_health("999999999"))   # no such user, not a crash

SECRET = {"ctrader_access_token": "SECRET-A", "ctrader_refresh_token": "SECRET-B",
          "license_key": "FORX-1111", "api_key": "sk_live_x", "symbol": "EURUSD",
          "nested": {"telegram_bot_token": "123:AA", "risk": 0.01}}
red = ops_api._redact(SECRET)
for k in ("ctrader_access_token", "ctrader_refresh_token", "license_key", "api_key"):
    check(f"{k} is dropped", k not in red)
check("nested secrets are dropped too", "telegram_bot_token" not in red["nested"])
check("non-secret fields survive",
      red["symbol"] == "EURUSD" and red["nested"]["risk"] == 0.01)
check("a list of dicts is redacted as well",
      "ctrader_access_token" not in ops_api._redact([SECRET])[0])

print("\n   the audit log redacts arguments too")
safe = control._safe_args({"user_id": "1", "ctrader_access_token": "SECRET",
                           "api_key": "sk_live", "value": "0.01"})
check("token argument is redacted", safe["ctrader_access_token"] == "[REDACTED]")
check("key argument is redacted", safe["api_key"] == "[REDACTED]")
check("ordinary arguments are kept", safe["user_id"] == "1" and safe["value"] == "0.01")

# ─────────────────────────────────────────────────────────────
print("\n4. Safe failure — UNKNOWN is never rounded to HEALTHY")
_ol, _od, _oh, _osb = (user_store.load, user_loop.get_dash,
                       ownership.holds, ownership.shared_backed)
try:
    ownership.shared_backed = lambda: True
    ownership.holds = lambda _u: None            # backend unreachable
    r = ops_api.user_ownership("123456")
    check("unreadable ownership reports UNKNOWN", r["status"] == ops_api.UNKNOWN, r)
    check("it does NOT claim the lease is active", r.get("lease") != "ACTIVE")

    # A user whose every subsystem is unreadable must not read as healthy.
    user_store.load = lambda _u: {"paper": True, "ctrader_access_token": "x"}
    user_loop.get_dash = lambda _u: {}
    parts = {
        "license": ops_api._unknown("store down"),
        "broker": ops_api._ok(broker="CONNECTED"),
        "risk": ops_api._ok(guard="ACTIVE"),
        "worker": ops_api._ok(running=True),
        "ownership": ops_api._unknown("backend down"),
        "positions": ops_api._ok(protection="N/A"),
        "reconcile": ops_api._ok(state="OK"),
        "errors": ops_api._ok(errors=[]),
    }
    st, cause, blocked = ops_api._classify(parts)
    check("any UNKNOWN part makes the whole verdict UNKNOWN",
          st == ops_api.UNKNOWN, st)
    check("and UNKNOWN blocks rather than authorizes", blocked is True)
    check("the report names what could not be verified",
          "license" in cause and "ownership" in cause, cause)
    check("the advice is to not act", "Do not act" in ops_api._advice(st))
finally:
    (user_store.load, user_loop.get_dash,
     ownership.holds, ownership.shared_backed) = _ol, _od, _oh, _osb

print("\n   a genuine block is classified as itself, not as UNKNOWN")
base = {"license": ops_api._ok(license="ACTIVE"),
        "broker": ops_api._ok(broker="CONNECTED"),
        "risk": ops_api._ok(guard="ACTIVE", guard_reasons=[]),
        "worker": ops_api._ok(running=True),
        "ownership": ops_api._ok(lease="ACTIVE"),
        "positions": ops_api._ok(protection="N/A"),
        "reconcile": ops_api._ok(state="OK"),
        "errors": ops_api._ok(errors=[])}
check("all good → HEALTHY, nothing blocked",
      ops_api._classify(base) == (ops_api.HEALTHY, "", False))
check("revoked licence → LICENSE_BLOCKED",
      ops_api._classify({**base, "license": ops_api._ok(license="REVOKED")})[0]
      == ops_api.LICENSE_BLOCKED)
check("lost lease → OWNERSHIP_LOST",
      ops_api._classify({**base, "ownership": ops_api._ok(lease="OWNERSHIP_LOST")})[0]
      == ops_api.OWNERSHIP_LOST_ST)
check("risk guard holding → RISK_BLOCKED",
      ops_api._classify({**base, "risk": ops_api._ok(guard="HOLDING",
                                                     guard_reasons=["dd"])})[0]
      == ops_api.RISK_BLOCKED)
check("no stop on an open position → SAFE_MODE",
      ops_api._classify({**base,
                         "positions": ops_api._ok(protection="MISSING_STOP")})[0]
      == ops_api.SAFE_MODE)
check("a blocked client always has new entries BLOCKED",
      all(ops_api._classify({**base, k: v})[2] is True for k, v in (
          ("license", ops_api._ok(license="REVOKED")),
          ("worker", ops_api._ok(running=False)))))

# ─────────────────────────────────────────────────────────────
print("\n5. Investigation changes nothing")
check("investigate() records that it took no financial action",
      "financial_action_taken" in OPS and '"financial_action_taken": False' in OPS)
for verb in ("place_order", "close_position", "force_close", "force_trade",
             "user_store.update", "user_store.save"):
    check(f"the ops module never calls {verb}", verb not in OPS)

print("\n6. Every ops tool is registered and reachable")
handlers = [ln for ln in CA.splitlines() if ln.strip().startswith('"ops_')]
check("all registered ops tools are declared level 1",
      all(any(f'"{a}"' in h for h in handlers) for a in
          ("ops_system_health", "ops_user_health", "ops_investigate")))
declared = {a for a in control.LEVEL_1_READ if a.startswith("ops_")}
registered = {ln.split('"')[1] for ln in handlers}
check("no ops tool is registered without a level",
      registered <= declared, registered - declared)
check("no ops tool is declared without a handler",
      declared <= registered, declared - registered)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — read-only by default, financial actions unreachable.")
