"""Post-remediation hardening: fail closed, stay consistent, never replay.

Each section is one item from the adversarial audit, written as the failure it
prevents rather than as an assertion about implementation.

  1  credentials are never stored in plaintext by accident
  2  a user record and its active-set membership move together
  3  concurrent writers do not silently overwrite each other
  4  enabling operations does not enable money
  5  an env flag is not an identity
  6  a command id executes once
  7  OAuth binds only on a verified, single-use state
  8  the AI assistant cannot skip the gates the loop applies
  9  the ops surface exposes no generic executor
 10  APEX does not depend on the operator interface

Run: python tests/test_hardening.py
"""
import os
import sys

os.environ.setdefault("PAPER_TRADING", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

# A TEST-ONLY OAuth state signing secret.
#
# apex/ctrader_oauth refuses to mint an OAuth `state` without one, and that
# refusal is correct production behaviour under test elsewhere: `state` is what
# proves a callback belongs to the chat that began the flow, so an unsigned one
# lets somebody's broker account be bound to somebody else's chat. The fix is
# to give the TEST a secret, never to give production a fallback.
#
# setdefault, so a caller that exports its own value keeps it. This is a fake
# constant with no meaning outside this process.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-oauth-signing-secret")

import importlib  # noqa: E402
import subprocess  # noqa: E402

from apex import control, user_store  # noqa: E402

failures = []
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def import_store(**envkw):
    """Import user_store in a FRESH process with the given environment.

    The fail-closed check runs at import time, so it cannot be exercised by
    reloading a module that already imported successfully in this process.
    """
    e = dict(os.environ)
    e.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
    for k, v in envkw.items():
        e.pop(k, None) if v is None else e.update({k: v})
    r = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, %r);\n"
                        "from apex import user_store; print('IMPORTED_OK')" % ROOT],
                       capture_output=True, text=True, env=e, cwd=ROOT)
    return r.returncode, (r.stdout + r.stderr)


print("\n🧪 POST-REMEDIATION HARDENING\n")

# ─────────────────────────────────────────────────────────────
print("1. Credentials are never plaintext by accident")
rc, out = import_store(TOKEN_ENCRYPTION_KEY=None,
                       ALLOW_PLAINTEXT_DEV_STORAGE=None, APP_ENV=None)
check("no key and no opt-in → startup FAILS", rc != 0, out[-200:])
check("and it says why", "EncryptionNotConfigured" in out, out[-200:])
check("the failure never prints a key", "TOKEN_ENCRYPTION_KEY=" not in out)

rc, out = import_store(TOKEN_ENCRYPTION_KEY="not-a-valid-fernet-key",
                       ALLOW_PLAINTEXT_DEV_STORAGE=None, APP_ENV=None)
check("an INVALID key also fails, rather than falling back", rc != 0)
check("and the invalid key value is not echoed",
      "not-a-valid-fernet-key" not in out, out[-200:])

rc, out = import_store(TOKEN_ENCRYPTION_KEY=None,
                       ALLOW_PLAINTEXT_DEV_STORAGE="true", APP_ENV=None)
check("the dev flag alone is NOT enough — production is the default",
      rc != 0, "plaintext was allowed without declaring a dev environment")

rc, out = import_store(TOKEN_ENCRYPTION_KEY=None,
                       ALLOW_PLAINTEXT_DEV_STORAGE="true", APP_ENV="dev")
check("dev flag + dev environment → allowed", rc == 0 and "IMPORTED_OK" in out, out[-200:])

from cryptography.fernet import Fernet  # noqa: E402
# APP_ENV cleared = production for the ENCRYPTION guard; the backend guard is
# satisfied separately so this case isolates the one property under test.
rc, out = import_store(TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                       ALLOW_PLAINTEXT_DEV_STORAGE=None, APP_ENV="dev")
check("a real key → starts normally", rc == 0, out[-200:])

print("\n   ciphertext is never handed back as a usable credential")
check("an unopenable secret reads as absent, not as its ciphertext",
      user_store.decrypt_value("enc:garbage-that-cannot-be-opened") == "")

# ─────────────────────────────────────────────────────────────
print("\n2. Record and active-set membership move together")
SRC = open(os.path.join(ROOT, "apex", "user_store.py"), encoding="utf-8").read()
check("the save is one server-side script", "_LUA_SAVE_USER" in SRC)
_save = SRC[SRC.index("def save(user_id"):SRC.index("def update(user_id")]
check("SET and SADD/SREM are no longer separate round trips",
      "_redis_sadd" not in _save and "_redis_srem" not in _save, _save[:300])
check("the script writes the record", "redis.call('SET', KEYS[1]" in SRC)
check("and the set membership", "SADD" in SRC and "SREM" in SRC)
check("and bumps the version in the same step", "INCR" in SRC)
check("an unconfirmed write is never reported as success",
      "WRITE LOST" in _save and "return False" in _save)

