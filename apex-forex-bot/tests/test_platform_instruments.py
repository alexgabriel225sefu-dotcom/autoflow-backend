"""What a broker lists, and which of it the engine can trade today.

WHY THIS EXISTS

A client's broker lists far more than the engine can size a position for.
Showing only the instruments that work hides what the broker offers; showing
everything as selectable puts a refusal far from the choice. So the whole list is
served, each entry classified, and the reason given when it cannot be traded.

WHAT THESE TESTS WILL NOT ACCEPT

* `tradeable` coming from anywhere but the engine's own allowlist
  (`forex.is_tradeable`): a second list would eventually disagree with the one
  that refuses the order;
* an index, a cross, a stock or a coin ever marked tradeable;
* a refusal with no reason, or a tradeable instrument carrying one;
* a duplicate or empty entry, or a symbol that raises;
* the read being anything but a read: no order-mutating name in the path, an
  absent data key when the broker did not answer, and a route that needs a
  session.

Run: python3 tests/test_platform_instruments.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-instr-")
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
from apex.platform import instruments as I               # noqa: E402
from apex.platform import ratelimit as RL                # noqa: E402

print("\n[1] tradeable is the engine's own answer")
NAMES = ["EURUSD", "EUR/USD", "GBP_USD", "USDJPY", "XAUUSD", "XAGUSD", "XAUEUR",
         "GBPJPY", "EURGBP", "AUDCHF", "US30", "NAS100", "SPX500", "GER40",
         "AAPL", "TSLA", "BTCUSD", "ETHUSD", "WEIRD_1", "123"]
for n in NAMES:
    c = I.classify(n)
    check(f"{n}: tradeable == forex.is_tradeable", c["tradeable"] == forex.is_tradeable(n),
          str(c))

print("\n[2] nothing the engine cannot size is ever offered")
for n in ["GBPJPY", "EURGBP", "AUDCHF", "US30", "NAS100", "SPX500", "GER40",
          "AAPL", "BTCUSD", "ETHUSD"]:
    check(f"{n} is not tradeable", I.classify(n)["tradeable"] is False)
for prefix in I.INDEX_PREFIXES:
    check(f"index prefix {prefix} is not tradeable on the engine's allowlist",
          not forex.is_tradeable(prefix + "X"),
          "an index the engine accepts would be shown as unsupported")

print("\n[3] classes and reasons")
expect = {"EURUSD": I.FOREX, "XAUUSD": I.METAL, "GBPJPY": I.CROSS, "US30": I.INDEX,
          "AAPL": I.STOCK, "BTCUSD": I.CRYPTO, "WEIRD_1": I.OTHER}
for n, cls in expect.items():
    check(f"{n} is {cls}", I.classify(n)["class"] == cls, str(I.classify(n)))
for n in NAMES:
    c = I.classify(n)
    if c["tradeable"]:
        check(f"{n}: tradeable carries no reason", c["reason"] is None)
    else:
        check(f"{n}: a refusal says why", bool(c["reason"]), str(c))
check("a cross's reason names the missing USD leg",
      "USD" in I.classify("GBPJPY")["reason"])
check("an index's reason names the calendar",
      "calendar" in I.classify("US30")["reason"])

print("\n[4] describe: sorted, de-duplicated, never raising")
d = I.describe(["US30", "EURUSD", "EUR/USD", "", None, "GBPJPY", "XAUUSD", "eurusd"])
ids = [c["id"] for c in d]
check("duplicates collapse", ids.count("EURUSD") == 1, str(ids))
check("empty and None are dropped", "" not in ids and len(ids) == 4, str(ids))
check("tradeable instruments come first",
      [c["tradeable"] for c in d] == sorted([c["tradeable"] for c in d], reverse=True),
      str([(c["id"], c["tradeable"]) for c in d]))
check("an empty or missing list is an empty list", I.describe([]) == [] and I.describe(None) == [])

print("\n[5] the read: a status, never a guess")


class _Broker:
    def __init__(self, names=None, boom=None):
        self.names, self.boom = names, boom

    def list_symbols(self):
        if self.boom:
            raise self.boom
        return self.names


def conn_fn(uid, ctid=None):
    return {"ctid": "801", "mode": "demo", "accessToken": "SECRET-TOKEN"}


ok = BR.symbols("u1", connection_fn=conn_fn,
                broker_fn=lambda: _Broker(["EURUSD", "US30", "GBPJPY"]))
check("an answered read is ok and carries the classified list",
      ok.get("status") == "ok" and [c["id"] for c in ok["symbols"]][0] == "EURUSD", str(ok))
check("and names the account and mode it was read for",
      ok.get("accountId") == "801" and ok.get("mode") == "demo")
bad = BR.symbols("u1", connection_fn=conn_fn,
                 broker_fn=lambda: _Broker(boom=RuntimeError("connect to host.example:5035 failed SECRET-TOKEN")))
check("a broker that cannot answer is `unavailable`, with no data key",
      bad.get("status") == "unavailable" and "symbols" not in bad, str(bad))
check("and the reason carries no token", "SECRET-TOKEN" not in str(bad), str(bad))
none = BR.symbols("u1", connection_fn=lambda uid, ctid=None: None)
check("nothing connected reads as not connected, not as an empty menu",
      none.get("connected") is False and "symbols" not in none, str(none))

print("\n[6] it is a read, wired like one")
src = open(os.path.join(ROOT, "apex", "platform", "instruments.py"), encoding="utf-8").read()
for banned in ("place_order", "close_position", "amend_sltp", "force_trade",
               "authorize_order", "bridge", "live_execution"):
    check(f"instruments.py names no `{banned}`", banned not in src)
check("`symbols` is metered with the other broker market-data reads",
      RL.classify("GET", "symbols") == "candles", RL.classify("GET", "symbols"))
api_src = open(os.path.join(ROOT, "apex", "platform", "api.py"), encoding="utf-8").read()
block = api_src[api_src.index('if route == "symbols"'):][:400]
check("the route authenticates before it reads", "_authenticate(headers)" in block, block)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All instrument checks passed.")
