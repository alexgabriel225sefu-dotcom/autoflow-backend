"""DCA (Dollar Cost Averaging) bot — 3Commas-style safety order system.

A DCA deal opens with a base order, then automatically fills
"safety orders" as price moves against the position, averaging
down (BUY) or up (SELL) the entry price.  Closes at take-profit
calculated from the new average entry after each safety fill.
"""
from datetime import datetime


def default_settings():
    return {
        "dca_enabled":          False,
        "dca_base_order_pct":   5.0,   # % of balance for the base (first) order
        "dca_safety_order_pct": 3.0,   # % of balance for each safety order
        "dca_max_safety_orders": 3,    # how many DCA layers max
        "dca_safety_step_pct":  2.5,   # price must move X% to trigger next safety
        "dca_safety_scale":     1.5,   # each safety order is 1.5x the previous
        "dca_take_profit_pct":  2.0,   # TP % from average entry
        "dca_stop_loss_pct":   10.0,   # SL % from base entry (0 = disabled)
    }


def open_deal(symbol, side, price, balance, settings):
    """Open a new DCA deal.  Returns deal dict, or None if balance < $1."""
    base_pct    = settings.get("dca_base_order_pct", 5.0) / 100
    safety_pct  = settings.get("dca_safety_order_pct", 3.0) / 100
    max_safety  = int(settings.get("dca_max_safety_orders", 3))
    step_pct    = settings.get("dca_safety_step_pct", 2.5) / 100
    scale       = settings.get("dca_safety_scale", 1.5)
    tp_pct      = settings.get("dca_take_profit_pct", 2.0) / 100
    sl_pct      = settings.get("dca_stop_loss_pct", 10.0) / 100

    base_size = balance * base_pct
    if base_size < 1.0 or price <= 0:
        return None

    base_qty = round(base_size / price, 6)

    safety_orders = []
    for i in range(max_safety):
        if side == "BUY":
            trigger = round(price * (1 - step_pct * (i + 1)), 6)
        else:
            trigger = round(price * (1 + step_pct * (i + 1)), 6)
        so_size = balance * safety_pct * (scale ** i)
        so_qty  = round(so_size / trigger, 6)
        safety_orders.append({"price": trigger, "qty": so_qty, "triggered": False})

    total_cost = round(price * base_qty, 6)
    tp_price   = round(price * (1 + tp_pct if side == "BUY" else 1 - tp_pct), 6)
    sl_price   = round(price * (1 - sl_pct if side == "BUY" else 1 + sl_pct), 6) if sl_pct > 0 else 0

    return {
        "symbol":             symbol,
        "side":               side,
        "base_price":         round(price, 6),
        "base_qty":           base_qty,
        "safety_orders":      safety_orders,
        "safety_filled":      0,
        "avg_entry":          round(price, 6),
        "total_qty":          base_qty,
        "total_cost":         total_cost,
        "take_profit_price":  tp_price,
        "stop_loss_price":    sl_price,
        "tp_pct":             tp_pct * 100,
        "step_pct":           step_pct * 100,
        "opened_at":          datetime.utcnow().isoformat(),
    }


def tick_deal(deal, price):
    """One tick: fill any triggered safety orders, then check TP/SL.
    Returns (updated_deal, [newly_filled_indices], exit_reason|None).
    """
    side = deal["side"]
    newly_filled = []

    for i, so in enumerate(deal["safety_orders"]):
        if so["triggered"]:
            continue
        hit = (side == "BUY" and price <= so["price"]) or \
              (side == "SELL" and price >= so["price"])
        if hit:
            so["triggered"] = True
            deal["total_cost"] = round(deal["total_cost"] + so["price"] * so["qty"], 6)
            deal["total_qty"]  = round(deal["total_qty"] + so["qty"], 6)
            deal["safety_filled"] += 1
            deal["avg_entry"] = round(deal["total_cost"] / deal["total_qty"], 6)
            tp_pct = deal.get("tp_pct", 2.0) / 100
            if side == "BUY":
                deal["take_profit_price"] = round(deal["avg_entry"] * (1 + tp_pct), 6)
            else:
                deal["take_profit_price"] = round(deal["avg_entry"] * (1 - tp_pct), 6)
            newly_filled.append(i)

    exit_reason = None
    if side == "BUY":
        if price >= deal["take_profit_price"]:
            exit_reason = "TAKE_PROFIT"
        elif deal["stop_loss_price"] > 0 and price <= deal["stop_loss_price"]:
            exit_reason = "STOP_LOSS"
    else:
        if price <= deal["take_profit_price"]:
            exit_reason = "TAKE_PROFIT"
        elif deal["stop_loss_price"] > 0 and price >= deal["stop_loss_price"]:
            exit_reason = "STOP_LOSS"

    return deal, newly_filled, exit_reason


def deal_pnl(deal, price):
    """Unrealised PnL in $ for an open deal."""
    if deal["side"] == "BUY":
        return round((price - deal["avg_entry"]) * deal["total_qty"], 4)
    return round((deal["avg_entry"] - price) * deal["total_qty"], 4)


def deal_pnl_pct(deal, price):
    """PnL as % of total cost invested so far."""
    if not deal["total_cost"]:
        return 0.0
    return round(deal_pnl(deal, price) / deal["total_cost"] * 100, 2)


def deal_summary(deal, price):
    """Human-readable one-liner for status messages."""
    pnl  = deal_pnl(deal, price)
    pct  = deal_pnl_pct(deal, price)
    sign = "+" if pnl >= 0 else ""
    n    = deal["safety_filled"]
    max_n = len(deal["safety_orders"])
    return (f"{'🟢 LONG' if deal['side'] == 'BUY' else '🔴 SHORT'} <b>{deal['symbol']}</b>  "
            f"avg ${deal['avg_entry']:.4f}  PnL: <b>{sign}${pnl:.4f} ({sign}{pct}%)</b>  "
            f"Safety: {n}/{max_n}  TP: ${deal['take_profit_price']:.4f}")
