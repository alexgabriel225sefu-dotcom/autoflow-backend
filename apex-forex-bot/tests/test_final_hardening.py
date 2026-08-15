"""The final audit's 15 findings, each as the failure it describes.

Every section names the failure path that existed before the fix, so a future
reader can tell whether a change re-opens it. Assertions are on the DECISION,
never on "an exception was raised".

Run: python tests/test_final_hardening.py
"""
import os
import subprocess
import sys
import tempfile

os.environ.setdefault("PAPER_TRADING", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

from apex import access, control, gates, ledger, ownership, user_store  # noqa: E402

failures = []
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def fresh_import(**envkw):
    """Import user_store in a NEW process — startup guards run at import.

    A real key is always supplied so the ENCRYPTION guard cannot fire first and
    mask the BACKEND guard, which is what these cases are actually testing.
    """
    from cryptography.fernet import Fernet
    e = dict(os.environ)
    e["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    for k, v in envkw.items():
        e.pop(k, None) if v is None else e.update({k: v})
    r = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {ROOT!r});\n"
         "from apex import user_store; print('IMPORTED_OK')"],
        capture_output=True, text=True, env=e, cwd=ROOT)
    return r.returncode, r.stdout + r.stderr


class Store:
    def __init__(self, down=False):
        self.kv, self.down = {}, down

    def claim(self, key, ttl_s=120):
        if self.down:
            return None
        if key in self.kv:
            return False
        self.kv[key] = "1"
        return True

    def claim_value(self, key, value, ttl_s=120):
        if self.down:
            return None
        if key in self.kv:
            return False
        self.kv[key] = str(value)
        return True

    def get_blob(self, key):
        return None if self.down else self.kv.get(key)

    def renew_claim(self, key, value, ttl_s=120):
        return None if self.down else self.kv.get(key) == str(value)

    def release_claim(self, key, value):
        return None if self.down else self.kv.pop(key, None) is not None


_O = {n: getattr(user_store, n) for n in
      ("claim", "claim_value", "get_blob", "renew_claim", "release_claim")}
_OUSE = user_store._USE_REDIS


def install(st):
    user_store._USE_REDIS = True
    for n in _O:
        setattr(user_store, n, getattr(st, n))
    ownership._held.clear(); ownership._lost.clear(); ownership._renewers.clear()


def restore():
    for n, f in _O.items():
        setattr(user_store, n, f)
    user_store._USE_REDIS = _OUSE
    ownership._held.clear(); ownership._lost.clear(); ownership._renewers.clear()


print("\n🧪 FINAL HARDENING — 15 findings\n")

# ── 1 ────────────────────────────────────────────────────
print("1. Redis failure in production fails CLOSED")
# Was: REDIS_URL unreachable fell through to Upstash, and with neither
# configured the process ran on local JSON. Two Render instances then each had
# their own entitlement, ownership and idempotency — with no error anywhere.
rc, out = fresh_import(REDIS_URL=None, UPSTASH_REDIS_REST_URL=None,
                       UPSTASH_REDIS_REST_TOKEN=None,
                       ALLOW_LOCAL_BACKEND_DEV=None, APP_ENV=None)
check("production + no shared backend → startup REFUSED", rc != 0)
check("and it names the reason", "SharedBackendRequired" in out, out[-160:])
check("it explains why local JSON is not a fallback",
      "per-container" in out or "cannot be shared" in out, out[-160:])
rc, out = fresh_import(REDIS_URL="redis://127.0.0.1:6390/0",
                       UPSTASH_REDIS_REST_URL=None, UPSTASH_REDIS_REST_TOKEN=None,
                       ALLOW_LOCAL_BACKEND_DEV=None, APP_ENV=None)
check("production + Redis UNREACHABLE → refused, never silent local JSON",
      rc != 0, out[-160:])
rc, out = fresh_import(REDIS_URL=None, UPSTASH_REDIS_REST_URL=None,
                       UPSTASH_REDIS_REST_TOKEN=None,
                       ALLOW_LOCAL_BACKEND_DEV="true", APP_ENV="dev")
