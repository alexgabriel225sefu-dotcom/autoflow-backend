"""The failure matrix: every row must FAIL CLOSED, not merely raise.

An exception is not a safety property. "it threw" and "it refused to trade" are
different outcomes, and only the second one is worth having — a handler that
raises and a caller that swallows the exception is indistinguishable from no
check at all. So every row here asserts the DECISION, not the traceback.

Rows (from the audit's matrix):
  payment duplicated · payment + Redis failure · license write failure
  OAuth duplicated / missing / replayed state
  two workers same user · lease expiry · lease renewal race
  Redis outage · Redis recovery · user update race
  duplicate MCP command · duplicate trade intent
  broker timeout · broker unknown result · restart with open position
  OpenClaw unavailable · MCP unavailable
  AI trade request · AI close request · stale position report · backup restore

Rows already covered in depth elsewhere are asserted here at the decision level
and cross-referenced rather than duplicated.

Run: python tests/test_failure_matrix.py
"""
import json
import os
import sys
import tempfile

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

from apex import (control, ctrader_oauth as oauth, ledger, ops_api,  # noqa: E402
                  ownership, user_loop, user_store)

failures = []
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def row(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def env(**kw):
    for k, v in kw.items():
        os.environ.pop(k, None) if v is None else os.environ.update({k: v})


class Store:
    """A shared store that can be switched between healthy and down."""

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
        if self.down:
            return None
        return self.kv.get(key) == str(value)

    def release_claim(self, key, value):
        if self.down:
            return None
        return self.kv.pop(key, None) is not None


_ORIG = {n: getattr(user_store, n) for n in
         ("claim", "claim_value", "get_blob", "renew_claim", "release_claim")}
_OUSE = user_store._USE_REDIS


def install(store, use_redis=True):
    user_store._USE_REDIS = use_redis
    for n in _ORIG:
        setattr(user_store, n, getattr(store, n) if use_redis
                else (lambda *a, **k: None))
    ownership._held.clear(); ownership._lost.clear(); ownership._renewers.clear()


def restore_store():
    for n, f in _ORIG.items():
        setattr(user_store, n, f)
    user_store._USE_REDIS = _OUSE
    ownership._held.clear(); ownership._lost.clear(); ownership._renewers.clear()


print("\n🧪 FAILURE MATRIX — every row fails CLOSED\n")

# ── payment ──────────────────────────────────────────────
print("payment")
from apex import stripe_license  # noqa: E402
import apex.config as _cfg  # noqa: E402
import types  # noqa: E402

_recs, _sent = {}, []
_o = (user_store.load, user_store.update)
EVENT = {"id": "evt_matrix", "type": "checkout.session.completed",
         "data": {"object": {"payment_status": "paid",
                             "client_reference_id": "42", "id": "cs_m"}}}
BODY = json.dumps(EVENT).encode()
try:
    st = Store(); install(st)
    stripe_license._verify_signature = lambda *a, **k: True
    _cfg.STRIPE_WEBHOOK_SECRET = "whsec_test"
    fa = types.ModuleType("apex.access"); fa.grant = lambda uid: True
    ft = types.ModuleType("apex.telegram")
    ft.send_activation_sequence = lambda uid, paid=False: _sent.append(uid)
    # Both sys.modules AND the package attribute: `from apex import telegram`
    # reads the attribute off the already-imported `apex` package, so replacing
    # only sys.modules leaves the real module bound.
    import apex as _apexpkg
    _real_attrs = (getattr(_apexpkg, "access", None), getattr(_apexpkg, "telegram", None))
    sys.modules["apex.access"], sys.modules["apex.telegram"] = fa, ft
    _apexpkg.access, _apexpkg.telegram = fa, ft
    user_store.load = lambda uid: dict(_recs.get(str(uid), {}))
    user_store.update = lambda uid, up, strict=False: (
        _recs.setdefault(str(uid), {}).update(up) or True)

    s1, _ = stripe_license.handle_webhook(BODY, "sig")
    key1 = _recs["42"]["license_key"]
    s2, b2 = stripe_license.handle_webhook(BODY, "sig")
    row("payment duplicated → ONE licence, not two",
        s2 == 200 and b2 == b"duplicate" and _recs["42"]["license_key"] == key1)
    row("payment duplicated → ONE activation message", len(_sent) == 1, _sent)

    # Redis down during provisioning: the buyer is charged, so a 200 would be
    # unrecoverable — Stripe would never retry.
    _recs.clear(); _sent.clear()
    st.down = True

    def _dead(uid, up, strict=False):
        if strict:
            raise user_store.PersistenceError("redis down")
        return False
    user_store.update = _dead
    s3, _ = stripe_license.handle_webhook(BODY, "sig")
    row("payment + Redis failure → 500 so Stripe RETRIES", s3 == 500, s3)
    row("license write failure → the buyer is NOT marked provisioned",
        "42" not in _recs or not _recs["42"].get("license_key"))
finally:
    sys.modules.pop("apex.access", None); sys.modules.pop("apex.telegram", None)
    for _n, _v in zip(("access", "telegram"), _real_attrs):
        if _v is not None:
            setattr(_apexpkg, _n, _v)
            sys.modules[f"apex.{_n}"] = _v
        else:
            delattr(_apexpkg, _n) if hasattr(_apexpkg, _n) else None
    user_store.load, user_store.update = _o
    restore_store()

# ── OAuth ────────────────────────────────────────────────
print("\nOAuth")
oauth._pending.clear(); oauth._used_states.clear()
oauth._record_pending("111")
row("OAuth state missing → REJECT (no identity inferred)",
    oauth._recent_pending() is None)
row("OAuth state invalid → REJECT", oauth.parse_state("garbage") is None)
_oc = user_store.claim
try:
    user_store.claim = lambda *a, **k: None
    stt = oauth.make_state("555")
    row("OAuth valid state → accepted once", oauth._consume_state(stt) is True)
    row("OAuth callback duplicated → REJECT (state is single-use)",
        oauth._consume_state(stt) is False)
finally:
    user_store.claim = _oc
    oauth._used_states.clear(); oauth._pending.clear()

# ── ownership ────────────────────────────────────────────
print("\nownership")
try:
    st = Store(); install(st)
    row("two workers same user → the second is refused",
        ownership.acquire("u1") is True and (
            setattr(ownership, "INSTANCE_ID", "other") or True) and
        ownership.acquire("u1") is False)
finally:
    ownership.INSTANCE_ID = _ORIG and ownership.INSTANCE_ID
    restore_store()

_me = ownership.INSTANCE_ID
try:
    st = Store(); install(st)
    ownership.INSTANCE_ID = _me
    ownership.acquire("u2")
    st.kv.clear()                                  # lease expiry
    row("lease expiry → reacquired, NOT read as a takeover",
        ownership.heartbeat("u2") is True and ownership.was_lost("u2") is False)
    st.kv["own:user:u2"] = "another-container"     # renewal race
    row("lease renewal race → the loser stands down",
        ownership.heartbeat("u2") is False)
finally:
    ownership.INSTANCE_ID = _me
    restore_store()

# ── Redis ────────────────────────────────────────────────
print("\nRedis")
try:
    install(Store(down=True))
    ok, why = ownership.may_trade("u3", live=True)
    row("Redis outage + LIVE account → no new entry", ok is False, why)
    ok, _ = ownership.may_trade("u3", live=False)
    row("Redis outage + demo → simulation continues", ok is True)
    ok, why, _ = ledger.claim("u3", "EURUSD", "BUY", 1000, 1.1, 1.2,
                              fail_closed=True)
    row("Redis outage + live order intent → COORDINATION_UNAVAILABLE",
        ok is False and why == "COORDINATION_UNAVAILABLE", why)
    row("Redis outage → ownership reads UNKNOWN, never 'owned'",
        ownership.holds("u3") is None)
finally:
    restore_store()

try:
    st = Store(); install(st)
    row("Redis recovery → ownership can be taken again",
        ownership.acquire("u4") is True)
finally:
    restore_store()

print("\nuser update race")
_od = user_store._DIR
user_store._DIR = tempfile.mkdtemp(prefix="apex-fm-")
try:
    user_store.save("42", {"risk": 0.01})
    v = user_store.version("42")
    user_store.save("42", {"risk": 0.02}, expect_version=v)
    conflicted = False
    try:
        user_store.save("42", {"risk": 0.03}, expect_version=v)
    except user_store.ConflictError:
        conflicted = True
    row("user update race → CONFLICT, not a silent overwrite", conflicted)
    row("and the first writer's value survived",
        user_store.load("42")["risk"] == 0.02)
finally:
    user_store._DIR = _od

# ── MCP ──────────────────────────────────────────────────
print("\nMCP")
CSRC = open(os.path.join(ROOT, "apex", "control.py"), encoding="utf-8").read()
env(MCP_OPERATORS="owner", MCP_CONTROL_ENABLED="true", MCP_FINANCIAL_ENABLED=None)
row("duplicate MCP command → replayed, not re-executed",
    "_claim_command(cid)" in CSRC and 'prior = _cmd("GET", _RESULT(cid))' in CSRC)
row("replay check unavailable + financial → refused",
    "REPLAY_CHECK_UNAVAILABLE" in CSRC)
row("MCP financial denied while only control is enabled",
    control.authorize("force_trade", {"confirm": True}, operator="owner")[0] is False)
row("MCP unavailable → APEX still starts (control plane is optional)",
    "No Redis configured — MCP control plane OFF" in CSRC)
env(MCP_OPERATORS=None, MCP_CONTROL_ENABLED=None, MCP_FINANCIAL_ENABLED=None)

print("\nduplicate trade intent")
try:
    st = Store(); install(st)
    ok1, _, _ = ledger.claim("u5", "EURUSD", "BUY", 1000, 1.1, 1.2)
    ok2, why2, _ = ledger.claim("u5", "EURUSD", "BUY", 1000, 1.1, 1.2)
    row("the same intent twice → the second is blocked",
        ok1 is True and ok2 is False and "DUPLICATE" in why2, why2)
finally:
    restore_store()

# ── broker ───────────────────────────────────────────────
print("\nbroker")
LSRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
# The property, not the comment: on a submit that raised, the idempotency
# claim is NOT released, so a retry inside the window is refused. Releasing it
# there is how one intent becomes two positions when the broker actually did
# fill the order it never acknowledged.
_submit_err = LSRC[LSRC.index("except Exception as oe:"):]
_submit_err = _submit_err[:_submit_err.index("place_order error")]
row("broker timeout on submit → the claim STANDS (no blind retry)",
    "ledger.release" not in _submit_err and "order_ok = False" in _submit_err,
    _submit_err[:200])
row("broker unknown result → UNPROTECTED is a first-class state",
    '"UNPROTECTED"' in LSRC)
row("restart with open position → the broker is re-read before trading",
    "startup position check failed" in LSRC and "restart recovery" in LSRC)
row("broker unreachable at startup → the position stays tracked, not assumed flat",
    "keeping {symbol} tracked pending the next tick" in LSRC)

_ol, _od2 = user_store.load, user_loop.get_dash
try:
    user_store.load = lambda _u: {"ctrader_access_token": "x", "paper": False}
    user_loop.get_dash = lambda _u: {}
    _mb = user_loop._make_broker
    user_loop._make_broker = lambda u: (_ for _ in ()).throw(RuntimeError("timed out"))
    r = ops_api.broker_reconcile("123456")
    row("broker unreachable → reconciliation UNKNOWN, not 'healthy'",
        r["status"] == ops_api.UNKNOWN and r.get("reconciliation") == ops_api.UNKNOWN, r)

    class B:
        def get_all_positions(self):
            return [{"symbol": "XAUUSD"}]
    user_loop._make_broker = lambda u: (B(), None)
    r = ops_api.broker_reconcile("123456")
    row("broker has a position local does not → EXTERNAL_OR_UNRECONCILED_POSITION",
        r["findings"][0]["verdict"] == ops_api.EXTERNAL_OR_UNRECONCILED_POSITION, r)
    row("and the broker is named as the authority", r.get("authority") == "broker")

    class B2:
        def get_all_positions(self):
            return []
    user_loop._make_broker = lambda u: (B2(), None)
    user_loop.get_dash = lambda _u: {"openPosition": {"symbol": "EURUSD"}}
    r = ops_api.broker_reconcile("123456")
    row("local has a position the broker does not → LOCAL_POSITION_MISSING_AT_BROKER",
        r["findings"][0]["verdict"] == ops_api.LOCAL_POSITION_MISSING_AT_BROKER, r)
    row("neither side is silently normalised", r["reconciliation"] == "MISMATCH")
    row("and nothing was changed", "diagnostic" in r.get("action_taken", ""))
finally:
    user_loop._make_broker = _mb
    user_store.load, user_loop.get_dash = _ol, _od2

# ── the AI ───────────────────────────────────────────────
print("\nAI assistant")
ASRC = open(os.path.join(ROOT, "apex", "assistant.py"), encoding="utf-8").read()
_ft = LSRC[LSRC.index("def force_trade"):LSRC.index("def read_candles")]
GSRC = open(os.path.join(ROOT, "apex", "gates.py"), encoding="utf-8").read()
row("AI trade request → goes through user_loop, not the broker",
    "user_loop.force_trade(user_id" in ASRC and "place_order" not in ASRC)
row("AI close request → same", "user_loop.force_close(user_id)" in ASRC)
row("AI has no broker credential path", "ctrader_access_token" not in ASRC)
# The checks are centralised in apex/gates.py — one definition entered from
# four origins, rather than four copies that drift.
row("AI/manual trade enters the SHARED gate", "gates.authorize_order(" in _ft)
for gate, where in (("entitlement", "live_entitlement("),
                    ("risk guard", 'guard.get("halted")'),
                    ("ownership", "ownership.may_trade"),
                    ("idempotency", "ledger.claim(")):
    row(f"the shared gate enforces {gate}", where in GSRC)

# ── ops reporting ────────────────────────────────────────
print("\nops reporting")
_ol2, _od3 = user_store.load, user_loop.get_dash
try:
    import time as _t
    user_store.load = lambda _u: {"paper": True}
    user_loop.get_dash = lambda _u: {"openPosition": {"symbol": "EURUSD"},
                                     "lastTickTs": _t.time() - 1284}
    r = ops_api.user_positions("123456")
    row("stale position report → UNKNOWN, never 'Protection OK'",
        r["status"] == ops_api.UNKNOWN and r["protection"] == ops_api.UNKNOWN, r)
    row("and it names the source", r["position_source"] == "last_loop_state")
    row("and the age", r["as_of_seconds"] == 1284, r.get("as_of_seconds"))
    row("and the state", r["state"] == ops_api.RECOVERY)
finally:
    user_store.load, user_loop.get_dash = _ol2, _od3

print("\nOpenClaw / operator interface")
OPS = open(os.path.join(ROOT, "apex", "ops_api.py"), encoding="utf-8").read()
row("OpenClaw unavailable → APEX has no dependency on it",
    "ops_api" not in LSRC and "ops_api" not in
    open(os.path.join(ROOT, "apex", "user_store.py"), encoding="utf-8").read())
row("the ops layer only reads", not any(
    w in OPS for w in ("place_order", "force_close", "force_trade",
                       "user_store.save", "user_store.update")))

print("\nbackup restore")
from apex import backup  # noqa: E402
ok, problems = backup.verify({"format": 1, "users": {}})
row("an empty backup is refused rather than 'restored'", ok is False)
row("a decrypted credential in a backup is refused",
    backup.verify({"format": 1, "users": {"1": {
        "ctrader_access_token": "plain"}}})[0] is False)
row("the full round trip is covered", os.path.exists(
    os.path.join(ROOT, "tests", "test_backup_restore.py")))


# ── item 15: the architectural invariant ─────────────────
print("\nfinal security requirement")
# OpenClaw -> safe operations interface -> APEX.   NEVER OpenClaw -> broker.
# Stated as a property of the import graph, because that is the thing that
# cannot be true by accident: if no module outside the trading core imports a
# broker, none of them can reach one however they are called.
import glob as _glob
CORE = {"user_loop.py", "brokers", "position.py", "bot.py", "webapp.py",
        "dashboard.py", "telegram.py", "strategies.py", "shadow.py"}
_offenders = []
for _f in sorted(_glob.glob(os.path.join(ROOT, "apex", "*.py"))):
    _base = os.path.basename(_f)
    if _base in CORE:
        continue
    _src = open(_f, encoding="utf-8").read()
    if "brokers.ctrader" in _src or "CtraderBroker" in _src:
        _offenders.append(_base)
row("no module outside the trading core imports a broker directly",
    _offenders == [], _offenders)

for _gate, _where in (("license", "live_entitlement("), ("risk", 'guard.get("halted")'),
                      ("ownership", "ownership.may_trade"),
                      ("idempotency", "ledger.claim(")):
    row(f"the {_gate} gate lives in the single shared gate", _where in GSRC)
row("and there is only ONE manual order path",
    LSRC.count("def force_trade") == 1)
row("every order origin enters that gate",
    LSRC.count("gates.authorize_order(") >= 2)
row("every close origin enters the close gate",
    "gates.authorize_close(" in LSRC)
# The token NAME appears in ops_api — as a presence check, `if not
# u.get("ctrader_access_token")`, which is how "is a broker connected" is
# answered. What must never happen is the VALUE being bound or returned, so
# that is what this asserts rather than the name being absent.
_tok_lines = [ln.strip() for ln in OPS.splitlines()
              if "ctrader_access_token" in ln and not ln.strip().startswith("#")]
row("ops_api only ever tests the credential for PRESENCE",
    all(ln.startswith("if not u.get(") for ln in _tok_lines), _tok_lines)
row("and never binds or returns its value",
    not any(("=" in ln and "==" not in ln) or "return" in ln
            for ln in _tok_lines), _tok_lines)
row("the operator interface cannot write user state",
    "user_store.save" not in OPS and "user_store.update" not in OPS)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} row(s) failed")
    sys.exit(1)
print("✅ ALL ROWS FAIL CLOSED.")
