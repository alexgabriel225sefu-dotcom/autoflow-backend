"""A trailing stop must not delete the take-profit.

ProtoOAAmendPositionSLTPReq carries `stopLoss` and `takeProfit` as proto2
OPTIONAL fields. A value the caller omits is genuinely absent from the wire
message, and the cTrader server reads absent as "no protection" rather than
"leave it alone" — so amending only the stop DELETES the target.

Confirmed on the owner's live account rather than inferred:

    order    BUY GBPUSD units=5848 @~1.36441 SL=1.36138 TP=1.37047
    trail    STOP_MOVED GBPUSD sl=1.36168        (amend, sl only)
    broker   position now reports takeProfit: None

`get_open_position` reads that field through `HasField`, so None there is the
broker's own answer, not ours. Every trailing or break-even ratchet was
quietly removing the trade's own target: from that moment the position could
only be closed by its stop, by a discretionary exit, or by the weekend
flatten. It could never reach the target it was opened for.

This is the kind of defect that hides in a green test suite — the amend
succeeds, the stop really does move, the log line is correct, and nothing
anywhere says the target is gone.

Run: python tests/test_trailing_keeps_tp.py
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PRODUCT", "forex")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="apex-tp-"))

from apex import user_loop  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name}  → {detail}")
    if not cond:
        failures.append(name)


class _Broker:
    """Records what actually went on the wire."""

    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    def amend_sltp(self, position_id, sl=None, tp=None, instrument=None):
        self.calls.append({"pid": position_id, "sl": sl, "tp": tp,
                           "instrument": instrument})
        return self.ok


class _Cfg:
    TRAILING_STOP = True
    BREAKEVEN_AT_R = 1.0


print("\n🎯  TRAILING KEEPS THE TARGET\n")

print("1. A ratchet carries the take-profit with it")
POS = {"positionId": 42, "entryPrice": 1.36441, "stopLoss": 1.36138,
       "takeProfit": 1.37047, "side": "BUY", "symbol": "GBPUSD"}
b = _Broker()
moved = user_loop._manage_trailing(b, _Cfg(), dict(POS), "GBPUSD", 1.3690,
                                   initial_risk=0.00303)
check("the stop did move", moved is not None and b.calls, moved)
if b.calls:
    call = b.calls[-1]
    check("…and the take-profit went with it", call["tp"] == 1.37047,
          f"tp={call['tp']} — omitting it deletes the target at the broker")
    check("the new stop is tighter, never looser", call["sl"] > POS["stopLoss"],
          call["sl"])
    check("the stop stays below price on a BUY", call["sl"] < 1.3690, call["sl"])

print("\n2. It works off `tp` too, not only `takeProfit`")
alt = dict(POS)
del alt["takeProfit"]
alt["tp"] = 1.37047
b2 = _Broker()
user_loop._manage_trailing(b2, _Cfg(), alt, "GBPUSD", 1.3690, initial_risk=0.00303)
check("the alternate key is read", b2.calls and b2.calls[-1]["tp"] == 1.37047,
      b2.calls[-1] if b2.calls else "no call")

print("\n3. A position with no target stays without one")
none_tp = dict(POS)
none_tp["takeProfit"] = None
b3 = _Broker()
user_loop._manage_trailing(b3, _Cfg(), none_tp, "GBPUSD", 1.3690,
                           initial_risk=0.00303)
check("no target is passed as None, not invented",
      b3.calls and b3.calls[-1]["tp"] is None,
      b3.calls[-1] if b3.calls else "no call")

print("\n4. Every call site passes both sides")
# Mechanical, because this is a defect of OMISSION: the call that forgets `tp`
# looks completely normal, succeeds, and moves the stop correctly.
SRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
calls = re.findall(r"amend_sltp\((.*?)\)\s*:", SRC, re.S)
calls = [c for c in calls if "pid" in c or "position_id" in c]
check("found the call sites", len(calls) >= 2, f"{len(calls)} found")
for i, c in enumerate(calls, 1):
    flat = " ".join(c.split())
    check(f"call site {i} passes tp=", "tp=" in flat, flat[:90])

print("\n5. A refused amend does not pretend it worked")
b4 = _Broker(ok=False)
res = user_loop._manage_trailing(b4, _Cfg(), dict(POS), "GBPUSD", 1.3690,
                                 initial_risk=0.00303)
check("a broker refusal returns None", res is None, res)
check("…and it was attempted", len(b4.calls) == 1, b4.calls)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the trail moves the stop, not the target.")