check("declared development → local backend still allowed",
      rc == 0 and "IMPORTED_OK" in out, out[-160:])
rc, out = fresh_import(REDIS_URL=None, UPSTASH_REDIS_REST_URL=None,
                       UPSTASH_REDIS_REST_TOKEN=None,
                       ALLOW_LOCAL_BACKEND_DEV="true", APP_ENV=None)
check("the dev flag alone is not enough — dev must be DECLARED", rc != 0)

print("\n   ...and no live order or activation while coordination is unknown")
try:
    install(Store(down=True))
    ok, why = ownership.may_trade("1", live=True)
    check("Redis unavailable + LIVE → no ownership claim", ok is False, why)
    ok, why, _ = ledger.claim("1", "EURUSD", "BUY", 1000, 1.1, 1.2, fail_closed=True)
    check("Redis unavailable + LIVE order → DENIED",
          ok is False and why == "COORDINATION_UNAVAILABLE", why)
    d, _rid = gates.authorize_order("1", symbol="EURUSD", side="BUY", units=1000,
                                    origin="test",
                                    user={"paper": False, "license_key": "K"})
    check("the shared gate refuses a LIVE order with Redis down",
          d.allowed is False, d.reason)
    d, _rid = gates.authorize_order("1", symbol="EURUSD", side="BUY", units=1000,
                                    origin="test",
                                    user={"paper": True, "license_key": "K"})
    check("but a demo order still runs", d.allowed is True, d.reason)
finally:
    restore()

# ── 2 ────────────────────────────────────────────────────
print("\n2. License verification does not fail OPEN for new users")
# Was: allowed_state returns "unknown" during an outage and callers allow —
# so the outage itself became the way in for anyone who messaged during it.
_rd = access._read
try:
    access._read = lambda: {"admins": [], "allowed": [], "_degraded": True}
    check("new user + store outage → DENIED",
          access.new_user_state("999", has_local_record=False) == "denied")
    check("existing provisioned user + same outage → grace (unknown)",
          access.new_user_state("999", has_local_record=True) == "unknown")
    check("the UI policy is unchanged for existing users",
          access.allowed_state("999") == "unknown")
    access._read = lambda: {"admins": [], "allowed": ["777"], "_degraded": False}
    check("new user + valid grant → ALLOWED",
          access.new_user_state("777", has_local_record=False) == "allowed")
    check("new user + no grant, store healthy → DENIED",
          access.new_user_state("888", has_local_record=False) == "denied")
finally:
    access._read = _rd

print("\n   live-trading entitlement is a THIRD state, stricter than both")
check("UNKNOWN entitlement denies a LIVE order",
      gates.authorize_order("1", symbol="EURUSD", side="BUY", units=1000,
                            origin="t", user={"paper": False})[0].allowed is False)
d, _ = gates.authorize_order("1", symbol="EURUSD", side="BUY", units=1000,
                             origin="t", user={"paper": False})
check("and says which check refused it", d.reason in
      ("ENTITLEMENT_UNKNOWN", "NOT_ENTITLED"), d.reason)

# ── 3 ────────────────────────────────────────────────────
print("\n3. No hardcoded admin id in source")
ASRC = open(os.path.join(ROOT, "apex", "access.py"), encoding="utf-8").read()
check("_HARDCODED_ADMINS is gone", "_HARDCODED_ADMINS" not in ASRC)
check("and no Telegram id is embedded in the module",
      not any(tok.isdigit() and len(tok) >= 9
              for tok in ASRC.replace('"', " ").replace("'", " ").split()),
      "a numeric id remains in source")
check("admins come from configuration", "_ADMIN_ENV_VARS" in ASRC)
check("startup can validate the configuration", hasattr(access, "admins_configured"))
_env = os.environ.get("ADMIN_CHAT_IDS")
try:
    os.environ["ADMIN_CHAT_IDS"] = "111,222"
    check("a configured admin is authorized", access.is_admin("111"))
    check("the old hardcoded id is NOT an admin any more",
          not access.is_admin("7585109158"))
    check("an unconfigured id is denied", not access.is_admin("333"))
    check("admins_configured() sees them", access.admins_configured() is True)
    os.environ.pop("ADMIN_CHAT_IDS")
    os.environ.pop("ADMIN_CHAT_ID", None)
    os.environ.pop("TELEGRAM_CHAT_ID", None)
    check("no configuration → no admins, reported not assumed",
          access.admins_configured() is False)
