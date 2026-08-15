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
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

from apex import control, ops_api, ownership, user_loop, user_store  # noqa: E402

DEGRADED_ST = ops_api.DEGRADED

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
# Levels 2 and 3 also require a named, allowlisted operator (see
# tests/test_hardening.py section 5). These checks are about the LEVEL rules,
# so they supply a valid operator and vary only the switches.
OP = "owner"
env(MCP_OPERATORS=OP, MCP_CONTROL_ENABLED=None, MCP_FINANCIAL_ENABLED=None)
check("reads work with everything switched off",
      control.authorize("ops_user_health", {"user_id": "1"})[0] is True)
check("a controlled op is refused",
      control.authorize("restart_loop", {}, operator=OP)[0] is False)
check("and says why",
      "LEVEL_2_DISABLED" in control.authorize("restart_loop", {}, operator=OP)[1])
check("a financial action is refused",
      control.authorize("force_trade", {}, operator=OP)[0] is False)

env(MCP_CONTROL_ENABLED="true")
ok, why = control.authorize("restart_loop", {}, operator=OP)
check("with ops enabled it still needs confirmation",
      ok is False and "CONFIRMATION_REQUIRED" in why, why)
check("confirmed, it passes",
      control.authorize("restart_loop", {"confirm": True}, operator=OP)[0] is True)

# The point of the whole level split: enabling operations must not enable money.
ok, why = control.authorize("force_trade", {"confirm": True}, operator=OP)
check("enabling LEVEL 2 does NOT enable LEVEL 3",
      ok is False and "FINANCIAL_DISABLED" in why, why)
check("closing a position is financial too",
      control.authorize("force_close", {"confirm": True}, operator=OP)[0] is False)

env(MCP_FINANCIAL_ENABLED="true")
check("financial needs its own switch AND a confirmation",
      control.authorize("force_trade", {}, operator=OP)[0] is False)
check("both present → allowed",
      control.authorize("force_trade", {"confirm": True}, operator=OP)[0] is True)
env(MCP_CONTROL_ENABLED=None, MCP_FINANCIAL_ENABLED=None)

print("\n   an unclassified action is treated as the dangerous kind")
check("an unknown action is level 3", control.level_of("ops_delete_everything") == 3)
check("and is therefore refused by default",
      control.authorize("ops_delete_everything", {"confirm": True},
                        operator=OP)[0] is False)
check("every registered read tool is level 1",
      all(control.level_of(a) == 1 for a in control.LEVEL_1_READ))
check("no action is in two levels at once",
      not (control.LEVEL_1_READ & control.LEVEL_2_CONTROLLED)
      and not (control.LEVEL_1_READ & control.LEVEL_3_FINANCIAL)
      and not (control.LEVEL_2_CONTROLLED & control.LEVEL_3_FINANCIAL))

# ─────────────────────────────────────────────────────────────

print("\n1b. system_health uses the REAL Redis probe, not a config flag")
# Was: `_USE_REDIS == True` -> "HEALTHY". Configured is not reachable, so a
# backend that died at 03:00 reported healthy until somebody noticed by other
# means.
_rh = user_store.redis_health
try:
    user_store.redis_health = lambda **k: {
        "configured": True, "reachable": True, "latency_ms": 12,
        "last_success": 1786800000, "failure_count": 0, "status": "HEALTHY"}
    h = ops_api.system_health()
    check("a healthy probe reports HEALTHY", h["redis"] == "HEALTHY", h["redis"])
    check("and carries the probe detail", h["redis_detail"]["latency_ms"] == 12, h)

    user_store.redis_health = lambda **k: {
        "configured": True, "reachable": False, "status": "DOWN",
        "failure_count": 3, "detail": "connection refused"}
    h = ops_api.system_health()
    check("an unreachable backend reports DOWN, not HEALTHY", h["redis"] == "DOWN", h)
    check("and the whole system is DOWN, not merely degraded",
          h["overall"] == "DOWN", h["overall"])
    check("ownership cannot be healthier than the backend it rides on",
          h["ownership_backend"] in ("DOWN", "NOT_CONFIGURED"), h)

    user_store.redis_health = lambda **k: {
        "configured": True, "reachable": True, "status": "DEGRADED",
        "latency_ms": 4200, "failure_count": 0,
        "detail": "round trip 4200ms exceeds 3000ms"}
    h = ops_api.system_health()
    check("a slow backend is DEGRADED, not HEALTHY", h["redis"] == "DEGRADED")
    check("and drags the overall verdict down", h["overall"] == DEGRADED_ST,
          h["overall"])

    def _boom(**k):
        raise RuntimeError("probe itself failed")
    user_store.redis_health = _boom
    h = ops_api.system_health()
    check("a probe that raises reports UNKNOWN, never HEALTHY",
          h["redis"] == ops_api.UNKNOWN, h["redis"])
    check("and the overall verdict is UNKNOWN", h["overall"] == ops_api.UNKNOWN)

    # Recovery.
    user_store.redis_health = lambda **k: {
        "configured": True, "reachable": True, "latency_ms": 8,
        "last_success": 1786800100, "failure_count": 0, "status": "HEALTHY"}
    h = ops_api.system_health()
    check("after recovery it reports healthy again", h["redis"] == "HEALTHY")
finally:
    user_store.redis_health = _rh

OPS2 = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "apex", "ops_api.py"), encoding="utf-8").read()
check("system_health no longer derives health from _USE_REDIS",
      '_USE_REDIS", False) else "NOT_CONFIGURED"' not in OPS2)
check("it calls the probe", "user_store.redis_health()" in OPS2)

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
print("\n4b. Stale position data is reported as stale, not as position data")
_ol2, _od2 = user_store.load, user_loop.get_dash
try:
    user_store.load = lambda _u: {"paper": True}
    import time as _t
    # Fresh: a tick moments ago.
    user_loop.get_dash = lambda _u: {"openPosition": {"symbol": "EURUSD",
                                                      "stopLoss": 1.1},
                                     "lastTickTs": _t.time(), "openCount": 1}
    r = ops_api.user_positions("123456")
    check("a recent tick reports the position", r["status"] == "OK", r)
    check("and marks it FRESH", r.get("freshness") == "FRESH", r)
    check("and names the source rather than implying a live broker read",
          r.get("position_source") == "last_loop_state", r)

    # Stale: older than the threshold.
    user_loop.get_dash = lambda _u: {"openPosition": {"symbol": "EURUSD",
                                                      "stopLoss": 1.1},
                                     "lastTickTs": _t.time() - 1200,
                                     "openCount": 1}
    r = ops_api.user_positions("123456")
    check("an old tick is UNKNOWN, not OK", r["status"] == ops_api.UNKNOWN, r)
    check("marked STALE", r.get("freshness") == "STALE", r)
    check("protection is not vouched for from stale data",
          r.get("protection") == ops_api.UNKNOWN, r)
    check("the reason says the age out loud", "1200s ago" in r.get("reason", ""),
          r.get("reason"))

    # No timestamp at all: age cannot be established.
    user_loop.get_dash = lambda _u: {"openPosition": {"symbol": "EURUSD"}}
    r = ops_api.user_positions("123456")
    check("no timestamp → UNKNOWN rather than assumed current",
          r["status"] == ops_api.UNKNOWN and r.get("freshness") == ops_api.UNKNOWN, r)
finally:
    user_store.load, user_loop.get_dash = _ol2, _od2

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
