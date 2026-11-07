"""The guided automation setup: symbol, strategy, risk, account, start.

The Trade screen posts one body here. This module checks every limit before
anything is stored, and it is the only place that decides whether that body
may start a loop.

LIVE DOES NOT START IN THIS FILE WHEN THE GATE IS CLOSED

`entitlement.live_readiness` is the existing verdict (release switch, live
accounts flag, terms, payment, operator approval). A closed or unreadable
verdict returns a state the screen can show — request access, or waiting for
approval — and does not activate a rule and does not call `automation.start`.
An open verdict still goes through `automation.start`, which asks the same
gate again. This file never reads the switch itself.

RISK IS CHECKED HERE, NOT ONLY IN THE BROWSER

A client can post the body without the screen. Capital, risk per trade, the
daily-loss ceiling, open positions, and the stop and target are refused when
they are outside the platform's own numbers (`risk_gates.PLATFORM` for the
percentages). A daily loss above the platform ceiling is refused rather than
quietly clamped, so the stored rule cannot say a number the engine will not
keep.
"""

from apex import forex as _fx
from apex.platform import automation as _auto
from apex.platform import engine_config as _ecfg
from apex.platform import entitlement as _ent
from apex.platform import risk_gates as _rg
from apex.platform import ruledoc as _rd
from apex.platform import store as _store

DISCLAIMER = "Past performance does not guarantee future results."
TRADED_SYMBOL_NOTE = (
    "This release trades the first symbol. Any others are recorded on the "
    "rule and are not watched.")

TIMEFRAMES = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")
LEVELS = _rd.AUTOMATION_LEVELS

# Lookback, in the strategy's own terms. The clock timeframe is the one the
# client chooses; none of these modules hard-codes a chart period.
_TIMEFRAME = {
    "auto": "Runs on the timeframe you choose. Each cycle re-reads the "
            "regime on those closed candles.",
    "mean_reversion": "Runs on the timeframe you choose. It needs enough "
                      "closed bars for an EMA200.",
    "trend": "Runs on the timeframe you choose. It needs enough closed bars "
             "for an EMA200 and a pullback to EMA20.",
    "breakout": "Runs on the timeframe you choose. The break is the high or "
                "low of the last 20 closed bars.",
    "fibonacci": "Runs on the timeframe you choose. The swing is measured on "
                 "those closed candles.",
    "fvg": "Runs on the timeframe you choose. A gap is read on those candles. "
           "There is no separate clock timeframe.",
    "ifvg": "Runs on the timeframe you choose. The invalidated gap is read "
            "on those candles.",
    "supply_demand": "Runs on the timeframe you choose. Zones are read on "
                     "those candles.",
    "liquidity_sweep": "Runs on the timeframe you choose. The sweep is of a "
                       "swing on those candles.",
    "evc": "Runs on the timeframe you choose. The equilibrium candle is read "
           "on those candles.",
    "momentum": "Runs on the timeframe you choose. ADX, RSI and MACD are "
                "computed on those candles.",
    "session_breakout": "Runs on the timeframe you choose, and only while a "
                        "session is open. The range is the last 16 closed bars.",
    "opening_range": "Runs on the timeframe you choose, and only while a "
                     "session is open. The range is the last 6 closed bars.",
    "zscore": "Runs on the timeframe you choose. The z-score uses the last "
              "40 closes.",
    "vol_regime": "Runs on the timeframe you choose. The squeeze is measured "
                  "on those candles.",
}

CAPITAL_MIN = 1.0
CAPITAL_MAX = 10_000_000.0
RISK_MIN = 0.05
DAILY_MIN = 0.1
POSITIONS_MIN = 1
POSITIONS_MAX = 8
STOP_MIN = 1.0
STOP_MAX = 500.0
TARGET_MIN = 1.0
TARGET_MAX = 2000.0
SYMBOLS_MAX = 8


