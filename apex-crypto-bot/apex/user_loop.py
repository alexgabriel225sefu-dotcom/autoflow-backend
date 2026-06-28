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
from apex import user_store, indicators, ai, strategies, binance, dca as dca_mod, grid as grid_mod

# Symbols auto-scanned in "auto" mode (highest-volume, best liquidity)
_AUTO_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT",
    "SOLUSDT", "AVAXUSDT", "DOTUSDT", "ADAUSDT",
]


_loops = {}   # user_id → {"running": bool, "thread": Thread, "dash": dict}
_lock = threading.Lock()


def _default_settings():
    s = {
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
    s.update(dca_mod.default_settings())
    s.update(grid_mod.default_settings())
    return s


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


# Standard spot TAKER fee per exchange. Real-time per-pair fees need account
# API keys; these public rates are used for paper P&L and break-even math.
_FEE_BY_EXCHANGE = {
    "binance":   0.001,    # 0.10%
    "binanceus": 0.001,    # 0.10%
    "coinbase":  0.006,    # 0.60% retail taker
    "kraken":    0.0026,   # 0.26%
    "bybit":     0.001,    # 0.10%
    "okx":       0.001,    # 0.10%
}


def _fee_pct(u):
    """Taker fee for this user's exchange (differentiates between exchanges)."""
    ex = (u.get("exchange") or cfg.EXCHANGE or "binance").lower()
    return _FEE_BY_EXCHANGE.get(ex, cfg.FEE_PCT)


def _suggest_trade(state, signal, symbol, price, alert):
    """Copilot mode: propose a trade and wait for the user to approve, instead
    of auto-executing. Only one open suggestion at a time (5-min window) so the
    user isn't spammed every tick while a proposal is pending."""
    pend = state.get("pendingSuggestion")
    now = time.time()
    if pend and now - pend.get("ts", 0) < 300:
        return
    state["pendingSuggestion"] = {"side": signal["action"], "symbol": symbol, "ts": now}
    alert("suggest", {"side": signal["action"], "symbol": symbol, "price": price,
                      "confidence": signal.get("confidence"),
                      "reasoning": signal.get("reasoning", ""),
                      "keyFactors": signal.get("keyFactors", [])})


def _open_trade(u, state, settings, side, price, druck_mult, alert, exchange=None, signal=None):
    symbol = settings["SYMBOL"]
    fee_rate = _fee_pct(u)
    # Break-even guard: the target must clear a round-trip fee plus a safety
    # margin, else the fees eat the profit (critical for tight/scalping configs).
    breakeven = fee_rate * 2
    if settings["TAKE_PROFIT_PCT"] <= breakeven * 1.5:
        print(f"[UserLoop] skip entry — TP {settings['TAKE_PROFIT_PCT']*100:.2f}% "
              f"doesn't clear round-trip fees {breakeven*100:.2f}%")
        return
    risk = settings["RISK_PER_TRADE"] * druck_mult
    qty = round((state["paperBalance"] * risk) / price, 6)
    if qty <= 0:
        return
    # Live: place a real market order and use the actual fill price/qty.
    if exchange is not None:
        # Round to Binance LOT_SIZE / MIN_NOTIONAL first; skip loudly if too small.
        rq, err = binance.round_qty(symbol, qty, price, exchange=exchange.exchange)
        if err:
            print(f"[UserLoop] entry rejected — {err}")
            state["_lastError"] = err
            alert("error", {"message": err, "symbol": symbol})
            return
        qty = rq
        try:
            order = exchange.place_order(side, qty, symbol)
            price = order.get("avgPrice") or price
            qty = order.get("executedQty") or qty
        except Exception as e:
            print(f"[UserLoop] live order failed ({e}) — skipping entry")
            state["_lastError"] = f"Binance rejected the order: {e}"
            alert("error", {"message": str(e), "symbol": symbol})
            return
    else:
        fee = price * qty * fee_rate
        if side == "BUY":
            state["paperBalance"] -= price * qty + fee
        else:
            state["paperBalance"] += price * qty - fee
    sl, tp = _calc_sltp(side, price, settings)
    state["openPosition"] = {
        "symbol": symbol, "side": side, "entryPrice": price, "quantity": qty,
        "stopLoss": sl, "takeProfit": tp, "openedAt": datetime.utcnow().isoformat(), "pnlPct": 0,
    }
    sig = signal or {}
    alert("open", {"side": side, "symbol": symbol, "price": price, "qty": qty,
                   "stopLoss": sl, "takeProfit": tp, "druckMult": druck_mult,
                   "reasoning": sig.get("reasoning", ""),
                   "keyFactors": sig.get("keyFactors", []),
                   "confidence": sig.get("confidence")})


def _close_trade(u, state, settings, price, reason, alert, exchange=None, signal=None):
    pos = state["openPosition"]
    if not pos:
        return
    side, entry, qty, symbol = pos["side"], pos["entryPrice"], pos["quantity"], pos["symbol"]
    # Live: close with a real market order in the opposite direction.
    if exchange is not None:
        try:
            order = exchange.place_order("SELL" if side == "BUY" else "BUY", qty, symbol)
            price = order.get("avgPrice") or price
        except Exception as e:
            print(f"[UserLoop] live close failed ({e})")
    fee_rate = _fee_pct(u)
    fee_both = (entry + price) * qty * fee_rate
    gross = (price - entry if side == "BUY" else entry - price) * qty
    pnl = gross - fee_both    # net of maker/taker fees
    if exchange is None:
        if side == "BUY":
            state["paperBalance"] += price * qty * (1 - fee_rate)
        else:
            state["paperBalance"] -= price * qty * (1 + fee_rate)
    strategies.record_trade(state["session"], pnl > 0, pnl)
    state["trades"].insert(0, {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "symbol": symbol, "side": side,
        "entry": round(entry, 6), "exit": round(price, 6), "qty": qty,
        "grossPnl": round(gross, 4), "feeUsd": round(fee_both, 4),
        "pnl": round(pnl, 4), "pnlPct": round(pnl / (entry * qty) * 100, 2) if entry and qty else 0,
        "reason": reason, "win": pnl > 0,
    })
    state["trades"] = state["trades"][:50]
    state["openPosition"] = None
    alert("close", {"side": side, "symbol": symbol, "entryPrice": entry, "exitPrice": price,
                    "pnl": pnl, "balance": state["paperBalance"], "reason": reason,
                    "reasoning": (signal or {}).get("reasoning", "")})


def _find_best_signal(exchange_name, timeframe, session):
    """Scan all AUTO_SYMBOLS and return (symbol, signal) with the strongest setup.
    Uses only rule_based_fallback + legendary strategies — no AI key required.
    """
    best_sym, best_sig, best_score = None, None, 0
    for sym in _AUTO_SYMBOLS:
        try:
            candles = binance.get_candles(sym, timeframe, 60, exchange=exchange_name)
            if not candles:
                continue
            ind = indicators.analyze(candles)
            strat = strategies.analyze(candles, session)
            sig = ai.rule_based_fallback(ind, None, strat)
            if sig["action"] not in ("BUY", "SELL"):
                continue
            # Score = confidence × criteria — weights both quality and multi-factor alignment
            score = sig["confidence"] * sig.get("criteriaScore", 0)
            if score > best_score:
                best_score, best_sym, best_sig = score, sym, sig
        except Exception as e:
            print(f"[AutoScan] {sym} failed: {e}")
    return best_sym, best_sig


def _tick_grid(u, settings, state, candles, price, alert, exchange):
    """Run one Grid tick.  Returns True if grid is active (skip strategy entry)."""
    deal = state.get("grid_deal")

    if not deal:
        if not settings.get("grid_enabled"):
            return False
        # Auto-range: use last 50 candles high/low if user didn't set range
        lower = settings.get("grid_lower", 0)
        upper = settings.get("grid_upper", 0)
        if lower <= 0 or upper <= lower:
            highs = [c["high"] for c in candles[-50:]]
            lows  = [c["low"]  for c in candles[-50:]]
            lower = round(min(lows) * 0.999, 6)
            upper = round(max(highs) * 1.001, 6)
        sym = settings["SYMBOL"]
        deal = grid_mod.create_grid(sym, lower, upper,
                                    settings.get("grid_levels", 10),
                                    state["paperBalance"],
                                    settings.get("grid_order_pct", 2.0))
        if not deal:
            return False
        deal = grid_mod.setup_orders(deal, price)
        state["grid_deal"] = deal
        alert("grid_start", {
            "symbol": sym, "lower": lower, "upper": upper,
            "levels": settings.get("grid_levels", 10), "step": deal["step"],
        })
        return True

    deal, events = grid_mod.tick_grid(deal, price)
    for ev in events:
        if ev["type"] == "sell":
            # Live: place real sell order
            if exchange:
                try:
                    exchange.place_order("SELL", ev["qty"], deal["symbol"])
                except Exception as e:
                    print(f"[Grid] sell failed: {e}")
            alert("grid_fill", {
                "type": "SELL", "symbol": deal["symbol"],
                "price": ev["price"], "qty": ev["qty"],
                "pnl": ev.get("pnl", 0), "round_trips": deal["round_trips"],
                "total_pnl": deal["total_pnl"],
            })
            state["paperBalance"] = round(
                state["paperBalance"] + ev["price"] * ev["qty"] * (1 - cfg.FEE_PCT), 4)
        elif ev["type"] == "buy":
            if exchange:
                try:
                    exchange.place_order("BUY", ev["qty"], deal["symbol"])
                except Exception as e:
                    print(f"[Grid] buy failed: {e}")
            state["paperBalance"] = round(
                state["paperBalance"] - ev["price"] * ev["qty"] * (1 + cfg.FEE_PCT), 4)

    # Check if price left the grid range — stop the grid
    if price < deal["lower"] * 0.97 or price > deal["upper"] * 1.03:
        alert("grid_out_of_range", {
            "symbol": deal["symbol"], "price": price,
            "lower": deal["lower"], "upper": deal["upper"],
            "total_pnl": deal["total_pnl"], "round_trips": deal["round_trips"],
        })
        state["grid_deal"] = None
        return False

    state["grid_deal"] = deal
    return True


def _tick_dca(u, settings, state, price, alert, exchange):
    """Run one DCA tick. Returns True if DCA handled the tick (skip strategy)."""
    deal = state.get("dca_deal")

    if deal:
        deal, filled, reason = dca_mod.tick_deal(deal, price)
        for i in filled:
            so = deal["safety_orders"][i]
            # Live: place real safety order
            if exchange:
                try:
                    exchange.place_order(deal["side"], so["qty"], deal["symbol"])
                except Exception as e:
                    print(f"[DCA] safety order {i} failed: {e}")
            pnl_pct = dca_mod.deal_pnl_pct(deal, price)
            sign = "+" if pnl_pct >= 0 else ""
            alert("dca_safety", {
                "index": i + 1,
                "symbol": deal["symbol"],
                "price": so["price"],
                "qty": so["qty"],
                "avg_entry": deal["avg_entry"],
                "take_profit_price": deal["take_profit_price"],
                "safety_filled": deal["safety_filled"],
                "max_safety": len(deal["safety_orders"]),
                "pnl_pct": pnl_pct,
            })
        if reason:
            pnl = dca_mod.deal_pnl(deal, price)
            pnl_pct = dca_mod.deal_pnl_pct(deal, price)
            # Live: close the full position
            if exchange:
                try:
                    close_side = "SELL" if deal["side"] == "BUY" else "BUY"
                    exchange.place_order(close_side, deal["total_qty"], deal["symbol"])
                except Exception as e:
                    print(f"[DCA] close order failed: {e}")
            if deal["side"] == "BUY":
                state["paperBalance"] = round(state["paperBalance"] + price * deal["total_qty"] * (1 - cfg.FEE_PCT), 4)
            else:
                state["paperBalance"] = round(state["paperBalance"] - price * deal["total_qty"] * (1 + cfg.FEE_PCT), 4)
            strategies.record_trade(state["session"], pnl > 0, pnl)
            state["trades"].insert(0, {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": deal["symbol"], "side": deal["side"],
                "entry": deal["avg_entry"], "exit": round(price, 6),
                "qty": deal["total_qty"], "pnl": round(pnl, 4),
                "pnlPct": pnl_pct, "reason": f"DCA_{reason}", "win": pnl > 0,
            })
            state["trades"] = state["trades"][:50]
            state["dca_deal"] = None
            alert("dca_close", {
                "symbol": deal["symbol"], "reason": reason,
                "avg_entry": deal["avg_entry"], "exit_price": round(price, 6),
                "pnl": round(pnl, 4), "pnl_pct": pnl_pct,
                "safety_filled": deal["safety_filled"],
                "balance": state["paperBalance"],
            })
        else:
            state["dca_deal"] = deal
        return True

    # No active DCA deal — open one on BUY signal if DCA enabled
    return False


def _tick(user_id, alert):
    u = _ensure_user(user_id)
    settings, state = u["settings"], u["state"]
    if settings.get("PAUSED"):
        return
    state["tickCount"] = state.get("tickCount", 0) + 1

    pos = state.get("openPosition")
    ex_name = u.get("exchange", "binance")
    timeframe = settings["TIMEFRAME"]

    # Auto-mode + no open position: scan all symbols and trade the best setup.
    # This is what makes the bot truly autonomous — it finds the opportunity itself.
    if not pos and settings.get("STRATEGY_MODE", "auto") == "auto":
        session = state.get("session", {})
        best_sym, best_sig = _find_best_signal(ex_name, timeframe, session)
        if best_sym and best_sig and best_sig["action"] in ("BUY", "SELL"):
            conf_ok = best_sig["confidence"] >= settings["MIN_CONFIDENCE"]
            crit_ok = best_sig.get("criteriaScore", 0) >= settings["MIN_CRITERIA"]
            if conf_ok and crit_ok:
                if best_sym != settings["SYMBOL"]:
                    settings["SYMBOL"] = best_sym
                    alert("auto_symbol", {"symbol": best_sym,
                                          "action": best_sig["action"],
                                          "confidence": best_sig["confidence"],
                                          "reasoning": best_sig.get("reasoning", "")})
                # Fall through to normal tick with the best symbol selected
        # Always use the (possibly updated) symbol for this tick
    symbol = (state.get("openPosition") or {}).get("symbol") or settings["SYMBOL"]
    candles = binance.get_candles(symbol, timeframe, cfg.CANDLES, exchange=ex_name)
    if not candles:
        return
    price = binance.get_price(symbol, exchange=ex_name)

    # Both paper (testnet) and real use LiveExchange.
    # paper=True → Binance Testnet (virtual USDT, real market prices)
    # paper=False → real Binance mainnet
    # Falls back to internal simulation if user has no API keys yet.
    exchange = None
    if u.get("api_key") and u.get("api_secret"):
        is_testnet = u.get("paper", True)
        try:
            exchange = binance.LiveExchange(u["api_key"], u["api_secret"],
                                            testnet=is_testnet, exchange=u.get("exchange", "binance"))
            if not state.get("openPosition"):
                real_bal = exchange.get_balance("USDT")
                if real_bal > 0:
                    state["paperBalance"] = real_bal
                    if state["startBalance"] <= cfg.PAPER_BALANCE:
                        state["startBalance"] = real_bal
        except Exception as e:
            print(f"[UserLoop:{user_id}] exchange sync failed ({e}) — internal simulation this tick")
            exchange = None

    # Safety: a LIVE user (paper=False, keys set) whose exchange we couldn't reach
    # this tick must NOT fall through to the internal paper simulation — that would
    # book virtual trades while the dashboard says LIVE. Pause this cycle, tell the
    # user, and never fake a real order.
    if not u.get("paper", True) and u.get("api_key") and exchange is None:
        if state.get("tickCount", 0) % 10 == 0:   # throttle so it's not spammy
            alert("error", {"symbol": symbol,
                            "message": "Live Binance connection failed (keys / region / "
                            "network) — trading paused this cycle. No simulated trades placed."})
        user_store.save(user_id, u)
        return

    dash = _loops.get(user_id, {}).get("dash", {})
    dash.update({"balance": state["paperBalance"], "startBalance": state["startBalance"],
                 "currentSymbol": symbol, "currentPrice": price,
                 "lastTick": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "trades": state["trades"], "mode": "PAPER" if u.get("paper", True) else "LIVE"})

    pos = state.get("openPosition")
    if pos:
        pnl = _pos_pnl(pos, price)
        pos["currentPnl"] = round(pnl, 4)
        pos["pnlPct"] = round(pnl / (pos["entryPrice"] * pos["quantity"]) * 100, 2)
        dash["openPosition"] = pos
    else:
        dash["openPosition"] = None

    # Heartbeat: a single calm ping every 30 ticks (~30 min) whether in a
    # position or flat. No more per-tick spam — trade alerts cover the action.
    tick = state["tickCount"]
    if tick % 30 == 0 and tick > 0:
        if pos:
            alert("heartbeat", {"tickCount": tick, "balance": state["paperBalance"], "openPosition": pos})
        else:
            alert("scan", {"tickCount": tick, "balance": state["paperBalance"], "symbol": symbol})

    # Grid mode runs alongside strategy (handles range-trading, saves result)
    if settings.get("grid_enabled") or state.get("grid_deal"):
        _tick_grid(u, settings, state, candles, price, alert, exchange)
        user_store.save(user_id, u)
        # Grid doesn't block strategy exit check — still close open strategy positions
        if not state.get("openPosition"):
            return  # flat + grid running = no need for strategy entry this tick

    # Exit check first
    trigger = _check_exit(pos, price)
    if trigger:
        _close_trade(u, state, settings, price, trigger, alert, exchange)
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

    # ── Trading brain = rule-based legendary-strategy engine, BY DEFAULT ──
    # It scores Turtle + Livermore + Soros + RSI/MACD/EMA confluence on every
    # tick using ZERO API quota and never rate-limits — so trading runs 24/7
    # non-stop, and the AI key stays 100% reserved for the chat (where a human
    # actually needs it: 1,500 Gemini msgs/day >> any real conversation).
    #
    # Per-tick AI signals are OPT-IN: only when the client added their OWN Groq
    # key (their own ~14,400/day quota). We never burn the shared chat key on
    # the 1,440-ticks/day loop.
    user_key = u.get("groq_key") or None
    if user_key:
        try:
            signal = ai.get_signal(ind, state["paperBalance"], pos, strat,
                                   symbol=symbol, timeframe=timeframe, user_key=user_key)
        except Exception as e:
            if getattr(e, "user_key", False):
                # Their Groq key is rate-limited — fall back silently, but
                # remind them at most once every ~30 min (no spam).
                last_alert = state.get("lastGroqAlertTick", -999)
                if state["tickCount"] - last_alert >= 30:
                    alert("groq_error", {"reason": str(e)})
                    state["lastGroqAlertTick"] = state["tickCount"]
            else:
                print(f"[UserLoop:{user_id}] AI error: {e}")
            signal = ai.rule_based_fallback(ind, pos, strat)
    else:
        signal = ai.rule_based_fallback(ind, pos, strat)

    state["lastSignal"] = {"action": signal["action"], "confidence": signal["confidence"],
                           "criteriaScore": signal.get("criteriaScore", 0),
                           "reasoning": signal.get("reasoning", "")}

    conf_ok = signal["confidence"] >= settings["MIN_CONFIDENCE"]
    crit_ok = signal.get("criteriaScore", 0) >= settings["MIN_CRITERIA"]
    vol_ok = float(ind.get("volumeRatio") or 0) >= 0.2

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
            (mode == "ptj" and (signal["confidence"] < 72 or signal.get("criteriaScore", 0) < 3))
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

    # DCA mode: hand off to DCA engine if enabled
    if settings.get("dca_enabled") and not pos:
        if state.get("dca_deal"):
            _tick_dca(u, settings, state, price, alert, exchange)
        elif signal["action"] in ("BUY", "SELL") and conf_ok and crit_ok and vol_ok:
            deal = dca_mod.open_deal(symbol, signal["action"], price,
                                     state["paperBalance"], settings)
            if deal:
                # Deduct base order from paper balance
                if exchange is None:
                    cost = deal["base_price"] * deal["base_qty"] * (1 + cfg.FEE_PCT)
                    state["paperBalance"] = round(state["paperBalance"] - cost, 4)
                else:
                    try:
                        exchange.place_order(signal["action"], deal["base_qty"], symbol)
                    except Exception as e:
                        print(f"[DCA] base order failed: {e}")
                        deal = None
            if deal:
                state["dca_deal"] = deal
                alert("dca_open", {
                    "side": deal["side"], "symbol": symbol,
                    "base_price": deal["base_price"], "base_qty": deal["base_qty"],
                    "take_profit_price": deal["take_profit_price"],
                    "stop_loss_price": deal["stop_loss_price"],
                    "safety_orders": [s["price"] for s in deal["safety_orders"]],
                    "tp_pct": deal["tp_pct"], "step_pct": deal["step_pct"],
                })
        user_store.save(user_id, u)
        return

    if signal["action"] == "CLOSE" and pos:
        _close_trade(u, state, settings, price, "AI_CLOSE", alert, exchange, signal=signal)
    elif signal["action"] in ("BUY", "SELL") and not pos and conf_ok and crit_ok and vol_ok:
        if u.get("copilot"):
            _suggest_trade(state, signal, symbol, price, alert)
        else:
            _open_trade(u, state, settings, signal["action"], price, druck, alert, exchange, signal=signal)

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


def _open_trade_fixed(u, state, settings, side, price, amount_usd, alert, exchange=None):
    """Like _open_trade but sizes by exact dollar amount instead of risk %."""
    symbol = settings["SYMBOL"]
    fee_rate = _fee_pct(u)
    qty = round(amount_usd / price, 6)
    if qty <= 0:
        return
    if exchange is not None:
        # Validate/round against Binance's LOT_SIZE + MIN_NOTIONAL before sending,
        # so we can tell the user exactly why instead of silently skipping.
        rq, err = binance.round_qty(symbol, qty, price, exchange=exchange.exchange)
        if err:
            print(f"[UserLoop] entry rejected — {err}")
            state["_lastError"] = err
            alert("error", {"message": err, "symbol": symbol})
            return
        qty = rq
        try:
            order = exchange.place_order(side, qty, symbol)
            price = order.get("avgPrice") or price
            qty = order.get("executedQty") or qty
        except Exception as e:
            print(f"[UserLoop] live order failed ({e}) — skipping entry")
            state["_lastError"] = f"Binance rejected the order: {e}"
            alert("error", {"message": str(e), "symbol": symbol})
            return
    else:
        fee = price * qty * fee_rate
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
                   "stopLoss": sl, "takeProfit": tp, "amountUsd": round(amount_usd, 2)})