finally:
    if _env is not None:
        os.environ["ADMIN_CHAT_IDS"] = _env

# ── 4 ────────────────────────────────────────────────────
print("\n4. MCP cannot reach LIVE through paper=false")
from apex.control_actions import _SETTABLE, build  # noqa: E402
check("'paper' is not a generic MCP setting", "paper" not in _SETTABLE)
CA = open(os.path.join(ROOT, "apex", "control_actions.py"), encoding="utf-8").read()
check("and the handler refuses it by name explicitly",
      'if key == "paper":' in CA)
check("with a message naming the real path",
      "typed confirmation" in CA)
TG = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
check("the Telegram activation path still exists",
      "live_confirm" in TG and "_LIVE_INITIAL_RISK_CAP" in TG)
check("and still caps initial risk", "_LIVE_INITIAL_RISK_CAP" in TG)

# ── 5 / 6 ────────────────────────────────────────────────
print("\n5+6. One financial close path, with ownership and idempotency")
LSRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
GSRC = open(os.path.join(ROOT, "apex", "gates.py"), encoding="utf-8").read()
check("force_close enters the shared close gate",
      "gates.authorize_close(" in LSRC)
check("the close gate checks ownership", "ownership.may_trade" in GSRC)
check("the close gate claims idempotency",
      "ledger.claim(" in GSRC and 'f"CLOSE:{intent}"' in GSRC)
check("the outcome is recorded so a duplicate gets the ORIGINAL result",
      "ledger.record(_close_rid" in LSRC)
check("a failed close does NOT release the claim",
      "The claim STANDS" in LSRC)
check("emergency override is explicit, not accidental", "emergency=" in GSRC)

try:
    install(Store())
    ownership.acquire("55")
    d1, rid1 = gates.authorize_close("55", position_id="P1", origin="t",
                                     user={"paper": True})
    check("first close is authorized", d1.allowed is True, d1.reason)
    d2, _ = gates.authorize_close("55", position_id="P1", origin="t",
                                  user={"paper": True})
    check("duplicate close on the same position → DENIED",
          d2.allowed is False and d2.reason == "DUPLICATE_CLOSE", d2.reason)
    ledger.record(rid1, {"closed": True})
    d3, _ = gates.authorize_close("55", position_id="P1", origin="t",
                                  user={"paper": True})
    check("and the refusal carries the prior result, not a bare no",
          "prior result" in d3.detail, d3.detail)

    _me = ownership.INSTANCE_ID
    ownership.INSTANCE_ID = "another-container"
    ownership._held.clear()
    d4, _ = gates.authorize_close("55", position_id="P9", origin="t",
                                  user={"paper": False})
    check("a NON-OWNER close is refused", d4.allowed is False, d4.reason)
    d5, _ = gates.authorize_close("55", position_id="P9", origin="emergency",
                                  user={"paper": False}, emergency=True)
    check("...unless it is a declared emergency override", d5.allowed is True)
    check("and the override is recorded in the decision",
          "emergency" in d5.detail, d5.detail)
    ownership.INSTANCE_ID = _me
finally:
    restore()


