"""A crash between the broker send and the bookkeeping must not become a second order.

THE WINDOW

`force_trade` (the one door Approve, /buy and the platform's rule orders go
through) does, in this order:

    1. gates.authorize_order  -> takes the idempotency claim
    2. broker.place_order     -> the order EXISTS at the broker from here
    3. ledger.record          -> remembers the broker's answer
    4. _persist_open_position -> the restart-recovery snapshot
    5. (later, in the loop)   -> journal / trade log

A process that dies after (2) and before (4) leaves a real position at the
broker and no local record of it. The next tick, possibly in a new container,
must (a) not send the same order again and (b) end up managing the position.

WHAT IS PROVEN HERE, WITH THE REAL force_trade / ledger / live_ledger /
recovery_verdict, and only the broker and the shared store simulated:

  * the claim taken before the send survives the "crash" and a restart (the
    in-process ledger is wiped, the shared store is not), so an identical
    retry is refused and the broker is asked exactly once;
  * a crash AFTER the snapshot was written is adopted, not re-opened;
  * the platform's live ledger keeps the claim when the outcome write is lost,
    and an UNKNOWN outcome never releases it.

THE WINDOW BEFORE THE SNAPSHOT IS CLOSED (section [5]): the snapshot is
written BEFORE the broker call, marked `pending`, and the confirmed result
overwrites it. A crash between send and confirm therefore leaves something for
restart recovery to adopt, with the original stop. A definite rejection puts the
previous snapshot back; an ambiguous one keeps the intent; a live account whose
intent cannot be written sends nothing.

The steps above are therefore, in order: claim, INTENT SNAPSHOT, send, record,
confirmed snapshot.

Run: python3 tests/test_crash_window_send_to_journal.py
"""
import os
import sys
import tempfile
import threading
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-crashwin-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex import gates as GATES                             # noqa: E402
from apex import ledger, user_loop as UL, user_store        # noqa: E402


_REAL_PERSIST = UL._persist_open_position


class Crash(BaseException):
    """The process dying. BaseException so no `except Exception` swallows it."""


