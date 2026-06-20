"""Per-user trading loop manager — each client gets their own isolated loop."""
import threading
import time
from apex import user_store, indicators, ai, strategies, state as state_mod, forex
from apex.brokers import oanda as oanda_broker


_loops = {}   # user_id → {"thread": Thread, "running": bool, "dash": dict}
_lock  = threading.Lock()


def _make_broker(user):
    """Create OANDA broker for this user's credentials."""
    import types
    fake_cfg = types.SimpleNamespace(
        OANDA_API_TOKEN  = user.get("oanda_token", ""),
        OANDA_ACCOUNT_ID = user.get("oanda_account_id", ""),
        OANDA_ENV        = user.get("oanda_env", "practice"),
        SYMBOL           = user.get("symbol", "EUR_USD"),
        TIMEFRAME        = user.get("timeframe", "5m"),
        CANDLES          = 200,
        PAPER_TRADING    = user.get("paper", True),
        PAPER_BALANCE    = float(user.get("paper_balance", 1000)),
        STOP_LOSS_PIPS   = float(user.get("sl_pips", 20)),
        TAKE_PROFIT_PIPS = float(user.get("tp_pips", 40)),
        RISK_PER_TRADE   = float(user.get("risk", 0.005)),
        LEVERAGE         = float(user.get("leverage", 30)),
        MARGIN_CAP       = 0.5,
        MAX_SPREAD_PIPS  = 3.0,
        MIN_CONFIDENCE   = int(user.get("min_confidence", 62)),
    )
    return oanda_broker.OandaBroker(fake_cfg), fake_cfg


def _loop(user_id, alert_fn):
    user = user_store.load(user_id)
    broker, cfg = _make_broker(user)
    dash = {
        "broker": f"OANDA ({cfg.OANDA_ENV})",
        "balance": cfg.PAPER_BALANCE,
        "startBalance": cfg.PAPER_BALANCE,
        "symbol": cfg.SYMBOL,
        "trades": [],
    }
    with _lock:
        if user_id in _loops:
            _loops[user_id]["dash"] = dash

    st = state_mod.BotState()

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

            ind = indicators.compute(candles)
            balance = broker.get_balance() if not cfg.PAPER_TRADING else dash["balance"]
            open_pos = broker.get_open_position(cfg.SYMBOL)
            signal = ai.get_signal(ind, balance, open_pos)

            # position management via strategies module
            result = strategies.decide(signal, ind, open_pos, st, cfg, broker)
            if result:
                dash["trades"].append(result)
                if alert_fn:
                    alert_fn(user_id, result)

            dash["balance"] = broker.get_balance() if not cfg.PAPER_TRADING else dash.get("balance", cfg.PAPER_BALANCE)
            dash["currentPrice"] = ind.get("price")

        except Exception as e:
            print(f"[UserLoop:{user_id}] Error: {e}")

        time.sleep(cfg.LOOP_INTERVAL_MS // 1000 if hasattr(cfg, "LOOP_INTERVAL_MS") else 300)


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
    """Restart loops for all previously active users (after VM reboot)."""
    for uid in user_store.all_active():
        start(uid, alert_fn)
