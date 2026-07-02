"""Per-user trading loop manager — each client gets their own isolated loop."""
import threading
import time
from datetime import datetime
from apex import user_store, indicators, ai, strategies, forex, news, market
from apex.brokers.oanda import OandaBroker


_loops = {}   # user_id → {"thread": Thread, "running": bool, "dash": dict}
_lock  = threading.Lock()

_LOOP_INTERVAL = 300  # 5 minutes between ticks
_HEARTBEAT_TICKS = 30  # heartbeat every 30 ticks (~2.5 hours swing)
_AI_ERROR_THROTTLE = 30  # alert AI failure at most once per 30 ticks
_SKIP_WARN_THROTTLE = 6  # "don't trade now" market-condition warnings (~30 min)


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

    Selection order:
      • cTrader linked (token + account) → cTrader (free, international)
      • OANDA token present or live mode  → OANDA
      • paper + no broker linked          → Yahoo Finance data (free, no account)
    """
    import types
    paper = user.get("paper", True)
    oanda_token = user.get("oanda_token", "")
    ct_token = user.get("ctrader_access_token", "")
    ct_account = user.get("ctrader_account_id", "")
    fake_cfg = types.SimpleNamespace(
        OANDA_API_TOKEN  = oanda_token,
        OANDA_ACCOUNT_ID = user.get("oanda_account_id", ""),
        OANDA_ENV        = user.get("oanda_env", "practice"),
        CTRADER_ACCESS_TOKEN  = ct_token,
        CTRADER_REFRESH_TOKEN = user.get("ctrader_refresh_token", ""),
        CTRADER_ACCOUNT_ID    = ct_account,
        CTRADER_ENV           = user.get("ctrader_env", "demo"),
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
        STRATEGY         = (user.get("strategy") or "mean_reversion").lower(),
    )
    # cTrader linked → use it (paper uses its data; live places real orders worldwide).
    if ct_token and ct_account:
        from apex.brokers.ctrader import CtraderBroker
        return CtraderBroker(fake_cfg), fake_cfg
    # Paper + no broker linked → free Yahoo Finance data, zero signup.
    if paper and not oanda_token:
        from apex.brokers import yahoo
        return yahoo, fake_cfg
    return OandaBroker(fake_cfg), fake_cfg


def _broker_label(user, cfg):
    if user.get("ctrader_access_token") and user.get("ctrader_account_id"):
        return f"cTrader ({getattr(cfg, 'CTRADER_ENV', 'demo')})"
    if user.get("oanda_token") or not user.get("paper", True):
        return f"OANDA ({cfg.OANDA_ENV})"
    return "Yahoo (paper data)"


def _loop(user_id, alert_fn, gen=None):
    user = user_store.load(user_id)
    broker, cfg = _make_broker(user)

    paper_balance = cfg.PAPER_BALANCE
    open_pos = None  # tracked locally for paper mode
    tick = 0
    data_fails = 0   # consecutive get_candles failures — alert the user at 3
    last_ai_error_tick = -_AI_ERROR_THROTTLE  # allow first error immediately
    last_warn_tick = -_SKIP_WARN_THROTTLE     # smart-alert skip warnings (throttled)
    last_mkt_tick = -_SKIP_WARN_THROTTLE      # market-pulse heads-up (throttled)

    acct_env = (user.get("ctrader_env") or user.get("oanda_env") or "practice").lower()
    mode_label = ("📝 PAPER (simulation)" if cfg.PAPER_TRADING
                  else ("🔴 REAL orders · demo account 🧪" if acct_env in ("demo", "practice")
                        else "🔴 REAL orders · LIVE account"))
    dash = {
        "broker": _broker_label(user, cfg),
        "mode": mode_label,
        "strategy": ai.STRATEGY_MODES.get(cfg.STRATEGY, ai.STRATEGY_MODES["mean_reversion"])["label"],
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
            entry = _loops.get(user_id, {})
            if not entry.get("running") or (gen is not None and entry.get("gen") != gen):
                break  # stopped, or replaced by a newer loop (restart race)
        try:
            if not forex.is_market_open():
                time.sleep(60)
                continue

            # Data fetch is the loop's lifeline — if it fails silently the user
            # just sees "Last tick: None" forever. Count failures and tell them.
            try:
                candles = broker.get_candles(cfg.SYMBOL, cfg.TIMEFRAME, cfg.CANDLES)
                data_err = None if candles else "broker returned no candles"
            except Exception as e:
                candles, data_err = None, str(e)
            if not candles:
                data_fails += 1
                print(f"[UserLoop:{user_id}] data error ({data_fails}): {data_err}")
                if data_fails == 3 and alert_fn:
                    alert_fn(user_id, {
                        "action": "DATA_ERROR",
                        "reason": data_err,
                        "symbol": cfg.SYMBOL,
                        "broker": dash.get("broker", "your broker"),
                    })
                time.sleep(30)
                continue
            data_fails = 0

            tick += 1
            price = candles[-1]["close"]
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            dash["currentPrice"] = price
            dash["lastTick"] = now_str

            # Live: sync position from broker; paper: use local tracking.
            # If the position read FAILS we must not assume flat — entering
            # blind is how positions stack. Skip the tick and alert instead.
            if not cfg.PAPER_TRADING:
                prev_pos = open_pos
                try:
                    open_pos = broker.get_open_position(cfg.SYMBOL)
                except Exception as e:
                    data_fails += 1
                    print(f"[UserLoop:{user_id}] position read error ({data_fails}): {e}")
                    if data_fails == 3 and alert_fn:
                        alert_fn(user_id, {
                            "action": "DATA_ERROR",
                            "reason": f"can't read open positions: {e}",
                            "symbol": cfg.SYMBOL,
                            "broker": dash.get("broker", "your broker"),
                        })
                    time.sleep(30)
                    continue
                data_fails = 0
                prev_balance = paper_balance
                try:
                    paper_balance = broker.get_balance()
                    dash["balStale"] = False
                except Exception as e:
                    # Keep trading on the last known balance, but never show a
                    # stale number as fresh — the client compares it to cTrader.
                    dash["balStale"] = True
                    print(f"[UserLoop:{user_id}] balance read error: {e}")
                # cTrader executed the SL/TP server-side: the position we were
                # managing vanished between ticks. Tell the client — silence
                # here made broker-side exits invisible in Telegram.
                if prev_pos and not open_pos:
                    pnl_est = round(paper_balance - prev_balance, 2) if not dash.get("balStale") else None
                    result = {"action": "BROKER_CLOSE", "symbol": cfg.SYMBOL,
                              "side": prev_pos.get("side", ""), "price": price,
                              "entryPrice": prev_pos.get("entryPrice"),
                              "netPnl": pnl_est, "balance": round(paper_balance, 2),
                              "grossPnl": pnl_est, "costUsd": 0.0,
                              "openedAt": prev_pos.get("openedAt"), "time": now_str}
                    _log_trade(user_id, result)
                    dash["trades"].insert(0, result)
                    dash["trades"] = dash["trades"][:50]
                    if alert_fn:
                        alert_fn(user_id, result)

                # Client-side protective stop: if the broker somehow holds the
                # position without a stop — or price already crossed it — close
                # at market. A naked position must never survive a tick.
                if open_pos:
                    side_ = open_pos.get("side")
                    stop_ = open_pos.get("stopLoss")
                    if not stop_ and open_pos.get("entryPrice"):
                        pip_g = forex.pip_size(cfg.SYMBOL, price)
                        stop_ = (open_pos["entryPrice"] - cfg.STOP_LOSS_PIPS * pip_g
                                 if side_ == "BUY"
                                 else open_pos["entryPrice"] + cfg.STOP_LOSS_PIPS * pip_g)
                    breached = stop_ and ((side_ == "BUY" and price <= stop_) or
                                          (side_ == "SELL" and price >= stop_))
                    if breached:
                        try:
                            broker.close_position(cfg.SYMBOL)
                            if alert_fn:
                                alert_fn(user_id, {"action": "CLOSE", "symbol": cfg.SYMBOL,
                                                   "price": price,
                                                   "reasoning": "🛡 Protective stop — price crossed the stop level; closed at market"})
                        except Exception as e:
                            print(f"[UserLoop:{user_id}] protective close failed: {e}")
                        open_pos = None
                        dash["openPosition"] = None
            else:
                # Reconcile with manual trades (force_trade/force_close write to
                # the shared dash via chat/commands). Adopt a manually-opened
                # position the loop doesn't know about, and clear one closed by
                # hand — otherwise the loop's local state clobbers it next tick.
                dash_pos = dash.get("openPosition")
                if dash_pos and not open_pos:
                    open_pos = dash_pos
                elif open_pos and dash_pos is None and dash.get("_manualClose"):
                    open_pos = None
                    dash["_manualClose"] = False
                # Sync balance if a manual close adjusted it
                dash_bal = dash.get("balance")
                if dash_bal and dash_bal != paper_balance and dash.get("_manualBal"):
                    paper_balance = dash_bal
                    dash["_manualBal"] = False

            dash["balance"] = paper_balance
            dash["openPosition"] = open_pos

            # ── Paper SL/TP enforcement ──
            # In LIVE mode OANDA holds the stop/target server-side, so a hit
            # closes the position and get_open_position() reflects it next tick.
            # In PAPER mode nothing closes the trade unless we check the price
            # ourselves — without this, stops are decorative and a losing paper
            # trade runs forever (only an AI "CLOSE" would ever exit it).
            if cfg.PAPER_TRADING and open_pos:
                hi = candles[-1].get("high", price)
                lo = candles[-1].get("low", price)
                sl = open_pos.get("stopLoss")
                tp = open_pos.get("takeProfit")
                pside = open_pos.get("side")
                hit = None
                if pside == "BUY":
                    if sl and lo <= sl:      hit = "STOP_LOSS"
                    elif tp and hi >= tp:    hit = "TAKE_PROFIT"
                else:  # SELL
                    if sl and hi >= sl:      hit = "STOP_LOSS"
                    elif tp and lo <= tp:    hit = "TAKE_PROFIT"
                if hit:
                    # Fill at the SL/TP level (realistic), not the candle close.
                    exit_price = sl if hit == "STOP_LOSS" else tp
                    units_ = open_pos.get("units", 1000)
                    gross = forex.pnl_usd(pside, open_pos["entryPrice"],
                                          exit_price, units_, cfg.SYMBOL)
                    pv = forex.pip_value_per_unit(cfg.SYMBOL, exit_price)
                    cost_usd = open_pos.get("entrySpreadPips", 0.0) * pv * units_
                    net = gross - cost_usd
                    paper_balance += net
                    result = {"action": "CLOSE", "symbol": cfg.SYMBOL,
                              "price": exit_price, "entryPrice": open_pos.get("entryPrice"),
                              "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
                              "netPnl": round(net, 2), "balance": round(paper_balance, 2),
                              "reason": hit, "openedAt": open_pos.get("openedAt"),
                              "time": now_str}
                    _log_trade(user_id, result)
                    # Persist so the simulated balance survives a restart.
                    user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
                    open_pos = None
                    dash["openPosition"] = None
                    dash["balance"] = paper_balance
                    dash["trades"].insert(0, result)
                    dash["trades"] = dash["trades"][:50]
                    if alert_fn:
                        alert_fn(user_id, result)
                    time.sleep(_LOOP_INTERVAL)
                    continue

            ind = indicators.analyze(candles)
            strat_data = strategies.analyze(candles)

            # Market Pulse: store a plain-language read for /market, and ping the
            # user (throttled) when the market gets notable (elevated volatility).
            mp = market.pulse(ind, strat_data, cfg.SYMBOL)
            if mp:
                dash["market"] = mp
                if mp.get("notable") and alert_fn and tick - last_mkt_tick >= _SKIP_WARN_THROTTLE:
                    last_mkt_tick = tick
                    alert_fn(user_id, {"action": "MARKET_PULSE", "symbol": cfg.SYMBOL, **mp})

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
                signal = ai.get_signal(ind, paper_balance, open_pos, strat_data,
                                       mode=getattr(cfg, "STRATEGY", "mean_reversion"))
            except Exception as e:
                print(f"[UserLoop:{user_id}] AI error: {e}")
                if tick - last_ai_error_tick >= _AI_ERROR_THROTTLE and alert_fn:
                    alert_fn(user_id, {
                        "action": "AI_ERROR",
                        "reason": str(e),
                        "symbol": cfg.SYMBOL,
                    })
                    last_ai_error_tick = tick
                signal = ai.signal_for_mode(getattr(cfg, "STRATEGY", "mean_reversion"), ind, strat_data, open_pos)

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
                    if alert_fn and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                        last_warn_tick = tick
                        alert_fn(user_id, {"action": "SKIP_WARN", "symbol": cfg.SYMBOL,
                                           "reason": f"spread is unusually wide ({spread:.1f} pips) — "
                                                     "entering now would hand the edge to the broker"})
                elif cfg.TAKE_PROFIT_PIPS <= spread * 1.5:
                    print(f"[UserLoop:{user_id}] skip entry — TP {cfg.TAKE_PROFIT_PIPS:g}p doesn't clear spread {spread:.1f}p")
                    entry_ok = False

            # Flash-crash circuit breaker: skip entry when the latest candle's
            # range is extreme for an FX major (>1.2% ≈ a violent spike).
            if entry_ok and _flash_spike(candles, 0.012):
                entry_ok = False
                if alert_fn and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                    last_warn_tick = tick
                    alert_fn(user_id, {"action": "FLASH_WARN", "symbol": cfg.SYMBOL})

            # News guard: stand aside around high-impact releases for either
            # currency in the pair. Fail-open (no event / feed down → trades).
            if entry_ok:
                ev = news.high_impact_window(cfg.SYMBOL.split("_"))
                if ev:
                    entry_ok = False
                    if alert_fn and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                        last_warn_tick = tick
                        alert_fn(user_id, {"action": "NEWS_WARN", "symbol": cfg.SYMBOL, "event": ev})

            # Copilot mode: propose the trade and wait for approval instead of
            # auto-executing. Re-read the flag each time so /copilot takes effect
            # without a restart (entry_ok is rare, so the extra load is cheap).
            if entry_ok and user_store.load(user_id).get("copilot"):
                _suggest_trade(user_id, signal, cfg.SYMBOL, price, alert_fn)
                entry_ok = False

            if entry_ok:
                pip = forex.pip_size(cfg.SYMBOL, price)
                sl_price = (price - cfg.STOP_LOSS_PIPS * pip
                            if action == "BUY"
                            else price + cfg.STOP_LOSS_PIPS * pip)
                tp_price = (price + cfg.TAKE_PROFIT_PIPS * pip
                            if action == "BUY"
                            else price - cfg.TAKE_PROFIT_PIPS * pip)
                # Risk-based sizing: never risk more than RISK_PER_TRADE of balance.
                units = forex.calc_units(paper_balance, cfg.RISK_PER_TRADE,
                                         cfg.STOP_LOSS_PIPS, cfg.SYMBOL, price)
                units = max(int(units), forex.min_units(cfg.SYMBOL))

                broker.place_order(action, units, cfg.SYMBOL, sl=sl_price, tp=tp_price)

                if cfg.PAPER_TRADING:
                    open_pos = {"side": action, "entryPrice": price,
                                "symbol": cfg.SYMBOL, "units": units,
                                "quantity": units, "stopLoss": sl_price, "takeProfit": tp_price,
                                "entrySpreadPips": spread, "openedAt": now_str}
                else:
                    # A read hiccup right after the fill must not look like
                    # "no position" — assume the order we just sent is live.
                    try:
                        open_pos = broker.get_open_position(cfg.SYMBOL)
                    except Exception:
                        open_pos = None
                    open_pos = open_pos or {"side": action, "entryPrice": price,
                                            "symbol": cfg.SYMBOL, "units": units,
                                            "quantity": units, "stopLoss": sl_price,
                                            "takeProfit": tp_price, "openedAt": now_str}

                dash["openPosition"] = open_pos
                result = {"action": action, "symbol": cfg.SYMBOL, "confidence": confidence,
                          "price": price, "spreadPips": round(spread, 1), "time": now_str,
                          "stopLoss": sl_price, "takeProfit": tp_price,
                          "reasoning": signal.get("reasoning", ""),
                          "keyFactors": signal.get("keyFactors", [])}
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
                          "openedAt": open_pos.get("openedAt"), "time": now_str,
                          "reasoning": signal.get("reasoning", "")}
                _log_trade(user_id, result)
                if cfg.PAPER_TRADING:
                    # Persist so the simulated balance survives a restart.
                    user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
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
        # Generation token: a stop()+start() restart can race a thread that is
        # asleep in its 5-minute tick — it wakes, sees the NEW entry's
        # running=True and keeps trading alongside the new loop (two engines
        # fighting over one account: open/close churn). The token lets the old
        # thread recognise it was replaced and exit.
        gen = _loops.get(user_id, {}).get("gen", 0) + 1
        _loops[user_id] = {"running": True, "gen": gen, "dash": {}}

    user_store.update(user_id, {"active": True})
    t = threading.Thread(target=_loop, args=(user_id, alert_fn, gen), daemon=True)
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


def _flash_spike(candles, pct):
    """True if the latest candle's high-low range exceeds `pct` of price — a
    flash-crash/spike signature. Fail-safe to False on bad data."""
    try:
        c = candles[-1]
        hi, lo = float(c["high"]), float(c["low"])
        ref = float(c.get("close") or c.get("open") or hi) or hi
        return ref > 0 and (hi - lo) / ref >= pct
    except Exception:
        return False


def _suggest_trade(user_id, signal, symbol, price, alert_fn):
    """Copilot mode: store a pending proposal and notify the user to approve it,
    instead of auto-executing. One open suggestion at a time (5-min window)."""
    user = user_store.load(user_id)
    pend = user.get("pending_suggestion")
    now = time.time()
    if pend and now - pend.get("ts", 0) < 300:
        return
    user_store.update(user_id, {"pending_suggestion": {
        "side": signal["action"], "symbol": symbol, "ts": now}})
    if alert_fn:
        alert_fn(user_id, {"action": "SUGGEST", "symbol": symbol, "side": signal["action"],
                           "price": price, "confidence": signal.get("confidence"),
                           "reasoning": signal.get("reasoning", ""),
                           "keyFactors": signal.get("keyFactors", [])})


def pending_suggestion(user_id):
    """Return the user's pending copilot suggestion ({side,symbol,ts}) or None."""
    return user_store.load(str(user_id)).get("pending_suggestion")


