"""What the performance report is allowed to claim.

Max drawdown used to be computed from each journal row's `balance` field —
the account balance at that moment. So anything that moved the balance
WITHOUT being a trade moved the curve, and the report attributed it to
trading:

  * A WITHDRAWAL read as a loss. Four winning trades and one $1,000 withdrawal
    from a $4,000 account reported "max drawdown 24.69%" — a dip the client
    never suffered, on a run where every single trade made money.
  * ONE WRONG ROW INVENTED A PEAK. A real journal carrying four foreign rows
    at $470,586 beside an account of ~$3,200 reported 99.32%. Over the same
    trades, excluding those rows, the true figure was 0.51%.

The curve is now rebuilt from realised P&L, anchored on what the account held
before the first closed trade. That makes it the same arithmetic as the netPnl
figure printed beside it — two numbers from one source instead of two sources
free to disagree — and deposits, withdrawals and a wrong balance field cannot
bend it.

And a drawdown past 100% is refused rather than printed. It means the equity
path went below zero, which a real brokered account cannot do (the broker
closes it out first), so the journal is not describing one consistent account
and no percentage from it is actionable. Same rule the trading gates use:
UNKNOWN is refused, not guessed. Every consumer must survive that None —
there were three, and two of them would have thrown.

Run: python tests/test_stats_equity.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex import stats  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name}  → {detail}")
    if not cond:
        failures.append(name)


def rows(spec):
    return [{"time": t, "netPnl": p, "balance": b} for t, p, b in spec]


print("\n📉  PERFORMANCE REPORT\n")

print("1. Money moving in or out is not a trading loss")
withdrew = rows([("d1", 10.0, 4000.0), ("d2", 10.0, 4010.0),
                 ("d3", 10.0, 3020.0),          # $1,000 withdrawn here
                 ("d4", 10.0, 3030.0)])
s = stats.compute(withdrew)
check("a withdrawal creates no drawdown", s["maxDrawdownPct"] == 0.0,
      f"{s['maxDrawdownPct']}% — every one of these four trades won")
check("…and the net P&L is still the trades", s["netPnl"] == 40.0, s["netPnl"])

deposited = rows([("d1", 10.0, 1000.0), ("d2", -50.0, 5950.0),  # +$5,000 in
                  ("d3", 10.0, 5960.0)])
d = stats.compute(deposited)
check("a deposit does not hide a real losing trade",
      d["maxDrawdownPct"] > 0, f"{d['maxDrawdownPct']}% — the -$50 must show")

print("\n2. One wrong row cannot invent a peak")
real = rows([("08-18", 100.60, 2909.14), ("08-19", -6.78, 3002.96),
             ("08-20", -0.26, 3214.00), ("08-21", 21.12, 3224.04),
             ("08-24", 21.69, 3243.51)])
foreign = rows([("08-19", 930.0, 470586.42)])
clean = stats.compute(real)
check("a clean journal reports a small, real drawdown",
      0 <= clean["maxDrawdownPct"] < 5, clean["maxDrawdownPct"])
mixed = stats.compute(real[:2] + foreign + real[2:])
check("the foreign row does not produce a 99% drawdown",
      mixed["maxDrawdownPct"] is None or mixed["maxDrawdownPct"] < 50,
      f"{mixed['maxDrawdownPct']}% — a $470k balance beside a $3k account")

print("\n3. The curve is the same arithmetic as the P&L beside it")
s2 = stats.compute(real)
anchor = real[0]["balance"] - real[0]["netPnl"]
check("it starts at what the account held before trade one",
      abs(s2["equity"][0]["value"] - (anchor + real[0]["netPnl"])) < 0.01,
      s2["equity"][0])
check("it ends at that anchor plus the reported net P&L",
      abs(s2["equity"][-1]["value"] - (anchor + s2["netPnl"])) < 0.02,
      f"{s2['equity'][-1]['value']} vs {anchor + s2['netPnl']}")
check("one point per closed trade",
      len(s2["equity"]) == s2["trades"], f"{len(s2['equity'])} vs {s2['trades']}")

print("\n4. An impossible drawdown is refused, not printed")
blown = rows([("a", 100.0, 3000.0), ("b", -32440.0, 470586.42),
              ("c", 21.0, 3243.0)])
b = stats.compute(blown)
check("a below-zero equity path yields None", b["maxDrawdownPct"] is None,
      f"{b['maxDrawdownPct']} — over 100% cannot describe a real account")
check("the rest of the report still computes", b["trades"] == 3
      and b["netPnl"] is not None)
check("an empty journal is 0, not None",
      stats.compute([])["maxDrawdownPct"] == 0.0,
      "no trades is 'no drawdown', not 'unknowable'")

print("\n5. Every consumer survives that None")
# Behaviour, not a substring: the naive text check flags the guarded call too,
# because `x!=null?x.toFixed(1):'—'` still contains `.toFixed` right after the
# name. In JS, count the guards against the calls — one guard per call, or a
# call is bare. In Python, actually render the message.
TERM = open(os.path.join(ROOT, "apex", "static", "terminal.html"),
            encoding="utf-8").read()
WEBAPP = open(os.path.join(ROOT, "apex", "webapp.py"), encoding="utf-8").read()
for name, src in (("terminal.html", TERM), ("webapp.py", WEBAPP)):
    calls = src.count("maxDrawdownPct.toFixed")
    guards = src.count("maxDrawdownPct!=null?")
    check(f"{name}: every .toFixed is behind a null guard",
          calls > 0 and guards >= calls,
          f"{calls} call(s), {guards} guard(s) — a bare one throws on None")

# The Telegram report, rendered for real with an unusable drawdown.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PRODUCT", "forex")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
import tempfile                                            # noqa: E402
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="apex-stats-"))
from apex import telegram as tg, user_store, user_loop      # noqa: E402

sent = []
_real_send, _real_dash = tg.send_to, user_loop.get_dash
try:
    tg.send_to = lambda cid, text, *a, **k: sent.append(text)
    user_loop.get_dash = lambda cid: {}
    for uid, spec, label in (
        ("stats-ok", [("a", 10.0, 1000.0), ("b", -50.0, 950.0)], "a normal journal"),
        ("stats-bad", [("a", 100.0, 3000.0), ("b", -32440.0, 470586.42)],
         "an inconsistent journal"),
        ("stats-empty", [], "an empty journal"),
    ):
        for t, p, b in spec:
            user_store.append_trade(uid, {"time": t, "symbol": "EURUSD",
                                          "netPnl": p, "balance": b})
        sent.clear()
        try:
            tg._handle_stats(uid)
            ok, why = bool(sent), ""
        except Exception as e:                              # noqa: BLE001
            ok, why = False, f"{type(e).__name__}: {e}"
        check(f"/report renders for {label}", ok, why)
    sent.clear()
    tg._handle_stats("stats-bad")
    check("the inconsistent one says why", any("inconsistent" in m for m in sent),
          sent[:1])
finally:
    tg.send_to, user_loop.get_dash = _real_send, _real_dash

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the report only claims what the trades support.")
