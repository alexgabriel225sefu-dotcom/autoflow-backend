"""The assembled live order path — every gate, proven to refuse.

`tests/test_platform_live_invariants.py` reads `place()` and asserts the gates
are present and in order. That is a claim about the source. This file is the
claim about the BEHAVIOUR: each gate is closed in turn and the order must not
be placed, and the broker — a fake that records what it was asked — must never
have been called.

THE TWO THAT MATTER MOST

  * THE CLAIM IS TAKEN BEFORE THE BROKER CALL, and an UNKNOWN outcome does not
    release it. A submit that raised may have filled; releasing the key there
    turns one uncertain order into two certain ones. Asserted by making the
    broker raise and then checking the key is still held.

  * NOTHING IS PLACED WITH THE RELEASE SWITCH OFF. Every call refuses at the
    switch today, which is what makes this module safe to have written before
    the §12 review. The rest of the file turns the switch on explicitly, in a
    test, to reach the gates behind it.

Run: python3 tests/test_platform_live_execution.py
"""
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-liveexec-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("A4T_EMERGENCY_HALT", None)

from apex import user_store                             # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


# A shared backend: the ledger and the audit trail both refuse without one,
# correctly, and this path uses both.
class Fake:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}

    def install(self):
        user_store._USE_REDIS = True
        user_store._BACKEND = "redis"
        for n in ("set_blob_nx", "set_blob", "get_blob", "get_blob_strict",
                  "del_blob", "claim", "claim_value", "release_claim", "incr"):
            setattr(user_store, n, getattr(self, n))

    def set_blob_nx(self, k, v):
        with self.lock:
            if k in self.data:
                return False
            self.data[k] = v
            return True

    def set_blob(self, k, v, ttl_s=None):
        with self.lock:
            self.data[k] = v
        return True

    def get_blob(self, k):
        with self.lock:
            return self.data.get(k)

    def get_blob_strict(self, k):
        return self.get_blob(k)

    def del_blob(self, k):
        with self.lock:
            return self.data.pop(k, None)

    def claim(self, k, ttl_s=120):
        return self.claim_value(k, "1", ttl_s=ttl_s)

    def claim_value(self, k, v, ttl_s=120):
        with self.lock:
            if k in self.data:
                return False
            self.data[k] = str(v)
            return True

    def release_claim(self, k, v):
        with self.lock:
            if self.data.get(k) != str(v):
                return False
            del self.data[k]
        return True

    def incr(self, k, ttl_s=60):
        with self.lock:
            self.data[k] = int(self.data.get(k, 0)) + 1
            return self.data[k]


FAKE = Fake()
FAKE.install()

from apex.platform import decision as D                 # noqa: E402
from apex.platform import emergency as EM               # noqa: E402
from apex.platform import entitlement as ENT            # noqa: E402
from apex.platform import licence as LIC                # noqa: E402
from apex.platform import live_execution as LX          # noqa: E402
from apex.platform import live_ledger as LED            # noqa: E402
from apex.platform import plans as PLANS                # noqa: E402
from apex.platform import ruledoc as RD                 # noqa: E402
from apex.platform import snapshot as SN                # noqa: E402

USER = "aaaa0000-1111-4222-8333-aaaa44445555"
ACCOUNT = "9001"

# The pilot guard (apex/platform/live_pilot.py) fails closed unless it is told
# which account, which instruments, and the largest order. This file exercises
# the gates BEHIND it, so it configures the pilot for its own user and account
# and leaves every assertion about those gates untouched. The guard's own
# refusals are proven in section [19b] below.
os.environ["A4T_LIVE_PILOT_PAIRS"] = f"{USER}:{ACCOUNT}"
os.environ["A4T_LIVE_PILOT_SYMBOLS"] = "EURUSD,GBPUSD"
os.environ["A4T_LIVE_PILOT_MAX_UNITS"] = "10000000"
NOW = 1_760_000_000.0
BAR = 3600