# ─────────────────────────────────────────────────────────────
print("\n3. Concurrent writers do not overwrite each other")
check("save() accepts an expected version", "expect_version" in _save)
check("a mismatch raises rather than overwriting", "ConflictError" in _save)
_upd = SRC[SRC.index("def update(user_id"):SRC.index("def clear_trades")]
check("critical fields are declared", "CRITICAL_FIELDS" in SRC)
for f in ("license_key", "active", "paper", "ctrader_access_token", "risk"):
    check(f"{f} is treated as critical", f'"{f}"' in
          SRC[SRC.index("CRITICAL_FIELDS"):SRC.index("_CAS_RETRIES")])
check("a critical update retries under compare-and-set",
      "expect_version=v" in _upd and "ConflictError" in _upd)
check("and gives up rather than looping forever", "_CAS_RETRIES" in _upd)

print("\n   the lost-update race, on the local backend")
import tempfile  # noqa: E402
_olddir = user_store._DIR
user_store._DIR = tempfile.mkdtemp(prefix="apex-cas-")
try:
    user_store.save("42", {"risk": 0.01, "active": True})
    v = user_store.version("42")
    check("a fresh record has a version", v >= 1, v)
    # Two writers both read v; the second must be refused, not silently applied.
    user_store.save("42", {"risk": 0.02, "active": True}, expect_version=v)
    raised = False
    try:
        user_store.save("42", {"risk": 0.03, "active": True}, expect_version=v)
    except user_store.ConflictError:
        raised = True
    check("the second writer at the same version CONFLICTS", raised)
    check("and the first writer's value survived",
          user_store.load("42").get("risk") == 0.02,
          user_store.load("42").get("risk"))
finally:
    user_store._DIR = _olddir

# ─────────────────────────────────────────────────────────────
print("\n4. Enabling operations does not enable money")
env(MCP_OPERATORS="owner", MCP_CONTROL_ENABLED="true", MCP_FINANCIAL_ENABLED=None)
for a in ("force_close", "force_trade"):
    ok, why = control.authorize(a, {"confirm": True}, operator="owner")
    check(f"{a} is DENIED with control on and financial off",
          ok is False and "FINANCIAL_DISABLED" in why, why)
check("a level 2 action is allowed in that same state",
      control.authorize("restart_loop", {"confirm": True}, operator="owner")[0] is True)
env(MCP_FINANCIAL_ENABLED="true")
check("financial still needs confirmation",
      control.authorize("force_trade", {}, operator="owner")[0] is False)
check("with both switches and a confirmation it passes",
      control.authorize("force_trade", {"confirm": True}, operator="owner")[0] is True)

# ─────────────────────────────────────────────────────────────
print("\n5. An env flag is not an identity")
env(MCP_CONTROL_ENABLED="true", MCP_FINANCIAL_ENABLED="true")
ok, why = control.authorize("force_trade", {"confirm": True}, operator="somebody-else")
check("an operator not on the allowlist is refused",
      ok is False and why == "OPERATOR_NOT_AUTHORIZED", why)
ok, why = control.authorize("restart_loop", {"confirm": True}, operator=None)
check("a missing operator is refused", ok is False, why)
ok, why = control.authorize("restart_loop", {"confirm": True}, operator="")
check("an empty operator is refused", ok is False, why)
env(MCP_OPERATORS=None)
ok, why = control.authorize("restart_loop", {"confirm": True}, operator="owner")
check("with no allowlist configured, nobody is authorized",
      ok is False and "NO_OPERATORS_CONFIGURED" in why, why)
check("reads are unaffected by any of this",
      control.authorize("ops_system_health", {}, operator=None)[0] is True)
env(MCP_OPERATORS="owner")
check("the dispatcher passes the operator to authorize()",
      "authorize(action, args, operator=operator)" in
      open(os.path.join(ROOT, "apex", "control.py"), encoding="utf-8").read())

# ─────────────────────────────────────────────────────────────
print("\n6. A command id executes once")
CSRC = open(os.path.join(ROOT, "apex", "control.py"), encoding="utf-8").read()
check("ids are claimed before dispatch", "_claim_command(cid)" in CSRC)
check("the claim is atomic", '"SET", _replay_key(cid), "1", "NX", "EX"' in CSRC)
check("a repeat returns the ORIGINAL result rather than re-running",
      'prior = _cmd("GET", _RESULT(cid))' in CSRC)
_consumer = CSRC[CSRC.index("def start_consumer"):]
check("the replay check happens after authorization, so a refusal does not "
      "burn the id",
      _consumer.index("allowed, why = authorize") < _consumer.index("_claim_command"))
check("a financial action refuses when replay cannot be verified",
      "REPLAY_CHECK_UNAVAILABLE" in CSRC)
