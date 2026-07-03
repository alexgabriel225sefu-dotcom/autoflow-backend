"""Per-user trading loop manager — each client gets their own isolated loop."""
import os
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
_LOSS_COOLDOWN_MIN = 5    # brief pause after a loss (was 20) — trade more freely


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
        CANDLES          = 240,  # M5 history for indicators (H1 gate removed → 720 was overkill)
        PAPER_TRADING    = paper,
        PAPER_BALANCE    = float(user.get("paper_balance", 1000)),
        STOP_LOSS_PIPS   = float(user.get("sl_pips", 20)),
        TAKE_PROFIT_PIPS = float(user.get("tp_pips", 40)),
        RISK_PER_TRADE   = float(user.get("risk", 0.01)),  # 1% default (was 0.5%) — bigger, still safe
        LEVERAGE         = float(user.get("leverage", 30)),
        MARGIN_CAP       = 0.5,
        MAX_SPREAD_PIPS  = 3.0,
        MIN_CONFIDENCE   = int(user.get("min_confidence", 55)),  # was 62 — trade more freely
        STRATEGY         = (user.get("strategy") or "auto").lower(),
        ATR_STOPS        = bool(user.get("atr_stops", True)),  # dynamic RR 1:2 by default
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

    symbol = cfg.SYMBOL
    # Multi-symbol scanner (premium spec): the client can watch ANY basket of
    # instruments their broker offers; the bot enters only the strongest
    # setup per cycle, one open position at a time.
    # Auto-Pilot: the bot picks the instruments itself from a curated liquid
    # universe (validated per broker at enable time). Otherwise the client's
    # own /symbol or /watch basket is used.
    autopilot = bool(user.get("autopilot"))
    if autopilot and user.get("autopilot_universe"):
        watchlist = [w for w in user["autopilot_universe"] if w][:8]
    else:
        watchlist = [w for w in (user.get("watchlist") or []) if w][:6]
    paper_balance = cfg.PAPER_BALANCE
    # REAL mode: the stored seed goes stale the moment a trade closes — read
    # the broker's actual balance BEFORE the first status can be asked for,
    # and persist it so any future restart seeds correctly too.
    if not cfg.PAPER_TRADING:
        try:
            paper_balance = broker.get_balance()
            user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
        except Exception as e:
            print(f"[UserLoop:{user_id}] initial balance read failed: {e}")
    open_pos = None  # tracked locally for paper mode
    tick = 0
    data_fails = 0   # consecutive get_candles failures — alert the user at 3
    last_loss_at = 0.0  # entry cooldown anchor (any losing close)
    last_close_at = 0.0 # re-entry lock after ANY close — kills open/close churn
    loss_streak = 0     # adaptive risk ladder: 2 losses → half risk, 3+ → quarter
    prev_open_syms = set()  # multi-position: detect broker-side closes tick-to-tick
    rate_limit_until = 0.0  # while > now, do only the minimal 1-symbol fetch
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
        "symbol": symbol,
        "watchlist": watchlist,
        "autopilot": autopilot,
        "trades": [],
        "lastTick": None,
        "currentPrice": None,
    }
    with _lock:
        if user_id in _loops:
            _loops[user_id]["dash"] = dash

    health = {"lats": [], "spreads": [], "degraded": False}

    def _health_check(lat=None, spread=None):
        """Broker Health Monitor (premium spec #8): when latency or spread
        blows past the broker's own recent norm, suspend entries and say so —
        degraded execution silently eats the edge."""
        if lat is not None:
            health["lats"] = (health["lats"] + [lat])[-30:]
        if spread is not None and spread > 0:
            health["spreads"] = (health["spreads"] + [spread])[-30:]
        bad = None
        lats, sps = health["lats"], health["spreads"]
        if len(lats) >= 6:
            med = sorted(lats)[len(lats) // 2]
            if lats[-1] > max(8.0, med * 5):
                bad = f"data latency {lats[-1]:.1f}s (normal ~{med:.1f}s)"
        if not bad and len(sps) >= 8 and spread is not None:
            med = sorted(sps)[len(sps) // 2]
            if spread > max(med * 4, med + 2):
                bad = f"spread {spread:.1f}p vs normal ~{med:.1f}p"
        was = health["degraded"]
        health["degraded"] = bool(bad)
        dash["brokerHealth"] = "degraded: " + bad if bad else "ok"
        if bad and not was and alert_fn:
            alert_fn(user_id, {"action": "BROKER_HEALTH", "status": "degraded",
                               "reason": bad, "symbol": symbol})
        elif was and not bad and alert_fn:
            alert_fn(user_id, {"action": "BROKER_HEALTH", "status": "recovered",
                               "symbol": symbol})
        return health["degraded"]

    def _skip(reason):
        """Journal every rejected entry (premium spec #12) — clients see the
        discipline, not just the trades: 'refused 14 weak setups today'."""
        today = datetime.now().strftime("%Y-%m-%d")
        if dash.get("skipsDay") != today:
            dash["skipsDay"], dash["skipsToday"] = today, 0
        dash["skipsToday"] = dash.get("skipsToday", 0) + 1
        lst = dash.setdefault("skips", [])
        lst.insert(0, {"time": datetime.now().strftime("%H:%M"), "reason": str(reason)[:120]})
        del lst[30:]

    while True:
        with _lock:
            entry = _loops.get(user_id, {})
            if not entry.get("running") or (gen is not None and entry.get("gen") != gen):
                break  # stopped, or replaced by a newer loop (restart race)
        try:
            if not forex.is_market_open():
                time.sleep(60)
                continue

            # ── MULTI-POSITION: how many concurrent trades, and total-risk cap.
            # Live-only (paper stays single). Total exposure is bounded by
            # sizing each trade at max_total_risk / maxpos, so N positions never
            # risk more than max_total_risk of the account combined.
            maxpos = int(user_store.load(user_id).get("maxpos", 1)) if not cfg.PAPER_TRADING else 1
            maxpos = max(1, min(maxpos, 8))
            max_total_risk = float(user_store.load(user_id).get("max_total_risk", 0.05))
            per_trade_risk = min(cfg.RISK_PER_TRADE, max_total_risk / maxpos)

            def _nrm(x):
                return (x or "").upper().replace("_", "").replace("/", "").replace("-", "")

            rate_ok = time.time() >= rate_limit_until
            all_positions = None
            open_syms, open_exposure = set(), []
            if not cfg.PAPER_TRADING and rate_ok:
                try:
                    all_positions = broker.get_all_positions()
                    open_syms = {_nrm(p["symbol"]) for p in all_positions}
                    open_exposure = [forex.usd_exposure(p["symbol"], p["side"]) for p in all_positions]
                except Exception as e:
                    all_positions = None  # unknown → don't open blind this tick
                    print(f"[UserLoop:{user_id}] positions read: {e}")
            # Report positions that closed at the broker since last tick.
            if all_positions is not None:
                # Focused symbol's close is reported by the single-position path
                # below; only announce the OTHER (self-managed) ones here.
                closed_now = prev_open_syms - open_syms - {_nrm(symbol)}
                for cs in closed_now:
                    if alert_fn:
                        alert_fn(user_id, {"action": "BROKER_CLOSE_MULTI", "symbol": cs,
                                           "balance": round(paper_balance, 2)})
                prev_open_syms = set(open_syms)
            open_count = len(open_syms)
            dash["openCount"] = open_count
            dash["maxpos"] = maxpos

            # ── Basket/Auto-Pilot scan: shop every watched symbol (that isn't
            # already open) and focus on the strongest candidate. Only scan if
            # we have a free slot. The winner still passes the FULL pipeline.
            slot_free = (all_positions is not None) and (open_count < maxpos)
            # Scan at most once every 3 ticks (~15 min) — 8 historical requests
            # every 5 min was tripping cTrader's trendbar rate limit and
            # freezing the loop. Between scans, keep the last focus.
            due_to_scan = (tick % 3 == 0)
            if watchlist and slot_free and due_to_scan and rate_ok:
                best = None
                for ws in watchlist:
                    if _nrm(ws) in open_syms:
                        continue  # already holding this one
                    try:
                        time.sleep(0.35)  # space out trendbar requests — cTrader rate-limits bursts
                        c2 = broker.get_candles(ws, cfg.TIMEFRAME, 160)
                        if not c2 or len(c2) < 130:
                            continue
                        ind2 = indicators.analyze(c2)
                        st2 = strategies.analyze(c2)
                        m2 = cfg.STRATEGY
                        if m2 == "auto":
                            reg2 = strategies.detect_regime(c2)
                            if reg2["regime"] == "quiet":
                                continue
                            m2 = {"trending": "trend", "ranging": "mean_reversion",
                                  "volatile": "breakout"}.get(reg2["regime"], "mean_reversion")
                        s2 = ai.signal_for_mode(m2, ind2, st2, None)
                        if (s2.get("action") in ("BUY", "SELL")
                                and s2.get("confidence", 0) >= cfg.MIN_CONFIDENCE
                                and (not best or s2["confidence"] > best[1])):
                            best = (ws, s2["confidence"])
                    except Exception as e:
                        print(f"[UserLoop:{user_id}] scan {ws}: {e}")
                if best:
                    symbol = best[0]
                    dash["symbol"] = symbol

            # Data fetch is the loop's lifeline — if it fails silently the user
            # just sees "Last tick: None" forever. Count failures and tell them.
            try:
                _t0 = time.time()
                candles = broker.get_candles(symbol, cfg.TIMEFRAME, cfg.CANDLES)
                _health_check(lat=time.time() - _t0)
                data_err = None if candles else "broker returned no candles"
            except Exception as e:
                candles, data_err = None, str(e)
            if not candles:
                data_fails += 1
                print(f"[UserLoop:{user_id}] data error ({data_fails}): {data_err}")
                rate_limited = "rate" in str(data_err).lower() or "BLOCKED_PAYLOAD" in str(data_err)
                if rate_limited:
                    rate_limit_until = time.time() + 120  # pause scanner/positions 2 min
                if data_fails == 3 and alert_fn and not rate_limited:
                    alert_fn(user_id, {
                        "action": "DATA_ERROR",
                        "reason": data_err,
                        "symbol": symbol,
                        "broker": dash.get("broker", "your broker"),
                    })
                # Rate-limit → back off longer so the limit resets; transient
                # rate limits shouldn't spam the user with data-error alerts.
                time.sleep(90 if rate_limited else 30)
                continue
            data_fails = 0

            tick += 1
            price = candles[-1]["close"]
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            dash["currentPrice"] = price
            dash["lastTick"] = now_str
            dash["lastTickTs"] = time.time()  # epoch — status shows "Xm ago", timezone-proof

            # Live: sync position from broker; paper: use local tracking.
            # If the position read FAILS we must not assume flat — entering
            # blind is how positions stack. Skip the tick and alert instead.
            if not cfg.PAPER_TRADING:
                prev_pos = open_pos
                try:
                    # Focus this tick on the SCANNED symbol; its position (if any)
                    # is managed here. Other open positions ride their broker
                    # SL/TP. In single-position mode (maxpos 1) fall back to
                    # whatever symbol currently holds the one position.
                    open_pos = broker.get_open_position(symbol)
                    if maxpos == 1 and watchlist and not open_pos:
                        for ws in watchlist:
                            if ws == symbol:
                                continue
                            p_ = broker.get_open_position(ws)
                            if p_:
                                symbol = ws
                                dash["symbol"] = symbol
                                open_pos = p_
                                candles = broker.get_candles(symbol, cfg.TIMEFRAME, cfg.CANDLES) or candles
                                break
                except Exception as e:
                    data_fails += 1
                    print(f"[UserLoop:{user_id}] position read error ({data_fails}): {e}")
                    if data_fails == 3 and alert_fn:
                        alert_fn(user_id, {
                            "action": "DATA_ERROR",
                            "reason": f"can't read open positions: {e}",
                            "symbol": symbol,
                            "broker": dash.get("broker", "your broker"),
                        })
                    time.sleep(30)
                    continue
                data_fails = 0
                prev_balance = paper_balance
                try:
                    paper_balance = broker.get_balance()
                    dash["balStale"] = False
                    if abs(paper_balance - prev_balance) >= 0.01:
                        user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
                except Exception as e:
                    # Keep trading on the last known balance, but never show a
                    # stale number as fresh — the client compares it to cTrader.
                    dash["balStale"] = True
                    print(f"[UserLoop:{user_id}] balance read error: {e}")
                if not open_pos and dash.get("manualHold"):
                    dash["manualHold"] = False
                # A balance jump with NO position close = deposit/withdrawal.
                # Shift the baseline so profit % keeps measuring TRADING only.
                if (abs(paper_balance - prev_balance) >= 0.01
                        and not (prev_pos and not open_pos)):
                    dash["startBalance"] = dash.get("startBalance", prev_balance) + (paper_balance - prev_balance)
                # cTrader executed the SL/TP server-side: the position we were
                # managing vanished between ticks. Tell the client — silence
                # here made broker-side exits invisible in Telegram.
                if prev_pos and not open_pos:
                    last_close_at = time.time()  # re-entry lock (churn guard)
                    pnl_est = round(paper_balance - prev_balance, 2) if not dash.get("balStale") else None
                    if pnl_est is not None and pnl_est < 0:
                        last_loss_at = time.time()
                        loss_streak += 1
                    elif pnl_est is not None and pnl_est > 0:
                        loss_streak = 0
                    result = {"action": "BROKER_CLOSE", "symbol": symbol,
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
                        pip_g = forex.pip_size(symbol, price)
                        stop_ = (open_pos["entryPrice"] - cfg.STOP_LOSS_PIPS * pip_g
                                 if side_ == "BUY"
                                 else open_pos["entryPrice"] + cfg.STOP_LOSS_PIPS * pip_g)
                    breached = stop_ and ((side_ == "BUY" and price <= stop_) or
                                          (side_ == "SELL" and price >= stop_))
                    if breached:
                        try:
                            broker.close_position(symbol)
                            if alert_fn:
                                alert_fn(user_id, {"action": "CLOSE", "symbol": symbol,
                                                   "price": price,
                                                   "reasoning": "🛡 Protective stop — price crossed the stop level; closed at market"})
                        except Exception as e:
                            print(f"[UserLoop:{user_id}] protective close failed: {e}")
                        last_loss_at = time.time()
                        last_close_at = time.time()
                        loss_streak += 1
                        open_pos = None
                        dash["openPosition"] = None
            else:
                if open_pos and open_pos.get("symbol") and open_pos["symbol"] != symbol:
                    symbol = open_pos["symbol"]
                    dash["symbol"] = symbol
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
                                          exit_price, units_, symbol)
                    pv = forex.pip_value_per_unit(symbol, exit_price)
                    cost_usd = open_pos.get("entrySpreadPips", 0.0) * pv * units_
                    net = gross - cost_usd
                    paper_balance += net
                    if net < 0:
                        last_loss_at = time.time()
                        loss_streak += 1
                    else:
                        loss_streak = 0
                    result = {"action": "CLOSE", "symbol": symbol,
                              "price": exit_price, "entryPrice": open_pos.get("entryPrice"),
                              "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
                              "netPnl": round(net, 2), "balance": round(paper_balance, 2),
                              "reason": hit, "openedAt": open_pos.get("openedAt"),
                              "time": now_str}
                    _log_trade(user_id, result)
                    # Persist so the simulated balance survives a restart.
                    user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
                    last_close_at = time.time()
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

            # Market regime → in AUTO mode it picks the engine, halves risk in
            # violent markets and stands aside in dead ones (premium spec #1).
            regime = strategies.detect_regime(candles)
            dash["regime"] = regime
            active_mode = cfg.STRATEGY
            regime_block = False
            if active_mode == "auto":
                picked = {"trending": "trend", "ranging": "mean_reversion",
                          "volatile": "breakout"}.get(regime["regime"])
                regime_block = regime["regime"] == "quiet"
                active_mode = picked or "mean_reversion"
                dash["strategy"] = f"Auto → {ai.STRATEGY_MODES[active_mode]['label']}"

            # Market Pulse: store a plain-language read for /market, and ping the
            # user (throttled) when the market gets notable (elevated volatility).
            mp = market.pulse(ind, strat_data, symbol)
            if mp:
                dash["market"] = mp
                if mp.get("notable") and alert_fn and tick - last_mkt_tick >= _SKIP_WARN_THROTTLE:
                    last_mkt_tick = tick
                    alert_fn(user_id, {"action": "MARKET_PULSE", "symbol": symbol, **mp})

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
                    "symbol": symbol,
                    "price": price,
                    "balance": paper_balance,
                    "tick": tick,
                    "posInfo": pos_info,
                })

            # AI signal with rule-based fallback
            try:
                signal = ai.get_signal(ind, paper_balance, open_pos, strat_data,
                                       mode=active_mode)
            except Exception as e:
                print(f"[UserLoop:{user_id}] AI error: {e}")
                if tick - last_ai_error_tick >= _AI_ERROR_THROTTLE and alert_fn:
                    alert_fn(user_id, {
                        "action": "AI_ERROR",
                        "reason": str(e),
                        "symbol": symbol,
                    })
                    last_ai_error_tick = tick
                signal = ai.signal_for_mode(active_mode, ind, strat_data, open_pos)

            action = signal.get("action", "HOLD")
            confidence = signal.get("confidence", 0)

            entry_ok = action in ("BUY", "SELL") and not open_pos and confidence >= cfg.MIN_CONFIDENCE
            # ── Multi-position gates (live) ──
            if entry_ok and not cfg.PAPER_TRADING:
                if all_positions is None:
                    entry_ok = False  # couldn't read positions — don't stack blind
                elif open_count >= maxpos:
                    entry_ok = False
                    _skip(f"at max positions ({open_count}/{maxpos})")
                elif _nrm(symbol) in open_syms:
                    entry_ok = False  # already holding this symbol
                else:
                    # Correlation guard: cap how many positions share the same
                    # USD direction, so 5 trades aren't secretly one USD bet.
                    new_exp = forex.usd_exposure(symbol, action)
                    if new_exp != 0:
                        same_dir = sum(1 for e in open_exposure if e == new_exp)
                        if same_dir >= 2:
                            entry_ok = False
                            _skip(f"correlation guard — already {same_dir} {'USD-long' if new_exp>0 else 'USD-short'} positions")
            # Quiet regime (AUTO): no edge, no trade.
            if entry_ok and regime_block:
                entry_ok = False
                _skip(regime.get("label", "market too quiet"))
                if alert_fn and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                    last_warn_tick = tick
                    alert_fn(user_id, {"action": "SKIP_WARN", "symbol": symbol,
                                       "reason": regime.get("label", "market too quiet")})
            # (Multi-timeframe gate relaxed to advisory by request — no longer
            # blocks entries, so the bot trades more freely.)
            # (Re-entry lock removed by request — the ATR stop floor already
            # prevents same-candle churn, so trade freely.)
            # Post-loss cooldown: the worst trade after a stop-out is the next
            # one taken 5 minutes later in the same falling knife.
            if entry_ok and last_loss_at and time.time() - last_loss_at < _LOSS_COOLDOWN_MIN * 60:
                left = int((_LOSS_COOLDOWN_MIN * 60 - (time.time() - last_loss_at)) / 60) + 1
                entry_ok = False
                _skip(f"post-loss cooldown ({left}m left)")
                if alert_fn and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                    last_warn_tick = tick
                    alert_fn(user_id, {"action": "SKIP_WARN", "symbol": symbol,
                                       "reason": f"cooling down after a loss — entries resume in ~{left}m"})
            if entry_ok:
                # ── Cost control: the spread is forex's hidden fee. Skip a too-wide
                #    spread and refuse trades whose target can't clear a round-trip
                #    spread plus a safety margin (break-even guard). ──
                try:
                    bid, ask = broker.get_bid_ask(symbol)
                    spread = forex.spread_pips(bid, ask, symbol)
                except Exception:
                    spread = 0.0
                _health_check(spread=spread)
                # Cost-aware edge (premium spec #5): round-trip commission in
                # pips joins the spread — the target must clear REAL costs.
                comm_pips = 0.0
                try:
                    comm_rt = float(os.getenv("COMMISSION_PER_LOT_RT", "7"))
                    pv_lot = forex.pip_value_per_unit(symbol, price) * 100_000
                    comm_pips = comm_rt / pv_lot if pv_lot > 0 else 0.0
                except Exception:
                    comm_pips = 0.0
                if health["degraded"]:
                    entry_ok = False
                    _skip(f"broker health: {dash.get('brokerHealth', 'degraded')}")
                max_spread = getattr(cfg, "MAX_SPREAD_PIPS", 3.0)
                if not entry_ok:
                    pass
                elif spread > max_spread:
                    print(f"[UserLoop:{user_id}] skip entry — spread {spread:.1f}p > {max_spread}p limit")
                    entry_ok = False
                    _skip(f"spread too wide ({spread:.1f}p > {max_spread:g}p)")
                    if alert_fn and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                        last_warn_tick = tick
                        alert_fn(user_id, {"action": "SKIP_WARN", "symbol": symbol,
                                           "reason": f"spread is unusually wide ({spread:.1f} pips) — "
                                                     "entering now would hand the edge to the broker"})
                elif cfg.TAKE_PROFIT_PIPS <= (spread + comm_pips) * 1.5:
                    print(f"[UserLoop:{user_id}] skip entry — TP {cfg.TAKE_PROFIT_PIPS:g}p doesn't clear costs {spread + comm_pips:.1f}p")
                    entry_ok = False
                    _skip(f"edge too thin: TP {cfg.TAKE_PROFIT_PIPS:g}p vs real costs {spread + comm_pips:.1f}p (spread+commission)")

            # Flash-crash circuit breaker: skip entry when the latest candle's
            # range is extreme for an FX major (>1.2% ≈ a violent spike).
            if entry_ok and _flash_spike(candles, 0.012):
                entry_ok = False
                _skip("flash-crash guard: extreme candle range")
                if alert_fn and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                    last_warn_tick = tick
                    alert_fn(user_id, {"action": "FLASH_WARN", "symbol": symbol})

            # News guard: stand aside around high-impact releases for either
            # currency in the pair. Fail-open (no event / feed down → trades).
            if entry_ok:
                ev = news.high_impact_window(symbol.split("_"))
                if ev:
                    entry_ok = False
                    _skip(f"news guard: {ev.get('title', 'high-impact event') if isinstance(ev, dict) else ev}")
                    if alert_fn and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                        last_warn_tick = tick
                        alert_fn(user_id, {"action": "NEWS_WARN", "symbol": symbol, "event": ev})

            # Copilot mode: propose the trade and wait for approval instead of
            # auto-executing. Re-read the flag each time so /copilot takes effect
            # without a restart (entry_ok is rare, so the extra load is cheap).
            if entry_ok and user_store.load(user_id).get("copilot"):
                _suggest_trade(user_id, signal, symbol, price, alert_fn)
                entry_ok = False

            if entry_ok:
                pip = forex.pip_size(symbol, price)
                stop_pips_eff = cfg.STOP_LOSS_PIPS
                # Dynamic ATR stops (premium spec #10): SL = 1.5×ATR, TP = 3×ATR
                # — distances that breathe with the instrument's volatility.
                atr_v = 0.0
                if getattr(cfg, "ATR_STOPS", False):
                    try:
                        atr_v = float(ind.get("atr") or 0)
                    except (TypeError, ValueError):
                        atr_v = 0.0
                if atr_v > 0:
                    # Wider stop + far target so trades breathe and profits run.
                    sl_dist, tp_dist = 2.0 * atr_v, 5.0 * atr_v
                    # FLOOR: on a 5-min candle the ATR of a calm FX pair is only
                    # ~2 pips, so 1.5×ATR is a sub-noise stop that the spread
                    # alone triggers instantly — the churn that bled the account.
                    # Never let the stop sit inside spread+noise: at least 4×
                    # the current spread and a sane per-class pip floor.
                    min_stop = max(4.0 * spread * pip, 10.0 * pip)
                    if sl_dist < min_stop:
                        sl_dist = min_stop
                        tp_dist = 2.0 * sl_dist  # keep RR ≥ 1:2
                    stop_pips_eff = forex.to_pips(sl_dist, symbol, price)
                else:
                    sl_dist = cfg.STOP_LOSS_PIPS * pip
                    tp_dist = cfg.TAKE_PROFIT_PIPS * pip
                    if tp_dist < sl_dist:
                        # RR guard: a target smaller than the stop bleeds the
                        # account through costs no matter the win rate.
                        tp_dist = 2.0 * sl_dist
                        try:
                            signal.setdefault("keyFactors", []).append("TP auto-raised to 2×SL (RR guard)")
                        except Exception:
                            pass
                sl_price = price - sl_dist if action == "BUY" else price + sl_dist
                tp_price = price + tp_dist if action == "BUY" else price - tp_dist
                # Adaptive risk ladder (premium spec #3): consecutive losses
                # shrink the risk — 2 losses → ½, 3+ → ¼; violent regime → ½.
                risk_mult = 1.0 if loss_streak < 2 else (0.5 if loss_streak == 2 else 0.25)
                if regime.get("regime") == "volatile":
                    risk_mult *= 0.5
                units = forex.calc_units(paper_balance, per_trade_risk,
                                         stop_pips_eff, symbol, price,
                                         mult=risk_mult)
                units = max(int(units), forex.min_units(symbol))

                broker.place_order(action, units, symbol, sl=sl_price, tp=tp_price)

                if cfg.PAPER_TRADING:
                    open_pos = {"side": action, "entryPrice": price,
                                "symbol": symbol, "units": units,
                                "quantity": units, "stopLoss": sl_price, "takeProfit": tp_price,
                                "entrySpreadPips": spread, "openedAt": now_str}
                else:
                    # A read hiccup right after the fill must not look like
                    # "no position" — assume the order we just sent is live.
                    try:
                        open_pos = broker.get_open_position(symbol)
                    except Exception:
                        open_pos = None
                    open_pos = open_pos or {"side": action, "entryPrice": price,
                                            "symbol": symbol, "units": units,
                                            "quantity": units, "stopLoss": sl_price,
                                            "takeProfit": tp_price, "openedAt": now_str}

                dash["openPosition"] = open_pos
                result = {"action": action, "symbol": symbol, "confidence": confidence,
                          "price": price, "spreadPips": round(spread, 1), "time": now_str,
                          "stopLoss": sl_price, "takeProfit": tp_price,
                          "reasoning": signal.get("reasoning", ""),
                          "keyFactors": signal.get("keyFactors", [])}
                dash["trades"].insert(0, result)
                dash["trades"] = dash["trades"][:50]
                if alert_fn:
                    alert_fn(user_id, result)

            elif action == "CLOSE" and open_pos and dash.get("manualHold"):
                # /buy - /sell trades belong to the USER: the strategy engine
                # must not close them (a mean-reversion bot would instantly
                # exit a manual entry placed near the mean). SL/TP rule them.
                pass
            elif action == "CLOSE" and open_pos:
                # A strategy exit is NOT always a win — label it honestly.
                broker.close_position(symbol)
                units_ = open_pos.get("units") or open_pos.get("quantity", 1000)
                gross = forex.pnl_usd(open_pos["side"], open_pos["entryPrice"],
                                      price, units_, symbol)
                pv = forex.pip_value_per_unit(symbol, price)
                cost_usd = open_pos.get("entrySpreadPips", 0.0) * pv * units_
                net = gross - cost_usd
                if cfg.PAPER_TRADING:
                    paper_balance += net
                if net < 0:
                    last_loss_at = time.time()
                    loss_streak += 1
                elif net > 0:
                    loss_streak = 0
                result = {"action": "CLOSE", "symbol": symbol, "price": price,
                          "entryPrice": open_pos.get("entryPrice"),
                          "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
                          "netPnl": round(net, 2), "balance": round(paper_balance, 2),
                          "openedAt": open_pos.get("openedAt"), "time": now_str,
                          "reasoning": signal.get("reasoning", "")}
                _log_trade(user_id, result)
                if cfg.PAPER_TRADING:
                    # Persist so the simulated balance survives a restart.
                    user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
                last_close_at = time.time()
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