class SetupInvalid(ValueError):
    def __init__(self, problems):
        self.problems = [str(p) for p in (problems or [])]
        super().__init__("; ".join(self.problems) or "invalid setup")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def bounds():
    """The numbers this release will store. The screen shows them; the
    check below is what refuses a body that ignores the screen."""
    return {
        "capitalAllocated": {"min": CAPITAL_MIN, "max": CAPITAL_MAX},
        "riskPercentDemo": {"min": RISK_MIN,
                            "max": float(_rg.PLATFORM["maxRiskPercentDemo"])},
        "riskPercentLive": {"min": RISK_MIN,
                            "max": float(_rg.PLATFORM["maxRiskPercentLive"])},
        "maxDailyLossPercent": {
            "min": DAILY_MIN,
            "max": float(_rg.PLATFORM["maxDailyLossPercent"]),
        },
        "maxOpenPositions": {"min": POSITIONS_MIN, "max": POSITIONS_MAX},
        "stopLossPips": {"min": STOP_MIN, "max": STOP_MAX},
        "takeProfitPips": {"min": TARGET_MIN, "max": TARGET_MAX},
        "timeframes": list(TIMEFRAMES),
        "levels": list(LEVELS),
        "symbolsMax": SYMBOLS_MAX,
    }


def _catalogue():
    from apex.platform import strategy_catalog as _scat
    return _scat


def library():
    """Every registered strategy, offered or withheld, with no invented result.

    `backtest` is null. This release has no published per-strategy backtest,
    and a number here would be made up. `timeframeNote` says which candles
    the strategy reads; the clock timeframe is the client's.
    """
    cat = _catalogue()
    described = []
    missing = []
    for row in cat.describe():
        note = _TIMEFRAME.get(row["id"])
        if not note:
            missing.append(row["id"])
            note = "Runs on the timeframe you choose."
        described.append(dict(row, timeframeNote=note, backtest=None))
    out = {
        "strategies": described,
        "withheld": cat.withheld(),
        "ruleBuilderId": cat.catalogue().get("ruleBuilderId"),
        "disclaimer": DISCLAIMER,
        "tradedSymbolNote": TRADED_SYMBOL_NOTE,
        "bounds": bounds(),
    }
    if missing:
        out["timeframeUnstated"] = missing
    unclassified = cat.drift()["unclassified"]
    if unclassified:
        out["unclassified"] = unclassified
    return out


def live_view(gate):
    """The screen's live state, taken from the gate and not decided here."""
    gate = gate if isinstance(gate, dict) else {}
    req = gate.get("request") if isinstance(gate.get("request"), dict) else {}
    status = str(req.get("status") or "none")
    summary = str(gate.get("summary") or "")
    if gate.get("open") is True:
        return {"open": True, "state": "open", "label": "Start on live",
                "requestStatus": status, "summary": summary}
    if status == "pending":
        state, label = "awaiting", "Awaiting approval"
    elif gate.get("status") == "unknown" or status == "unknown":
        state, label = "unknown", "Live status unknown"
    else:
        state, label = "request", "Request live access"
    return {"open": False, "state": state, "label": label,
            "requestStatus": status, "summary": summary}


def _between(problems, field, value, lo, hi, *, whole=False):
    if whole:
        ok = isinstance(value, int) and not isinstance(value, bool)
    else:
        ok = _num(value)
    if not ok or value < lo or value > hi:
        kind = "an integer" if whole else "a number"
        _add(problems, field, f"must be {kind} from {lo:g} to {hi:g}")
        return False
    return True


def _add(problems, field, detail):
    problems.append(f"{field}: {detail}")


