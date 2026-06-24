"""Per-user trading loop manager — each client gets their own isolated loop."""
import threading
import time
from datetime import datetime
from apex import user_store, indicators, ai, strategies, forex
from apex.brokers.oanda import OandaBroker


_loops = {}   # user_id → {"thread": Thread, "running": bool, "dash": dict}
_lock  = threading.Lock()

_LOOP_INTERVAL = 300  # 5 minutes between ticks
_HEARTBEAT_TICKS = 30  # heartbeat every 30 ticks (~2.5 hours swing)
_AI_ERROR_THROTTLE = 30  # alert AI failure at most once per 30 ticks


def _log_trade(user_id, record):
    """Persist a closed trade to the per-user tax journal (date, entry, exit,
    fees/spread cost, gross & net PnL) — exportable for tax reporting."""
    try:
        user_store.append_trade(user_id, {
            "time":      record.get("time"),
            "symbol":    record.get("symbol"),
            "entry":     record.get("entryPrice"),
            "exit":      record.get("price"),
            "grossPnl":  record.get("grossPnl"),
            "costUsd":   record.get("costUsd"),
            "netPnl":    record.get("netPnl"),
            "balance":   record.get("balance"),
            "openedAt":  record.get("openedAt"),
        })
    except Exception as e:
        print(f"[UserLoop:{user_id}] trade-log failed: {e}")


def _make_broker(user):
    """Create the per-user broker with isolated config.

    Paper mode with no OANDA token → Yahoo Finance data (free, no account).
    Live mode (or OANDA token present) → OANDA broker.
    """
    import types
    paper = user.get("paper", True)
    oanda_token = user.get("oanda_token", "")
    fake_cfg = types.SimpleNamespace(
        OANDA_API_TOKEN  = oanda_token,
        OANDA_ACCOUNT_ID = user.get("oanda_account_id", ""),
        OANDA_ENV        = user.get("oanda_env", "practice"),
        SYMBOL           = user.get("symbol", "EUR_USD"),
        TIMEFRAME        = user.get("timeframe", "5m"),
        CANDLES          = 200,
        PAPER_TRADING    = paper,
        PAPER_BALANCE    = float(user.get("paper_balance", 1000)),
        STOP_LOSS_PIPS   = float(user.get("sl_pips", 20)),
        TAKE_PROFIT_PIPS = float(user.get("tp_pips", 40)),
        RISK_PER_TRADE   = float(user.get("risk", 0.005)),
        LEVERAGE         = float(user.get("leverage", 30)),
        MARGIN_CAP       = 0.5,
        MAX_SPREAD_PIPS  = 3.0,
        MIN_CONFIDENCE   = int(user.get("min_confidence", 62)),
    )
    # Paper + no OANDA token → free Yahoo Finance data, zero signup.
    if paper and not oanda_token:
        from apex.brokers import yahoo
        return yahoo, fake_cfg
    return OandaBroker(fake_cfg), fake_cfg


