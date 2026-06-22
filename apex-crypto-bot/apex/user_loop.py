"""Per-user crypto trading loop — each client gets an isolated thread + state.

Key design: the risk pause NEVER latches. When a risk limit trips, the loop
alerts once, pauses trading silently for RISK_PAUSE_MIN minutes, then auto-resets
the counters and resumes. A manual /resume clears it instantly. This is the fix
for the old bot's "STRATEGY STOP spam forever" bug.
"""
import time
import threading
from datetime import datetime
from apex import config as cfg
from apex import user_store, indicators, ai, strategies, binance


_loops = {}   # user_id → {"running": bool, "thread": Thread, "dash": dict}
_lock = threading.Lock()


def _default_settings():
    return {
        "SYMBOL": cfg.SYMBOL,
        "TIMEFRAME": cfg.TIMEFRAME,
        "STRATEGY_MODE": cfg.STRATEGY_MODE,
        "RISK_PER_TRADE": cfg.RISK_PER_TRADE,
        "STOP_LOSS_PCT": cfg.STOP_LOSS_PCT,
        "TAKE_PROFIT_PCT": cfg.TAKE_PROFIT_PCT,
        "MIN_CONFIDENCE": cfg.MIN_CONFIDENCE,
        "MIN_CRITERIA": cfg.MIN_CRITERIA,
        "PAUSED": False,
    }


def _ensure_user(user_id):
    """Load user, filling defaults for first-time clients (paper, $100)."""
    u = user_store.load(user_id)
    changed = False
    if "settings" not in u:
        u["settings"] = _default_settings()
        changed = True
    else:
        for k, v in _default_settings().items():
            u["settings"].setdefault(k, v)
    if "paper" not in u:
        u["paper"] = True
        changed = True
    if "state" not in u:
        u["state"] = {
            "paperBalance": cfg.PAPER_BALANCE,
            "startBalance": cfg.PAPER_BALANCE,
            "openPosition": None,
            "trades": [],
            "session": strategies.new_session(cfg.PAPER_BALANCE),
            "tickCount": 0,
        }
        changed = True
    else:
        u["state"].setdefault("session", strategies.new_session(u["state"].get("paperBalance", cfg.PAPER_BALANCE)))
        u["state"].setdefault("trades", [])
        u["state"].setdefault("tickCount", 0)
    if changed:
        user_store.save(user_id, u)
    return u


def _calc_sltp(side, price, settings):
    sl, tp = settings["STOP_LOSS_PCT"], settings["TAKE_PROFIT_PCT"]
    if side == "BUY":
        return price * (1 - sl), price * (1 + tp)
    return price * (1 + sl), price * (1 - tp)


def _check_exit(pos, price):
    if not pos:
        return None
    if pos["side"] == "BUY" and price <= pos["stopLoss"]:
        return "STOP_LOSS"
    if pos["side"] == "BUY" and price >= pos["takeProfit"]:
        return "TAKE_PROFIT"
    if pos["side"] == "SELL" and price >= pos["stopLoss"]:
        return "STOP_LOSS"
    if pos["side"] == "SELL" and price <= pos["takeProfit"]:
        return "TAKE_PROFIT"
    return None


def _pos_pnl(pos, price):
    if pos["side"] == "BUY":
        return (price - pos["entryPrice"]) * pos["quantity"]
    return (pos["entryPrice"] - price) * pos["quantity"]


def _open_trade(u, state, settings, side, price, druck_mult, alert):
    symbol = settings["SYMBOL"]
    risk = settings["RISK_PER_TRADE"] * druck_mult
    qty = round((state["paperBalance"] * risk) / price, 6)
    if qty <= 0:
        return
    fee = price * qty * cfg.FEE_PCT
    if side == "BUY":
        state["paperBalance"] -= price * qty + fee
    else:
        state["paperBalance"] += price * qty - fee
    sl, tp = _calc_sltp(side, price, settings)
    state["openPosition"] = {
        "symbol": symbol, "side": side, "entryPrice": price, "quantity": qty,
        "stopLoss": sl, "takeProfit": tp, "openedAt": datetime.utcnow().isoformat(), "pnlPct": 0,
    }
    alert("open", {"side": side, "symbol": symbol, "price": price, "qty": qty,
                   "stopLoss": sl, "takeProfit": tp, "druckMult": druck_mult})


