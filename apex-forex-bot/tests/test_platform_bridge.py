"""From decision to order: what reaches the gate, and what never gets that far.

THE PROPERTY THIS FILE PROTECTS

There is one execution path. This module hands work to
`user_loop.force_trade`, which already does ownership.may_trade,
gates.authorize_order, gates.audit, ledger.claim/record and only then
broker.place_order. Re-implementing those five steps beside it would create
two places that must both stay correct forever, and the first time they
disagreed one would be placing orders the other believed refused.

So the tests below assert two things: that nothing but BUY and SELL ever
reaches the executor, and that everything which does carries the RULE's own
stop rather than the engine's. The second matters as much as the first — a
position opened at the engine's ATR stop under a client's rule is the silent
substitution this codebase was rebuilt to prevent, and it would look entirely
normal on every screen.

No broker is imported anywhere in this file. The executor is injected.

Run: python tests/test_platform_bridge.py
"""
import math
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-bridge-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex import forex  # noqa: E402
from apex.platform import bridge as B  # noqa: E402
from apex.platform import decision as D  # noqa: E402
from apex.platform import execution as E  # noqa: E402
from apex.platform import ruledoc as R  # noqa: E402
from apex.platform.snapshot import MarketSnapshot  # noqa: E402

failures = []
sent = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def spy(user_id, side, symbol=None, lots=None, **kw):
    """Stands in for user_loop.force_trade. Records, places nothing."""
    sent.append(dict(kw, user_id=user_id, side=side, symbol=symbol,
                     lots=lots))
    return {"ok": True, "side": side, "symbol": symbol, "units": 1000}


def candles(n=300, base=1.1000, amp=0.0040, period=53):
    out = []
    for i in range(n):
        c = base + amp * math.sin(2 * math.pi * i / period)
        pad = 0.0005 + 0.0002 * abs(math.sin(i / 5.0))
        out.append({"open": c - pad / 3, "high": c + pad, "low": c - pad,
                    "close": c, "volume": 1000 + i})
    return out


TS = 1758542400.0
CS = candles()


def snap(cs=None):
    cs = cs if cs is not None else CS
    return MarketSnapshot(symbol="EUR_USD", timeframe="1h", candles=cs,
                          price=cs[-1]["close"], ts=TS, spread_pips=1.0)


def doc(**over):
    d = R.blank(user_id="u-1", account_id="ct-demo-1", symbols=["EUR_USD"],
                timeframe="1h")
    d["state"] = R.ACTIVE
    d["sides"] = "BUY"
    d["entry"] = {"combine": "AND", "conditions": [
        {"id": "rsi", "params": {"op": "below", "value": 30}}]}
    d["exit"] = {"combine": "OR", "conditions": [
        {"id": "rsi", "params": {"op": "above", "value": 70}}]}
    for k, v in over.items():
        d[k] = v
    return d


def dec(verdict=D.BUY, code=None):
    return D.RuleDecision(verdict=verdict, rule_doc_id="r1",
                          rule_doc_version=1, symbol="EUR_USD",
                          snapshot_ts=TS, side=(verdict if verdict in
                                                (D.BUY, D.SELL) else None),
                          reason="test", refusal_code=code)


def submit(d=None, decision=None, s=None, balance=10000.0, **kw):
    sent.clear()
    return B.submit(d or doc(), decision or dec(), s or snap(),
                    user_id="u-1", account_id="ct-demo-1", mode="demo",
                    balance=balance, executor=spy, **kw)