class FakeBroker:
    """Records what it was asked for, and never does anything."""

    def __init__(self, reply=None, raises=None):
        self.calls = []
        self.reply = reply if reply is not None else {
            "ok": True, "positionId": "pos-1"}
        self.raises = raises

    def __call__(self, req):
        self.calls.append(req)
        if self.raises:
            raise self.raises
        return self.reply


def bars(n=60, start=1.2000, step=0.0012):
    out, t = [], NOW - BAR * n
    px = start
    for _ in range(n):
        px += step
        out.append({"time": t, "open": px, "high": px * 1.002,
                    "low": px * 0.998, "close": px})
        t += BAR
    return out


def snap(**kw):
    c = bars()
    kw.setdefault("spread_pips", 0.6)
    return SN.MarketSnapshot(symbol="EURUSD", timeframe="1h", candles=c,
                             price=c[-1]["close"], ts=c[-1]["time"] + BAR,
                             balance=10_000, equity=10_000,
                             open_positions=[], **kw)


def rule(**over):
    d = RD.blank(user_id=USER, account_id=ACCOUNT, symbols=["EURUSD"],
                 timeframe="1h")
    d["name"] = "live path rule"
    d["state"] = RD.ACTIVE
    d["version"] = 1
    d["sides"] = "BUY"
    d["entry"] = {"combine": "AND", "conditions": [
        {"id": "rsi", "params": {"period": 14, "op": "below", "value": 30}}]}
    d["stopLoss"] = {"mode": "pips", "atrMultiple": None, "pips": 20}
    d["takeProfit"] = {"mode": "pips", "rr": None, "pips": 40}
    d.update(over)
    return d


def buy(**over):
    kw = dict(verdict=D.BUY, rule_doc_id="rule-live", rule_doc_version=1,
              symbol="EURUSD", snapshot_ts=NOW, side=D.BUY,
              reason="entry conditions met")
    kw.update(over)
    return D.RuleDecision(**kw)


STATE = {"positions": [], "dailyRealisedPnl": 0.0, "dailyTradesOpened": 0,
         "peakBalance": 10_000, "spreadPips": 0.6, "slippagePoints": 0.0}


def balance():
    return 10_000.0


def live_mode():
    return "live"


def place(**over):
    kw = dict(user_id=USER, account_id=ACCOUNT, balance_reader=balance,
              mode_reader=live_mode, state=dict(STATE), timeframe="1h",
              now=NOW)
    kw.update(over)
    doc = kw.pop("rule_doc", None) or rule()
    dec = kw.pop("decision", None) or buy()
    sp = kw.pop("snapshot", None) or snap()
    return LX.place(doc, dec, sp, **kw)


def entitle():
    LIC.grant(USER, plan=PLANS.FOUNDER_LIVE, expires_at=None)


def reset():
    """A clean store, with the paid plan back on the account.

    The licence lives in the same backend as the ledger and the audit trail,
    so clearing the fake wipes it as well — a test that forgot this refused
    everything at the entitlement gate and looked like nine broken gates.
    """
    FAKE.data.clear()
    entitle()


def unentitle():
    PLANS._lic._store._write(
        f"{PLANS._lic._store._ns()}:{PLANS._lic._store._P}:licence:{USER}",
        None)


# ═══════════════════════════════════════════════════════════════════════════
print("\n[1] with the release switch OFF, nothing reaches a broker")
entitle()
b = FakeBroker()
r = place(broker=b)
check("the order is refused", r["placed"] is False, str(r))
check("at the release switch", r["code"] == LX.LIVE_NOT_ENABLED, str(r["code"]))
check("and the broker was never called", b.calls == [], str(len(b.calls)))
check("the refusal names what closes it",
      "§12" in r["detail"] or "not enabled" in r["detail"], r["detail"])


# Everything below turns the switch on explicitly, to reach the gates behind
# it. This is the only place in the product where that happens.
_real_switch = ENT.live_execution_enabled
LX._ent.live_execution_enabled = lambda: True


