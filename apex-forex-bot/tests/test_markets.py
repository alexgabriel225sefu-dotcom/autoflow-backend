"""The Markets board must not spend the broker's allowance, or invent a price.

cTrader's documented limit is the constraint:

    "5 requests per second for any historical data requests. These limits are
     per connection, no matter how many users are authorized through it."

Daily bars are historical. Eight instruments, fetched per client per screen
open, is the same waste candle_cache was built to end — except on a screen
every client opens first. So one snapshot serves everyone.

The second half is honesty. A price nobody quoted must never appear as 0.00,
and a stale snapshot must never be presented as today's.

Run: python tests/test_markets.py
"""
import base64
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


if not shutil.which("redis-server"):
    print("\n  SKIP  redis-server not on PATH — these checks CANNOT run here.")
    sys.exit(0)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
_redis = subprocess.Popen(
    ["redis-server", "--port", str(PORT), "--save", "", "--appendonly", "no"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)
os.environ["REDIS_URL"] = f"redis://127.0.0.1:{PORT}/0"
os.environ["APP_ENV"] = "production"
os.environ["PRODUCT"] = "forex"
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-signing-secret")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="apex-mkt-"))
os.environ.setdefault("TOKEN_ENCRYPTION_KEY",
                      base64.urlsafe_b64encode(os.urandom(32)).decode())

from apex import markets as mk  # noqa: E402


class Broker:
    """Counts every historical fetch, because that is the thing being bounded."""

    def __init__(self, **behaviour):
        self.calls = 0
        self.behaviour = behaviour

    def get_candles(self, instrument=None, interval=None, limit=None, to_ts=None):
        self.calls += 1
        b = self.behaviour.get(instrument, "ok")
        if b == "raise":
            raise RuntimeError("broker said no")
        if b == "empty":
            return []
        if b == "one":
            return [{"close": 1.0}]
        if b == "zero":
            return [{"close": 0}, {"close": 1.10}]
        return [{"close": 1.00}, {"close": 1.10}]


def fresh():
    # Only the shared snapshot. The broker's own candle cache is a separate
    # layer with its own test; the fake broker here has none, so a reset would
    # be resetting nothing.
    mk.reset()


print("\n1. One snapshot serves every client")
fresh()
b = Broker()
first = mk.snapshot(b)
after_one = b.calls
for _ in range(25):
    mk.snapshot(b)
check(f"the first build fetches once per instrument ({after_one})",
      after_one == len(first["rows"]), f"{after_one} vs {len(first['rows'])}")
check(f"25 further clients cost nothing ({b.calls} total)", b.calls == after_one,
      "a per-client fetch would spend cTrader's historical allowance on one screen")
check("and they are served the cached answer", mk.snapshot(b)["cached"] is True)

print("\n2. The universe is what the platform actually trades")
forex, metals = mk.universe()
check("forex instruments are listed", len(forex) > 0, str(forex))
check("metals are separated", all(m in ("XAUUSD", "XAGUSD") for m in metals), str(metals))
check("no instrument appears in both", not set(forex) & set(metals))
syms = {r["symbol"] for r in first["rows"]}
check("every listed instrument is in the snapshot", set(forex + metals) == syms)

print("\n3. Change is measured against the previous close")
fresh()
row = mk.snapshot(Broker())["rows"][0]
check("price is the latest close", row["price"] == 1.10, str(row))
check("change is +10.00% from 1.00 to 1.10", row["changePct"] == 10.0, str(row))

print("\n4. A price nobody quoted is never invented")
fresh()
sym = mk.universe()[0][0]
for behaviour, why in (("raise", "broker error"), ("empty", "no bars"),
                       ("one", "a single bar"), ("zero", "a zero previous close")):
    fresh()
    rows = mk.snapshot(Broker(**{sym: behaviour}))["rows"]
    r = next(x for x in rows if x["symbol"] == sym)
    check(f"{why} -> unavailable, not a number", r["available"] is False, str(r))
    check(f"...and carries no price field ({why})", "price" not in r, str(r))
    check(f"...and no zero change ({why})", r.get("changePct") is None, str(r))

print("\n5. A total blackout keeps the last snapshot, and says it is old")
fresh()
good = Broker()
built = mk.snapshot(good)
check("a good snapshot is built", any(r["available"] for r in built["rows"]))
time.sleep(0.01)
dead = Broker(**{s: "raise" for s in mk.universe()[0] + mk.universe()[1]})
out = mk.snapshot(dead, force=True)
check("the previous rows are still served", any(r["available"] for r in out["rows"]),
      "an empty board reads as 'the market has nothing', which is a different claim")
check("...and it is flagged stale", out.get("stale") is True, str(out.get("stale")))
check("the UI is told when it was from", isinstance(out.get("asOf"), int))

print("\n6. The endpoint is scoped to an authenticated client")
BOT = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()
route = BOT[BOT.index('if self.path.startswith("/api/app/markets")'):]
route = route[:route.index("/api/app/tick")]
check("identity is checked before any broker work",
      route.index("_telegram_identity") < route.index("_make_broker"),
      "an unauthenticated caller must not be able to make us poll a broker")
check("a denied caller is refused", "_telegram_denied" in route)
check("a broker failure answers a reason, not an empty list",
      "MARKET_DATA_UNAVAILABLE" in route)

print("\n7. The screen renders unavailable as unavailable")
HTML = open(os.path.join(ROOT, "apex", "static", "terminal.html"), encoding="utf-8").read()
check("a row with no price says so", "'</div><div class=\"mpx\">unavailable</div>" in HTML
      or 'unavailable</div>' in HTML)
check("free margin is not derived and shown as a broker fact",
      "not reported by the ctrader account api" in HTML.lower())
check("markets polls on its own cadence, not the position tick",
      "setInterval(()=>loadMarkets(), 30000)" in HTML)

print("\n8. Symbol detail refuses an instrument the platform does not trade")
SYM = BOT[BOT.index('if self.path.startswith("/api/app/symbol")'):]
SYM = SYM[:SYM.index('if self.path.startswith("/api/app/account")')]
SYMC = "\n".join(l for l in SYM.splitlines() if not l.strip().startswith("#"))
check("the symbol is checked against the universe BEFORE a broker is built",
      SYMC.index("_y_mk.universe()") < SYMC.index("_make_broker"),
      "a crafted value must not become a broker request")
check("an unknown instrument is refused by name", "UNKNOWN_INSTRUMENT" in SYMC)
check("the timeframe is an allowlist, not free text",
      '("1m", "5m", "15m", "1h", "4h", "1d")' in SYMC)
check("the symbol is length-clamped", "[:16]" in SYMC)
check("candles go through the broker's cached path",
      "_y_br.get_candles(" in SYMC,
      "get_candles routes through candle_cache, so two clients on the same "
      "instrument cost one historical request")
check("no candles is stated, not drawn as an empty chart",
      "MARKET_DATA_UNAVAILABLE" in SYMC)
check("spread is omitted when either quote is missing",
      "_y_bid is not None and _y_ask is not None" in SYMC,
      "a spread computed from one live and one stale quote is a made-up number")
check("the position drawn on the chart is read server-side",
      "get_dash(_y_chat)" in SYMC and '"position"' in SYMC)
check("...and is never taken from the request",
      "_y_qs.get(\"pos\")" not in SYMC and '"entryPrice"' in SYMC)
check("identity is checked first",
      SYMC.index("_telegram_identity") < SYMC.index("_y_mk.universe()"))
import re as _re
check("every route local is prefixed",
      not {m.group(1) for m in _re.finditer(r'^\s+([a-z][\w]*) = (?!=)', SYMC, _re.M)})

print("\n9. The screen opens an instrument, and says when it cannot")
check("a market row opens the instrument", "openSymbol(row.dataset.sym)" in HTML)
check("the screen exists", 'id="s-symbol"' in HTML and 'id="symChart"' in HTML)
check("it has its own chart object, not a shared one", "symChart=mkChart(" in HTML)
check("an untraded instrument is worded plainly",
      "not one the platform trades" in HTML)
check("unavailable data is worded, not blanked",
      "Market data for this instrument is unavailable" in HTML)
check("a missing quote renders as unavailable, not zero",
      'class="na">Not available' in HTML)

mk.reset()
print("\n" + "=" * 50)
_redis.terminate()
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL MARKETS CHECKS PASSED - one fetch for everyone, and no invented price.")