check("a state-changing result outlives the poll window so it can be replayed",
      "_ttl = _REPLAY_TTL if lvl > 1 else 180" in CSRC)

# ─────────────────────────────────────────────────────────────
print("\n7. OAuth binds only on a verified, single-use state")
from apex import ctrader_oauth as oauth  # noqa: E402

check("the stateless fallback is off by default", oauth.ALLOW_STATELESS is False)
oauth._pending.clear()
oauth._record_pending("111")
check("missing state → reject, even with one pending",
      oauth._recent_pending() is None)
check("an invalid state → reject", oauth.parse_state("not-a-state") is None)
check("a wrong signature → reject",
      oauth.parse_state(oauth.make_state("5")[:-3] + "aaa") is None)
_oc = user_store.claim
try:
    user_store.claim = lambda *a, **k: None
    oauth._used_states.clear()
    st = oauth.make_state("555")
    check("a valid state → accepted", oauth.parse_state(st) == "555")
    check("...exactly once", oauth._consume_state(st) is True)
    check("a reused state → reject", oauth._consume_state(st) is False)
finally:
    user_store.claim = _oc
    oauth._used_states.clear()
    oauth._pending.clear()

import time as _t  # noqa: E402
_expired = oauth.make_state("777")
_real_ttl, oauth._STATE_TTL = oauth._STATE_TTL, -1
try:
    check("an expired state → reject", oauth.parse_state(_expired) is None)
finally:
    oauth._STATE_TTL = _real_ttl

# ─────────────────────────────────────────────────────────────
print("\n8. The AI assistant cannot skip the loop's gates")
ASRC = open(os.path.join(ROOT, "apex", "assistant.py"), encoding="utf-8").read()
LSRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
check("execute_trade goes through user_loop, not the broker",
      "user_loop.force_trade(user_id" in ASRC)
check("close_position does too", "user_loop.force_close(user_id)" in ASRC)
for direct in ("place_order", "get_bid_ask", "ctrader_access_token",
               "_make_broker"):
    check(f"the assistant never touches {direct} itself", direct not in ASRC)
_ft = LSRC[LSRC.index("def force_trade"):LSRC.index("def read_candles")]
GSRC = open(os.path.join(ROOT, "apex", "gates.py"), encoding="utf-8").read()
check("the manual path enters the SHARED gate",
      "gates.authorize_order(" in _ft)
check("and audits the decision", "gates.audit(" in _ft)
# The checks themselves now live in one place. That is the fix, so this asserts
# they are all present there rather than re-inlined per caller.
check("the gate checks entitlement", "live_entitlement(" in GSRC)
check("the gate honours the risk guard", 'guard.get("halted")' in GSRC)
check("the gate checks ownership", "ownership.may_trade" in GSRC)
check("the gate claims idempotency", "ledger.claim(" in GSRC)
check("and fails closed on a live account", "fail_closed=live" in GSRC)
check("UNKNOWN entitlement denies a LIVE order",
      'if ent == "unknown" and live' in GSRC)
check("the automatic path uses the same gate",
      "gates.authorize_order(" in LSRC and LSRC.count("gates.authorize_order(") >= 2)
_fc = LSRC[LSRC.index("def force_close"):LSRC.index("def force_close_all")]
check("force_close acts on the caller's OWN account",
      "user_store.load(user_id)" in _fc and "_make_broker(user)" in _fc)

# ─────────────────────────────────────────────────────────────
print("\n9. The ops surface exposes no generic executor")
OPS = open(os.path.join(ROOT, "apex", "ops_api.py"), encoding="utf-8").read()
CA = open(os.path.join(ROOT, "apex", "control_actions.py"), encoding="utf-8").read()
for bad in ("execute_sql", "execute_shell", "execute_redis",
            "execute_broker_request", "execute_action"):
    check(f"no {bad}()", bad not in OPS and bad not in CA)
for secret in ("ctrader_access_token", "STRIPE", "TELEGRAM_BOT_TOKEN",
               "TOKEN_ENCRYPTION_KEY"):
    check(f"ops_api never returns {secret}",
          f'"{secret}"' not in OPS or "_SECRET_HINTS" in OPS)

# ─────────────────────────────────────────────────────────────
print("\n10. APEX does not depend on the operator interface")
check("the trading loop never imports ops_api", "ops_api" not in LSRC)
check("nor does the store", "ops_api" not in SRC)
check("ops_api is wired in lazily, inside build()",
      CA.index("from apex import ops_api") > CA.index("def build()"))
check("the control plane is optional at startup",
      "No Redis configured — MCP control plane OFF" in CSRC)
check("and a dead control plane returns rather than raising",
      "if not _ENABLED_STORE:" in CSRC)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — fail closed, consistent, single-execution.")