def restore_switch():
    LX._ent.live_execution_enabled = _real_switch


try:
    print("\n[2] §8 the emergency stop is checked first")
    os.environ[EM.ENV_VAR] = "all"
    try:
        b = FakeBroker()
        r = place(broker=b)
        check("a global halt refuses", r["placed"] is False and
              r["code"] == LX.HALTED, str(r))
        check("and nothing reached the broker", b.calls == [])
    finally:
        os.environ.pop(EM.ENV_VAR, None)

    print("\n[3] §2 the plan has to cover live")
    unentitle()
    b = FakeBroker()
    r = place(broker=b)
    check("a client without the paid plan is refused",
          r["code"] == LX.NOT_ENTITLED, str(r))
    check("and nothing reached the broker", b.calls == [])
    entitle()

    print("\n[4] §3 the mode comes from the BROKER, and must say live")
    b = FakeBroker()
    r = place(broker=b, mode_reader=lambda: "demo")
    check("a demo account is refused on the live path",
          r["code"] == LX.MODE_NOT_LIVE, str(r))

    def _unreachable():
        raise RuntimeError("broker unreachable")

    b = FakeBroker()
    r = place(broker=b, mode_reader=_unreachable)
    check("a mode that cannot be verified is refused, not assumed",
          r["code"] == LX.MODE_UNVERIFIED, str(r))
    check("and neither reached the broker", b.calls == [])
    check("there is no parameter that lets a caller ASSERT the mode",
          "mode=" not in LX.place.__doc__
          and "mode_reader" in LX.place.__doc__)

    print("\n[5] a decision that is not an entry places nothing")
    b = FakeBroker()
    r = place(broker=b, decision=buy(verdict=D.HOLD, side=None,
                                     reason="conditions not met"))
    check("a HOLD is refused", r["code"] == LX.NOT_A_TRADE, str(r))
    check("and nothing reached the broker", b.calls == [])

    print("\n[6] §9 the per-client order rate, which refuses when unsure")
    _real_rate = LX._rate.authorize

    def _over(_uid, **kw):
        raise LX._rate.OrderRateExceeded("6 in the last minute, cap is 6",
                                         window="minute", cap=6)

    LX._rate.authorize = _over
    try:
        b = FakeBroker()
        r = place(broker=b)
        check("over the cap refuses", r["code"] == LX.RATE_LIMITED, str(r))
        check("and nothing reached the broker", b.calls == [])
    finally:
        LX._rate.authorize = _real_rate

    def _cannot(_uid, **kw):
        raise LX._rate.OrderRateUnavailable("the counter could not answer")

    LX._rate.authorize = _cannot
    try:
        b = FakeBroker()
        r = place(broker=b)
        check("a counter that cannot answer refuses too, with its own code",
              r["code"] == LX.RATE_UNKNOWN, str(r))
        check("which is NOT the same code as being over the cap",
              LX.RATE_UNKNOWN != LX.RATE_LIMITED)
        check("and nothing reached the broker", b.calls == [])
    finally:
        LX._rate.authorize = _real_rate

    print("\n[7] §5 the risk gates stand between the rule and the order")
    # The order must BUILD and then be refused by a gate — a zero balance
    # fails the build instead, which is correct and earlier, and would have
    # tested the wrong thing. A daily-trade count over the rule's own limit
    # leaves the build intact and trips §5.
    b = FakeBroker()
    over_limit = dict(STATE, dailyTradesOpened=5)
    r = place(broker=b, rule_doc=rule(limits={**RD.blank(
        user_id=USER, account_id=ACCOUNT)["limits"], "maxDailyTrades": 1}),
        state=over_limit)
    check("a refusal from the gates stops the order",
          r["code"] == LX.RISK_REFUSED, str(r))
    check("and names WHICH gate refused",
          str(r.get("gate", "")).startswith("risk:"), str(r.get("gate")))
    check("and nothing reached the broker", b.calls == [])

    print("\n[8] §6 the claim is taken BEFORE the broker call")
    reset()
    b = FakeBroker()
    r = place(broker=b)
    check("a clean order is placed", r["placed"] is True, str(r))
    check("the broker was called exactly once", len(b.calls) == 1)
    check("and the same decision cannot be placed again",
          place(broker=FakeBroker())["code"] == LX.ALREADY_CLAIMED,
          str(place(broker=FakeBroker())))

    print("\n[9] §6 an UNKNOWN outcome keeps the claim")
    reset()
    b = FakeBroker(raises=TimeoutError("the broker did not answer"))
    r = place(broker=b)
    check("the result is reported as unknown, not as a failure to place",
          r["outcome"] == "unknown" and r["placed"] is False, str(r))
    check("the broker WAS called — this is after the send", len(b.calls) == 1)
    check("and the claim is STILL HELD, so a retry is refused",
          place(broker=FakeBroker())["code"] == LX.ALREADY_CLAIMED,
          "a submit that timed out may have filled; releasing the key here "
          "turns one uncertain order into two certain ones")

    print("\n[10] a confirmed broker REJECTION releases the claim")
    reset()
    b = FakeBroker(reply={"ok": False, "code": "MARKET_CLOSED"})
    r = place(broker=b)
    check("the order is reported as not placed", r["placed"] is False, str(r))
    check("with the broker's own refusal", r["code"] == "BROKER_REJECTED",
          str(r))
    check("and the decision may be attempted again, because nothing exists",
          place(broker=FakeBroker())["placed"] is True,
          "the broker confirmed there is no order")

    print("\n[11] §7 every refusal is in the audit trail")
    from apex.platform import audit as AUD                  # noqa: E402

    reset()
    place(broker=FakeBroker(), mode_reader=lambda: "demo")
    rows = [r for r in AUD.query(USER) if r.get("kind") == AUD.REFUSAL]
    check("the refusal was recorded", len(rows) == 1, str(len(rows)))
    check("naming its gate", rows and rows[0].get("gate") == "mode_verification",
          str(rows[0].get("gate") if rows else None))
    check("and its code", rows and rows[0].get("code") == LX.MODE_NOT_LIVE,
          str(rows[0].get("code") if rows else None))
    check("and the trail verifies", AUD.verify(USER).get("ok") is True,
          str(AUD.verify(USER)))

    print("\n[12] §7 a placed order is recorded, and carries no credential")
    reset()
    place(broker=FakeBroker())
    orders = [r for r in AUD.query(USER) if r.get("kind") == AUD.LIVE_ORDER]
    check("the order is in the trail", len(orders) >= 1, str(len(orders)))
    check("with the rule version that was traded",
          orders and orders[0].get("ruleDocVersion") == 1,
          str(orders[0].get("ruleDocVersion") if orders else None))
    import json as _json
    blob = _json.dumps(orders)
    for leak in ("accessToken", "refreshToken", "password"):
        if leak in blob:
            check(f"{leak} is masked, not stored",
                  "<redacted>" in blob, blob[:160])

    print("\n[13] an audit trail that cannot record stops the order")
    reset()
    _real_rec = LX._audit.record_live_order

    def _down(**kw):
        raise RuntimeError("audit unavailable")

    LX._audit.record_live_order = _down
    try:
        b = FakeBroker()
        r = place(broker=b)
        check("the order is refused", r["code"] == LX.AUDIT_UNAVAILABLE,
              str(r))
        check("and was NOT sent", b.calls == [],
              "an order nobody can attribute afterwards is the one case "
              "where refusing is cheaper than proceeding")
    finally:
        LX._audit.record_live_order = _real_rec
    check("and the claim was released, so the next attempt may proceed",
          place(broker=FakeBroker())["placed"] is True,
          "nothing was sent, so holding the key would strand the decision")

