"""Per-user trading loop manager — each client gets their own isolated loop."""
import os
import threading
import time
from datetime import datetime
from apex import user_store, indicators, ai, strategies, forex, news, market
from apex import config as cfg_mod
from apex.brokers.ctrader import CtraderBroker as _CtraderBroker


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
    """Create the per-user broker with isolated config — cTrader exclusively."""
    import types
    from apex import config as _appcfg
    paper = user.get("paper", False)
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
        # Crypto CFDs are leveraged far lower than FX (retail ~2-5x vs 30x), so
        # the margin cap must assume less leverage or it sizes positions the
        # account can't actually margin.
        LEVERAGE         = float(user.get("leverage", 5 if _appcfg.PRODUCT == "crypto" else 30)),
        MARGIN_CAP       = 0.5,
        MAX_SPREAD_PIPS  = 3.0,
        PRODUCT          = _appcfg.PRODUCT,  # so the loop's crypto branches fire
        # Asset-class-aware spread/volatility guards (crypto uses a %-of-price
        # spread limit + higher flash-spike bar; forex keeps the pip limit).
        # Pulled from the global product config so PRODUCT=crypto takes effect.
        MAX_SPREAD_PCT   = getattr(_appcfg, "MAX_SPREAD_PCT", 0),
        FLASH_SPIKE_PCT  = getattr(_appcfg, "FLASH_SPIKE_PCT", 0.012),
        MIN_CONFIDENCE   = int(user.get("min_confidence", 65)),
        STRATEGY         = (user.get("strategy") or "auto").lower(),
        ATR_STOPS        = bool(user.get("atr_stops", True)),  # dynamic RR 1:2 by default
        # ── Strategy Builder knobs (all per-user, all enforced in the loop) ──
        HTF_CONFIRM      = bool(user.get("htf", False)),          # multi-timeframe gate
        EXIT_MODE        = (user.get("exit_mode") or "fixed").lower(),
        TRAILING_STOP    = bool(user.get("trailing", False)),     # move SL behind price
        BREAKEVEN_AT_R   = float(user.get("breakeven_r", 0)),     # 0 = off; 1 = at +1R
        NEWS_FILTER      = bool(user.get("news_filter", _appcfg.PRODUCT != "crypto")),
        SESSION_FILTER   = list(user.get("session_filter") or []),  # [] = all sessions
        MAX_TRADES_DAY   = int(user.get("max_trades_day", 10)),
        MAX_DD_PCT       = float(user.get("max_dd_pct", 20)),
        MAX_DAILY_LOSS_PCT = float(user.get("max_daily_loss_pct", 3)),
    )
    return _CtraderBroker(fake_cfg), fake_cfg


def _broker_label(user, cfg):
    if user.get("ctrader_access_token") and user.get("ctrader_account_id"):
        return f"cTrader ({getattr(cfg, 'CTRADER_ENV', 'demo')})"
    if user.get("oanda_token"):
        return f"OANDA ({cfg.OANDA_ENV})"
    if getattr(cfg, 'PAPER_TRADING', False):
        return "Yahoo (paper data)"
    return "cTrader (not linked)"


def _looks_like_auth_error(msg: str) -> bool:
    """Broker errors that a token refresh + reconnect can heal (expired token,
    dropped/unroutable connection) vs. plain data hiccups."""
    m = (msg or "").lower()
    return any(k in m for k in (
        "auth", "token", "route", "not_authenticated", "expired",
        "invalid_request", "access", "unauthor"))


