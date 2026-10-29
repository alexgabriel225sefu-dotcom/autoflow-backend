"""Does the broker's minimum order size risk more than the client chose?

WHY THIS EXISTS

On 2026-10-28 a client chose 1% per trade on a $3,817 account and started gold.
The broker's minimum for gold is 1 oz and a stop of about 2.5 x ATR on the
hourly chart is close to $100, so each trade risked 2.2%-2.7%, not 1%. Nothing
on the Trade page said so before Start; the first loss was $84 and the day
ended 4.9% down. The engine already notes this once it has traded
(`minLotNotice`); this is the same fact, asked for BEFORE Start.

WHAT THESE TESTS WILL NOT ACCEPT

* an estimate that says "fine" when the minimum size risks several times the
  chosen risk, or one that cries wolf on an ordinary FX trade;
* a number shown without its basis, or without saying it is an estimate;
* the read being anything but a read: no order-mutating name, no data key when
  the broker did not answer, metered with the other market-data reads, and a
  route that needs a session.

Run: python3 tests/test_platform_min_lot.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-minlot-")
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


from apex import forex                                   # noqa: E402
from apex.platform import broker_read as BR              # noqa: E402
from apex.platform import ratelimit as RL                # noqa: E402

print("\n[1] the 28 October case")
# Gold near 4040 with an hourly ATR of about $40: 2.5 x ATR is a $100 stop.
gold = BR.estimate_min_lot(balance=3817.21, risk_fraction=0.01, symbol="XAUUSD",
                           price=4040.0, atr=40.0, broker_min=1.0)
check("it says the minimum size exceeds what was chosen", gold and gold["exceeds"], str(gold))
check("at 1 oz, about $100 of stop risks about $100", gold and 90 <= gold["riskUsd"] <= 110, str(gold))
check("which is more than twice the 1% chosen", gold and gold["riskPct"] > 2 * gold["targetPct"], str(gold))
check("and names the minimum and its unit", gold and gold["minUnits"] == 1.0 and gold["unitLabel"] == "oz", str(gold))
check("the target is the client's own 1%", gold and abs(gold["targetUsd"] - 38.17) < 0.01, str(gold))

print("\n[2] it does not cry wolf")
eur = BR.estimate_min_lot(balance=3817.21, risk_fraction=0.01, symbol="EURUSD",
                          price=1.0850, atr=0.0012, broker_min=1000)
check("an ordinary FX trade fits inside the chosen risk", eur and not eur["exceeds"], str(eur))
big = BR.estimate_min_lot(balance=250_000, risk_fraction=0.01, symbol="XAUUSD",
                          price=4040.0, atr=40.0, broker_min=1.0)
check("a large account sizes gold to the target, not to the minimum",
      big and not big["exceeds"] and big["units"] > 1, str(big))

print("\n[3] it will not guess")
check("no ATR, no estimate",
      BR.estimate_min_lot(balance=3817, risk_fraction=0.01, symbol="XAUUSD",
                          price=4040, atr=0, broker_min=1) is None)
check("no balance, no estimate",
      BR.estimate_min_lot(balance=0, risk_fraction=0.01, symbol="XAUUSD",
                          price=4040, atr=40, broker_min=1) is None)
check("junk is no estimate",
      BR.estimate_min_lot(balance="x", risk_fraction=0.01, symbol="XAUUSD",
                          price=4040, atr=40, broker_min=1) is None)

print("\n[4] the read: a status, never a guess")


def bars(n=60, base=4000.0, rng=40.0):
    out, px = [], base
    for i in range(n):
        out.append({"open": px, "high": px + rng / 2, "low": px - rng / 2,
                    "close": px + (1 if i % 2 else -1), "time": i})
        px = out[-1]["close"]
    return out


class _Broker:
    def __init__(self, boom=None, minimum=1.0, few=False):
        self.boom, self.minimum, self.few = boom, minimum, few

    def get_candles(self, sym, tf, n):
        if self.boom:
            raise self.boom
        return bars(5 if self.few else 60)

    def get_balance(self):
        return 3817.21

    def min_units(self, sym):
        return self.minimum


def conn_fn(uid, ctid=None):
    return {"ctid": "801", "mode": "demo", "accessToken": "SECRET-TOKEN"}


ok = BR.min_lot("u1", symbol="XAUUSD", timeframe="1h", risk_percent=1,
                connection_fn=conn_fn, broker_fn=lambda: _Broker())
check("an answered read is ok and carries the estimate",
      ok.get("status") == "ok" and ok["minLot"]["exceeds"] is True, str(ok))
check("with its basis, so it can be shown as an estimate",
      "ATR" in ok["minLot"]["basis"], str(ok))
check("and the account and mode it was read for", ok.get("accountId") == "801" and ok.get("mode") == "demo")
bad = BR.min_lot("u1", symbol="XAUUSD", timeframe="1h", risk_percent=1,
                 connection_fn=conn_fn,
                 broker_fn=lambda: _Broker(boom=RuntimeError("connect failed SECRET-TOKEN")))
check("a broker that cannot answer is `unavailable`, with no data key",
      bad.get("status") == "unavailable" and "minLot" not in bad, str(bad))
check("and the reason carries no token", "SECRET-TOKEN" not in str(bad), str(bad))
few = BR.min_lot("u1", symbol="XAUUSD", timeframe="1h", risk_percent=1,
                 connection_fn=conn_fn, broker_fn=lambda: _Broker(few=True))
check("too few bars to estimate a stop is `unavailable`, not a made-up number",
      few.get("status") == "unavailable" and "minLot" not in few, str(few))
none = BR.min_lot("u1", symbol="XAUUSD", timeframe="1h", risk_percent=1,
                  connection_fn=lambda uid, ctid=None: None)
check("nothing connected reads as not connected",
      none.get("connected") is False and "minLot" not in none, str(none))

print("\n[5] a bad request is refused before a broker is opened")
opened = []
for label, kw in [("an unknown timeframe", dict(symbol="XAUUSD", timeframe="7h", risk_percent=1)),
                  ("a symbol the engine does not trade", dict(symbol="US30", timeframe="1h", risk_percent=1)),
                  ("a risk of zero", dict(symbol="XAUUSD", timeframe="1h", risk_percent=0)),
                  ("a risk over 100", dict(symbol="XAUUSD", timeframe="1h", risk_percent=101)),
                  ("a risk that is not a number", dict(symbol="XAUUSD", timeframe="1h", risk_percent="lots"))]:
    try:
        BR.min_lot("u1", connection_fn=lambda *a, **k: opened.append(1) or conn_fn(*a), **kw)
        check(f"{label} is refused", False, "no ValueError")
    except ValueError:
        check(f"{label} is refused", True)
check("and none of them opened a broker", opened == [], str(opened))

print("\n[6] it is a read, wired like one")
check("`trade/min-lot` is metered with the other broker market-data reads",
      RL.classify("GET", "trade/min-lot") == "candles", RL.classify("GET", "trade/min-lot"))
api_src = open(os.path.join(ROOT, "apex", "platform", "api.py"), encoding="utf-8").read()
block = api_src[api_src.index('if route == "trade/min-lot"'):][:600]
check("the route authenticates before it reads", "_authenticate(headers)" in block, block)
src = open(os.path.join(ROOT, "apex", "platform", "broker_read.py"), encoding="utf-8").read()
fn = src[src.index("def estimate_min_lot"):src.index("def _shape")]
for banned in ("place_order", "close_position", "amend_sltp", "force_trade",
               "authorize_order", "bridge", "live_execution"):
    check(f"the estimate names no `{banned}`", banned not in fn)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All minimum-lot checks passed.")