def pending_suggestion(user_id):
    """Return the user's pending copilot suggestion ({side,symbol,ts}) or None."""
    u = _ensure_user(str(user_id))
    return u.get("state", {}).get("pendingSuggestion")


def clear_suggestion(user_id):
    """Drop the pending copilot suggestion (after approve/reject)."""
    u = _ensure_user(str(user_id))
    u.get("state", {}).pop("pendingSuggestion", None)
    user_store.save(str(user_id), u)


def force_trade(user_id, side, symbol=None, alert_fn=None, amount_usd=None):
    """Manual trade entry called by the AI assistant or /buy /sell commands.

    amount_usd — if set, use this exact dollar amount instead of the risk %
    setting. Lets users say "enter with $60" and get exactly that exposure.
    """
    user_id = str(user_id)
    u = _ensure_user(user_id)
    settings, state = u["settings"], u["state"]
    if symbol:
        settings["SYMBOL"] = symbol.upper()
    sym = settings["SYMBOL"]
    if state.get("openPosition"):
        return {"ok": False, "error": "Position already open"}
    ex_name = u.get("exchange", "binance")
    price = binance.get_price(sym, exchange=ex_name)
    if not price:
        return {"ok": False, "error": "Could not fetch price"}
    alert = alert_fn or (lambda *a: None)
    state.pop("_lastError", None)   # clear any stale error before this attempt
    exchange = None
    if u.get("api_key") and u.get("api_secret"):
        try:
            exchange = binance.LiveExchange(u["api_key"], u["api_secret"],
                                            testnet=u.get("paper", True), exchange=ex_name)
        except Exception as e:
            print(f"[UserLoop:{user_id}] live exchange build failed: {e}")
            exchange = None
    # Don't silently simulate a paper trade for a real-money user.
    if not u.get("paper", True) and u.get("api_key") and exchange is None:
        return {"ok": False, "error": "Live Binance connection failed — order NOT placed. "
                                      "Check your API keys / region, then try again."}

    if amount_usd and float(amount_usd) > 0:
        # User specified an exact dollar amount — override risk % sizing.
        _open_trade_fixed(u, state, settings, side.upper(), price, float(amount_usd), alert, exchange)
    else:
        _open_trade(u, state, settings, side.upper(), price, 1.0, alert, exchange)

    user_store.save(user_id, u)
    pos = state.get("openPosition")
    if pos:
        return {"ok": True, "side": side, "symbol": sym, "price": round(price, 6),
                "quantity": round(pos["quantity"], 6),
                "amountUsd": round(pos["quantity"] * price, 2),
                "stopLoss": round(pos["stopLoss"], 6), "takeProfit": round(pos["takeProfit"], 6)}
    return {"ok": False, "error": state.pop("_lastError", None) or "Order did not fill"}


def force_close(user_id, alert_fn=None):
    """Manual position close called by the AI assistant."""
    user_id = str(user_id)
    u = _ensure_user(user_id)
    settings, state = u["settings"], u["state"]
    if not state.get("openPosition"):
        return {"ok": False, "error": "No open position"}
    sym = state["openPosition"]["symbol"]
    ex_name = u.get("exchange", "binance")
    price = binance.get_price(sym, exchange=ex_name) or state["openPosition"]["entryPrice"]
    alert = alert_fn or (lambda *a: None)
    exchange = None
    if u.get("api_key") and u.get("api_secret"):
        try:
            exchange = binance.LiveExchange(u["api_key"], u["api_secret"],
                                            testnet=u.get("paper", True), exchange=ex_name)
        except Exception:
            pass
    _close_trade(u, state, settings, price, "MANUAL_CLOSE", alert, exchange)
    user_store.save(user_id, u)
    trades = state.get("trades", [])
    if trades:
        t = trades[0]
        return {"ok": True, "symbol": sym, "pnl": t["pnl"], "pnlPct": t["pnlPct"]}
    return {"ok": True, "symbol": sym}


def start_all(alert_fn=None):
    for uid in user_store.all_active():
        start(uid, alert_fn)