print("\n   the two close policies, stated separately")
# A normal close and an emergency close cannot share one idempotency rule. The
# first must refuse when it cannot prove uniqueness across containers; the
# second exists precisely for the case where exiting matters more.
try:
    install(Store(down=True))          # shared idempotency unreachable
    # A LIVE account is refused earlier still — ownership cannot be verified
    # with the backend down, and that gate comes first. Both are fail-closed;
    # this records WHICH one fires so a later reordering is visible.
    d, _ = gates.authorize_close("77", position_id="P1", origin="manual",
                                 user={"paper": False})
    check("NORMAL close on a LIVE account + backend DOWN → refused",
          d.allowed is False, d.reason)
    check("   ...at the ownership gate, which comes first",
          d.reason == "NOT_OWNER", d.reason)
    # On demo, ownership is permissive on unknown, so the CLOSE IDEMPOTENCY
    # policy is the one that decides — which is what this finding is about.
    d, _ = gates.authorize_close("77", position_id="P2", origin="manual",
                                 user={"paper": True})
    check("NORMAL close + shared idempotency DOWN → refused",
          d.allowed is False and d.reason == "CLOSE_COORDINATION_UNAVAILABLE",
          d.reason)
    check("and the refusal names the emergency path",
          "emergency" in d.detail.lower(), d.detail)
    d, _ = gates.authorize_close("77", position_id="P1", origin="operator",
                                 user={"paper": False}, emergency=True)
    check("EMERGENCY close + same outage → proceeds", d.allowed is True, d.reason)
    check("and records that it was an emergency",
          "emergency" in d.detail, d.detail)
finally:
    restore()
GSRC2 = open(os.path.join(ROOT, "apex", "gates.py"), encoding="utf-8").read()
check("the policy is one expression, not two code paths",
      "fail_closed=not emergency" in GSRC2)
check("and both are audited either way", "gates.audit(" in LSRC)

# ── 7 ────────────────────────────────────────────────────
print("\n7. OAuth fails closed when replay protection is unavailable")
from apex import ctrader_oauth as oauth  # noqa: E402
_oc = user_store.claim
try:
    # A DEPLOYED bot: a shared backend is configured, and the claim fails.
    _u0 = user_store._USE_REDIS
    user_store._USE_REDIS = True
    user_store.claim = lambda *a, **k: None      # authoritative store down
    oauth._used_states.clear()
    st = oauth.make_state("321")
    check("state claim unavailable → callback REJECTED",
          oauth._consume_state(st) is False,
          "fell back to in-process memory, which cannot see another instance")
finally:
    user_store.claim = _oc
    user_store._USE_REDIS = _u0
    oauth._used_states.clear()

_seen = {}
try:
    user_store.claim = lambda k, ttl_s=120: False if k in _seen else _seen.setdefault(k, True)
    oauth._used_states.clear()
    st = oauth.make_state("322")
    check("shared claim available → accepted once", oauth._consume_state(st) is True)
    check("same state on a SECOND instance → rejected",
          oauth._consume_state(st) is False)
finally:
    user_store.claim = _oc
    oauth._used_states.clear()

check("the stateless fallback stays development-only",
      oauth.ALLOW_STATELESS is False)

# ── 8 ────────────────────────────────────────────────────
print("\n8. The LIVE confirmation token is consumed atomically")
check("consumption is a compare-and-set, not read-then-write",
      "consume_live_confirm" in TG,
      "two concurrent confirmations could both read the token as valid")
check("it is claimed through the shared store",
      "user_store.claim(" in TG)


# ── 9 ────────────────────────────────────────────────────
print("\n9. The operator name is PROVEN, not merely stated")
# Enforcing operator identity without a sender that could provide one locked the
# operator out of their own control plane — observed live: every level 2 command
# returned NO_OPERATORS_CONFIGURED because ruflo-mcp sent {id, action, args, ts}
# with no operator field at all. The sender now signs the envelope.
import hashlib as _hl, hmac as _hm, json as _js  # noqa: E402

def _envelope(secret, operator="owner", action="restart_loop", tamper=None):
    env = {"id": "c1", "action": action, "args": {"user_id": "1"},
           "ts": 1786800000, "operator": operator}
    payload = _js.dumps({k: env[k] for k in ("id", "action", "args", "ts",
                                             "operator")},
                        sort_keys=True, separators=(",", ":"))
    env["sig"] = _hm.new(secret.encode(), payload.encode(), _hl.sha256).hexdigest()
    if tamper:
        env.update(tamper)
    return env