def _loop(user_id, alert_fn):
    user = user_store.load(user_id)
    broker, cfg = _make_broker(user)

    paper_balance = cfg.PAPER_BALANCE
    open_pos = None  # tracked locally for paper mode
    tick = 0
    last_ai_error_tick = -_AI_ERROR_THROTTLE  # allow first error immediately

    dash = {
        "broker": f"OANDA ({cfg.OANDA_ENV})",
        "balance": paper_balance,
        "startBalance": paper_balance,
        "symbol": cfg.SYMBOL,
        "trades": [],
        "lastTick": None,
        "currentPrice": None,
    }
    with _lock:
        if user_id in _loops:
            _loops[user_id]["dash"] = dash

    while True:
        with _lock:
            if not _loops.get(user_id, {}).get("running"):
                break
        try:
            if not forex.is_market_open():
                time.sleep(60)
                continue

            candles = broker.get_candles(cfg.SYMBOL, cfg.TIMEFRAME, cfg.CANDLES)
            if not candles:
                time.sleep(30)
                continue

            tick += 1
            price = candles[-1]["close"]
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            dash["currentPrice"] = price
            dash["lastTick"] = now_str

            # Live: sync position from broker; paper: use local tracking
            if not cfg.PAPER_TRADING:
                open_pos = broker.get_open_position(cfg.SYMBOL)
                try:
                    paper_balance = broker.get_balance()
                except Exception:
                    pass

            dash["balance"] = paper_balance
            dash["openPosition"] = open_pos

            ind = indicators.analyze(candles)
            strat_data = strategies.analyze(candles)

            # Check risk limits
            stop_check = strategies.should_stop(paper_balance, dash["startBalance"])
            if stop_check["stop"]:
                print(f"[UserLoop:{user_id}] Strategy stop: {stop_check['reasons']}")
                if alert_fn:
                    alert_fn(user_id, {"action": "STOP", "reasons": stop_check["reasons"]})
                time.sleep(_LOOP_INTERVAL)
                continue

            # Heartbeat — let user know bot is alive even during quiet markets
            if tick % _HEARTBEAT_TICKS == 0 and alert_fn:
                pos_info = (f" | Position: {open_pos['side']} @ {open_pos['entryPrice']}"
                            if open_pos else " | No open position")
                alert_fn(user_id, {
                    "action": "HEARTBEAT",
                    "symbol": cfg.SYMBOL,
                    "price": price,
                    "balance": paper_balance,
                    "tick": tick,
                    "posInfo": pos_info,
                })

            # AI signal with rule-based fallback
            try:
                signal = ai.get_signal(ind, paper_balance, open_pos, strat_data)
            except Exception as e:
                print(f"[UserLoop:{user_id}] AI error: {e}")
                if tick - last_ai_error_tick >= _AI_ERROR_THROTTLE and alert_fn:
                    alert_fn(user_id, {
                        "action": "AI_ERROR",
                        "reason": str(e),
                        "symbol": cfg.SYMBOL,
                    })
                    last_ai_error_tick = tick
                signal = ai.mean_reversion_signal(ind, open_pos)

            action = signal.get("action", "HOLD")
            confidence = signal.get("confidence", 0)

            entry_ok = action in ("BUY", "SELL") and not open_pos and confidence >= cfg.MIN_CONFIDENCE
            if entry_ok:
                # ── Cost control: the spread is forex's hidden fee. Skip a too-wide
                #    spread and refuse trades whose target can't clear a round-trip
                #    spread plus a safety margin (break-even guard). ──
                try:
                    bid, ask = broker.get_bid_ask(cfg.SYMBOL)
                    spread = forex.spread_pips(bid, ask, cfg.SYMBOL)
                except Exception:
                    spread = 0.0
                max_spread = getattr(cfg, "MAX_SPREAD_PIPS", 3.0)
                if spread > max_spread:
                    print(f"[UserLoop:{user_id}] skip entry — spread {spread:.1f}p > {max_spread}p limit")
                    entry_ok = False
                elif cfg.TAKE_PROFIT_PIPS <= spread * 1.5:
                    print(f"[UserLoop:{user_id}] skip entry — TP {cfg.TAKE_PROFIT_PIPS:g}p doesn't clear spread {spread:.1f}p")
                    entry_ok = False

            if entry_ok:
                pip = forex.pip_size(cfg.SYMBOL)
                sl_price = (price - cfg.STOP_LOSS_PIPS * pip
                            if action == "BUY"
                            else price + cfg.STOP_LOSS_PIPS * pip)
                tp_price = (price + cfg.TAKE_PROFIT_PIPS * pip
                            if action == "BUY"
                            else price - cfg.TAKE_PROFIT_PIPS * pip)
                # Risk-based sizing: never risk more than RISK_PER_TRADE of balance.
                units = forex.calc_units(paper_balance, cfg.RISK_PER_TRADE,
                                         cfg.STOP_LOSS_PIPS, cfg.SYMBOL, price)
                units = max(int(units), 1000)

                broker.place_order(action, units, cfg.SYMBOL, sl=sl_price, tp=tp_price)

                if cfg.PAPER_TRADING:
                    open_pos = {"side": action, "entryPrice": price,
                                "symbol": cfg.SYMBOL, "units": units,
                                "quantity": units, "stopLoss": sl_price, "takeProfit": tp_price,
                                "entrySpreadPips": spread, "openedAt": now_str}
                else:
                    open_pos = broker.get_open_position(cfg.SYMBOL)

                dash["openPosition"] = open_pos
                result = {"action": action, "symbol": cfg.SYMBOL, "confidence": confidence,
                          "price": price, "spreadPips": round(spread, 1), "time": now_str}
                dash["trades"].insert(0, result)
                dash["trades"] = dash["trades"][:50]
                if alert_fn:
                    alert_fn(user_id, result)

            elif action == "CLOSE" and open_pos:
                broker.close_position(cfg.SYMBOL)
                gross = cost_usd = net = 0.0
                if cfg.PAPER_TRADING and open_pos:
                    units_ = open_pos.get("units", 1000)
                    gross = forex.pnl_usd(open_pos["side"], open_pos["entryPrice"],
                                          price, units_, cfg.SYMBOL)
                    # Net profit = gross minus the spread cost (forex's real fee).
                    pv = forex.pip_value_per_unit(cfg.SYMBOL, price)
                    cost_usd = open_pos.get("entrySpreadPips", 0.0) * pv * units_
                    net = gross - cost_usd
                    paper_balance += net
                result = {"action": "CLOSE", "symbol": cfg.SYMBOL, "price": price,
                          "entryPrice": open_pos.get("entryPrice"),
                          "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
                          "netPnl": round(net, 2), "balance": round(paper_balance, 2),
                          "openedAt": open_pos.get("openedAt"), "time": now_str}
                _log_trade(user_id, result)
                open_pos = None
                dash["openPosition"] = None
                dash["balance"] = paper_balance
                dash["trades"].insert(0, result)
                dash["trades"] = dash["trades"][:50]
                if alert_fn:
                    alert_fn(user_id, result)

        except Exception as e:
            print(f"[UserLoop:{user_id}] Error: {e}")

        time.sleep(_LOOP_INTERVAL)


def start(user_id, alert_fn=None):
    user_id = str(user_id)
    with _lock:
        if user_id in _loops and _loops[user_id]["running"]:
            return False
        _loops[user_id] = {"running": True, "dash": {}}

    user_store.update(user_id, {"active": True})
    t = threading.Thread(target=_loop, args=(user_id, alert_fn), daemon=True)
    t.start()
    with _lock:
        _loops[user_id]["thread"] = t
    print(f"[UserLoop] Started for user {user_id}")
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
    user_id = str(user_id)
    with _lock:
        return _loops.get(user_id, {}).get("running", False)


def get_dash(user_id):
    user_id = str(user_id)
    with _lock:
        return _loops.get(user_id, {}).get("dash", {})


def start_all(alert_fn=None):
    """Restart loops for all previously active users (after server reboot)."""
    for uid in user_store.all_active():
        start(uid, alert_fn)