def _refresh_ctrader_token(user_id, cfg) -> bool:
    """Self-heal a cTrader connection: swap the expired access token for a fresh
    one using the stored refresh token, persist it, and drop the pooled
    connection so the next tick re-authenticates. Returns True on success.
    (When cTrader itself is down the refresh call also fails — harmless, we just
    keep retrying.)"""
    try:
        from apex.brokers import ctrader as _ct
        refresh = (getattr(cfg, "CTRADER_REFRESH_TOKEN", "")
                   or user_store.load(user_id).get("ctrader_refresh_token", ""))
        if not refresh:
            return False
        tok = _ct.refresh_access_token(refresh)
        access = tok.get("accessToken") or tok.get("access_token")
        new_refresh = tok.get("refreshToken") or tok.get("refresh_token") or refresh
        if not access:
            return False
        user_store.update(user_id, {"ctrader_access_token": access,
                                    "ctrader_refresh_token": new_refresh})
        cfg.CTRADER_ACCESS_TOKEN = access
        cfg.CTRADER_REFRESH_TOKEN = new_refresh
        try:
            _ct._drop_conn(getattr(cfg, "CTRADER_ENV", "demo"),
                           cfg.CTRADER_ACCOUNT_ID)
        except Exception:
            pass
        print(f"[UserLoop:{user_id}] cTrader token refreshed + reconnected")
        return True
    except Exception as e:
        print(f"[UserLoop:{user_id}] token refresh failed (cTrader may be down): {e}")
        return False


def _manage_trailing(broker, cfg, pos, symbol, price):
    """Trailing stop + break-even (Strategy Builder exit modes). Moves the SL
    only in the favourable direction — never loosens it, never closes the trade.
    Real-broker only (needs a live positionId + amend_sltp). Returns the new SL
    if it moved, else None. Fail-soft everywhere."""
    try:
        if not pos or not price or not hasattr(broker, "amend_sltp"):
            return None
        trailing = bool(getattr(cfg, "TRAILING_STOP", False))
        be_r = float(getattr(cfg, "BREAKEVEN_AT_R", 0) or 0)
        if not (trailing or be_r > 0):
            return None
        pid = pos.get("positionId")
        entry = pos.get("entryPrice")
        cur_sl = pos.get("stopLoss") or pos.get("sl")
        side = pos.get("side")
        if not (pid and entry and cur_sl and side in ("BUY", "SELL")):
            return None
        risk = abs(float(entry) - float(cur_sl))
        if risk <= 0:
            return None
        profit = (price - entry) if side == "BUY" else (entry - price)
        if profit <= 0:
            return None
        new_sl = float(cur_sl)
        # Break-even: once profit >= R×risk, lock the stop at entry.
        if be_r > 0 and profit >= be_r * risk:
            new_sl = max(new_sl, entry) if side == "BUY" else min(new_sl, entry)
        # Trailing: keep the stop one risk-unit (1R) behind price, tighten-only.
        if trailing:
            trail = (price - risk) if side == "BUY" else (price + risk)
            new_sl = max(new_sl, trail) if side == "BUY" else min(new_sl, trail)
        improved = (new_sl - cur_sl) if side == "BUY" else (cur_sl - new_sl)
        if improved > risk * 0.05:  # only amend on a meaningful move
            if broker.amend_sltp(pid, sl=new_sl, instrument=symbol):
                return new_sl
    except Exception as e:
        print(f"[Trailing] manage failed: {e}")
    return None