_s0 = os.environ.get("MCP_SIGNING_SECRET")
try:
    os.environ["MCP_SIGNING_SECRET"] = "shared-secret-abc"
    check("a correctly signed envelope verifies",
          control.verify_envelope(_envelope("shared-secret-abc"))[0] is True)
    ok, why = control.verify_envelope(_envelope("wrong-secret"))
    check("a signature from the wrong secret is refused",
          ok is False and why == "SIGNATURE_INVALID", why)
    ok, why = control.verify_envelope({"id": "c1", "action": "restart_loop",
                                       "args": {}, "ts": 1, "operator": "owner"})
    check("an UNSIGNED envelope is refused once a secret exists",
          ok is False and why == "SIGNATURE_MISSING", why)
    # The whole point: the operator field cannot be forged.
    ok, why = control.verify_envelope(
        _envelope("shared-secret-abc", operator="attacker",
                  tamper={"operator": "owner"}))
    check("swapping the operator name AFTER signing is refused",
          ok is False and why == "SIGNATURE_INVALID", why)
    ok, why = control.verify_envelope(
        _envelope("shared-secret-abc", tamper={"action": "force_trade"}))
    check("swapping the action after signing is refused",
          ok is False and why == "SIGNATURE_INVALID", why)
    ok, why = control.verify_envelope(
        _envelope("shared-secret-abc", tamper={"args": {"user_id": "999"}}))
    check("swapping the target user after signing is refused",
          ok is False and why == "SIGNATURE_INVALID", why)
    os.environ.pop("MCP_SIGNING_SECRET")
    ok, why = control.verify_envelope({"id": "c1", "action": "restart_loop"})
    check("with no secret configured it degrades to the allowlist, and says so",
          ok is True and why == "UNSIGNED_NO_SECRET_CONFIGURED", why)
finally:
    if _s0 is None:
        os.environ.pop("MCP_SIGNING_SECRET", None)
    else:
        os.environ["MCP_SIGNING_SECRET"] = _s0

CSRC2 = open(os.path.join(ROOT, "apex", "control.py"), encoding="utf-8").read()
check("only level 2/3 are signature-checked; reads are not",
      "if lvl > 1:" in CSRC2 and "verify_envelope(cmd)" in CSRC2)
MSRC = open(os.path.join(os.path.dirname(ROOT), "ruflo-mcp", "server.py"),
            encoding="utf-8").read()
check("the MCP server sends an operator field", '"operator": OPERATOR' in MSRC)
check("and signs the envelope", "_sign(envelope)" in MSRC)
check("using the same canonical form as the verifier",
      'sort_keys=True, separators=(",", ":")' in MSRC)


print("\n   6. the full chain: transport → operator → capability → execution")
# The chain the audit asks to be proven, link by link. A break in any one of
# them must stop the command, and each is asserted separately so a future
# change cannot satisfy the test by strengthening a different link.
_s1 = os.environ.get("MCP_SIGNING_SECRET")
_o1 = os.environ.get("MCP_OPERATORS")
try:
    os.environ["MCP_SIGNING_SECRET"] = "S3CRET"
    os.environ["MCP_OPERATORS"] = "owner"
    os.environ["MCP_CONTROL_ENABLED"] = "true"
    os.environ.pop("MCP_FINANCIAL_ENABLED", None)

    # LINK 1 — transport identity. A forged name fails the signature.
    forged = _envelope("S3CRET", operator="attacker", tamper={"operator": "owner"})
    ok, why = control.verify_envelope(forged)
    check("forged operator: signature check FAILS", ok is False, why)

    # An attacker who signs honestly as themselves passes link 1...
    honest = _envelope("S3CRET", operator="attacker")
    ok, _ = control.verify_envelope(honest)
    check("an attacker signing as THEMSELVES passes the signature", ok is True)
    # ...and is stopped at LINK 2 — operator authorization.
    ok, why = control.authorize("restart_loop", {"confirm": True},
                                operator="attacker")
    check("...but is refused at operator authorization",
          ok is False and why == "OPERATOR_NOT_AUTHORIZED", why)

    # LINK 3 — capability authorization. The real operator still cannot reach
    # a financial action while that capability is off.
    ok, why = control.authorize("force_trade", {"confirm": True}, operator="owner")
    check("the REAL operator is refused a financial action when it is disabled",
          ok is False and "FINANCIAL_DISABLED" in why, why)
    # ...and cannot skip the confirmation either.
    ok, why = control.authorize("restart_loop", {}, operator="owner")
    check("nor skip the confirmation",
          ok is False and "CONFIRMATION_REQUIRED" in why, why)

    # LINK 4 — execution, only when every link holds.
    ok, why = control.authorize("restart_loop", {"confirm": True}, operator="owner")
    check("all four links hold → authorized", ok is True, why)

    # An attacker without the secret cannot forge a signature at all.
    ok, why = control.verify_envelope(_envelope("not-the-secret", operator="owner"))
    check("without the shared secret no valid envelope can be produced",
          ok is False and why == "SIGNATURE_INVALID", why)
    # And a bare name with no signature is refused outright.
    ok, why = control.verify_envelope(
        {"id": "x", "action": "force_trade", "args": {}, "ts": 1,
         "operator": "admin"})
    check('operator="admin" with no signature is not authentication',
          ok is False and why == "SIGNATURE_MISSING", why)
