"""Exit management — SL/TP, breakeven, trailing, runner mode.

Pure functions over a position dict — used identically by the live loop
(apex/bot.py) and the backtest (backtest.py), so what you backtest is what
trades.
"""
from apex import config as cfg
from apex import forex, logger


def calc_sltp(side, price, atr_value, symbol):
    if cfg.ATR_BASED_SL and atr_value > 0:
        sl_dist, tp_dist = atr_value * cfg.ATR_SL_MULT, atr_value * cfg.ATR_TP_MULT
    else:
        sl_dist = forex.from_pips(cfg.STOP_LOSS_PIPS, symbol, price)
        tp_dist = forex.from_pips(cfg.TAKE_PROFIT_PIPS, symbol, price)
    return {"stopLoss": price - sl_dist if side == "BUY" else price + sl_dist,
            "takeProfit": price + tp_dist if side == "BUY" else price - tp_dist}


def check_position(pos, price):
    """Mutates pos in-place (trailing, breakeven, runner) and returns the close
    trigger ('STOP_LOSS' | 'TAKE_PROFIT' | 'TRAIL_PROFIT') or None."""
    if not pos:
        return None
    side = pos["side"]
    symbol = pos.get("symbol", cfg.SYMBOL)
    entry = pos["entryPrice"]

    # Breakeven (PTJ): la +1R mută SL la entry ±1 pip — trade-ul nu mai poate pierde
    if cfg.BREAKEVEN_AT_R > 0 and not pos.get("beDone") and pos.get("initialStop"):
        one_r = abs(entry - pos["initialStop"]) * cfg.BREAKEVEN_AT_R
        pip = forex.from_pips(1, symbol, price)
        be_price = entry + pip if side == "BUY" else entry - pip
        if ((side == "BUY" and price >= entry + one_r and be_price > pos["stopLoss"])
                or (side == "SELL" and price <= entry - one_r and be_price < pos["stopLoss"])):
            pos["stopLoss"] = be_price
            pos["beDone"] = True
            logger.info(f"🛡️ Breakeven: SL moved to {be_price:.5f}")

    # Trailing stop (strâns în runner mode — Seykota: let profits run)
    if cfg.TRAILING_STOP:
        trail_pips = cfg.RUNNER_TRAIL_PIPS if pos.get("runner") else cfg.TRAILING_STOP_PIPS
        trail_dist = forex.from_pips(trail_pips, symbol, price)
        if side == "BUY":
            pos["trailHigh"] = max(pos.get("trailHigh") or price, price)
            pos["stopLoss"] = max(pos["stopLoss"], pos["trailHigh"] - trail_dist)
        else:
            pos["trailLow"] = min(pos.get("trailLow") or price, price)
            pos["stopLoss"] = min(pos["stopLoss"], pos["trailLow"] + trail_dist)

    pnl_pips = forex.to_pips(price - entry if side == "BUY" else entry - price, symbol, price)
    pos["pnlPips"] = round(pnl_pips, 1)

    hit_sl = price <= pos["stopLoss"] if side == "BUY" else price >= pos["stopLoss"]
    hit_tp = price >= pos["takeProfit"] if side == "BUY" else price <= pos["takeProfit"]
    if hit_sl:
        return "TRAIL_PROFIT" if pos.get("runner") else "STOP_LOSS"
    if hit_tp and not pos.get("runner"):
        # Runner doar pe paper — la live brokerul execută TP-ul server-side oricum
        if cfg.LET_WINNERS_RUN and cfg.TRAILING_STOP and cfg.PAPER_TRADING:
            pos["runner"] = True
            logger.info(f"🏃 TP hit at {price} — runner mode: letting profit run "
                        f"(trail {cfg.RUNNER_TRAIL_PIPS:g} pips)")
            return None
        return "TAKE_PROFIT"
    return None


# ─────────────────────────────────────────────────────────────────────────
# user_loop.py mirror — the exit math the MULTI-USER live loop actually runs
#
# calc_sltp/check_position above belong to the single-user path (apex/bot.py).
# apex/user_loop.py — the loop that trades every real client — never imports
# this module: it carries its own inline copy of the entry SL/TP maths and its
# own _manage_trailing(). Backtesting against calc_sltp/check_position was
# therefore measuring a strategy nobody trades (1.5/3.0 ATR + fixed 10-pip
# trail vs the live 2.5/5.0 ATR + 1R trail).
#
# The three pure functions below reproduce user_loop.py exactly so the
# backtest can simulate what actually trades. user_loop.py KEEPS its inline
# copy — rewriting live trading code purely to de-duplicate is not worth the
# risk — so tests/test_userloop_mirror.py pins these against the real loop's
# behaviour and fails if either side drifts.
# ─────────────────────────────────────────────────────────────────────────