try:
    print("\n1. only BUY and SELL ever reach the executor")
    for verdict, code in ((D.HOLD, None), (D.REJECT, D.INSUFFICIENT_DATA),
                          (D.CLOSE, None)):
        r = submit(decision=dec(verdict, code))
        check(f"{verdict} places nothing", r["ok"] is False and sent == [],
              f"{r.get('refusal')} sent={len(sent)}")
        check(f"{verdict} is refused as not executable",
              r["refusal"]["code"] == E.NOT_EXECUTABLE, str(r["refusal"]))
        check(f"{verdict} is still journalled",
              r["journal"] is not None and r["journal"].kind == "error")
    r = submit()
    check("BUY reaches the executor exactly once",
          r["ok"] is True and len(sent) == 1, f"{r}")
    check("and it goes as a rule, not as a manual order",
          sent[0]["origin"] == "rule", str(sent[0].get("origin")))

    print("\n2. the position carries the RULE's stop, not the engine's")
    r = submit(doc(stopLoss={"mode": "pips", "pips": 20}))
    price = CS[-1]["close"]
    want = round(price - forex.from_pips(20, "EUR_USD", price), 6)
    check("a 20-pip rule stop is passed through as a price",
          abs(sent[0]["sl_override"] - want) < 1e-6,
          f"{sent[0]['sl_override']} vs {want}")
    check("the stop is below entry for a BUY", sent[0]["sl_override"] < price)
    r = submit(doc(stopLoss={"mode": "pips", "pips": 20}),
               decision=dec(D.SELL))
    check("and above entry for a SELL", sent[0]["sl_override"] > price,
          str(sent[0]["sl_override"]))
    r = submit(doc(stopLoss={"mode": "atr", "atrMultiple": 2.0}))
    check("an ATR stop is computed from the snapshot's own candles",
          sent[0]["sl_override"] is not None and
          sent[0]["sl_override"] < price)
    r = submit(doc(stopLoss={"mode": "pips", "pips": 20},
                   takeProfit={"mode": "rr", "rr": 3.0}))
    risk = price - sent[0]["sl_override"]
    check("a 3R target is three times the risk",
          abs((sent[0]["tp_override"] - price) - 3 * risk) < 1e-6,
          f"{sent[0]['tp_override']}")
    r = submit(doc(sizing={"mode": "risk_percent", "riskPercent": 0.5,
                           "fixedVolume": None}))
    check("the rule's risk percent is what sizing uses, not cfg's",
          abs(sent[0]["risk_override"] - 0.005) < 1e-9,
          str(sent[0].get("risk_override")))
    r = submit(doc(sizing={"mode": "fixed_volume", "fixedVolume": 0.02,
                           "riskPercent": None}))
    check("a fixed-volume rule passes lots instead of a risk percent",
          sent[0]["lots"] == 0.02 and sent[0]["risk_override"] is None,
          str(sent[0]))

    print("\n3. a stop that cannot be computed refuses — it never borrows one")
    # atr(period=14) builds true ranges from n-1 bars, so it needs 15 candles
    # before its last value is defined. 10 is short enough to be undefined.
    short = snap(candles(10))
    r = submit(doc(stopLoss={"mode": "atr", "atrMultiple": 2.0}), s=short)
    check("too little history for ATR places nothing",
          r["ok"] is False and sent == [], str(r.get("refusal")))
    check("and says which term it could not compute",
          r["refusal"]["code"] == "NO_ATR", str(r["refusal"]))
    r = submit(doc(stopLoss={"mode": "none"}))
    check("a rule with no stop mode places nothing",
          r["ok"] is False and sent == [], str(r.get("refusal")))
    r = submit(balance=None)
    check("no balance means no computable size, so nothing is sent",
          r["ok"] is False and sent == [] and
          r["refusal"]["code"] == E.SIZING_FAILED, str(r.get("refusal")))

    print("\n4. a constraint the path cannot honour blocks the order")
    r = submit(doc(order={"type": "MARKET", "maxSlippagePoints": 2,
                          "expiresAfterSec": None}))
    check("a slippage ceiling the connector cannot express places nothing",
          r["ok"] is False and sent == [], str(r.get("refusal")))
    check("and is refused as an unsupported constraint",
          r["refusal"]["code"] == E.CONSTRAINT_UNSUPPORTED,
          str(r["refusal"]))
    check("the refusal names the constraint, so the form can point at it",
          "maxSlippagePoints" in r["refusal"]["detail"], r["refusal"]["detail"])
    r = submit(doc(order={"type": "LIMIT", "maxSlippagePoints": None,
                          "expiresAfterSec": None}))
    check("a LIMIT rule places nothing — the connector does MARKET only",
          r["ok"] is False and sent == [], str(r.get("refusal")))
    check("and the reason is the order type, not something about constraints",
          "MARKET orders only" in r["refusal"]["detail"],
          r["refusal"]["detail"])
    check("the supported set is stated, not assumed",
          B.SUPPORTED_CONSTRAINTS == frozenset()
          and B.SUPPORTED_ORDER_TYPES == frozenset({"MARKET"}))

    print("\n5. every attempt is traceable, whether it traded or not")
    r = submit()
    j = r["journal"]
    check("an execution entry links the rule, its version and the request",
          j.rule_doc_id == "r1" and j.rule_doc_version == 1
          and j.execution_request is not None)
    check("and records what came back from the executor",
          j.broker_result == {"ok": True, "side": "BUY",
                              "symbol": "EUR_USD", "units": 1000},
          str(j.broker_result))
    check("a refusal is journalled too, with the same shape",
          submit(decision=dec(D.HOLD))["journal"].error is not None)
    r1 = submit(correlation_id="corr-1")
    check("the correlation id given by the caller is the one recorded",
          r1["journal"].correlation_id == "corr-1")
    check("the request carries demo or live explicitly",
          r1["request"].mode == "demo")

    print("\n6. the bridge owns no path of its own")
    # Checked through the AST, not by searching the text. The module's own
    # docstring names these very functions in order to say it does not call
    # them, and a substring search cannot tell an explanation from a call —
    # it would fail on honest prose and pass on a call hidden in a getattr.
    import ast
    tree = ast.parse(open(os.path.join(ROOT, "apex", "platform",
                                       "bridge.py")).read())
    called, imported = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                called.add(f.attr)
            elif isinstance(f, ast.Name):
                called.add(f.id)
        elif isinstance(node, ast.Attribute):
            called.add(node.attr)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module or ''}.{a.name}"
                            for a in node.names)
    for forbidden in ("authorize_order", "authorize_close", "place_order",
                      "close_position", "amend_sltp", "claim", "record"):
        check(f"bridge.py never calls {forbidden}()", forbidden not in called,
              "found in the AST")
    check("bridge.py imports no broker",
          not any("broker" in m for m in imported), str(imported))
    check("bridge.py imports no ledger and no gate",
          not any(m.endswith(("ledger", "gates")) for m in imported),
          str(imported))
    check("it delegates to the one controller instead",
          "force_trade" in called or any("user_loop" in m for m in imported))
    print("\n7. force_trade sizes against the stop it is actually using")
    # The sections above use a spy, so they never reach the real controller.
    # This one does — with gates.authorize_order forced to DENY, so sizing runs
    # in full and no order can possibly be placed. What it proves is narrow and
    # important: an overridden stop must also become the stop distance sizing
    # reads. Overriding the price alone would size the position against the
    # engine's ATR stop while trading the client's, and every screen would look
    # normal while the size was wrong.
    from types import SimpleNamespace

    from apex import gates as _gates
    from apex import ownership as _own
    from apex import user_loop as _ul

    class _Cfg:
        SYMBOL = "EUR_USD"; TIMEFRAME = "1h"; STOP_LOSS_PIPS = 15
        TAKE_PROFIT_PIPS = 30; RISK_PER_TRADE = 0.02; PAPER_BALANCE = 10000
        ATR_STOPS = True; LEVERAGE = 30; PAPER_TRADING = True; CANDLES = 200

    class _Broker:
        def get_candles(self, sym, tf, n):
            return CS[-int(n):]

        def get_bid_ask(self, sym):
            p = CS[-1]["close"]
            return p - 0.00005, p + 0.00005

        def leverage_for(self, sym):
            return 30

        def min_units(self, sym):
            return 1000

    seen = {}
    _real = {"mb": _ul._make_broker, "load": _ul.user_store.load,
             "dash": _ul.get_dash, "may": _own.may_trade,
             "auth": _gates.authorize_order, "units": _ul.forex.calc_units}
    try:
        _ul._make_broker = lambda user: (_Broker(), _Cfg())
        _ul.user_store.load = lambda uid: {"paper": True,
                                           "paper_balance": 10000}
        _ul.get_dash = lambda uid: {}
        _own.may_trade = lambda uid, live=False: (True, "ok")
        # The gate REFUSES, so this test cannot place an order even if
        # everything else in force_trade went wrong.
        _gates.authorize_order = lambda *a, **k: (
            _gates.Decision(False, "TEST_DENY", "denied by the test"), None)

        def _capture(balance, risk, stop_pips, sym, price, **kw):
            seen["risk"] = risk
            seen["stop_pips"] = stop_pips
            return _real["units"](balance, risk, stop_pips, sym, price, **kw)
        _ul.forex.calc_units = _capture

        price = CS[-1]["close"]
        # Deliberately far from this fixture's ATR stop (~25 pips). A value near
        # it would let both assertions pass without distinguishing anything.
        want_stop = round(price - forex.from_pips(60, "EUR_USD", price), 6)
        out = _ul.force_trade("u-1", "BUY", symbol="EUR_USD",
                              sl_override=want_stop, risk_override=0.005,
                              origin="rule")
        check("the gate is what stops it, so nothing was placed",
              out.get("ok") is False and "TEST_DENY" in str(out.get("error")),
              str(out)[:80])
        check("sizing used the RULE's 60-pip stop, not the engine's ATR one",
              abs(seen.get("stop_pips", 0) - 60.0) < 0.5,
              str(seen.get("stop_pips")))
        check("and the RULE's risk percent, not cfg's 2%",
              abs(seen.get("risk", 0) - 0.005) < 1e-9, str(seen.get("risk")))

        seen.clear()
        out = _ul.force_trade("u-1", "BUY", symbol="EUR_USD")
        check("without overrides the engine's own sizing is untouched",
              seen.get("risk") == _Cfg.RISK_PER_TRADE, str(seen.get("risk")))
        check("and its stop distance is the ATR one, nowhere near 60 pips",
              abs(seen.get("stop_pips", 0) - 60.0) > 5.0,
              str(seen.get("stop_pips")))

        out = _ul.force_trade("u-1", "BUY", symbol="EUR_USD",
                              sl_override=price, origin="rule")
        check("a stop at the entry price is refused, not sized against zero",
              out.get("ok") is False and "hit on entry" in
              str(out.get("error")), str(out)[:110])
        near = round(price - forex.from_pips(0.05, "EUR_USD", price), 6)
        out = _ul.force_trade("u-1", "BUY", symbol="EUR_USD",
                              sl_override=near, origin="rule")
        check("and so is a stop a fraction of a pip away, which would size an "
              "enormous position",
              out.get("ok") is False and "hit on entry" in
              str(out.get("error")), str(out)[:110])
    finally:
        _ul._make_broker = _real["mb"]; _ul.user_store.load = _real["load"]
        _ul.get_dash = _real["dash"]; _own.may_trade = _real["may"]
        _gates.authorize_order = _real["auth"]
        _ul.forex.calc_units = _real["units"]
finally:
    shutil.rmtree(_TMP, ignore_errors=True)

print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
