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
        sl_dist = forex.from_pips(cfg.STOP_LOSS_PIPS, symbol)
        tp_dist = forex.from_pips(cfg.TAKE_PROFIT_PIPS, symbol)
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
        pip = forex.from_pips(1, symbol)
        be_price = entry + pip if side == "BUY" else entry - pip
        if ((side == "BUY" and price >= entry + one_r and be_price > pos["stopLoss"])
                or (side == "SELL" and price <= entry - one_r and be_price < pos["stopLoss"])):
            pos["stopLoss"] = be_price
            pos["beDone"] = True
            logger.info(f"🛡️ Breakeven: SL moved to {be_price:.5f} — risk-free trade")

    # Trailing stop (strâns în runner mode — Seykota: let profits run)
    if cfg.TRAILING_STOP:
        trail_pips = cfg.RUNNER_TRAIL_PIPS if pos.get("runner") else cfg.TRAILING_STOP_PIPS
        trail_dist = forex.from_pips(trail_pips, symbol)
        if side == "BUY":
            pos["trailHigh"] = max(pos.get("trailHigh") or price, price)
            pos["stopLoss"] = max(pos["stopLoss"], pos["trailHigh"] - trail_dist)
        else:
            pos["trailLow"] = min(pos.get("trailLow") or price, price)
            pos["stopLoss"] = min(pos["stopLoss"], pos["trailLow"] + trail_dist)

    pnl_pips = forex.to_pips(price - entry if side == "BUY" else entry - price, symbol)
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
