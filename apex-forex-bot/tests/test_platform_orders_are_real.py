"""A platform order must reach the broker, not a print statement.

THE BUG THIS FILE EXISTS TO CATCH, AND IT WOULD HAVE REPORTED SUCCESS

`brokers/ctrader.place_order` opens with:

    if getattr(self._c, "PAPER_TRADING", True):
        print(f"[PAPER][cTrader] {side} {units} {sym} sl={sl} tp={tp}")
        return {"orderId": f"CT_PAPER_{...}", "status": "FILLED"}

and `user_loop._make_broker` built a platform client's config with

    paper = _conn["mode"] != "live"

so every platform client on a DEMO account ran with PAPER_TRADING=True. The
loop would evaluate the rule, decide to buy, "place" the order, receive
`status: FILLED`, journal it and show an open position — while cTrader
received nothing at all.

That is the worst shape a bug can take here. Every screen this product owns
would have agreed the trade happened. The only way to find it was to look at
the broker, and the first person to do that would have been a client.

`paper` and the account's MODE are different axes, and `_mode_of` in
user_loop.py says so in prose while naming the account this broke:

    "`paper` distinguishes simulated fills from broker-executed ones; it says
     nothing about whether the broker account is real money. Account 47765456
     runs paper=false against a cTrader DEMO account"

Run: python3 tests/test_platform_orders_are_real.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-realorders-")
os.environ["DATA_DIR"] = _TMP
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


from apex import user_loop                                  # noqa: E402
from apex.platform import ctrader_link as CTL               # noqa: E402

USER = "11111111-2222-4333-8444-555555555555"


def broker_for(mode):
    """The config `_make_broker` builds for a platform account in `mode`."""
    def _conn(uid, **kw):
        return {"accessToken": "not-a-real-token", "ctid": 47765456,
                "mode": mode, "userId": uid}
    real = CTL.get_ctrader_connection
    # The real CTraderBroker constructor opens a socket to cTrader. This test
    # is about the CONFIG that constructor is handed, so it is stubbed — the
    # first version of this file hung for two minutes on a live connection.
    real_broker = user_loop._CtraderBroker
    user_loop._CtraderBroker = lambda cfg: object()
    CTL.get_ctrader_connection = _conn
    try:
        # A user record with NO cTrader credentials of its own, which is what
        # a platform client has — the tokens live in the platform namespace.
        _b, cfg = user_loop._make_broker({}, USER)
        return cfg
    finally:
        CTL.get_ctrader_connection = real
        user_loop._CtraderBroker = real_broker


# ── 1. a demo platform account places REAL orders ───────────────────────────
print("\n[1] a platform DEMO account is executed, not simulated")
cfg = broker_for("demo")
check("PAPER_TRADING is off",
      getattr(cfg, "PAPER_TRADING", None) is False,
      f"PAPER_TRADING={getattr(cfg, 'PAPER_TRADING', None)!r} — the broker "
      f"would return a fake CT_PAPER fill and never contact cTrader")
check("and the demo/live axis is carried by ctrader_env",
      getattr(cfg, "CTRADER_ENV", None) == "demo",
      f"CTRADER_ENV={getattr(cfg, 'CTRADER_ENV', None)!r}")

# ── 2. a live platform account, same answer on this axis ────────────────────
print("\n[2] a platform LIVE account is executed too, and says so")
cfg = broker_for("live")
check("PAPER_TRADING is off",
      getattr(cfg, "PAPER_TRADING", None) is False)
check("and ctrader_env reports live",
      getattr(cfg, "CTRADER_ENV", None) == "live",
      "this is the axis that selects the live endpoint")

# ── 3. the two axes are genuinely independent ───────────────────────────────
# The failure was treating one as the other. Asserting they DIFFER between
# demo and live on one axis and AGREE on the other is what pins that apart.
print("\n[3] mode and simulation are separate facts")
demo, live = broker_for("demo"), broker_for("live")
check("the environments differ",
      demo.CTRADER_ENV != live.CTRADER_ENV,
      "mode must still be distinguishable")
check("but neither simulates",
      demo.PAPER_TRADING is False and live.PAPER_TRADING is False,
      "a connected account is executed on whichever server its mode names")

# A platform read supplies the selected ctid explicitly. Older user records
# can still carry ctrader_account_id=None; that must not become int(None) in
# the broker constructor.
print("\n[3b] an explicitly selected account repairs a null legacy id")
real_broker = user_loop._CtraderBroker
real_conn = CTL.get_ctrader_connection
user_loop._CtraderBroker = lambda cfg: object()
CTL.get_ctrader_connection = lambda uid, **kw: {
    "accessToken": "not-a-real-token", "ctid": 47765456,
    "mode": "demo", "userId": uid,
}
try:
    _b, cfg = user_loop._make_broker(
        {"ctrader_account_id": None}, USER, ctid=47765456)
    check("selected ctid reaches the broker config",
          cfg.CTRADER_ACCOUNT_ID == 47765456,
          repr(cfg.CTRADER_ACCOUNT_ID))
finally:
    CTL.get_ctrader_connection = real_conn
    user_loop._CtraderBroker = real_broker

# ── 4. the broker really does fake a fill when told to ──────────────────────
# Without this, section [1] proves nothing: it would pass just as happily if
# PAPER_TRADING did nothing at all. The harness has to be shown capable of
# detecting the positive before its negative is worth anything.
print("\n[4] and the thing being guarded against is real")
import types                                                # noqa: E402
from apex.brokers import ctrader as CT                      # noqa: E402

fake = CT.CtraderBroker.__new__(CT.CtraderBroker)
fake._c = types.SimpleNamespace(PAPER_TRADING=True, SYMBOL="EURUSD")
res = CT.CtraderBroker.place_order(fake, "BUY", 1000, "EURUSD")
check("with PAPER_TRADING on, place_order returns a FAKE filled order",
      str(res.get("orderId", "")).startswith("CT_PAPER_")
      and res.get("status") == "FILLED",
      str(res))
check("so the guard in [1] is load-bearing, not decorative", True)

# ── 5. the blast radius was wider than orders ───────────────────────────────
# PAPER_TRADING does not only fake the fill. Every READ is faked too, and the
# consequences were on screens the client trusts:
#
#   get_all_positions() -> []                 "no positions", always
#   get_balance()       -> PAPER_BALANCE      an invented number
#
# and the invented balance is what RISK SIZING is computed from, so even an
# order that had gone out would have been sized off a fiction. Asserted here
# so the next person to touch `paper` sees the whole cost, not just the one
# symptom that happened to be noticed first.
print("\n[5] and the reads were faked too, which is how sizing was wrong")
paper_cfg = types.SimpleNamespace(PAPER_TRADING=True, SYMBOL="EURUSD",
                                  PAPER_BALANCE=10_000.0)
pb = CT.CtraderBroker.__new__(CT.CtraderBroker)
pb._c = paper_cfg
check("a paper broker reports NO positions whatever the account holds",
      CT.CtraderBroker.get_all_positions(pb) == [],
      "the Positions screen showed this, not cTrader's answer")
check("and an invented balance, which sizing then trusts",
      CT.CtraderBroker.get_balance(pb) == 10_000.0,
      "risk percent was computed from a number the broker never gave")
# And the platform's own read path builds its broker through the same
# constructor, so the fix covers the screens as well as the orders.
rb = open(os.path.join(ROOT, "apex", "platform", "broker_read.py"),
          encoding="utf-8").read()
check("the platform's read path uses the same constructor",
      "_make_broker" in rb,
      "if it built its own broker, fixing one would not fix the other")

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All platform-order-reality checks passed.")