def validate(body, *, known_strategy_ids=None):
    """Problems with `body`. Empty means the numbers may be stored."""
    problems = []
    if not isinstance(body, dict):
        return ["body: must be an object"]

    syms = body.get("symbols")
    if not isinstance(syms, list) or not syms:
        _add(problems, "symbols", "at least one instrument is required")
    elif len(syms) > SYMBOLS_MAX:
        _add(problems, "symbols", f"at most {SYMBOLS_MAX} instruments")
    elif not all(isinstance(s, str) and s.strip() for s in syms):
        _add(problems, "symbols", "every entry must be a non-empty string")
    else:
        bad = [s for s in syms if not _fx.is_tradeable(s)]
        if bad:
            _add(problems, "symbols",
                 "this platform trades forex with a USD leg and metals — "
                 + ", ".join(sorted(set(bad))) + " is outside that")

    if body.get("timeframe") not in TIMEFRAMES:
        _add(problems, "timeframe",
             "must be one of " + ", ".join(TIMEFRAMES))

    account = body.get("account")
    if account not in ("demo", "live"):
        _add(problems, "account", "must be demo or live")

    level = body.get("automationLevel")
    if level not in LEVELS:
        _add(problems, "automationLevel",
             "must be one of " + ", ".join(LEVELS))

    risk_max = (float(_rg.PLATFORM["maxRiskPercentLive"])
                if account == "live"
                else float(_rg.PLATFORM["maxRiskPercentDemo"]))
    _between(problems, "capitalAllocated", body.get("capitalAllocated"),
             CAPITAL_MIN, CAPITAL_MAX)
    _between(problems, "riskPercent", body.get("riskPercent"),
             RISK_MIN, risk_max)
    _between(problems, "maxDailyLossPercent", body.get("maxDailyLossPercent"),
             DAILY_MIN, float(_rg.PLATFORM["maxDailyLossPercent"]))
    _between(problems, "maxOpenPositions", body.get("maxOpenPositions"),
             POSITIONS_MIN, POSITIONS_MAX, whole=True)
    _between(problems, "stopLossPips", body.get("stopLossPips"),
             STOP_MIN, STOP_MAX)
    _between(problems, "takeProfitPips", body.get("takeProfitPips"),
             TARGET_MIN, TARGET_MAX)

    strategy = body.get("strategy")
    source = body.get("sourceRuleId")
    has_strategy = isinstance(strategy, str) and bool(strategy.strip())
    has_source = isinstance(source, str) and bool(source.strip())
    if has_strategy == has_source:
        _add(problems, "strategy",
             "choose one library strategy, or one method of your own")
    elif has_strategy:
        if known_strategy_ids is None:
            known_strategy_ids = _catalogue().ids()
        if strategy not in set(known_strategy_ids):
            _add(problems, "strategy",
                 f"{strategy!r} is not a strategy this release offers")
    return problems


def _bind(user_id, intent):
    """The connected account of `intent`, selected if it was not already.

    Selecting records a choice. It does not start a loop. A live account is
    still subject to `ctrader_link.live_allowed`, which refuses the select
    when the flag is off — this function does not override that.
    """
    from apex.platform import ctrader_link as _link
    st = _link.public_status(user_id) or {}
    if not st.get("connected"):
        raise _auto.AutomationRefused(
            "NOT_CONNECTED",
            "Connect a cTrader account before starting automation.")
    matches = [a for a in (st.get("accounts") or [])
               if isinstance(a, dict) and a.get("mode") == intent]
    if not matches:
        raise _auto.AutomationRefused(
            "NO_MATCHING_ACCOUNT",
            f"No {intent} account is connected.")
    chosen = matches[0]
    selected = st.get("selected") or {}
    if str(selected.get("ctid") or "") != str(chosen.get("ctid")):
        _link.select_account(user_id, chosen.get("ctid"))
    return str(chosen.get("ctid"))


