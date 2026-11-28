"""The 24/7 scan, as objects instead of a single winner.

WHAT THIS REPLACES

The loop's own scan read every watched instrument, kept the one with the
highest confidence, and discarded the rest. Two consequences:

  * ranking was by confidence alone, which compares one strategy's opinion of
    its own trigger against another's as though they were one scale;
  * six of seven readings per pass left no trace, so §61 — "why didn't APEX
    trade GBPUSD?" — had no answer for anything passed over.

This produces a SetupCandidate for every instrument looked at, including the
ones that could not be read, and hands the whole list to the decision engine.
Nothing is thrown away.

COST DISCIPLINE (§28, §29)

The expensive reads are ordered behind the cheap ones. Candles come from
`candle_cache`, and a bid/ask quote — one broker call per instrument — is taken
ONLY for a symbol whose rule engine already produced a direction. A symbol with
no signal costs one cached candle read and nothing else.

Requests stay spaced. cTrader allows 5 historical requests per second per
connection regardless of how many users are authorised through it, which is the
constraint `candle_cache` exists for; the spacing here is the same discipline
for the misses.

THIS MODULE DOES NOT DECIDE AND DOES NOT EXECUTE

It observes and describes. `decision.evaluate_all` decides,
`gates.authorize_order` authorises, and the execution controller is the only
path to the broker.
"""

import time

from apex import indicators, regime as _regime, setups, strategies

SCANNER_VERSION = "1.0.0"

# Enough bars for the 130-candle regime floor plus indicator warm-up.
_SCAN_CANDLES = 160

# Spacing between historical reads, in seconds. cTrader rate-limits bursts.
_REQUEST_SPACING_S = 0.35

# Which engine to run in AUTO mode, per regime. Kept as data so a new regime
# does not need a new branch.
_AUTO_ENGINE = {
    _regime.TRENDING: "trend",
    _regime.BREAKOUT: "breakout",
    _regime.HIGH_VOLATILITY: "breakout",
    _regime.RANGING: "mean_reversion",
    _regime.LOW_VOLATILITY: "mean_reversion",
}


def _htf(candles):
    """Higher-timeframe direction, or None when it could not be read."""
    try:
        h = strategies.htf_trend(candles)
    except Exception:
        return None
    if isinstance(h, dict):
        t = h.get("trend")
    else:
        t = h
    return t if t in ("BULLISH", "BEARISH") else None


def _spread_pips(broker, forex, symbol):
    """One quote. None when the broker did not answer — never zero.

    A zero spread reads as a perfect fill and would make an unreadable quote
    score better than a real one.
    """
    try:
        b, a = broker.get_bid_ask(symbol)
        sp = forex.spread_pips(b, a, symbol)
        return sp if sp and sp > 0 else None
    except Exception:
        return None