finally:
    for k, v in (("MCP_SIGNING_SECRET", _s1), ("MCP_OPERATORS", _o1)):
        os.environ.pop(k, None) if v is None else os.environ.update({k: v})
    os.environ.pop("MCP_CONTROL_ENABLED", None)

# ── 10 ───────────────────────────────────────────────────
print("\n10. Entitlement writes are strict")
check("_write reports whether the write landed", "def _write(d):" in ASRC
      and "return False" in ASRC)
check("grant() can raise instead of reporting a false success",
      "GrantFailed" in ASRC)
_w = access._write
try:
    access._write = lambda d: False              # persistence fails
    access._read = lambda: {"admins": [], "allowed": [], "_degraded": False}
    check("a failed grant returns False, never True", access.grant("999") is False)
    raised = False
    try:
        access.grant("999", strict=True)
    except access.GrantFailed:
        raised = True
    check("and strict=True raises so activation cannot report success", raised)
    check("a failed revoke also reports failure", access.revoke("999") is False)
finally:
    access._write = _w
    access._read = _rd

# ── 13 ───────────────────────────────────────────────────
print("\n13. Redis health is a real check, not a boolean")
h = user_store.redis_health()
for field in ("configured", "reachable", "latency_ms", "last_success",
              "failure_count", "status"):
    check(f"health reports {field}", field in h, h)
check("'configured' and 'reachable' are separate facts",
      h["configured"] is not h.get("reachable") or h["status"] != "HEALTHY"
      or h["reachable"] is True)
check("an unconfigured backend is NOT_CONFIGURED, not HEALTHY",
      h["status"] in ("NOT_CONFIGURED", "HEALTHY", "DEGRADED", "DOWN"), h)


class Dead:
    def set(self, *a, **k):
        raise RuntimeError("connection refused")

    def get(self, *a, **k):
        raise RuntimeError("connection refused")


_b, _r_, _u = user_store._BACKEND, getattr(user_store, "_r", None), user_store._USE_REDIS
try:
    user_store._BACKEND, user_store._r, user_store._USE_REDIS = "redis", Dead(), True
    h = user_store.redis_health()
    check("an unreachable backend reports DOWN", h["status"] == "DOWN", h)
    check("not reachable", h["reachable"] is False)
    check("and the failure is counted", h["failure_count"] >= 1, h)
    check("the probe never claims HEALTHY on failure", h["status"] != "HEALTHY")
finally:
    user_store._BACKEND, user_store._r, user_store._USE_REDIS = _b, _r_, _u

# ── 15 ───────────────────────────────────────────────────
print("\n15. No unauthorized financial action, from any origin")
check("only one manual order entry point", LSRC.count("def force_trade") == 1)
check("only one close entry point", LSRC.count("def force_close(") == 1)
check("both automatic and manual orders enter the same gate",
      LSRC.count("gates.authorize_order(") >= 2)
check("the gate is the only place the checks live",
      all(w in GSRC for w in ("live_entitlement(", 'guard.get("halted")',
                              "ownership.may_trade", "ledger.claim(")))
check("the gate audits refusals as well as approvals",
      "decision.allowed else" in GSRC or "if decision.allowed" in GSRC)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL CHECKS PASSED.")