finally:
    restore_switch()

print("\n[14] the switch is back off, and refuses again")
b = FakeBroker()
r = place(broker=b)
check("the release switch refuses once more",
      r["code"] == LX.LIVE_NOT_ENABLED, str(r))
check("and the real entitlement module still says live is disabled",
      ENT.live_execution_enabled() is False)

# ═══════════════════════════════════════════════════════════════════════════
# THE SECOND DOOR
#
# `place()` above is the rule-driven path. `authorize_order` is the one the
# ENGINE's order gate calls, for an order that already exists. It runs the
# same gates minus the two that need a RuleDoc, and the thing worth proving is
# that it refuses in the same places — two doors with one policy.
print("\n[15] the engine door refuses at the switch, like the other one")
reset()


def auth(**over):
    kw = dict(symbol="EURUSD", side="BUY", units=1000,
              account_id=ACCOUNT, mode_reader=live_mode, now=NOW)
    kw.update(over)
    return LX.authorize_order(USER, **kw)


v = auth()
check("refused with the switch off", v["allowed"] is False, str(v))
check("at the release switch", v["code"] == LX.LIVE_NOT_ENABLED, str(v["code"]))

LX._ent.live_execution_enabled = lambda: True
try:
    print("\n[16] §8 the emergency stop outranks even the switch")
    os.environ[EM.ENV_VAR] = "all"
    try:
        v = auth()
        check("halted", v["allowed"] is False and v["code"] == LX.HALTED,
              str(v))
    finally:
        os.environ.pop(EM.ENV_VAR, None)

    print("\n[17] §2 an unentitled account is refused")
    unentitle()
    v = auth()
    check("refused on the plan", v["code"] == LX.NOT_ENTITLED, str(v))
    reset()

    print("\n[18] §3 the mode must come from the broker, and must be live")
    def boom():
        raise RuntimeError("the broker did not answer")

    v = auth(mode_reader=boom)
    check("an unverified mode is not a live mode",
          v["code"] == LX.MODE_UNVERIFIED, str(v))
    v = auth(mode_reader=lambda: "demo")
    check("and a demo account is not this path's business",
          v["code"] == LX.MODE_NOT_LIVE, str(v))

    print("\n[19] a fully clear order is allowed, and says so")
    reset()
    v = auth()
    check("allowed", v["allowed"] is True, str(v))
    check("with no refusal code", v["code"] is None, str(v["code"]))

    print("\n[19b] the pilot guard: the operator's own account, at a capped size")
    PILOT_ENV = ("A4T_LIVE_PILOT_PAIRS", "A4T_LIVE_PILOT_SYMBOLS",
                 "A4T_LIVE_PILOT_MAX_UNITS")
    saved = {k: os.environ.get(k) for k in PILOT_ENV}
    calls = []

    def counted_mode():
        calls.append(1)
        return "live"

    def set_pilot(pairs=f"{USER}:{ACCOUNT}", symbols="EURUSD", cap="10000"):
        for k, v in zip(PILOT_ENV, (pairs, symbols, cap)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    try:
        set_pilot()
        reset()
        v = auth(mode_reader=counted_mode, units=10000)
        check("inside the pilot, at exactly the cap, it is allowed",
              v["allowed"] is True, str(v))

        # Each of the three values missing on its own closes everything.
        for missing in range(3):
            vals = [f"{USER}:{ACCOUNT}", "EURUSD", "10000"]
            vals[missing] = None
            set_pilot(*vals)
            reset()
            v = auth(mode_reader=counted_mode)
            check(f"without {PILOT_ENV[missing]} nothing is sent",
                  v["allowed"] is False and v["code"] == "PILOT_UNCONFIGURED"
                  and v["gate"] == "pilot", str(v))
        for bad_pairs in ("justauser", f"{USER}:", f":{ACCOUNT}", ","):
            set_pilot(pairs=bad_pairs)
            reset()
            v = auth(mode_reader=counted_mode)
            check(f"a malformed pair list ({bad_pairs!r}) closes it",
                  v["code"] == "PILOT_UNCONFIGURED", str(v))
        for bad_cap in ("not-a-number", "0", "-5", "1.5"):
            set_pilot(cap=bad_cap)
            reset()
            v = auth(mode_reader=counted_mode)
            check(f"a cap of {bad_cap!r} closes it, it is not 'unlimited'",
                  v["code"] == "PILOT_UNCONFIGURED", str(v))

        set_pilot()
        reset()
        calls.clear()
        v = auth(mode_reader=counted_mode, units=10001)
        check("one unit over the cap is refused",
              v["allowed"] is False and v["code"] == "OVER_PILOT_SIZE"
              and v["gate"] == "pilot", str(v))
        for bad in (None, 0, -0.0, float("nan"), float("inf"), "big", True):
            v = auth(mode_reader=counted_mode, units=bad)
            check(f"a size that cannot be measured ({bad!r}) is refused",
                  v["allowed"] is False and v["code"] == "OVER_PILOT_SIZE",
                  str(v))

        v = auth(mode_reader=counted_mode, symbol="XAUUSD")
        check("an instrument outside the pilot is refused",
              v["code"] == "NOT_PILOT_SYMBOL" and v["gate"] == "pilot", str(v))
        set_pilot(symbols="eur/usd")
        reset()
        v = auth(mode_reader=counted_mode)
        check("instrument names are compared after normalising case and '/'",
              v["allowed"] is True, str(v))

        set_pilot(pairs=f"someone-else:{ACCOUNT}")
        reset()
        calls.clear()
        v = auth(mode_reader=counted_mode)
        check("a user outside the pilot is refused",
              v["allowed"] is False and v["code"] == "NOT_PILOT_ACCOUNT"
              and v["gate"] == "pilot", str(v))
        check("before the broker is even asked for the mode", calls == [],
              f"the mode reader ran {len(calls)} time(s): a refused client "
              f"must not cost a broker round trip")

        set_pilot(pairs=f"{USER}:1234")
        reset()
        v = auth(mode_reader=counted_mode)
        check("an account outside the pilot is refused",
              v["code"] == "NOT_PILOT_ACCOUNT", str(v))
        set_pilot(pairs=f"someone-else:{ACCOUNT},{USER}:1234")
        reset()
        v = auth(mode_reader=counted_mode)
        check("a listed user and a listed account that were never paired are "
              "refused", v["code"] == "NOT_PILOT_ACCOUNT", str(v))
        set_pilot()
        reset()
        v = auth(mode_reader=counted_mode, account_id=None)
        check("and so is an order that names no account",
              v["code"] == "NOT_PILOT_ACCOUNT", str(v))
        # A list is exact membership, not a substring match.
        set_pilot(pairs=f"{USER}:90010")
        reset()
        v = auth(mode_reader=counted_mode)
        check("account 9001 is not matched by 90010",
              v["code"] == "NOT_PILOT_ACCOUNT", str(v))
        set_pilot(pairs=f"x:1, {USER}:{ACCOUNT} ,y:2")
        reset()
        v = auth(mode_reader=counted_mode)
        check("a list with spaces and several pairs still admits a member",
              v["allowed"] is True, str(v))

        set_pilot(cap="999")
        reset()
        v = auth(mode_reader=counted_mode, units=500)
        check("a cap below the smallest order the instrument allows is no cap",
              v["allowed"] is False and v["code"] == "OVER_PILOT_SIZE"
              and v["gate"] == "pilot", str(v))
        set_pilot()

        # The mode the broker confirms must be the mode of the account the LOOP
        # holds, not of whatever is selected at the moment of the read.
        set_pilot(pairs=f"{USER}:{ACCOUNT},{USER}:999")
        reset()
        from apex.platform import ctrader_link as _CTL2
        _real_verify = _CTL2.verify_selected_mode
        _CTL2._store._write(_CTL2._k_conn(USER), {
            "userId": USER, "accessToken": "not-a-real-token",
            "ctid": ACCOUNT, "mode": "live", "accounts": [],
            "selectedCtid": ACCOUNT})
        _CTL2.verify_selected_mode = lambda uid, **kw: {
            "mode": "live", "verified": True, "ctid": ACCOUNT,
            "recorded": "live", "changed": False, "reason": None}
        try:
            g = LX.guard_engine_order(USER, symbol="EURUSD", side="BUY",
                                      units=1000, origin="loop",
                                      bound_account="999")
            check("a verified mode for a DIFFERENT account than the loop holds "
                  "is not an answer", g.get("code") == LX.MODE_UNVERIFIED,
                  str(g))
            g = LX.guard_engine_order(USER, symbol="EURUSD", side="BUY",
                                      units=1000, origin="loop",
                                      bound_account=ACCOUNT)
            check("while the loop's own account passes the mode gate",
                  g.get("code") != LX.MODE_UNVERIFIED, str(g))
        finally:
            _CTL2.verify_selected_mode = _real_verify
        set_pilot()
        reset()

        # §7: an order whose authorization could not be written down is not sent.
        set_pilot()
        reset()
        _real_rec = LX._audit.record_refusal

        def _audit_down(**kw):
            if kw.get("code") == "ALLOWED":
                raise RuntimeError("audit store unreachable")
            return _real_rec(**kw)

        LX._audit.record_refusal = _audit_down
        try:
            v = auth(mode_reader=counted_mode)
        finally:
            LX._audit.record_refusal = _real_rec
        check("an allowed order whose audit write fails is refused, not sent",
              v["allowed"] is False and v["code"] == LX.AUDIT_UNAVAILABLE
              and v["gate"] == "audit", str(v))
    finally:
        for k, val in saved.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val
        reset()

    print("\n[20] guard_engine_order has NO opinion on a non-platform account")
    # The Telegram bot's users reach `gates.authorize_order` too and have no
    # platform cTrader connection. None means "not mine to answer" — which is
    # not the same as allowed, and the distinction is what keeps the legacy
    # product working while a platform client is held to every gate.
    FAKE.data.clear()                      # no connection record anywhere
    g = LX.guard_engine_order("someone-else", symbol="EURUSD", side="BUY",
                              units=1000, origin="telegram")
    check("returns None rather than a verdict", g is None, str(g))

    print("\n[20b] but a PLATFORM account does get a verdict")
    # The other half, and the one that catches the mutation that matters: a
    # guard which returned None for EVERYBODY would pass [20] perfectly while
    # letting every platform live order through ungated.
    from apex.platform import ctrader_link as _CTL
    _CTL._store._write(_CTL._k_conn(USER), {
        "userId": USER, "accessToken": "not-a-real-token",
        "ctid": ACCOUNT, "mode": "live", "accounts": [],
    })
    reset()
    # `selectedCtid` is what select_account records for the chosen account; the
    # pilot guard compares it to the pilot list, so a record that omits it would
    # stop at the pilot gate instead of reaching the mode gate under test.
    _CTL._store._write(_CTL._k_conn(USER), {
        "userId": USER, "accessToken": "not-a-real-token",
        "ctid": ACCOUNT, "mode": "live", "accounts": [],
        "selectedCtid": ACCOUNT,
    })
    g = LX.guard_engine_order(USER, symbol="EURUSD", side="BUY",
                              units=1000, origin="loop")
    check("it answers rather than abstaining", g is not None, str(g))
    # The broker cannot be reached from a test, so §3 cannot be satisfied —
    # and that IS the expected answer. An unverified mode is not a live mode.
    check("and an unreachable broker means refused, never allowed",
          g.get("allowed") is False, str(g))
    check("with the mode gate named",
          g.get("code") in (LX.MODE_UNVERIFIED, LX.MODE_NOT_LIVE), str(g))
finally:
    restore_switch()

print("\n[21] and with the switch back off, the engine door is shut again")
reset()
v = auth()
check("refused once more", v["allowed"] is False, str(v))
check("at the release switch", v["code"] == LX.LIVE_NOT_ENABLED, str(v))
check("the real module still reports the switch closed",
      ENT.live_execution_enabled() is False)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All live-execution path checks hold.")
