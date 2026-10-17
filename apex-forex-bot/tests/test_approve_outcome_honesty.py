"""An approved order reports what the BROKER did, not what was asked for.

THE BUG, AND IT WAS ON THE ONE PATH A HUMAN EXPLICITLY AUTHORISED

`force_trade` is what Approve and the bot's own /buy go through. It called
the broker like this:

    ledger.record(_rid, broker.place_order(side, units, sym, sl=..., tp=...))

— and never looked at the result. Two of `place_order`'s outcomes are not a
placed order:

  UNPROTECTED    the position IS open at the broker and has NO stop-loss.
                 The attach was rejected and the safety close failed too.
                 `force_trade` then persisted `stopLoss: sl_price` for it, so
                 the loop's own management believed a stop was in force at
                 the broker — and the client was told "placed, with your
                 stop".
  SAFETY_CLOSED  the position opened and was immediately closed again.
                 `force_trade` persisted it as OPEN, so the client was told
                 they held a trade that no longer existed and the next tick
                 managed a position that was gone.

The autonomous loop has handled both for a long time. The path where a human
said "yes, do this" handled neither.

WHY THE PERSISTED STOP MATTERS AS MUCH AS THE MESSAGE

`stopLoss` on the stored position is not decoration — the trailing stop and
break-even logic read it, and the UNPROTECTED branch of the loop reads it.
Writing the requested price there told every one of them that the broker was
holding a stop it had explicitly refused.

Run: python3 tests/test_approve_outcome_honesty.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-approve-")
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
from apex import user_loop as UL                            # noqa: E402
from apex import user_store                                 # noqa: E402

USER = "ffffffff-6666-4666-8666-ffffffffffff"

# A real config, from the real factory, so the sizing and stop arithmetic
# under test is the arithmetic production runs.
_REAL_CFG = UL._make_broker({"paper": True})[1]

_CANDLES = [{"open": 1.0920, "high": 1.0940, "low": 1.0910, "close": 1.0930,
             "time": 1_700_000_000 + i * 300} for i in range(60)]


class _Broker:
    """A broker whose stop-loss attach fails in a chosen way."""

    def __init__(self, status):
        self.status = status
        self.calls = []

    def get_candles(self, sym, tf, n):
        return _CANDLES[-int(n):]

    def get_bid_ask(self, sym):
        return 1.0929, 1.0931

    def get_balance(self):
        return 10_000.0

    def get_open_position(self, sym=None):
        return None

    def place_order(self, side, units, sym, sl=None, tp=None):
        self.calls.append((side, units, sym, sl, tp))
        if self.status == "FILLED":
            return {"orderId": "o1", "status": "FILLED", "fillPrice": 1.0930}
        if self.status == "UNPROTECTED":
            return {"orderId": "o1", "status": "UNPROTECTED",
                    "fillPrice": 1.0930,
                    "reason": "the broker rejected the stop-loss and the "
                              "safety close did not go through — the "
                              "position is open with no stop"}
        return {"orderId": "o1", "status": "SAFETY_CLOSED",
                "fillPrice": 1.0930, "exitFillPrice": 1.0928,
                "commissionUsd": 0.0,
                "reason": "could not attach stop-loss at the broker — "
                          "position closed immediately for safety"}


def run(status, symbol="EURUSD"):
    """Drive the real force_trade against that broker.

    Everything around the broker is stubbed to the minimum that gets the
    call through the gate, because what is under test is what happens to the
    RESULT — not the gate, which has its own tests.
    """
    saved = {n: getattr(UL, n) for n in
             ("_make_broker", "_persist_open_position", "get_dash",
              "_alert_fn_for")}
    _ent = GATES.live_entitlement
    persisted = []
    alerts = []
    br = _Broker(status)
    user_store.save(USER, {"id": USER, "paper": True})
    try:
        UL._make_broker = lambda user, user_id=None: (br, _REAL_CFG)
        UL._persist_open_position = lambda uid, cfg, pos: persisted.append(pos)
        UL.get_dash = lambda uid: {}
        UL._alert_fn_for = lambda uid, fn: (
            lambda u, payload: alerts.append(payload))
        # Entitlement only. The REAL gate still runs — what is under test is
        # what happens to the broker's answer, and a test that stubbed the
        # gate would not prove the call reached the broker through it.
        GATES.live_entitlement = lambda uid, u=None: ("allowed", "stubbed")
        # A DISTINCT instrument per case. The idempotency ledger refuses an
        # identical order within its window — correctly — so re-running the
        # same BUY/EURUSD/0.01 three times tested the ledger, not this.
        out = UL.force_trade(USER, "BUY", symbol=symbol, lots=0.01,
                             sl_override=1.0900, tp_override=1.0960,
                             origin="approval")
    finally:
        for name, fn in saved.items():
            setattr(UL, name, fn)
        GATES.live_entitlement = _ent
    return out, persisted, alerts, br


# ── 1. an open position with no stop is not reported as placed ──────────────
print("\n[1] UNPROTECTED is not reported as a placed order")
out, persisted, alerts, br = run("UNPROTECTED")
check("the broker was asked for the stop the client wanted",
      br.calls and br.calls[0][3] == 1.0900, str(br.calls))
check("the answer is not ok", out.get("ok") is not True, str(out))
check("and it is named, not blamed on something generic",
      out.get("error") == "OPEN_WITHOUT_STOP", str(out.get("error")))
check("the detail says the position is open with no stop",
      "no stop" in str(out.get("detail")).lower(), str(out.get("detail")))

print("\n[2] and the stop it does NOT have is not written down")
# The half that matters to the engine rather than to the reader. Trailing,
# break-even and the loop's own UNPROTECTED branch all read this field.
check("the position is still persisted, so the loop keeps managing it",
      len(persisted) == 1, str(persisted))
if persisted:
    check("with NO stop-loss recorded", persisted[0].get("stopLoss") is None,
          f"{persisted[0].get('stopLoss')} — recording the requested price "
          f"tells the trailing logic the broker is holding a stop it refused")
    check("and no initial stop either",
          persisted[0].get("initialStop") is None,
          str(persisted[0].get("initialStop")))
    check("at the price the broker actually filled",
          persisted[0].get("entryPrice") == 1.0930,
          str(persisted[0].get("entryPrice")))

print("\n[3] and the client is alerted, not left to find out")
check("an UNPROTECTED alert was raised",
      any(a.get("action") == "UNPROTECTED" for a in alerts), str(alerts))


# ── 4. a position that was closed again is not reported as open ─────────────
print("\n[4] SAFETY_CLOSED is not reported as an open position")
out, persisted, alerts, br = run("SAFETY_CLOSED", "USDJPY")
check("the answer is not ok", out.get("ok") is not True, str(out))
check("and it is named", out.get("error") == "OPENED_AND_CLOSED",
      str(out.get("error")))
check("NOTHING is persisted as open", not persisted,
      f"{persisted} — the client would be shown a position they do not hold, "
      f"and the next tick would manage one that is gone")
check("the detail says it was closed again",
      "closed" in str(out.get("detail")).lower(), str(out.get("detail")))


# ── 5. a real fill is still a real fill ─────────────────────────────────────
print("\n[5] a successful order is unchanged")
out, persisted, alerts, br = run("FILLED", "GBPUSD")
check("it reports ok", out.get("ok") is True, str(out))
check("the position is persisted", len(persisted) == 1, str(persisted))
if persisted:
    check("WITH the stop the broker accepted",
          persisted[0].get("stopLoss") == 1.0900,
          str(persisted[0].get("stopLoss")))
check("and nothing was alerted", not alerts, str(alerts))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All approve-outcome honesty checks passed.")