def _close_trade(u, state, settings, price, reason, alert):
    pos = state["openPosition"]
    if not pos:
        return
    side, entry, qty, symbol = pos["side"], pos["entryPrice"], pos["quantity"], pos["symbol"]
    fee_both = (entry + price) * qty * cfg.FEE_PCT
    pnl = (price - entry if side == "BUY" else entry - price) * qty - fee_both
    if side == "BUY":
        state["paperBalance"] += price * qty * (1 - cfg.FEE_PCT)
    else:
        state["paperBalance"] -= price * qty * (1 + cfg.FEE_PCT)
    strategies.record_trade(state["session"], pnl > 0, pnl)
    state["trades"].insert(0, {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "symbol": symbol, "side": side,
        "entry": round(entry, 6), "exit": round(price, 6), "qty": qty,
        "pnl": round(pnl, 4), "pnlPct": round(pnl / (entry * qty) * 100, 2) if entry and qty else 0,
        "reason": reason, "win": pnl > 0,
    })
    state["trades"] = state["trades"][:50]
    state["openPosition"] = None
    alert("close", {"side": side, "symbol": symbol, "entryPrice": entry, "exitPrice": price,
                    "pnl": pnl, "balance": state["paperBalance"], "reason": reason})


def _tick(user_id, alert):
    u = _ensure_user(user_id)
    settings, state = u["settings"], u["state"]
    if settings.get("PAUSED"):
        return
    state["tickCount"] = state.get("tickCount", 0) + 1

    symbol = (state["openPosition"] or {}).get("symbol") or settings["SYMBOL"]
    timeframe = settings["TIMEFRAME"]
    candles = binance.get_candles(symbol, timeframe, cfg.CANDLES)
    if not candles:
        return
    price = binance.get_price(symbol)

    dash = _loops.get(user_id, {}).get("dash", {})
    dash.update({"balance": state["paperBalance"], "startBalance": state["startBalance"],
                 "currentSymbol": symbol, "currentPrice": price,
                 "lastTick": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "trades": state["trades"], "mode": "PAPER" if u.get("paper", True) else "LIVE"})

    pos = state["openPosition"]
    if pos:
        pnl = _pos_pnl(pos, price)
        pos["currentPnl"] = round(pnl, 4)
        pos["pnlPct"] = round(pnl / (pos["entryPrice"] * pos["quantity"]) * 100, 2)
        dash["openPosition"] = pos
    else:
        dash["openPosition"] = None

    # Heartbeat only while a position is open (live PnL is useful; skip spam).
    if pos and state["tickCount"] % 6 == 0:
        alert("heartbeat", {"tickCount": state["tickCount"], "balance": state["paperBalance"], "openPosition": pos})

    # Exit check first
    trigger = _check_exit(pos, price)
    if trigger:
        _close_trade(u, state, settings, price, trigger, alert)
        user_store.save(user_id, u)
        return

    # ── Self-healing risk pause (never latches) ──
    session = state["session"]
    portfolio = state["paperBalance"] + (_pos_pnl(pos, price) if pos else 0)
    stop = strategies.should_stop(session, portfolio, state["startBalance"])
    if stop["stop"]:
        now = time.time()
        if not session.get("stopStartedAt"):
            session["stopStartedAt"] = now
            alert("risk_pause", {"reasons": stop["reasons"]})
            user_store.save(user_id, u)
            return
        if now - session["stopStartedAt"] < cfg.RISK_PAUSE_MIN * 60:
            user_store.save(user_id, u)
            return  # silent cooldown
        strategies.reset_risk(session, state["paperBalance"])
        alert("risk_resume", {})
        # fall through and trade this tick

    if state["paperBalance"] < 1:
        user_store.save(user_id, u)
        return

    ind = indicators.analyze(candles)
    strat = strategies.analyze(candles, session)
    user_key = u.get("groq_key") or None
    try:
        signal = ai.get_signal(ind, state["paperBalance"], pos, strat,
                               symbol=symbol, timeframe=timeframe, user_key=user_key)
    except Exception as e:
        if getattr(e, "user_key", False):
            alert("groq_error", {"reason": str(e)})
            signal = ai.rule_based_fallback(ind, pos)
        else:
            print(f"[UserLoop:{user_id}] AI error: {e}")
            signal = ai.rule_based_fallback(ind, pos)

    state["lastSignal"] = {"action": signal["action"], "confidence": signal["confidence"],
                           "criteriaScore": signal.get("criteriaScore", 0),
                           "reasoning": signal.get("reasoning", "")}

    conf_ok = signal["confidence"] >= settings["MIN_CONFIDENCE"]
    crit_ok = signal.get("criteriaScore", 0) >= settings["MIN_CRITERIA"]
    vol_ok = float(ind.get("volumeRatio") or 0) >= 0.4

    druck = (strategies.druckenmiller_multiplier(signal["confidence"], signal.get("criteriaScore", 0),
                                                 strat["livermore"], strat["turtle"]) if not pos else 1.0)

    # Strategy-mode gate
    mode = settings.get("STRATEGY_MODE", "auto")
    if mode != "auto" and not pos and signal["action"] in ("BUY", "SELL"):
        lv, tu, so = strat["livermore"], strat["turtle"], strat["soros"]
        blocked = (
            (mode == "turtle" and not tu.get("signal")) or
            (mode == "livermore" and not ((lv["trend"] == "BULLISH" and signal["action"] == "BUY") or (lv["trend"] == "BEARISH" and signal["action"] == "SELL"))) or
            (mode == "soros" and not ((so["direction"] == "BULLISH" and signal["action"] == "BUY") or (so["direction"] == "BEARISH" and signal["action"] == "SELL"))) or
            (mode == "ptj" and (signal["confidence"] < 85 or signal.get("criteriaScore", 0) < 4))
        )
        if blocked:
            signal["action"] = "HOLD"

    # Don't fight strong Livermore structure
    lv_str = strat["livermore"].get("strength") or 0
    if not pos and lv_str >= 0.8:
        if strat["livermore"]["trend"] == "BEARISH" and signal["action"] == "BUY":
            signal["action"] = "HOLD"
        if strat["livermore"]["trend"] == "BULLISH" and signal["action"] == "SELL":
            signal["action"] = "HOLD"

    # Post-loss cooldown (Seykota — no revenge trading)
    if not pos and signal["action"] in ("BUY", "SELL"):
        if strategies.cooldown_remaining(session, cfg.COOLDOWN_AFTER_LOSS_MIN) > 0:
            signal["action"] = "HOLD"

    if signal["action"] == "CLOSE" and pos:
        _close_trade(u, state, settings, price, "AI_CLOSE", alert)
    elif signal["action"] in ("BUY", "SELL") and not pos and conf_ok and crit_ok and vol_ok:
        _open_trade(u, state, settings, signal["action"], price, druck, alert)

    user_store.save(user_id, u)