class MemStore:
    """A shared store that survives a 'restart' (the in-process state does not)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.kv = {}
        self.users = {}

    def install(self):
        self.saved = {n: getattr(user_store, n) for n in (
            "load", "save", "update", "claim_value", "release_claim",
            "renew_claim", "get_blob", "get_blob_strict", "set_blob", "claim",
            "_USE_REDIS")}
        user_store._USE_REDIS = True
        user_store.load = lambda uid: dict(self.users.get(str(uid), {}))
        user_store.save = lambda uid, data, **k: self.users.__setitem__(str(uid), dict(data)) or True
        user_store.update = lambda uid, patch, **k: self.users.setdefault(str(uid), {}).update(patch) or True
        user_store.claim_value = self.claim_value
        user_store.claim = lambda k, ttl_s=120, **kw: self.claim_value(k, "1", ttl_s)
        user_store.release_claim = self.release_claim
        user_store.get_blob = lambda k: self.kv.get(k)
        user_store.get_blob_strict = lambda k: self.kv.get(k)
        user_store.set_blob = lambda k, v, ttl_s=None: self.kv.__setitem__(k, v) or True

    def restore(self):
        for n, f in self.saved.items():
            setattr(user_store, n, f)

    def claim_value(self, k, v, ttl_s=120):
        with self.lock:
            if k in self.kv:
                return False
            self.kv[k] = str(v)
            return True

    def release_claim(self, k, v):
        with self.lock:
            if self.kv.get(k) != str(v):
                return False
            del self.kv[k]
            return True


STORE = MemStore()
STORE.install()

USER = "cccccccc-7777-4777-8777-cccccccccccc"
_REAL_CFG = UL._make_broker({"paper": True})[1]
LIVE_CFG = types.SimpleNamespace(PAPER_TRADING=False)
_CANDLES = [{"open": 1.0920, "high": 1.0940, "low": 1.0910, "close": 1.0930,
             "time": 1_700_000_000 + i * 300} for i in range(60)]


class Broker:
    """Records every order it is asked for; reports the position it 'holds'."""

    def __init__(self):
        self.orders = []
        self.position = None

    def get_candles(self, sym, tf, n):
        return _CANDLES[-int(n):]

    def get_bid_ask(self, sym):
        return 1.0929, 1.0931

    def get_balance(self):
        return 10_000.0

    def get_open_position(self, sym=None):
        return dict(self.position) if self.position else None

    def place_order(self, side, units, sym, sl=None, tp=None):
        self.orders.append((side, units, sym, sl, tp))
        self.position = {"symbol": sym, "side": side, "units": units,
                         "entryPrice": 1.0930, "stopLoss": sl, "takeProfit": tp,
                         "positionId": 777001}
        return {"orderId": "o1", "status": "FILLED", "fillPrice": 1.0930}


def trade(broker, persist):
    """Drive the real force_trade; `persist` replaces step 4."""
    saved = {n: getattr(UL, n) for n in
             ("_make_broker", "_persist_open_position", "get_dash",
              "_alert_fn_for")}
    _ent = GATES.live_entitlement
    try:
        UL._make_broker = lambda user, user_id=None: (broker, _REAL_CFG)
        UL._persist_open_position = persist
        UL.get_dash = lambda uid: {}
        UL._alert_fn_for = lambda uid, fn: None
        GATES.live_entitlement = lambda uid, u=None: ("allowed", "stubbed")
        return UL.force_trade(USER, "BUY", symbol="EURUSD", lots=0.01,
                              sl_override=1.0900, tp_override=1.0960,
                              origin="approval")
    finally:
        for name, fn in saved.items():
            setattr(UL, name, fn)
        GATES.live_entitlement = _ent


def real_persist(uid, cfg, pos):
    """The REAL snapshot writer, as a cTrader account would use it."""
    return _REAL_PERSIST(uid, LIVE_CFG, pos)


def die_after_send(uid, cfg, pos):
    """The intent is written (really); the confirmed snapshot never is."""
    if pos and pos.get("pending"):
        return real_persist(uid, cfg, pos)
    raise Crash("process killed after the broker accepted the order")


def restart():
    """A new process: in-process ledger and loop registry gone, store intact."""
    with ledger._local_lock:
        ledger._local.clear()


try:
    STORE.users[USER] = {"id": USER, "paper": True}

    # ── 1. crash after the send, before the snapshot ───────────────────────
    print("\n[1] the process dies after the broker accepted the order")
    broker = Broker()
    crashed = False
    try:
        trade(broker, die_after_send)
    except Crash:
        crashed = True
    check("the 'crash' reached the caller (nothing swallowed it)", crashed)
    check("the broker was asked once", len(broker.orders) == 1, str(broker.orders))
    check("and a position exists at the broker", broker.position is not None)

    print("\n[2] the next tick, in a NEW process, does not send it again")
    restart()
    again = trade(broker, lambda *a: None)
    check("the identical order is refused", again.get("ok") is False, str(again))
    check("as a duplicate, from the shared claim (the local ledger was wiped)",
          "DUPLICATE" in str(again.get("error")), str(again.get("error")))
    check("the broker was NOT asked a second time", len(broker.orders) == 1,
          str(broker.orders))

    print("\n[3] the claim protects a bounded window, not the position")
    # DESIGN, asserted so nobody reads the claim as more than it is: the
    # idempotency key lives for window_s*2 (240s). The loop ticks every 300s,
    # so by the time the next tick runs the claim is gone. From then on the
    # only thing between the account and a second order is the position
    # sync (maxpos), which is why [4] and [5] matter.
    ok_late, why_late, _ = ledger.claim(USER, "EURUSD", "BUY", 1000.0, 1.0900, 1.0960,
                                        now=2_000_000_000.0, fail_closed=True)
    ok_later, _, _ = ledger.claim(USER, "EURUSD", "BUY", 1000.0, 1.0900, 1.0960,
                                  now=2_000_000_000.0 + 3 * ledger.DEFAULT_WINDOW_S,
                                  fail_closed=True)
    check("an identical order a few windows later is a new claim",
          ok_later is True, why_late)

    # ── 4. crash AFTER the snapshot: adopted, not re-opened ────────────────
    print("\n[4] a crash after the snapshot was written is adopted on restart")
    STORE.kv.clear(); restart()
    STORE.users[USER] = {"id": USER, "paper": True}
    broker = Broker()

    def snapshot_then_die(uid, cfg, pos):
        real_persist(uid, cfg, pos)             # the REAL writer
        if pos and not pos.get("pending"):
            raise Crash("killed before the journal write")
        return True

    try:
        trade(broker, snapshot_then_die)
    except Crash:
        pass
    snap = STORE.users[USER].get("open_position_snapshot") or {}
    check("the snapshot reached the store", snap.get("symbol") == "EURUSD", str(snap))
    check("with the ORIGINAL stop, which the broker cannot give back",
          snap.get("initialStop") == 1.09, str(snap.get("initialStop")))
    live = broker.get_open_position("EURUSD")
    check("restart recovery adopts the broker's position",
          UL.recovery_verdict(live, True) == UL.ADOPT)
    check("and an unreachable broker keeps it tracked, never 'closed'",
          UL.recovery_verdict(None, False) == UL.KEEP_TRACKED)
    risk = UL._risk_from_snapshot(snap.get("entryPrice"), snap.get("initialStop"))
    check("the initial risk is recoverable, so trailing resumes on the real R",
          risk is not None and risk > 0, str(risk))
    restart()
    check("and the retry is still refused", trade(broker, lambda *a: None).get("ok") is False)
    check("the broker was asked once in total", len(broker.orders) == 1)

    # ── 5. the window before the snapshot is closed ────────────────────────
    print("\n[5] a crash between send and confirm leaves an intent for recovery to adopt")
    STORE.kv.clear(); restart()
    STORE.users[USER] = {"id": USER, "paper": True}
    broker = Broker()
    try:
        trade(broker, die_after_send)
    except Crash:
        pass
    check("a position exists at the broker", broker.position is not None)
    snap = STORE.users[USER].get("open_position_snapshot") or {}
    check("and an INTENT snapshot is on record for restart recovery to find",
          snap.get("symbol") == "EURUSD" and snap.get("pending") is True, str(snap))
    check("with the original stop, which the broker cannot give back",
          snap.get("initialStop") == 1.09, str(snap.get("initialStop")))
    check("restart recovery adopts the broker's position",
          UL.recovery_verdict(broker.get_open_position("EURUSD"), True) == UL.ADOPT)
    check("the initial risk is recoverable, so trailing resumes on the real R",
          (UL._risk_from_snapshot(snap.get("entryPrice"), snap.get("initialStop")) or 0) > 0)

    print("\n[5b] a confirmed fill replaces the intent; a definite rejection restores the old snapshot")
    STORE.kv.clear(); restart()
    PREV = {"symbol": "GBPUSD", "side": "SELL", "entryPrice": 1.25, "units": 1000,
            "stopLoss": 1.26, "initialStop": 1.26, "openedAt": "2026-11-02 08:00:00"}
    STORE.users[USER] = {"id": USER, "paper": True, "open_position_snapshot": dict(PREV)}
    broker = Broker()
    out = trade(broker, real_persist)
    snap = STORE.users[USER].get("open_position_snapshot") or {}
    check("a filled order succeeded", out.get("ok") is True, str(out))
    check("and the confirmed snapshot is no longer pending",
          snap.get("symbol") == "EURUSD" and not snap.get("pending"), str(snap))

    STORE.kv.clear(); restart()
    STORE.users[USER] = {"id": USER, "paper": True, "open_position_snapshot": dict(PREV)}

    class Rejecting(Broker):
        def place_order(self, side, units, sym, sl=None, tp=None):
            self.orders.append((side, units, sym, sl, tp))
            raise RuntimeError("order rejected: invalid volume")

    broker = Rejecting()
    out = trade(broker, real_persist)
    check("the order was refused by the broker", out.get("ok") is False and out.get("ambiguous") is False, str(out))
    check("the broker was asked once", len(broker.orders) == 1)
    check("the PREVIOUS snapshot is put back, exactly",
          STORE.users[USER].get("open_position_snapshot") == PREV,
          str(STORE.users[USER].get("open_position_snapshot")))

    print("\n[5c] an ambiguous answer keeps the intent (a timeout may have filled)")
    STORE.kv.clear(); restart()
    STORE.users[USER] = {"id": USER, "paper": True, "open_position_snapshot": dict(PREV)}

    class TimedOut(Broker):
        def place_order(self, side, units, sym, sl=None, tp=None):
            self.orders.append((side, units, sym, sl, tp))
            raise RuntimeError("connection timed out")

    broker = TimedOut()
    out = trade(broker, real_persist)
    snap = STORE.users[USER].get("open_position_snapshot") or {}
    check("reported as ambiguous", out.get("ambiguous") is True, str(out))
    check("the intent stays on record for recovery to resolve",
          snap.get("symbol") == "EURUSD" and snap.get("pending") is True, str(snap))

    print("\n[5d] a safety-closed order withdraws its intent")
    STORE.kv.clear(); restart()
    STORE.users[USER] = {"id": USER, "paper": True, "open_position_snapshot": dict(PREV)}

    class SafetyClosed(Broker):
        def place_order(self, side, units, sym, sl=None, tp=None):
            self.orders.append((side, units, sym, sl, tp))
            return {"orderId": "o9", "status": "SAFETY_CLOSED", "fillPrice": 1.093,
                    "exitFillPrice": 1.0929, "reason": "no stop accepted"}

    out = trade(SafetyClosed(), real_persist)
    check("reported as opened-and-closed", out.get("error") == "OPENED_AND_CLOSED", str(out))
    check("the previous snapshot is back, not an open EURUSD",
          STORE.users[USER].get("open_position_snapshot") == PREV)

    print("\n[5e] a LIVE account whose intent cannot be written sends nothing")
    STORE.kv.clear(); restart()
    STORE.users[USER] = {"id": USER, "paper": False}
    _own, _auth, _upd = UL.ownership.may_trade, GATES.authorize_order, user_store.update
    UL.ownership.may_trade = lambda uid, live: (True, "OWNER")
    GATES.authorize_order = lambda *a, **k: (GATES.Decision(True, "ALLOWED", ""), "rid-5e")
    user_store.update = lambda uid, patch, **k: False       # the write does not land
    try:
        broker = Broker()
        out = trade(broker, real_persist)
    finally:
        UL.ownership.may_trade, GATES.authorize_order, user_store.update = _own, _auth, _upd
    check("the order is refused as SNAPSHOT_UNAVAILABLE", out.get("error") == "SNAPSHOT_UNAVAILABLE", str(out))
    check("and the broker was never asked", broker.orders == [], str(broker.orders))
    STORE.users[USER] = {"id": USER, "paper": True}
    STORE.kv.clear(); restart()
    _upd = user_store.update
    user_store.update = lambda uid, patch, **k: False
    try:
        broker = Broker()
        out = trade(broker, real_persist)
    finally:
        user_store.update = _upd
    check("(control) the same failure on a DEMO account still sends, as before",
          out.get("ok") is True and len(broker.orders) == 1, str(out))
finally:
    pass

# ── 6. the platform's live ledger ───────────────────────────────────────────
print("\n[6] platform live ledger: outcome write lost after the send")
from apex.platform import decision as D                     # noqa: E402
from apex.platform import live_ledger as LED                # noqa: E402

dec = D.RuleDecision(verdict=D.BUY, rule_doc_id="rule-x", rule_doc_version=1,
                     symbol="EURUSD", snapshot_ts=1_760_000_000.0, side=D.BUY,
                     reason="entry conditions met")
kw = dict(user_id=USER, account_id="9001", timeframe="1h", strategy=None)
STORE.kv.clear()
c1 = LED.claim(dec, **kw)
sent = []
sent.append("order")                         # the broker call happened ...
# ... and the process died before confirm_filled ran: no outcome, no release.
try:
    LED.claim(dec, **kw)
    second = None
except LED.AlreadyClaimed as e:
    second = e
check("a second tick on the same bar is refused", second is not None)
check("and it is the SAME decision's claim", second and second.setup_key == c1.setup_key)
check("with no outcome on record (the write was lost) — not read as 'free'",
      second is not None and second.outcome is None)
check("only one order was sent", len(sent) == 1)

row = LED.abandon_unknown(c1, detail="process died after the broker call")
check("recording UNKNOWN does not release the claim", row["released"] is False)
try:
    LED.claim(dec, **kw)
    again_ok = True
except LED.AlreadyClaimed:
    again_ok = False
check("so the retry is STILL refused after UNKNOWN", again_ok is False)

# A confirmed fill keeps the claim and records it; a confirmed rejection frees it.
STORE.kv.clear()
c2 = LED.claim(dec, **kw)
LED.confirm_filled(c2, broker_reply={"ok": True}, position_id="777001")
try:
    LED.claim(dec, **kw)
    refused_after_fill = False
except LED.AlreadyClaimed as e:
    refused_after_fill = (e.outcome or {}).get("outcome") == LED.FILLED
check("after a confirmed fill the retry is refused WITH the original outcome",
      refused_after_fill)

STORE.restore()
print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All crash-window checks passed.")
