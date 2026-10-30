"""The hard gate in front of live trading.

Each condition is closed on its own, with the others satisfied. A failed read
is unknown and closed. An existing founder licence is not the confirmed
payment record. Secrets in a store error do not reach the client.

Run: python3 tests/test_platform_live_gate.py
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-livegate-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("A4T_EMERGENCY_HALT", None)
for _banned in ("A4T_LIVE_EXECUTION", "APEX_ALLOW_LIVE_ACCOUNTS",
                "A4T_LIVE_PILOT_PAIRS", "A4T_LIVE_PILOT_SYMBOLS",
                "A4T_LIVE_PILOT_MAX_UNITS", "PAPER_TRADING"):
    os.environ.pop(_banned, None)

from apex import user_store                              # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


class Fake:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}

    def install(self):
        user_store._USE_REDIS = True
        user_store._BACKEND = "redis"
        for name in ("set_blob_nx", "set_blob", "get_blob", "get_blob_strict",
                     "del_blob", "claim", "claim_value", "release_claim", "incr"):
            setattr(user_store, name, getattr(self, name))

    def set_blob_nx(self, key, value):
        with self.lock:
            if key in self.data:
                return False
            self.data[key] = value
            return True

    def set_blob(self, key, value, ttl_s=None):
        with self.lock:
            self.data[key] = value
        return True

    def get_blob(self, key):
        with self.lock:
            return self.data.get(key)

    def get_blob_strict(self, key):
        return self.get_blob(key)

    def del_blob(self, key):
        with self.lock:
            return self.data.pop(key, None)

    def claim(self, key, ttl_s=120):
        return self.claim_value(key, "1", ttl_s=ttl_s)

    def claim_value(self, key, value, ttl_s=120):
        with self.lock:
            if key in self.data:
                return False
            self.data[key] = str(value)
            return True

    def release_claim(self, key, value):
        with self.lock:
            if self.data.get(key) != str(value):
                return False
            del self.data[key]
        return True

    def incr(self, key, ttl_s=60):
        with self.lock:
            self.data[key] = int(self.data.get(key, 0)) + 1
            return self.data[key]


Fake().install()

from apex.platform import billing as B                  # noqa: E402
from apex.platform import ctrader_link as CL             # noqa: E402
from apex.platform import entitlement as E               # noqa: E402
from apex.platform import licence as L                   # noqa: E402
from apex.platform import live_execution as LX           # noqa: E402
from apex.platform import live_gate as LG                # noqa: E402
from apex.platform import plans as P                     # noqa: E402
from apex.platform import store as ST                    # noqa: E402

ACTOR = "operator-1"
CLIENT = "client-1"
FRESH = "fresh-user-1"


def codes(verdict):
    return [item["code"] for item in verdict["missing"]]


def satisfy(user):
    for doc in LG.DOCUMENTS:
        LG.publish(doc, "v1", actor=ACTOR)
    LG.accept_current(user)
    LG.grant_operator_licence(user, actor=ACTOR)
    LG.request_live(user)
    LG.decide(user, "approved", actor=ACTOR, reason="reviewed")


def verdict(user, *, switch=True, accounts=True):
    return LG.public_verdict(
        user, release_switch=switch, live_accounts_allowed=accounts)


print("\n[1] the price is the approved offer, and checkout still cannot charge")
check("49700 cents", LG.PRICE_MINOR == B.APPROVED_PRICE_MINOR == 49700,
      str(LG.PRICE_MINOR))
check("usd", LG.CURRENCY == B.APPROVED_CURRENCY == "usd")
check("founder lifetime plan", LG.PLAN == B.APPROVED_PLAN == "founder_lifetime")
check("checkout is not implemented", B.checkout_implemented() is False)
check("the offer says so", B.public_offer()["checkoutImplemented"] is False)

print("\n[2] default closed, with the real switches, nothing set")
check("the release switch is off", E.live_execution_enabled() is False)
base = LG.public_verdict(
    FRESH,
    release_switch=E.live_execution_enabled(),
    live_accounts_allowed=CL.live_allowed())
check("not open", base["open"] is False and base["status"] == "closed",
      json.dumps(base)[:240])
check("the switch is a known miss, not an unknown",
      "RELEASE_SWITCH" in codes(base) and "LIVE_ACCOUNTS" in codes(base),
      str(codes(base)))

print("\n[3] an existing founder licence is not the confirmed record")
OLD = "existing-client-1"
L.grant(OLD, plan=P.FOUNDER_LIVE, expires_at=None)
held = L.status_for(OLD)
check("the old licence is on file",
      held["state"] == L.ACTIVE and held["plan"] == P.FOUNDER_LIVE, str(held))
old = verdict(OLD)
check("and it still does not open the gate", old["open"] is False, str(codes(old)))
check("the paid record is what is missing", "PAID_LICENCE" in codes(old),
      str(codes(old)))

print("\n[4] each condition blocks on its own")
USER = "gate-user-1"
satisfy(USER)
opened = verdict(USER)
check("all satisfied is open", opened["open"] is True and opened["status"] == "open",
      str(codes(opened)))
check("the open sentence does not say live trading is available",
      "live trading is available" not in opened["summary"].lower(),
      opened["summary"])

alone = verdict(USER, switch=False)
check("the switch blocks alone",
      alone["open"] is False and codes(alone) == ["RELEASE_SWITCH"],
      str(codes(alone)))
alone = verdict(USER, accounts=False)
check("live accounts block alone",
      alone["open"] is False and codes(alone) == ["LIVE_ACCOUNTS"],
      str(codes(alone)))

published = ST._read_strict(LG._key("published"))
ST._write_strict(LG._key("published"),
                 {k: v for k, v in published.items() if k != "terms"})
alone = verdict(USER)
check("unpublished legal terms block",
      alone["open"] is False and "LEGAL_TERMS" in codes(alone)
      and "PAID_LICENCE" not in codes(alone), str(codes(alone)))
LG.publish("terms", "v1", actor=ACTOR)
alone = verdict(USER)
check("republishing the accepted version clears that block",
      alone["open"] is True, str(codes(alone)))

LG.publish("refund", "v2", actor=ACTOR)
alone = verdict(USER)
check("a stale acceptance blocks alone",
      alone["open"] is False and codes(alone) == ["REFUND_TERMS_ACCEPTED"],
      str(codes(alone)))
LG.accept_current(USER)
check("accepting the current versions opens it again",
      verdict(USER)["open"] is True, str(codes(verdict(USER))))

ST._delete(LG._key(f"paid:{USER}"))
check("the founder plan is still granted",
      L.status_for(USER)["plan"] == P.FOUNDER_LIVE)
alone = verdict(USER)
check("without the paid record the gate is closed",
      alone["open"] is False and codes(alone) == ["PAID_LICENCE"],
      str(codes(alone)))
LG.grant_operator_licence(USER, actor=ACTOR)

ST._delete(LG._key(f"request:{USER}"))
alone = verdict(USER)
check("no request blocks alone",
      alone["open"] is False and codes(alone) == ["OPERATOR_APPROVAL"],
      str(codes(alone)))
LG.request_live(USER)
alone = verdict(USER)
check("a pending request blocks alone",
      alone["open"] is False and codes(alone) == ["OPERATOR_APPROVAL"]
      and "not approved" in alone["missing"][0]["detail"],
      str(alone["missing"]))
LG.decide(USER, "rejected", actor=ACTOR, reason="not this account")
alone = verdict(USER)
check("a rejection blocks alone",
      alone["open"] is False and "declined" in alone["missing"][0]["detail"],
      str(alone["missing"]))
LG.decide(USER, "approved", actor=ACTOR, reason="ok")
check("approval opens it", verdict(USER)["open"] is True)

print("\n[5] the order door reads the gate before the broker")
_real_switch = E.live_execution_enabled
_real_allowed = CL.live_allowed
seen = []


def _mode():
    seen.append("mode")
    raise RuntimeError("the broker must not be asked")


try:
    E.live_execution_enabled = lambda: True
    LX._ent.live_execution_enabled = E.live_execution_enabled
    CL.live_allowed = lambda: True
    L.grant("order-user-1", plan=P.FOUNDER_LIVE, expires_at=None)
    blocked = LX.authorize_order(
        "order-user-1", symbol="EURUSD", side="BUY", units=1000,
        account_id="1", mode_reader=_mode)
    check("a founder licence without the gate is refused",
          blocked["allowed"] is False and blocked["code"] == "LIVE_GATE_CLOSED",
          str(blocked))
    check("and the broker mode was not read", seen == [], str(seen))

    satisfy("order-user-2")
    CL.live_allowed = _real_allowed
    seen.clear()
    E.live_execution_enabled = lambda: True
    LX._ent.live_execution_enabled = E.live_execution_enabled
    blocked = LX.authorize_order(
        "order-user-2", symbol="EURUSD", side="BUY", units=1000,
        account_id="1", mode_reader=_mode)
    check("live accounts still closed by the real flag",
          blocked["code"] == "LIVE_GATE_CLOSED" and seen == [], str(blocked))

    CL.live_allowed = lambda: True
    satisfy(USER)
    seen.clear()
    # The pilot is a later gate. It is stubbed here so this assertion is
    # about the new gate, and no pilot environment variable is set.
    _real_ident = LX._pilot.check_identity
    _real_size = LX._pilot.check_order
    LX._pilot.check_identity = lambda *_a, **_k: None
    LX._pilot.check_order = lambda *_a, **_k: None
    try:
        allowed = LX.authorize_order(
            USER, symbol="EURUSD", side="BUY", units=1000,
            account_id="1", mode_reader=_mode)
        check("an open gate reaches the mode read",
              seen == ["mode"] and allowed["code"] == "MODE_UNVERIFIED",
              str(allowed))
        check("order_block itself is quiet when the gate is open",
              LG.order_block(USER) is None, str(LG.order_block(USER)))
    finally:
        LX._pilot.check_identity = _real_ident
        LX._pilot.check_order = _real_size
finally:
    E.live_execution_enabled = _real_switch
    LX._ent.live_execution_enabled = _real_switch
    CL.live_allowed = _real_allowed

print("\n[6] a store error is unknown, and scrubbed")
_real_read = ST._read_strict
_SECRET = "https://broker.example/path?token=sekret Bearer abcdefghijklmnopqrstuvwxyz"


def _boom(key):
    if "livegate" in str(key):
        raise RuntimeError(_SECRET)
    return _real_read(key)


ST._read_strict = _boom
try:
    bad = verdict("redact-user")
finally:
    ST._read_strict = _real_read
blob = json.dumps(bad)
check("unknown and closed", bad["open"] is False and bad["status"] == "unknown",
      bad["status"])
check("the url is gone", "broker.example" not in blob and "https://" not in blob, blob)
check("the token is gone", "sekret" not in blob and "Bearer" not in blob, blob)
check("the scrubbed text is what the client sees", "[redacted-url]" in blob, blob)

print("\n[7] demo is not blocked by a closed live gate")
DEMO = "demo-user-1"
P.start_trial(DEMO)
ST._write_strict(CL._k_conn(DEMO), {
    "userId": DEMO,
    "accessToken": "not-a-real-token",
    "expiresAt": time.time() + 86400,
    "selectedCtid": "501",
    "selectedMode": "demo",
    "accounts": [{"ctid": "501", "mode": "demo"}],
})
cap = E.capability(DEMO)
check("demo can still automate",
      cap["accountMode"] == "demo" and cap["canAutomate"] is True, str(cap))
check("and the gate on that verdict is not open",
      cap["liveGate"]["open"] is False, str(cap.get("liveGate")))

print("\n[8] HTTP: a client cannot publish, grant, or decide")
import apex.platform.identity as ID                       # noqa: E402
from apex.platform import api as A                        # noqa: E402


class _Principal:
    def __init__(self, user_id):
        self.user_id = user_id
        self.email = "person@example.test"
        self.email_verified = True

    def as_dict(self):
        return {"userId": self.user_id, "email": self.email,
                "emailVerified": True}


def _verify(token, **_kw):
    return _Principal(ACTOR if token == "op" else CLIENT)


ID.verify_token = _verify
_saved_ops = os.environ.get(LG.OPERATOR_ENV)
os.environ[LG.OPERATOR_ENV] = ACTOR


def call(method, path, token, body=None):
    raw = json.dumps(body).encode() if body is not None else None
    return A.handle(method, "/api/v1/" + path,
                    {"Authorization": f"Bearer {token}"}, raw)


try:
    ST._delete(LG._key("published"))
    status, payload = call("POST", "live/terms/publish", "client",
                           {"document": "terms", "version": "attacker"})
    check("a client cannot publish", status == 403
          and payload["error"]["code"] == "NOT_OPERATOR", str(payload))
    status, payload = call("POST", "live/licence/grant", "client",
                           {"userId": CLIENT})
    check("a client cannot grant", status == 403, str(payload))
    status, payload = call("POST", f"live/requests/{CLIENT}/decide", "client",
                           {"decision": "approved"})
    check("a client cannot decide", status == 403, str(payload))
    check("and nothing was published by those calls",
          ST._read_strict(LG._key("published")) is None,
          str(ST._read_strict(LG._key("published"))))

    status, payload = call("POST", "live/accept", "client", {"version": "attacker"})
    check("accepting with nothing published is refused",
          status == 409 and payload["error"]["code"] == "NOT_PUBLISHED",
          str(payload))
    check("and no acceptance was stored",
          ST._read_strict(LG._key(f"accept:{CLIENT}")) is None)

    status, _ = call("POST", "live/terms/publish", "op",
                     {"document": "terms", "version": "v9"})
    check("an operator can publish", status == 200, str(status))
    for doc in ("refund", "tax"):
        call("POST", "live/terms/publish", "op", {"document": doc, "version": "v9"})
    status, payload = call("POST", "live/accept", "client", {"version": "attacker"})
    check("the client accepts the published version, not the body's",
          status == 200, str(payload)[:200])
    stored = ST._read_strict(LG._key(f"accept:{CLIENT}"))
    check("the stored version is the published one",
          stored["terms"]["version"] == "v9", str(stored))

    status, _ = call("POST", "live/request", "client", {"mode": "live"})
    check("the request is recorded", status == 200, str(status))
    check("it did not create a broker connection",
          ST._read_strict(CL._k_conn(CLIENT)) is None)
    status, payload = call("GET", f"live/requests/{CLIENT}", "op")
    check("the operator can read it",
          status == 200 and payload["status"] == "pending", str(payload)[:240])
    check("the read carries no payment reference",
          "paymentRef" not in json.dumps(payload))
    status, payload = call("POST", f"live/requests/{CLIENT}/decide", "op",
                           {"decision": "approved", "reason": "reviewed"})
    check("the operator can approve",
          status == 200 and payload["status"] == "approved", str(payload)[:240])
    status, _ = call("POST", "live/licence/grant", "op", {"userId": CLIENT})
    check("the operator can record the licence", status == 200, str(status))

    shown = LG.public_verdict(
        CLIENT, release_switch=E.live_execution_enabled(),
        live_accounts_allowed=CL.live_allowed())
    check("the real switches still close it", shown["open"] is False,
          str(codes(shown)))
    shown = verdict(CLIENT)
    check("with both locks stubbed open, the gate is open",
          shown["open"] is True, str(codes(shown)))

    _real_read = ST._read_strict

    def _queue_down(key):
        if str(key).endswith("livegate:queue"):
            raise RuntimeError("store down")
        return _real_read(key)

    ST._read_strict = _queue_down
    try:
        status, payload = call("GET", "live/queue", "op")
    finally:
        ST._read_strict = _real_read
    check("a failed queue read is an error, not an empty list",
          status == 503 and payload.get("requests") is None, str(payload)[:200])
finally:
    if _saved_ops is None:
        os.environ.pop(LG.OPERATOR_ENV, None)
    else:
        os.environ[LG.OPERATOR_ENV] = _saved_ops

print("\n[8b] with no operator ids, every review route is refused")
from apex.platform import ratelimit as _RL                # noqa: E402
_RL.reset_all()
_saved_again = os.environ.get(LG.OPERATOR_ENV)


def _forbidden(label, method, path, body=None):
    status, payload = call(method, path, "op", body)
    err = (payload or {}).get("error") or {}
    check(label, status == 403 and err.get("code") == "NOT_OPERATOR",
          str(payload)[:240])


try:
    for _label in ("unset", "empty"):
        if _label == "unset":
            os.environ.pop(LG.OPERATOR_ENV, None)
        else:
            os.environ[LG.OPERATOR_ENV] = ""
        check(f"{_label}: nobody is an operator", LG.operators() == set(),
              str(LG.operators()))
        _forbidden(f"{_label}: GET live/queue", "GET", "live/queue")
        _forbidden(f"{_label}: GET live/requests/{{id}}",
                   "GET", f"live/requests/{CLIENT}")
        _forbidden(f"{_label}: POST decide approve", "POST",
                   f"live/requests/{CLIENT}/decide", {"decision": "approved"})
        _forbidden(f"{_label}: POST decide reject", "POST",
                   f"live/requests/{CLIENT}/decide", {"decision": "rejected"})
finally:
    if _saved_again is None:
        os.environ.pop(LG.OPERATOR_ENV, None)
    else:
        os.environ[LG.OPERATOR_ENV] = _saved_again

print("\n[9] a confirmed payment writes the record; a missing amount does not")
SECRET = "whsec_test_secret"


def sign(body, secret=SECRET):
    ts = int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256)
    return f"t={ts},v1={mac.hexdigest()}"


def event(obj, eid):
    return json.dumps({
        "id": eid, "type": "checkout.session.completed",
        "data": {"object": obj},
    }).encode()


payer = "payer-1"
body = event({
    "payment_status": "paid",
    "metadata": {B.USER_META_KEY: payer},
    "amount_total": 49700,
    "currency": "usd",
    "payment_intent": "pi_gate_1",
}, "evt_gate_paid")
status, payload = B.handle_event(body, sign(body), secret=SECRET)
check("the payment is accepted", status == 200 and payload.get("outcome") == "granted",
      str(payload))
paid = ST._read_strict(LG._key(f"paid:{payer}"))
check("and the paid record is the lifetime price",
      paid and paid.get("source") == "payment" and paid.get("priceMinor") == 49700
      and paid.get("currency") == "usd" and paid.get("term") == "lifetime",
      str(paid))

other = "payer-2"
body = event({
    "payment_status": "paid",
    "metadata": {B.USER_META_KEY: other},
}, "evt_gate_no_amount")
status, payload = B.handle_event(body, sign(body), secret=SECRET)
check("a payment with no amount still grants the plan",
      status == 200 and L.status_for(other)["plan"] == P.FOUNDER_LIVE,
      str(payload))
check("and does not write the paid record",
      ST._read_strict(LG._key(f"paid:{other}")) is None)

check("a smaller charge writes nothing",
      LG.note_confirmed_payment(
          "payer-3", {"amount_total": 100, "currency": "usd"}, lifetime=True)
      is False)
check("and a wrong currency writes nothing",
      LG.note_confirmed_payment(
          "payer-3", {"amount_total": 49700, "currency": "eur"}, lifetime=True)
      is False)
check("nothing is on file for that client",
      ST._read_strict(LG._key("paid:payer-3")) is None)

refund = json.dumps({
    "id": "evt_gate_refund", "type": "charge.refunded",
    "data": {"object": {
        "payment_intent": "pi_gate_1",
        "amount": 49700, "amount_refunded": 49700,
    }},
}).encode()
status, payload = B.handle_event(refund, sign(refund), secret=SECRET)
check("a full refund is revoked",
      status == 200 and payload.get("outcome") == "revoked", str(payload))
check("and the paid record is gone",
      ST._read_strict(LG._key(f"paid:{payer}")) is None)

print("\n[10] the check sits on the real door, ahead of the broker read")
auth_src = open(os.path.join(ROOT, "apex", "platform", "live_execution.py"),
                encoding="utf-8").read()
auth = auth_src[auth_src.index("def authorize_order"):auth_src.index("def guard_engine_order")]
place = auth_src[auth_src.index("def place"):auth_src.index("def authorize_order")]
check("authorize_order asks the gate before the mode",
      auth.index("order_block") < auth.index("mode_reader()"))
check("and still after the entitlement",
      auth.index("entitlement_of") < auth.index("_pilot.check_identity"))
check("place asks it too",
      place.index("order_block") < place.index("mode_reader()"))
pre = open(os.path.join(ROOT, "apex", "platform", "automation.py"),
           encoding="utf-8").read()
pre = pre[pre.index("def _preflight"):pre.index("def _note_engine_refused")]
check("a live start asks the gate, after the broker mode",
      pre.index("verify_selected_mode") < pre.index("live_readiness")
      < pre.index("_pilot.check_identity"))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for item in _fails:
        print("  -", item)
    sys.exit(1)
print("All live-gate checks passed.")