# Mirrors user_loop.py's hardcoded ATR multipliers (NOT cfg.ATR_SL_MULT /
# ATR_TP_MULT, which only the bot.py path reads).
USERLOOP_SL_ATR_MULT = 2.5
USERLOOP_TP_ATR_MULT = 5.0


def calc_entry_sltp(side, price, atr_value, symbol, spread_pips=0.0,
                    sl_pips=20.0, tp_pips=40.0):
    """Entry stop/target exactly as user_loop.py computes them.

    ATR path: SL = 2.5×ATR, TP = 5×ATR, with SL floored at
    max(4×spread, 20 pips) — and TP re-derived as 2×SL whenever that floor
    bites, to keep RR ≥ 1:2. No-ATR path falls back to the configured pip
    distances, raising TP to 2×SL if it would otherwise sit inside the stop.

    Returns (stop_loss, take_profit), both rounded to 6dp like the live loop.
    """
    pip = forex.pip_size(symbol, price)
    if atr_value and atr_value > 0:
        sl_dist = USERLOOP_SL_ATR_MULT * atr_value
        tp_dist = USERLOOP_TP_ATR_MULT * atr_value
        floor_abs = 20.0 * pip
        min_stop = max(4.0 * spread_pips * pip, floor_abs)
        if sl_dist < min_stop:
            sl_dist = min_stop
            tp_dist = 2.0 * sl_dist
    else:
        sl_dist = sl_pips * pip
        tp_dist = tp_pips * pip
        if tp_dist < sl_dist:
            tp_dist = 2.0 * sl_dist
    buy = side == "BUY"
    return (round(price - sl_dist if buy else price + sl_dist, 6),
            round(price + tp_dist if buy else price - tp_dist, 6))


def trail_stop(side, entry, cur_sl, price, trailing=True, breakeven_r=0.0,
               initial_risk=None):
    """New stop from user_loop._manage_trailing(), or None if it shouldn't move.

    Tighten-only, and only while the trade is in profit. Break-even locks the
    stop at entry once profit ≥ breakeven_r × risk; the trail then keeps the
    stop one risk-unit behind price. A move smaller than 5% of risk is ignored
    (live skips the broker amend call there).

    initial_risk — the trade's ORIGINAL entry-to-stop distance, held constant
    for its lifetime. Omit it (the default) to reproduce live exactly.

    Live omits it, and that is the quirk this parameter exists to measure:
    `risk` is recomputed every call as abs(entry - cur_sl), so it stops being
    risk the moment the stop ratchets past entry — from then on it is locked
    profit. The first ratchet past breakeven collapses it to near zero and the
    trail snaps to a few pips behind price, where ordinary spread-sized noise
    closes the trade. That is the "many tiny wins, occasional full-stop loss"
    signature: winners get cut at noise distance while losers still run the
    full stop.

        BUY entry 1.1000, stop 1.0975 (25p risk), price walking up:
          1.1030 → risk 25.0p → stop 1.1005   (trail 25p — as intended)
          1.1040 → risk  5.0p → stop 1.1035   (trail 5p — noise-tight)
          1.1045 → risk 35.0p → stop 1.1035   (trail 10p — and now loose)

    Passing initial_risk keeps the trail a constant 1R behind price for the
    whole trade, which is what "trail one risk-unit" was meant to mean.
    """
    if not (entry and cur_sl and side in ("BUY", "SELL")) or not price:
        return None
    if not (trailing or breakeven_r > 0):
        return None
    buy = side == "BUY"
    risk = (abs(float(initial_risk)) if initial_risk
            else abs(float(entry) - float(cur_sl)))
    if risk <= 0:
        return None
    profit = (price - entry) if buy else (entry - price)
    if profit <= 0:
        return None
    new_sl = float(cur_sl)
    if breakeven_r > 0 and profit >= breakeven_r * risk:
        new_sl = max(new_sl, entry) if buy else min(new_sl, entry)
    if trailing:
        trail = (price - risk) if buy else (price + risk)
        new_sl = max(new_sl, trail) if buy else min(new_sl, trail)
    improved = (new_sl - cur_sl) if buy else (cur_sl - new_sl)
    return new_sl if improved > risk * 0.05 else None


def exit_trigger(side, stop_loss, take_profit, bar_high, bar_low):
    """Which broker-side order the bar would have filled, using the bar's
    RANGE rather than its close.

    Live, cTrader holds both the stop and the target server-side, so a wick
    through either level fills — checking only the close (as backtest.py did)
    silently skips every intrabar stop-out and biases results optimistic.

    When one bar spans both levels the true order is unknowable from OHLC, so
    the stop wins: an optimistic tie-break here is exactly how a backtest
    invents an edge that evaporates live.
    """
    buy = side == "BUY"
    hit_sl = (bar_low <= stop_loss) if buy else (bar_high >= stop_loss)
    if hit_sl:
        return "STOP_LOSS"
    hit_tp = (bar_high >= take_profit) if buy else (bar_low <= take_profit)
    return "TAKE_PROFIT" if hit_tp else None