def _loop(user_id, alert_fn, gen=None):
    user = user_store.load(user_id)

    # Self-heal cross-product pollution AT THE SOURCE. When crypto & forex shared
    # one Redis namespace, a user record could keep the OTHER product's symbols
    # (a forex account trading SOLUSD, etc.). Scrub them out of every stored field
    # — symbol, watchlist, autopilot_universe — and PERSIST, so the terminal, the
    # status card and the scanner all reflect a clean, single-product account
    # without the user running any command.
    _block = getattr(cfg_mod, "CROSS_PRODUCT_BLOCK", set())

    def _foreign(sym):
        return bool(sym) and (sym.upper().replace("_", "").replace("/", "").replace("-", "")
                              in _block)

    _patch = {}
    if _foreign(user.get("symbol")):
        _patch["symbol"] = cfg_mod.SYMBOL
        user["symbol"] = cfg_mod.SYMBOL
    for _fld in ("watchlist", "autopilot_universe"):
        _orig = user.get(_fld) or []
        _clean = [s for s in _orig if s and not _foreign(s)]
        if _clean != _orig:
            _patch[_fld] = _clean
            user[_fld] = _clean
    if _patch:
        try:
            user_store.update(user_id, _patch)
            print(f"[UserLoop:{user_id}] scrubbed cross-product symbols: {list(_patch)}")
        except Exception as e:
            print(f"[UserLoop:{user_id}] cross-product scrub persist failed: {e}")

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
    # Forex + metals only — drop crypto CFDs / indices / anything non-FX that a
    # cTrader/Pepperstone account also lists, so they can never bleed into the
    # forex bot ("crypto intră peste forex"). Crypto has its own bot. (Guarded
    # by PRODUCT so this never touches the crypto build that reuses this engine.)
    if getattr(cfg, "PRODUCT", "forex") != "crypto":
        watchlist = [w for w in watchlist if forex.is_tradeable(w)]
        if not forex.is_tradeable(symbol):
            symbol = watchlist[0] if watchlist else "EUR_USD"
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
    _crypto_build = getattr(cfg, "PRODUCT", "forex") == "crypto"
    tick = 0
    data_fails = 0   # consecutive get_candles failures — alert the user at 3
    last_refresh_at = 0.0  # throttle cTrader token-refresh/reconnect attempts
    bar_seen = {}    # nrm(symbol) -> [newest_bar_time, ticks_unchanged]
    stale_alerted = 0.0  # throttle "feed frozen" alerts
    last_loss_at = 0.0  # entry cooldown anchor (any losing close)
    last_close_at = 0.0 # re-entry lock after ANY close — kills open/close churn
    loss_streak = 0     # adaptive risk ladder: 2 losses → half risk, 3+ → quarter
    prev_open_syms = set()  # multi-position: detect broker-side closes tick-to-tick
    pos_details = {}    # nrm(symbol) -> {symbol, side, entry, units} for P&L on close
    spread_blocked = {}  # nrm(symbol) -> retry_ts: Auto-Pilot avoids symbols whose
                         # spread is blown out (weekend crypto) instead of camping on them
    rate_limit_until = 0.0  # while > now, do only the minimal 1-symbol fetch
    last_ai_error_tick = -_AI_ERROR_THROTTLE  # allow first error immediately
    last_warn_tick = -_SKIP_WARN_THROTTLE     # smart-alert skip warnings (throttled)
    last_mkt_tick = -_SKIP_WARN_THROTTLE      # market-pulse heads-up (throttled)

    acct_env = (user.get("ctrader_env") or user.get("oanda_env") or "demo").lower()
    mode_label = ("📝 Simulation" if cfg.PAPER_TRADING
                  else ("🧪 Demo" if acct_env in ("demo", "practice")
                        else "🔴 LIVE"))
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

    health = {"lats": [], "spreads": [], "degraded": False, "last_alert": 0.0}

    def _health_check(lat=None, spread=None):
        """Broker Health Monitor (premium spec #8): when latency blows past the
        broker's own recent norm, suspend entries and say so. The spread-based
        check is skipped for crypto — the Auto-Pilot scans a basket whose per-
        coin spreads differ 10x (SOL 600p vs BTC 5p), so a shared spread median
        is meaningless and would flip-flop degraded/recovered every scan (spam).
        The per-entry %-spread guard already blocks wide-spread entries."""
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
        if not bad and not _crypto_build and len(sps) >= 8 and spread is not None:
            med = sorted(sps)[len(sps) // 2]
            if spread > max(med * 4, med + 2):
                bad = f"spread {spread:.1f}p vs normal ~{med:.1f}p"
        was = health["degraded"]
        health["degraded"] = bool(bad)
        dash["brokerHealth"] = "degraded: " + bad if bad else "ok"
        # Throttle the alert to at most once per 30 min so a flapping condition
        # can't spam the client.
        now = time.time()
        if alert_fn and now - health["last_alert"] > 1800:
            if bad and not was:
                health["last_alert"] = now
                alert_fn(user_id, {"action": "BROKER_HEALTH", "status": "degraded",
                                   "reason": bad, "symbol": symbol})
            elif was and not bad:
                health["last_alert"] = now
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
                    # Remember each position's details so we can compute realized
                    # P&L when it later closes at the broker (multi-position).
                    for p in all_positions:
                        pos_details[_nrm(p["symbol"])] = {
                            "symbol": p["symbol"], "side": p["side"],
                            "entry": p.get("entryPrice"), "units": p.get("units", 0)}
                except Exception as e:
                    all_positions = None  # unknown → don't open blind this tick
                    print(f"[UserLoop:{user_id}] positions read: {e}")
            # Report + JOURNAL positions that closed at the broker since last tick.
            if all_positions is not None:
                # Focused symbol's close is reported by the single-position path
                # below; only announce the OTHER (self-managed) ones here.
                closed_now = prev_open_syms - open_syms - {_nrm(symbol)}
                for cs in closed_now:
                    det = pos_details.get(cs, {})
                    # Only journal positions WE opened (have details for). Without
                    # this, a position opened by another bot sharing the account
                    # is journaled here with mismatched data — e.g. a gold entry
                    # reported as BTCUSD — corrupting P&L and the tax journal.
                    if not det or not det.get("entry"):
                        continue
                    est_pnl = None
                    xp = None
                    try:
                        if det.get("entry") and det.get("units"):
                            xc = broker.get_candles(det["symbol"], cfg.TIMEFRAME, 2)
                            xp = xc[-1]["close"] if xc else None
                            if xp:
                                est_pnl = round(forex.pnl_usd(det["side"], det["entry"], xp,
                                                              det["units"], det["symbol"]), 2)
                    except Exception:
                        est_pnl = None
                    now2 = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    rec = {"action": "CLOSE", "symbol": det.get("symbol", cs),
                           "entryPrice": det.get("entry"), "price": xp,
                           "grossPnl": est_pnl, "costUsd": 0.0, "netPnl": est_pnl,
                           "balance": round(paper_balance, 2), "time": now2}
                    _log_trade(user_id, rec)
                    dash["trades"].insert(0, {**rec, "reasoning": "closed at broker (target/stop)"})
                    dash["trades"] = dash["trades"][:50]
                    if est_pnl is not None and est_pnl < 0:
                        loss_streak += 1
                        last_loss_at = time.time()
                    elif est_pnl is not None and est_pnl > 0:
                        loss_streak = 0
                    pos_details.pop(cs, None)
                    if alert_fn:
                        alert_fn(user_id, {"action": "BROKER_CLOSE_MULTI", "symbol": det.get("symbol", cs),
                                           "netPnl": est_pnl, "balance": round(paper_balance, 2)})
                prev_open_syms = set(open_syms)
            open_count = len(open_syms)
            dash["openCount"] = open_count
            dash["maxpos"] = maxpos

            # ── Basket/Auto-Pilot scan: shop every watched symbol (that isn't
            # already open) and focus on the strongest candidate. Only scan if
            # we have a free slot. The winner still passes the FULL pipeline.
            # Free-slot signal differs by mode: live reads broker positions,
            # paper tracks a single local position (all_positions is always None
            # in paper, which used to freeze the scanner and pin the focus).
            slot_free = ((open_pos is None) if cfg.PAPER_TRADING
                         else ((all_positions is not None) and (open_count < maxpos)))
            # Scan cadence: forex every 3 ticks (~15 min); crypto every 2 (~10
            # min) because setups rotate faster across the coin basket and only
            # the focus symbol is entered per tick, so scanning too rarely misses
            # most setups. Requests are spaced 0.35s to respect cTrader's limit.
            # Also rescan immediately when the focus is spread-blocked so the bot
            # doesn't camp on a dead symbol.
            _scan_every = 1 if _crypto_build else 3
            due_to_scan = (tick % _scan_every == 0) or (
                spread_blocked.get(_nrm(symbol), 0) > time.time())
            if watchlist and slot_free and due_to_scan and rate_ok:
                best = None
                for ws in watchlist:
                    if _nrm(ws) in open_syms:
                        continue  # already holding this one
                    if spread_blocked.get(_nrm(ws), 0) > time.time():
                        continue  # spread blown out recently — try others first
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
                elif (spread_blocked.get(_nrm(symbol), 0) > time.time()
                      or _nrm(symbol) in open_syms):
                    # Nothing signalled this scan AND the current focus is
                    # untradeable (spread-blocked or already open) — camp on ANY
                    # tradeable coin instead of freezing on the dead one and
                    # re-tripping its spread guard forever.
                    for ws in watchlist:
                        if _nrm(ws) in open_syms:
                            continue
                        if spread_blocked.get(_nrm(ws), 0) > time.time():
                            continue
                        symbol = ws
                        dash["symbol"] = symbol
                        break

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
                # Self-heal: on a cTrader auth/route error, refresh the token +
                # reconnect ONCE (throttled to every 3 min) before nagging the
                # client to /ctrader. If cTrader is fully down this no-ops and we
                # just keep retrying until their API recovers.
                elif (not cfg.PAPER_TRADING and cfg.CTRADER_ACCESS_TOKEN
                      and _looks_like_auth_error(data_err)
                      and data_fails >= 2 and time.time() - last_refresh_at > 180):
                    last_refresh_at = time.time()
                    if _refresh_ctrader_token(user_id, cfg):
                        data_fails = 0
                        time.sleep(5)
                        continue
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

            # ── Frozen-feed detection ──────────────────────────────────────
            # If the newest candle's timestamp stops advancing, the broker isn't
            # quoting this symbol (many brokers freeze crypto-CFD feeds on
            # weekends / off-hours). A frozen feed never produces a signal, so
            # the bot would sit silent forever. Detect it, mark the symbol so
            # Auto-Pilot rotates to a live one, and tell the user once.
            _bt = candles[-1]["time"]
            # Diagnostic: shows whether the newest candle advances (fresh feed)
            # or repeats (frozen feed) — visible in the host logs.
            print(f"[UserLoop:{user_id}] tick {tick} {symbol} px={price} "
                  f"newest_bar={datetime.utcfromtimestamp(_bt).strftime('%m-%d %H:%M')}UTC "
                  f"bars={len(candles)}")
            _bs = bar_seen.get(_nrm(symbol))
            if _bs and _bs[0] == _bt:
                _bs[1] += 1
            else:
                bar_seen[_nrm(symbol)] = [_bt, 0]
            if bar_seen[_nrm(symbol)][1] >= 3:  # ~15+ min with no new candle
                spread_blocked[_nrm(symbol)] = time.time() + 900  # rotate away 15 min
                live_syms = [w for w in watchlist
                             if bar_seen.get(_nrm(w), [0, 0])[1] < 3
                             and spread_blocked.get(_nrm(w), 0) <= time.time()]
                # A long-lived cTrader connection can keep answering (heartbeats)
                # while its trendbar stream goes stale. If EVERY watched symbol
                # is frozen, the connection itself is stale — drop it so the next
                # tick reconnects fresh (throttled), then tell the user once.
                if not live_syms and not cfg.PAPER_TRADING and time.time() - last_refresh_at > 300:
                    last_refresh_at = time.time()
                    try:
                        from apex.brokers import ctrader as _ct
                        _ct._drop_conn(getattr(cfg, "CTRADER_ENV", "demo"),
                                       cfg.CTRADER_ACCOUNT_ID)
                        for k in bar_seen:  # reset so we re-measure after reconnect
                            bar_seen[k][1] = 0
                        print(f"[UserLoop:{user_id}] feed stale on all symbols — dropped cTrader connection to reconnect")
                    except Exception as e:
                        print(f"[UserLoop:{user_id}] stale-feed reconnect failed: {e}")
                if not live_syms and alert_fn and time.time() - stale_alerted > 3600:
                    stale_alerted = time.time()
                    alert_fn(user_id, {
                        "action": "DATA_ERROR",
                        "reason": ("the broker's price feed stopped sending new candles — "
                                   "reconnecting to the broker now. If it persists the broker "
                                   "may be having a data issue; the bot resumes when prices move."),
                        "symbol": symbol,
                        "broker": dash.get("broker", "your broker"),
                    })

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

                # Trailing-stop / break-even management for the open position
                # (Strategy Builder exit modes). Fail-soft; real-broker only.
                if open_pos and not cfg.PAPER_TRADING:
                    moved = _manage_trailing(broker, cfg, open_pos, symbol, price)
                    if moved is not None:
                        open_pos["stopLoss"] = open_pos["sl"] = moved
                        if alert_fn:
                            alert_fn(user_id, {"action": "STOP_MOVED", "symbol": symbol,
                                               "sl": moved, "side": open_pos.get("side")})
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
                # Neutral default: crypto trends more than it ranges, so a
                # warming-up/unknown regime should default to trend-following,
                # not fading (the forex default).
                _default_mode = "trend" if _crypto_build else "mean_reversion"
                active_mode = picked or _default_mode
                dash["strategy"] = f"Auto → {ai.STRATEGY_MODES[active_mode]['label']}"

            # Market Pulse: store a plain-language read for /market, and ping the
            # user (throttled) when the market gets notable (elevated volatility).
            mp = market.pulse(ind, strat_data, symbol)
            if mp:
                dash["market"] = mp
                if mp.get("notable") and alert_fn and tick - last_mkt_tick >= _SKIP_WARN_THROTTLE:
                    last_mkt_tick = tick
                    alert_fn(user_id, {"action": "MARKET_PULSE", "symbol": symbol, **mp})

            # Check risk limits (per-user, from the Strategy Builder)
            stop_check = strategies.should_stop(
                paper_balance, dash["startBalance"],
                max_daily_loss_pct=getattr(cfg, "MAX_DAILY_LOSS_PCT", 3.0),
                max_dd_pct=getattr(cfg, "MAX_DD_PCT", 20.0),
                max_trades_day=getattr(cfg, "MAX_TRADES_DAY", 10))
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
            _sig_t0 = time.time()
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
            # Signal TTL: if AI analysis took too long the market moved on.
            _sig_age = time.time() - _sig_t0
            if entry_ok and _sig_age > 5.0:
                entry_ok = False
                _skip(f"signal TTL expired ({_sig_age:.1f}s > 5s)")
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
            if entry_ok and getattr(cfg, "HTF_CONFIRM", False):
                htf_c = None
                try:
                    htf_c = broker.get_candles(symbol, "1h", 60)
                except Exception:
                    pass
                if htf_c and len(htf_c) >= 55:
                    htf_dir = strategies.htf_trend(htf_c)
                    if (action == "BUY" and htf_dir == "BEARISH") or \
                       (action == "SELL" and htf_dir == "BULLISH"):
                        entry_ok = False
                        _skip(f"HTF gate: {action} blocked by H1 {htf_dir} trend")
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
                bid, ask = 0.0, 0.0
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
                # Spread guard — crypto uses a %-of-price limit (pip-count limits
                # are meaningless across crypto's varied pip sizes); forex keeps
                # the pip limit.
                max_spread = getattr(cfg, "MAX_SPREAD_PIPS", 3.0)
                max_spread_pct = getattr(cfg, "MAX_SPREAD_PCT", 0)
                spread_pct = ((ask - bid) / price * 100) if price > 0 else 0.0
                if not entry_ok:
                    pass
                elif max_spread_pct > 0 and spread_pct > max_spread_pct:
                    print(f"[UserLoop:{user_id}] skip entry — spread {spread_pct:.2f}% > {max_spread_pct:g}% limit")
                    entry_ok = False
                    # Let Auto-Pilot rotate to a tradeable symbol instead of
                    # camping on this one until its spread normalises. Alert only
                    # on the FIRST detection per block window — repeating the
                    # same 'holding off' every cycle reads as a stuck bot.
                    was_blocked = spread_blocked.get(_nrm(symbol), 0) > time.time()
                    if not was_blocked:  # arm ONCE — don't renew the 30-min TTL every tick
                        spread_blocked[_nrm(symbol)] = time.time() + 1800
                    _skip(f"spread too wide ({spread_pct:.2f}% > {max_spread_pct:g}%)")
                    if alert_fn and not was_blocked and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                        last_warn_tick = tick
                        alert_fn(user_id, {"action": "SKIP_WARN", "symbol": symbol,
                                           "reason": f"spread is unusually wide ({spread_pct:.2f}%) — "
                                                     "entering now would hand the edge to the broker"})
                elif max_spread_pct <= 0 and spread > max_spread:
                    print(f"[UserLoop:{user_id}] skip entry — spread {spread:.1f}p > {max_spread}p limit")
                    entry_ok = False
                    was_blocked = spread_blocked.get(_nrm(symbol), 0) > time.time()
                    if not was_blocked:
                        spread_blocked[_nrm(symbol)] = time.time() + 1800
                    _skip(f"spread too wide ({spread:.1f}p > {max_spread:g}p)")
                    if alert_fn and not was_blocked and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                        last_warn_tick = tick
                        alert_fn(user_id, {"action": "SKIP_WARN", "symbol": symbol,
                                           "reason": f"spread is unusually wide ({spread:.1f} pips) — "
                                                     "entering now would hand the edge to the broker"})
                # Break-even guard (pip-based) only applies to the forex pip model;
                # crypto's %-spread guard above already ensures the edge clears costs.
                elif max_spread_pct <= 0 and cfg.TAKE_PROFIT_PIPS <= (spread + comm_pips) * 1.5:
                    print(f"[UserLoop:{user_id}] skip entry — TP {cfg.TAKE_PROFIT_PIPS:g}p doesn't clear costs {spread + comm_pips:.1f}p")
                    entry_ok = False
                    _skip(f"edge too thin: TP {cfg.TAKE_PROFIT_PIPS:g}p vs real costs {spread + comm_pips:.1f}p (spread+commission)")

            # Flash-crash circuit breaker: skip entry when the latest candle's
            # range is extreme (>1.2% for FX majors; crypto is far more volatile,
            # so the threshold is raised via FLASH_SPIKE_PCT).
            if entry_ok and _flash_spike(candles, getattr(cfg, "FLASH_SPIKE_PCT", 0.012)):
                entry_ok = False
                _skip("flash-crash guard: extreme candle range")
                if alert_fn and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                    last_warn_tick = tick
                    alert_fn(user_id, {"action": "FLASH_WARN", "symbol": symbol})

            # Session filter (Strategy Builder): only trade the sessions the user
            # picked. [] = all sessions. Crypto ignores this (runs 24/5 on the CFD
            # feed). Forex reacts to session opens, so honouring it is real.
            if entry_ok and not _crypto_build:
                want_sess = getattr(cfg, "SESSION_FILTER", []) or []
                if want_sess:
                    try:
                        now_sess = (market.session() or {}).get("label", "")
                    except Exception:
                        now_sess = ""
                    if now_sess and not any(w.lower() in now_sess.lower() for w in want_sess):
                        entry_ok = False
                        _skip(f"session filter: {now_sess} not in {', '.join(want_sess)}")

            # News guard: stand aside around high-impact releases for either
            # currency in the pair. Fail-open (no event / feed down → trades).
            # Gated by the user's news_filter toggle (Strategy Builder).
            if entry_ok and getattr(cfg, "NEWS_FILTER", True):
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
                _crypto = _crypto_build
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
                    # Crypto's magnitude pip makes 10×pip a 0.01-0.1% sub-noise
                    # floor; use a %-of-price floor (~0.4%) so the stop clears
                    # crypto tick noise. Forex keeps the 10-pip floor.
                    floor_abs = (0.004 * price) if _crypto else (10.0 * pip)
                    min_stop = max(4.0 * spread * pip, floor_abs)
                    if sl_dist < min_stop:
                        sl_dist = min_stop
                        tp_dist = 2.0 * sl_dist  # keep RR ≥ 1:2
                    stop_pips_eff = forex.to_pips(sl_dist, symbol, price)
                elif _crypto:
                    # No ATR available on crypto → %-of-price stop, not the
                    # sub-noise fixed-pip default (20 pips = 0.02% on SOL).
                    sl_dist = 0.012 * price   # ~1.2% stop
                    tp_dist = 0.024 * price   # ~2.4% target (RR 1:2)
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
                risk_mult = strategies.druckenmiller_multiplier(
                    confidence, signal.get("criteriaScore", 0),
                    strat_data.get("livermore"), strat_data.get("turtle"))
                if loss_streak >= 3:
                    risk_mult *= 0.25
                elif loss_streak == 2:
                    risk_mult *= 0.5
                if regime.get("regime") == "volatile":
                    risk_mult *= 0.5
                units = forex.calc_units(paper_balance, per_trade_risk,
                                         stop_pips_eff, symbol, price,
                                         leverage=cfg.LEVERAGE, mult=risk_mult)
                floor = forex.safe_min_units(symbol, paper_balance, price,
                                             cfg.LEVERAGE, cfg.MARGIN_CAP)
                if floor == 0:
                    _skip("account too small for minimum lot on this instrument")
                    entry_ok = False
                if not entry_ok:
                    pass  # margin too small — skip to CLOSE handling below
                else:
                    units = forex.round_units(max(units, floor), symbol)

                    # Spread re-check: verify spread is still acceptable
                    # right before execution — it may have widened since analysis.
                    _skip_exec = False
                    try:
                        _rb, _ra = broker.get_bid_ask(symbol)
                        _rs = forex.spread_pips(_rb, _ra, symbol)
                        _rs_pct = ((_ra - _rb) / price * 100) if price > 0 else 0.0
                        _msp = getattr(cfg, "MAX_SPREAD_PCT", 0)
                        _msp_pip = getattr(cfg, "MAX_SPREAD_PIPS", 3.0)
                        if _msp > 0 and _rs_pct > _msp:
                            _skip_exec = True
                            _skip(f"spread widened before exec ({_rs_pct:.2f}% > {_msp:g}%)")
                        elif _msp <= 0 and _rs > _msp_pip:
                            _skip_exec = True
                            _skip(f"spread widened before exec ({_rs:.1f}p > {_msp_pip:g}p)")
                        else:
                            price = (_rb + _ra) / 2
                            sl_price = price - sl_dist if action == "BUY" else price + sl_dist
                            tp_price = price + tp_dist if action == "BUY" else price - tp_dist
                    except Exception:
                        pass
                    if _skip_exec:
                        entry_ok = False
                    else:
                        try:
                            from apex import control as _ctl
                            _ctl.event("order", f"{action} {symbol} units={units} @~{price} "
                                       f"SL={sl_price} TP={tp_price}", user_id=user_id)
                        except Exception:
                            pass
                        broker.place_order(action, units, symbol, sl=sl_price, tp=tp_price)

                        if cfg.PAPER_TRADING:
                            open_pos = {"side": action, "entryPrice": price,
                                        "symbol": symbol, "units": units,
                                        "quantity": units, "stopLoss": sl_price, "takeProfit": tp_price,
                                        "entrySpreadPips": spread, "openedAt": now_str}
                        else:
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


def start_watchdog(alert_fn=None, interval=180):
    """Self-healing watchdog: every `interval` seconds, restart any user marked
    active whose loop thread has died (crash, unhandled error, server hiccup).
    Runs 24/7 inside the bot process, so overnight recovery needs no operator and
    no external session — start() is idempotent, so healthy loops are untouched."""
    def _run():
        while True:
            time.sleep(interval)
            try:
                for uid in (user_store.all_active() or []):
                    if not is_running(uid):
                        print(f"[Watchdog] active loop for {uid} is down — restarting")
                        try:
                            start(uid, alert_fn)
                            from apex import control as _ctl
                            _ctl.event("watchdog", f"restarted dead loop for {uid}", user_id=uid)
                        except Exception as e:
                            print(f"[Watchdog] restart failed for {uid}: {e}")
            except Exception as e:
                print(f"[Watchdog] sweep error: {e}")
    threading.Thread(target=_run, daemon=True).start()
    print(f"[Watchdog] self-healing watchdog ON (every {interval}s)")


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
    # Forex + metals only — reject manual trades on crypto CFDs / indices.
    if getattr(cfg, "PRODUCT", "forex") != "crypto" and not forex.is_tradeable(sym):
        return {"ok": False, "error": f"{sym} isn't a forex/metal instrument — this is a "
                                      "forex bot (crypto has its own bot). Try e.g. EUR_USD or XAUUSD."}
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

    units = forex.calc_units(balance, cfg.RISK_PER_TRADE, stop_pips_eff, sym, price,
                             leverage=cfg.LEVERAGE)
    units = forex.round_units(max(units, forex.min_units(sym)), sym)

    try:
        from apex import control as _ctl
        _ctl.event("order", f"{side} {sym} units={units} @~{price} "
                   f"SL={sl_price} TP={tp_price} (manual)", user_id=user_id)
    except Exception:
        pass
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