def clear_suggestion(user_id):
    """Drop the pending copilot suggestion (after approve/reject)."""
    user_store.update(str(user_id), {"pending_suggestion": None})


def force_trade(user_id, side, symbol=None):
    """Open a manual trade immediately (called from AI assistant or /buy /sell commands)."""
    user_id = str(user_id)
    user = user_store.load(user_id)
    broker, cfg = _make_broker(user)
    sym = (symbol or cfg.SYMBOL).upper()
    try:
        candles = broker.get_candles(sym, cfg.TIMEFRAME, 5)
        price = candles[-1]["close"] if candles else 0.0
    except Exception:
        price = 0.0
    if not price:
        return {"ok": False, "error": "Could not fetch price"}

    try:
        bid, ask = broker.get_bid_ask(sym)
        spread = forex.spread_pips(bid, ask, sym)
    except Exception:
        spread = 0.0

    pip = forex.pip_size(sym, price)
    sl_price = (price - cfg.STOP_LOSS_PIPS * pip if side == "BUY"
                else price + cfg.STOP_LOSS_PIPS * pip)
    tp_price = (price + cfg.TAKE_PROFIT_PIPS * pip if side == "BUY"
                else price - cfg.TAKE_PROFIT_PIPS * pip)

    balance = user.get("paper_balance") or cfg.PAPER_BALANCE
    dash = get_dash(user_id)
    if dash:
        balance = dash.get("balance", balance)

    units = forex.calc_units(balance, cfg.RISK_PER_TRADE, cfg.STOP_LOSS_PIPS, sym, price)
    units = max(int(units), forex.min_units(sym))

    try:
        broker.place_order(side, units, sym, sl=sl_price, tp=tp_price)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    open_pos = {"side": side, "entryPrice": price, "symbol": sym,
                "units": units, "stopLoss": sl_price, "takeProfit": tp_price,
                "entrySpreadPips": spread, "openedAt": now_str}

    with _lock:
        loop_data = _loops.get(user_id, {})
    if loop_data:
        dash = loop_data.get("dash", {})
        dash["openPosition"] = open_pos
        result = {"action": side, "symbol": sym, "confidence": 99,
                  "price": price, "spreadPips": round(spread, 1), "time": now_str}
        trades = dash.get("trades", [])
        trades.insert(0, result)
        dash["trades"] = trades[:50]

    return {"ok": True, "side": side, "symbol": sym, "price": price,
            "units": units, "spread": round(spread, 1),
            "sl": round(sl_price, 5), "tp": round(tp_price, 5)}