def scan_symbol(broker, cfg, symbol, *, context=None, forex=None):
    """One instrument -> one SetupCandidate. Never raises.

    `context` carries what the account already knows, so the candidate can be
    ranked without this module reading account state itself:

        exposureCount, maxPositions, openSymbols, strategyVersion
    """
    ctx = dict(context or {})
    sym_open = str(symbol).replace("_", "").upper() in set(
        ctx.get("openSymbols") or [])

    try:
        candles = broker.get_candles(symbol, cfg.TIMEFRAME, _SCAN_CANDLES)
    except Exception as e:
        return setups.invalid(symbol, f"candles unavailable: {str(e)[:80]}",
                              timeframe=cfg.TIMEFRAME)
    if not candles or len(candles) < 130:
        return setups.invalid(symbol,
                              f"only {len(candles or [])} candles, need 130",
                              timeframe=cfg.TIMEFRAME)

    # Regime first: it decides which engine runs in AUTO, and it is the one
    # reading that stays useful even when no signal fires.
    try:
        bo = strategies.turtle_breakout(candles)
    except Exception:
        bo = None
    reg = _regime.classify(candles, symbol=symbol, timeframe=cfg.TIMEFRAME,
                           breakout=bo)

    mode = getattr(cfg, "STRATEGY", "auto")
    if mode == "auto":
        mode = _AUTO_ENGINE.get(reg.regime)
        if mode is None:
            # UNSTABLE and UNKNOWN have no engine. Standing aside is the
            # reading, and it is recorded rather than silently skipped.
            c = setups.SetupCandidate(
                symbol=symbol, direction="BUY", timeframe=cfg.TIMEFRAME,
                strategy_id="auto", strategy_version=ctx.get("strategyVersion"),
                regime=reg, status=setups.WATCH,
                status_reason=f"no engine for a {reg.regime} market")
            c.add_evidence("regime", reg.regime, passed=None,
                           detail=reg.label or "standing aside")
            return c

    try:
        ind = indicators.analyze(candles)
        strat = strategies.analyze(candles)
    except Exception as e:
        return setups.invalid(symbol, f"indicators failed: {str(e)[:80]}",
                              timeframe=cfg.TIMEFRAME)

    # The rule engine. Deliberately the same call the loop already made — this
    # is a re-shaping of the scan, not a new strategy.
    from apex import ai as _ai
    try:
        sig = _ai.signal_for_mode(mode, ind, strat, None) or {}
    except Exception as e:
        return setups.invalid(symbol, f"signal failed: {str(e)[:80]}",
                              timeframe=cfg.TIMEFRAME)

    action = sig.get("action")
    conf = sig.get("confidence")
    bar_ts = candles[-1].get("time") if candles else None

    if action not in ("BUY", "SELL"):
        c = setups.SetupCandidate(
            symbol=symbol, direction="BUY", timeframe=cfg.TIMEFRAME,
            strategy_id=mode, strategy_version=ctx.get("strategyVersion"),
            bar_ts=bar_ts, regime=reg, status=setups.WATCH,
            status_reason=f"no trigger ({action or 'none'})",
            features={"confidence": conf, "htfTrend": _htf(candles)})
        c.add_evidence("trigger", action or "none", passed=False,
                       detail=sig.get("reasoning") or "")
        return c

    # A direction exists, so the quote is now worth paying for (§28).
    sl_pips = float(getattr(cfg, "STOP_LOSS_PIPS", 0) or 0) or None
    spread = _spread_pips(broker, forex, symbol) if forex is not None else None

    c = setups.SetupCandidate(
        symbol=symbol, direction=action, timeframe=cfg.TIMEFRAME,
        strategy_id=mode, strategy_version=ctx.get("strategyVersion"),
        bar_ts=bar_ts, regime=reg, status=setups.CANDIDATE,
        trigger_state={"reasoning": sig.get("reasoning"),
                       "keyFactors": sig.get("keyFactors")},
        features={
            "confidence": conf,
            "htfTrend": _htf(candles),
            "structureTrend": (reg.evidence or {}).get("structureTrend"),
            "spreadPips": spread,
            "slPips": sl_pips,
            "exposureCount": ctx.get("exposureCount"),
            "maxPositions": ctx.get("maxPositions"),
            "sameSymbolOpen": sym_open,
            "price": candles[-1].get("close"),
        })
    c.add_evidence("trigger", f"{action} @ {conf}%", passed=True,
                   detail=sig.get("reasoning") or "")
    c.add_evidence("regime", reg.regime, passed=reg.fits(mode),
                   detail=reg.label or "")
    c.add_evidence("spread", spread, passed=None if spread is None else True,
                   detail="pips at scan time")
    c.add_evidence("higher_timeframe", c.features["htfTrend"],
                   passed=None if c.features["htfTrend"] is None else None,
                   detail="direction agreement is judged by the decision engine")
    # What would make this setup wrong. Recorded now so the thesis written at
    # entry inherits it rather than being composed after the fact.
    c.invalidation = [
        f"structure turns against a {action}",
        "the higher timeframe reverses",
        f"price trades through the {sl_pips or 'configured'}-pip stop",
    ]
    return c


def scan(broker, cfg, watchlist, *, context=None, forex=None, spacing_s=None,
         skip=None):
    """Every watched instrument -> a list of SetupCandidate, in scan order.

    `skip` is the set of symbols the caller already knows are untradeable this
    pass — spread-blocked, or already open. They are still RECORDED, because a
    screen that shows nothing for an instrument cannot distinguish "we skipped
    it" from "we never looked".
    """
    out = []
    gap = _REQUEST_SPACING_S if spacing_s is None else spacing_s
    skip = {str(s).replace("_", "").upper() for s in (skip or [])}
    for i, sym in enumerate(watchlist or []):
        if str(sym).replace("_", "").upper() in skip:
            c = setups.invalid(sym, "not eligible this pass "
                                    "(already open or spread-blocked)",
                               timeframe=getattr(cfg, "TIMEFRAME", None))
            out.append(c)
            continue
        if i and gap:
            time.sleep(gap)
        try:
            out.append(scan_symbol(broker, cfg, sym, context=context,
                                   forex=forex))
        except Exception as e:                 # one symbol must not stop a pass
            out.append(setups.invalid(sym, f"scan failed: {str(e)[:80]}",
                                      timeframe=getattr(cfg, "TIMEFRAME", None)))
    return out


def record(user_id, candidates, decisions, *, ranked=None):
    """Write the pass to the journal. Never raises.

    One `candidates.ranked` event for the pass, and one `decision.recorded`
    per candidate — which is what makes the losers answerable. Bounded by the
    journal's own cap; a pass over eight instruments is eight small rows.
    """
    try:
        from apex import ranking as _ranking, trade_events as _te
        _te.record(user_id, _te.CANDIDATES_RANKED,
                   payload=_ranking.snapshot(ranked or candidates))
        for d in decisions or []:
            _te.record(user_id, _te.DECISION_RECORDED, symbol=d.symbol,
                       payload=d.to_dict())
    except Exception as e:
        print(f"[Scanner:{user_id}] journal write failed: {e}")
