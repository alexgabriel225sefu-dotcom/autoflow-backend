"""Grid Bot — passive income on sideways markets.

Divides a price range into N equal levels. Places alternating BUY/SELL
orders at every grid line. Each time a BUY fills, the bot immediately
places a SELL one level up; each SELL fill triggers a BUY one level down.
Profit = grid_spacing × qty, collected on every round-trip.

Works best when price oscillates inside the defined range. Complements
the Strategy bot (which needs trends) and the DCA bot (which averages down).
"""
from datetime import datetime


def default_settings():
    return {
        "grid_enabled":      False,
        "grid_lower":        0.0,     # lower bound of the range ($)
        "grid_upper":        0.0,     # upper bound of the range ($)
        "grid_levels":       10,      # number of grid lines (default 10)
        "grid_order_pct":    2.0,     # % of balance per grid order
    }


def create_grid(symbol, lower, upper, levels, balance, order_pct):
    """Build the initial grid state.  Returns grid dict or None on bad params."""
    if lower <= 0 or upper <= lower or levels < 3:
        return None
    step = (upper - lower) / (levels - 1)
    orders = []
    order_size = balance * (order_pct / 100)
    for i in range(levels):
        price = round(lower + step * i, 6)
        orders.append({
            "price":     price,
            "side":      None,      # filled in by setup_orders()
            "qty":       round(order_size / price, 6),
            "filled":    False,
            "fill_time": None,
        })
    return {
        "symbol":      symbol,
        "lower":       round(lower, 6),
        "upper":       round(upper, 6),
        "levels":      levels,
        "step":        round(step, 6),
        "order_pct":   order_pct,
        "orders":      orders,
        "total_pnl":   0.0,
        "round_trips": 0,
        "opened_at":   datetime.utcnow().isoformat(),
        "last_price":  None,
    }


def setup_orders(grid, current_price):
    """Assign BUY to levels below price, SELL to levels above."""
    for o in grid["orders"]:
        if o["price"] < current_price:
            o["side"] = "BUY"
            o["filled"] = False
        elif o["price"] > current_price:
            o["side"] = "SELL"
            o["filled"] = False
        else:
            o["side"] = None   # at-the-money level — skip
    grid["last_price"] = current_price
    return grid


def tick_grid(grid, current_price):
    """Process one price tick.  Returns (grid, list_of_events).

    Each event is {"type": "buy"|"sell"|"round_trip", "price", "qty", "pnl"}.
    """
    if grid["last_price"] is None:
        grid["last_price"] = current_price
        return grid, []

    prev = grid["last_price"]
    events = []

    for i, o in enumerate(grid["orders"]):
        if o["side"] is None:
            continue

        # BUY order: triggers when price drops to or below the level
        if o["side"] == "BUY" and not o["filled"]:
            if current_price <= o["price"] <= prev or prev <= o["price"] <= current_price:
                pass  # price moving away — not a trigger
            if current_price <= o["price"] and prev > o["price"]:
                o["filled"] = True
                o["fill_time"] = datetime.utcnow().isoformat()
                events.append({"type": "buy", "price": o["price"], "qty": o["qty"], "level": i})
                # immediately flip to SELL one level up (if that level exists)
                if i + 1 < len(grid["orders"]):
                    grid["orders"][i + 1]["side"] = "SELL"
                    grid["orders"][i + 1]["filled"] = False

        # SELL order: triggers when price rises to or above the level
        elif o["side"] == "SELL" and not o["filled"]:
            if current_price >= o["price"] and prev < o["price"]:
                o["filled"] = True
                o["fill_time"] = datetime.utcnow().isoformat()
                pnl = round(grid["step"] * o["qty"], 6)  # profit = one step × qty
                grid["total_pnl"] = round(grid["total_pnl"] + pnl, 6)
                grid["round_trips"] += 1
                events.append({"type": "sell", "price": o["price"], "qty": o["qty"],
                               "pnl": pnl, "level": i})
                # flip back to BUY one level down
                if i - 1 >= 0:
                    grid["orders"][i - 1]["side"] = "BUY"
                    grid["orders"][i - 1]["filled"] = False

    grid["last_price"] = current_price
    return grid, events


def grid_status(grid, current_price):
    """One-line status summary."""
    buys  = sum(1 for o in grid["orders"] if o["side"] == "BUY"  and not o["filled"])
    sells = sum(1 for o in grid["orders"] if o["side"] == "SELL" and not o["filled"])
    sign  = "+" if grid["total_pnl"] >= 0 else ""
    return (f"📊 <b>Grid — {grid['symbol']}</b>  "
            f"${grid['lower']:.2f}–${grid['upper']:.2f}  ({grid['levels']} levels)\n"
            f"Buy orders: {buys}  Sell orders: {sells}  "
            f"Trips: {grid['round_trips']}  PnL: <b>{sign}${grid['total_pnl']:.4f}</b>\n"
            f"Price: ${current_price:.4f}  Step: ${grid['step']:.4f}")