def force_close(user_id):
    """Close the open position immediately (called from AI assistant or /close command)."""
    user_id = str(user_id)
    user = user_store.load(user_id)
    broker, cfg = _make_broker(user)

    with _lock:
        dash = _loops.get(user_id, {}).get("dash", {})
    open_pos = dash.get("openPosition")
    if not open_pos:
        return {"ok": False, "error": "No open position to close"}

    sym = open_pos.get("symbol", cfg.SYMBOL)
    try:
        candles = broker.get_candles(sym, cfg.TIMEFRAME, 5)
        price = candles[-1]["close"] if candles else 0.0
    except Exception:
        price = 0.0

    try:
        broker.close_position(sym)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    gross = cost_usd = net = 0.0
    if cfg.PAPER_TRADING and open_pos and price:
        units_ = open_pos.get("units", 1000)
        gross = forex.pnl_usd(open_pos["side"], open_pos["entryPrice"], price, units_, sym)
        pv = forex.pip_value_per_unit(sym, price)
        cost_usd = open_pos.get("entrySpreadPips", 0.0) * pv * units_
        net = gross - cost_usd

    with _lock:
        loop_data = _loops.get(user_id, {})
    if loop_data:
        d = loop_data.get("dash", {})
        old_bal = d.get("balance", cfg.PAPER_BALANCE)
        new_bal = round(old_bal + net, 2)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = {"action": "CLOSE", "symbol": sym, "price": price,
                  "entryPrice": open_pos.get("entryPrice"),
                  "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
                  "netPnl": round(net, 2), "balance": new_bal,
                  "openedAt": open_pos.get("openedAt"), "time": now_str}
        _log_trade(user_id, result)
        if cfg.PAPER_TRADING:
            # Persist so the simulated balance survives a restart.
            user_store.update(user_id, {"paper_balance": new_bal})
        d["openPosition"] = None
        d["balance"] = new_bal
        d["_manualClose"] = True   # tell the loop this close was manual
        d["_manualBal"] = True
        trades = d.get("trades", [])
        trades.insert(0, result)
        d["trades"] = trades[:50]

    return {"ok": True, "symbol": sym, "price": price,
            "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
            "netPnl": round(net, 2)}