def _loop(user_id, alert):
    print(f"[UserLoop] Started for user {user_id}")
    # First tick immediately, then on interval.
    while True:
        with _lock:
            if not _loops.get(user_id, {}).get("running"):
                break
        try:
            _tick(user_id, alert)
        except Exception as e:
            print(f"[UserLoop:{user_id}] Error: {e}")
        time.sleep(cfg.LOOP_INTERVAL_SEC)


def start(user_id, alert_fn=None):
    user_id = str(user_id)
    _ensure_user(user_id)
    with _lock:
        if user_id in _loops and _loops[user_id].get("running"):
            return False
        _loops[user_id] = {"running": True, "dash": {}}
    user_store.update(user_id, {"active": True})
    t = threading.Thread(target=_loop, args=(user_id, alert_fn or (lambda *a: None)), daemon=True)
    t.start()
    with _lock:
        _loops[user_id]["thread"] = t
    return True


def stop(user_id):
    user_id = str(user_id)
    with _lock:
        if user_id not in _loops:
            return False
        _loops[user_id]["running"] = False
    user_store.update(user_id, {"active": False})
    print(f"[UserLoop] Stopped for user {user_id}")
    return True


def is_running(user_id):
    with _lock:
        return _loops.get(str(user_id), {}).get("running", False)


def get_dash(user_id):
    with _lock:
        return _loops.get(str(user_id), {}).get("dash", {})


def reset_risk(user_id):
    """Manual /resume — clear any risk pause + counters instantly."""
    user_id = str(user_id)
    u = _ensure_user(user_id)
    strategies.reset_risk(u["state"]["session"], u["state"]["paperBalance"])
    u["settings"]["PAUSED"] = False
    user_store.save(user_id, u)


def start_all(alert_fn=None):
    for uid in user_store.all_active():
        start(uid, alert_fn)