def _terms(body, *, label):
    """The money terms, copied onto a blank rule. Pips, because that is the
    stop and target the engine applies exactly."""
    limits = {
        "maxOpenPositions": int(body["maxOpenPositions"]),
        "maxDailyTrades": None,
        "maxDailyLossPercent": float(body["maxDailyLossPercent"]),
        "maxExposurePercent": None,
        "maxSpreadPips": None,
        "onLimit": "block",
        "capitalAllocated": float(body["capitalAllocated"]),
    }
    return {
        "name": label,
        "automationLevel": body["automationLevel"],
        "sizing": {"mode": _rd.SIZING_RISK,
                   "riskPercent": float(body["riskPercent"]),
                   "fixedVolume": None},
        "stopLoss": {"mode": "pips", "pips": float(body["stopLossPips"]),
                     "atrMultiple": None},
        "takeProfit": {"mode": "pips", "pips": float(body["takeProfitPips"]),
                       "rr": None},
        "limits": limits,
    }


def build_doc(user_id, body, account_id, source_doc=None):
    """A RuleDoc for this setup. Does not store it."""
    cat = _catalogue()
    doc = _rd.blank(user_id=user_id, account_id=str(account_id or ""),
                    symbols=list(body.get("symbols") or []),
                    timeframe=body.get("timeframe") or "1h")
    if body.get("strategy"):
        doc = cat.apply_to(doc, body["strategy"])
        label = (cat.get(body["strategy"]) or {}).get("label") or body["strategy"]
    else:
        src = source_doc or {}
        doc["entry"] = src.get("entry") or {"combine": "AND", "conditions": []}
        doc["exit"] = src.get("exit") or {"combine": "OR", "conditions": []}
        doc["sides"] = src.get("sides") or "BOTH"
        label = src.get("name") or "My method"
    sym = (body.get("symbols") or [""])[0]
    doc.update(_terms(body, label=f"{label} · {sym}"))
    return _rd.normalise_symbols(doc)


def preview(user_id):
    """What the wizard renders. The live state is the gate's, read fresh."""
    out = library()
    try:
        out["live"] = live_view(_ent.live_readiness(user_id))
    except Exception:                                        # noqa: BLE001
        out["live"] = live_view(None)
    return out


def submit(user_id, body, *, starter=None, gate_reader=None, binder=None):
    """Validate, and start only when the account and the gate allow it.

    A live body whose gate is not open returns `executed: false` and does
    not write a rule and does not call start. Anything else that fails
    raises, before or after the write, and still does not report a start
    the engine did not make.
    """
    user_id = str(user_id)
    cat = _catalogue()
    problems = validate(body, known_strategy_ids=cat.ids())
    if problems:
        raise SetupInvalid(problems)
    body = dict(body)

    if body["account"] == "live":
        reader = gate_reader or _ent.live_readiness
        view = live_view(reader(user_id))
        if not view["open"]:
            return {"started": False, "executed": False, "account": "live",
                    "live": view}

    account_id = (binder or _bind)(user_id, body["account"])
    source = None
    if body.get("sourceRuleId"):
        try:
            source = _store.get(user_id, str(body["sourceRuleId"]))
        except _store.NotFound:
            raise SetupInvalid([
                "sourceRuleId: that method was not found on this account"])
        if cat.preset_of(source):
            raise SetupInvalid([
                "sourceRuleId: that rule is a library strategy — pick the "
                "strategy itself"])
    doc = build_doc(user_id, body, account_id, source)
    known = cat.ids()
    problems = _rd.validate(doc, known_strategy_ids=known)
    if problems:
        raise SetupInvalid(problems)
    stored = _store.create(user_id, doc)
    rid = stored["ruleDocId"]
    _store.activate(user_id, rid)
    runner = starter if starter is not None else _auto.start
    started = runner(user_id, rid)
    did, executed = True, True
    if isinstance(started, dict):
        state = started.get("state")
        did = started.get("started")
        if did is None:
            did = state == _auto.RUNNING
        executed = state == _auto.RUNNING
    return {"started": bool(did), "executed": bool(executed),
            "account": body["account"], "ruleDocId": rid,
            "automation": started, "tradedSymbolNote": TRADED_SYMBOL_NOTE}