def live_balance(user_id):
    """Read the account balance from the broker RIGHT NOW (real mode only).
    /status and the terminal must never show a number older than the request
    — a withdrawal between loop ticks made the cached figure look broken."""
    user = user_store.load(str(user_id))
    if user.get("paper", True):
        return None
    try:
        broker, _cfg = _make_broker(user)
        bal = broker.get_balance()
        user_store.update(str(user_id), {"paper_balance": round(bal, 2)})
        d = get_dash(str(user_id))
        if d:
            d["balance"] = bal
        return bal
    except Exception as e:
        print(f"[UserLoop:{user_id}] live_balance failed: {e}")
        return None


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
    # Size a manual /buy the SAME way the autonomous bot does — ATR-based with
    # a noise floor — so it's never tiny because of a leftover wide fixed /sl.
    stop_pips_eff = cfg.STOP_LOSS_PIPS
    try:
        ind_m = indicators.analyze(broker.get_candles(sym, cfg.TIMEFRAME, 60) or [])
        atr_m = float(ind_m.get("atr") or 0)
    except Exception:
        atr_m = 0.0
    if getattr(cfg, "ATR_STOPS", True) and atr_m > 0:
        sl_dist = 2.0 * atr_m
        min_stop = max(4.0 * spread * pip, 10.0 * pip)
        if sl_dist < min_stop:
            sl_dist = min_stop
        tp_dist = 2.5 * sl_dist
        stop_pips_eff = forex.to_pips(sl_dist, sym, price)
    else:
        sl_dist = cfg.STOP_LOSS_PIPS * pip
        tp_dist = (max(cfg.TAKE_PROFIT_PIPS, 2.0 * cfg.STOP_LOSS_PIPS)
                   if cfg.TAKE_PROFIT_PIPS < cfg.STOP_LOSS_PIPS else cfg.TAKE_PROFIT_PIPS) * pip
    sl_price = price - sl_dist if side == "BUY" else price + sl_dist
    tp_price = price + tp_dist if side == "BUY" else price - tp_dist

    balance = user.get("paper_balance") or cfg.PAPER_BALANCE
    dash = get_dash(user_id)
    if dash:
        balance = dash.get("balance", balance)

    units = forex.calc_units(balance, cfg.RISK_PER_TRADE, stop_pips_eff, sym, price)
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
        dash["manualHold"] = True  # user's trade — engine keeps hands off, SL/TP manage
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
