"""APEX TRADE BOT — main loop (port of index.js)."""
import os
import sys
import time
import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from apex import config as cfg
from apex import indicators, ai, logger, strategies, telegram as tg, state
from apex.exchanges import get_exchange
from apex.dashboard import render as render_dashboard

exchange = get_exchange()

# ─── Runtime pause control ───────────────────────────────
_bot_paused = False
_pause_lock = threading.Lock()


def _is_paused() -> bool:
    with _pause_lock:
        return _bot_paused


def set_paused(paused: bool):
    global _bot_paused
    with _pause_lock:
        _bot_paused = paused
    print(f"[BOT] {'PAUSED' if paused else 'RESUMED'} via Telegram")


def reload_exchange_connector():
    global exchange
    try:
        exchange = get_exchange()
        tg._exchange = exchange
        dash["exchange"] = cfg.EXCHANGE.upper()
        print(f"[BOT] Exchange reloaded → {cfg.EXCHANGE}")
    except Exception as e:
        print(f"[BOT] Exchange reload error: {e}")


def _load_runtime_config():
    """Apply persistent settings saved by Telegram commands (runtime.json)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    except Exception as e:
        print(f"[BOT] runtime.json error: {e}")
        return
    for k, v in data.items():
        os.environ[k] = str(v)
    if "EXCHANGE" in data:
        cfg.EXCHANGE = str(data["EXCHANGE"]).lower()
    if "TRADE_SYMBOL" in data:
        cfg.SYMBOL = str(data["TRADE_SYMBOL"])
    if "PAPER_TRADING" in data:
        cfg.PAPER_TRADING = str(data["PAPER_TRADING"]).lower() in ("true", "1", "yes", "on")
    if "RISK_PER_TRADE" in data:
        cfg.RISK_PER_TRADE = float(data["RISK_PER_TRADE"])
    _creds = [
        "BINANCE_API_KEY", "BINANCE_API_SECRET",
        "BYBIT_API_KEY", "BYBIT_API_SECRET",
        "OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE",
        "KRAKEN_API_KEY", "KRAKEN_API_SECRET",
        "KUCOIN_API_KEY", "KUCOIN_API_SECRET", "KUCOIN_API_PASSPHRASE",
        "COINBASE_API_KEY", "COINBASE_API_SECRET",
        "BITGET_API_KEY", "BITGET_API_SECRET", "BITGET_API_PASSPHRASE",
        "MEXC_API_KEY", "MEXC_API_SECRET",
    ]
    for key in _creds:
        if key in data:
            setattr(cfg, key, str(data[key]))
    print(f"[BOT] runtime.json loaded ({len(data)} settings)")


# ─── State ────────────────────────────────────────────────
open_position = None
paper_balance = cfg.PAPER_BALANCE
tick_count = 0
start_balance = 0.0
stop_alerted_at = 0.0

dash = {
    "balance": 0, "startBalance": 0, "currentSymbol": cfg.SYMBOL, "currentPrice": 0,
    "openPosition": None, "trades": [], "lastTick": None,
    "mode": "PAPER" if cfg.PAPER_TRADING else ("TESTNET" if (cfg.BYBIT_TESTNET or cfg.BINANCE_TESTNET) else "LIVE"),
    "exchange": cfg.EXCHANGE.upper(),
}

WHOLE_COINS = {"DOGEUSDT", "SHIBUSDT", "XRPUSDT", "ADAUSDT", "MATICUSDT", "TRXUSDT"}


# ─── License ──────────────────────────────────────────────
def verify_license():
    key, server = cfg.LICENSE_KEY, cfg.LICENSE_SERVER
    if not key:
        if os.getenv("BYPASS_LICENSE") == "true":
            print("⚠️  LICENSE_KEY not set — running in owner/dev mode (BYPASS_LICENSE=true).")
            return
        print("\n❌  LICENSE_KEY is not set.")
        print("    Add your license key from your purchase email.")
        print("    Purchase at: https://aicashsystem.space\n")
        sys.exit(1)
    try:
        res = requests.post(f"{server}/api/verify-license", json={"key": key}, timeout=10)
        data = res.json()
        if not data.get("valid"):
            print(f"\n❌  License invalid: {data.get('message')}\n")
            sys.exit(1)
        print(f"✅  License verified — welcome, {data.get('email', 'trader')}!")
    except Exception as e:
        print(f"⚠️   License server unreachable ({e}) — starting in grace mode.")


def validate():
    has_anthropic = bool(cfg.ANTHROPIC_API_KEY)
    has_groq = bool(cfg.GROQ_API_KEY)
    if not has_anthropic and not has_groq:
        if os.getenv("BYPASS_LICENSE") == "true":
            print("⚠️  No AI key — running in demo mode (HOLD-only signals).")
        else:
            print("❌ No AI key found! Add ANTHROPIC_API_KEY or GROQ_API_KEY.")
            sys.exit(1)
    if not has_anthropic and has_groq:
        print("ℹ️  ANTHROPIC_API_KEY missing — using Groq (free).")
    key_field = {"binance": "BINANCE_API_KEY", "bybit": "BYBIT_API_KEY", "okx": "OKX_API_KEY",
                 "kraken": "KRAKEN_API_KEY", "kucoin": "KUCOIN_API_KEY", "coinbase": "COINBASE_API_KEY",
                 "bitget": "BITGET_API_KEY", "mexc": "MEXC_API_KEY"}
    has_key = getattr(cfg, key_field[cfg.EXCHANGE], "")
    if not has_key and not cfg.PAPER_TRADING:
        print("⚠️  No exchange API key found — falling back to PAPER TRADING automatically")
        cfg.PAPER_TRADING = True


def get_balance():
    if cfg.PAPER_TRADING:
        return paper_balance
    try:
        return exchange.get_balance()
    except Exception as e:
        logger.warn(f"[BALANCE] API error: {e}")
        return 0


def calc_quantity(price, balance, symbol=None, druck_mult=1.0):
    symbol = symbol or cfg.SYMBOL
    risk_amount = balance * cfg.RISK_PER_TRADE * druck_mult
    qty = risk_amount / price
    return int(qty) if symbol in WHOLE_COINS else round(qty, 6)


def calc_sltp(side, price, atr_value):
    if cfg.ATR_BASED_SL and atr_value > 0:
        sl_dist, tp_dist = atr_value * cfg.ATR_SL_MULT, atr_value * cfg.ATR_TP_MULT
        return {"stopLoss": price - sl_dist if side == "BUY" else price + sl_dist,
                "takeProfit": price + tp_dist if side == "BUY" else price - tp_dist}
    return {"stopLoss": price * (1 - cfg.STOP_LOSS_PCT) if side == "BUY" else price * (1 + cfg.STOP_LOSS_PCT),
            "takeProfit": price * (1 + cfg.TAKE_PROFIT_PCT) if side == "BUY" else price * (1 - cfg.TAKE_PROFIT_PCT)}


def check_position(price):
    if not open_position:
        return None
    side = open_position["side"]
    if cfg.TRAILING_STOP:
        if side == "BUY":
            open_position["trailHigh"] = max(open_position.get("trailHigh") or price, price)
            trail_sl = open_position["trailHigh"] * (1 - cfg.TRAILING_STOP_DIST)
            if trail_sl > open_position["stopLoss"]:
                open_position["stopLoss"] = trail_sl
        else:
            open_position["trailLow"] = min(open_position.get("trailLow") or price, price)
            trail_sl = open_position["trailLow"] * (1 + cfg.TRAILING_STOP_DIST)
            if trail_sl < open_position["stopLoss"]:
                open_position["stopLoss"] = trail_sl
    pnl_pct = ((price - open_position["entryPrice"]) / open_position["entryPrice"] * 100 if side == "BUY"
               else (open_position["entryPrice"] - price) / open_position["entryPrice"] * 100)
    open_position["pnlPct"] = pnl_pct
    if side == "BUY":
        if price <= open_position["stopLoss"]:
            return "STOP_LOSS"
        if price >= open_position["takeProfit"]:
            return "TAKE_PROFIT"
    else:
        if price >= open_position["stopLoss"]:
            return "STOP_LOSS"
        if price <= open_position["takeProfit"]:
            return "TAKE_PROFIT"
    return None


def open_trade(side, price, balance, atr_value=0, symbol=None, druck_mult=1.0):
    global open_position, paper_balance
    symbol = symbol or cfg.SYMBOL
    quantity = calc_quantity(price, balance, symbol, druck_mult)
    if quantity <= 0:
        logger.warn(f"Quantity too small for {symbol} @ ${price} — skip")
        return
    min_notional = float(os.getenv("MIN_NOTIONAL", "10.0"))
    if not cfg.PAPER_TRADING and price * quantity < min_notional:
        logger.warn(f"Order notional ${price * quantity:.2f} below exchange minimum ${min_notional:.0f} — skip (increase balance or lower MIN_NOTIONAL)")
        return
    if druck_mult != 1.0:
        logger.info(f"🎯 Druckenmiller: position size ×{druck_mult:.2f}")
    exchange.place_order(side, quantity, symbol)
    if cfg.PAPER_TRADING:
        paper_balance += -price * quantity if side == "BUY" else price * quantity
    sltp = calc_sltp(side, price, atr_value)
    rr = abs(sltp["takeProfit"] - price) / abs(price - sltp["stopLoss"]) if (price - sltp["stopLoss"]) else 0
    open_position = {
        "symbol": symbol, "side": side, "entryPrice": price, "quantity": quantity,
        "stopLoss": sltp["stopLoss"], "takeProfit": sltp["takeProfit"],
        "openedAt": datetime.utcnow().isoformat(), "pnlPct": 0,
        "trailHigh": price if side == "BUY" else None, "trailLow": price if side == "SELL" else None,
    }
    dash["openPosition"] = open_position
    logger.print_trade(side, symbol, price, quantity)
    logger.info(f"SL: ${sltp['stopLoss']:.5f} | TP: ${sltp['takeProfit']:.5f} | R:R = 1:{rr:.2f}")
    tg.alert_open(side, symbol, price, quantity, sltp["stopLoss"], sltp["takeProfit"], druck_mult)
    state.save(paper_balance, open_position)


def close_trade(price, reason):
    global open_position, paper_balance
    if not open_position:
        return
    side = open_position["side"]
    entry_price = open_position["entryPrice"]
    quantity = open_position["quantity"]
    symbol = open_position.get("symbol", cfg.SYMBOL)
    close_side = "SELL" if side == "BUY" else "BUY"
    exchange.place_order(close_side, quantity, symbol)
    pnl = (price - entry_price) * quantity if side == "BUY" else (entry_price - price) * quantity
    if cfg.PAPER_TRADING:
        paper_balance += price * quantity if side == "BUY" else -price * quantity
    logger.print_trade(close_side, symbol, price, quantity, pnl)
    logger.info(f"Reason: {reason} | PnL: {'+' if pnl >= 0 else ''}${pnl:.4f}")
    strategies.record_trade(pnl > 0, pnl, start_balance or cfg.PAPER_BALANCE)
    bal = get_balance()
    tg.alert_close(reason, symbol, side, entry_price, price, pnl, bal)
    dash["trades"].insert(0, {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "symbol": symbol, "side": side,
        "entry": entry_price, "exit": price, "qty": quantity, "pnl": round(pnl, 4),
        "pnlPct": round(pnl / (entry_price * quantity) * 100, 2) if (entry_price * quantity) else 0,
        "reason": reason, "win": pnl > 0,
    })
    dash["trades"] = dash["trades"][:50]
    dash["openPosition"] = None
    dash["balance"] = bal
    open_position = None
    state.save(paper_balance, None)


def best_symbol():
    if not cfg.MULTI_SYMBOL or len(cfg.SCAN_SYMBOLS) <= 1:
        return cfg.SYMBOL
    results = []
    for sym in cfg.SCAN_SYMBOLS:
        try:
            candles = exchange.get_candles(sym, cfg.TIMEFRAME, 50)
            ind = indicators.analyze(candles)
            rsi_num = float(ind["rsi"])
            macd_h = float(ind["macdHist"])
            vol_r = float(ind["volumeRatio"])
            score = (abs(rsi_num - 50) / 50) * 0.4 + min(vol_r / 3, 1) * 0.4 + (0.2 if abs(macd_h) > 0 else 0)
            results.append({"sym": sym, "score": score})
        except Exception:
            results.append({"sym": sym, "score": 0})
    results.sort(key=lambda r: r["score"], reverse=True)
    best = results[0]
    if best["sym"] != cfg.SYMBOL:
        logger.info(f"📡 Scanner: best symbol → {best['sym']} (score: {best['score']:.2f})")
    return best["sym"]


def tick():
    global tick_count, stop_alerted_at
    if _is_paused():
        return
    tick_count += 1
    try:
        active_symbol = open_position["symbol"] if open_position else None
        symbol = active_symbol or best_symbol()

        if tick_count % 5 == 0:
            try:
                logger.print_stats(get_balance(), open_position, exchange.get_price(symbol))
            except Exception:
                logger.print_stats(get_balance(), open_position, None)
        if tick_count % 6 == 0:
            hb_balance = get_balance()
            try:
                hb_price = exchange.get_price(symbol)
            except Exception:
                hb_price = None
            tg.alert_heartbeat(tick_count, hb_balance, open_position, hb_price)

        logger.info(f"[{tick_count}] Analyzing {symbol} ({cfg.EXCHANGE})"
                    f"{' 🔒 active position' if active_symbol else ''}...")

        candles = exchange.get_candles(symbol, cfg.TIMEFRAME, cfg.CANDLES)
        price = exchange.get_price(symbol)
        balance = get_balance()
        logger.update_balance(balance)

        dash["balance"] = balance
        dash["currentSymbol"] = symbol
        dash["currentPrice"] = price
        dash["lastTick"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if open_position:
            pos_pnl = ((price - open_position["entryPrice"]) * open_position["quantity"] if open_position["side"] == "BUY"
                       else (open_position["entryPrice"] - price) * open_position["quantity"])
            dash["openPosition"] = {**open_position, "currentPnl": round(pos_pnl, 4)}

        trigger = check_position(price)
        if trigger:
            logger.warn(f"{trigger} hit at ${price}")
            close_trade(price, trigger)
            logger.print_stats(get_balance(), None, None)
            return

        ind = indicators.analyze(candles)
        strat_data = strategies.analyze(candles)

        portfolio_value = balance
        if open_position and price:
            portfolio_value = (balance + open_position["quantity"] * price if open_position["side"] == "BUY"
                               else balance - open_position["quantity"] * price)
        stop_check = strategies.should_stop(portfolio_value, start_balance or cfg.PAPER_BALANCE)
        if stop_check["stop"]:
            logger.warn(f"🛑 STRATEGY STOP: {' | '.join(stop_check['reasons'])}")
            now = time.time()
            if now - stop_alerted_at > 30 * 60:
                tg.alert_stop(stop_check["reasons"])
                stop_alerted_at = now
            logger.print_stats(get_balance(), open_position, price)
            return

        if strat_data["livermore"]["trend"] != "NEUTRAL":
            logger.info(f"📊 Livermore: {strat_data['livermore']['trend']} "
                        f"({strat_data['livermore'].get('reason')}) | "
                        f"Strength: {strat_data['livermore']['strength'] * 100:.0f}%")
        if strat_data["turtle"]["signal"]:
            logger.info(f"🐢 Turtle: {strat_data['turtle']['breakoutStr']} breakout {strat_data['turtle']['signal']}")

        signal = ai.get_signal(ind, balance, open_position, strat_data)
        logger.print_signal(signal, ind)

        too_low_balance = balance < 1
        min_criteria = int(os.getenv("MIN_CRITERIA", "3"))
        min_volume = float(os.getenv("MIN_VOLUME_RATIO", "0.7"))
        criteria_ok = (signal.get("criteriaScore", 0) or 0) >= min_criteria
        volume_ok = float(ind["volumeRatio"]) >= min_volume

        if too_low_balance:
            logger.warn(f"Balance too small (${balance:.2f}) — stop trading")
            return

        druck_mult = (strategies.druckenmiller_multiplier(
            signal["confidence"], signal.get("criteriaScore", 0), strat_data["livermore"], strat_data["turtle"])
            if not open_position else 1.0)

        live_str = strat_data["livermore"].get("strength") or 0
        turtle_sig = strat_data["turtle"]["signal"]
        if (not open_position and signal["action"] == "BUY"
                and strat_data["livermore"]["trend"] == "BEARISH" and live_str >= 0.8 and turtle_sig == "SELL"):
            logger.warn("⚡ Signal filtered: BUY against strong BEARISH structure — forced HOLD (PTJ)")
            tg.alert_filtered("BUY", "BEARISH 85%", "STRONG SELL")
            signal["action"] = "HOLD"
        if (not open_position and signal["action"] == "SELL"
                and strat_data["livermore"]["trend"] == "BULLISH" and live_str >= 0.8 and turtle_sig == "BUY"):
            logger.warn("⚡ Signal filtered: SELL against strong BULLISH structure — forced HOLD (PTJ)")
            tg.alert_filtered("SELL", "BULLISH 85%", "STRONG BUY")
            signal["action"] = "HOLD"

        if (signal["action"] == "HOLD" or signal["confidence"] < cfg.MIN_CONFIDENCE
                or not criteria_ok or (not volume_ok and not open_position)):
            logger.info(f"HOLD — confidence: {signal['confidence']}% | "
                        f"criteria: {signal.get('criteriaScore', '?')}/5 | volume: {ind['volumeRatio']}x")
        elif signal["action"] == "CLOSE" and open_position:
            close_trade(price, "AI_CLOSE")
        elif signal["action"] == "BUY" and not open_position:
            open_trade("BUY", price, balance, float(ind["atr"]), symbol, druck_mult)
        elif signal["action"] == "SELL" and not open_position:
            open_trade("SELL", price, balance, float(ind["atr"]), symbol, druck_mult)
        else:
            logger.info("Skip — position already open/closed")

        logger.print_stats(get_balance(), open_position, price)
    except Exception as err:
        logger.error(f"Tick error: {err}")


# ─── Dashboard HTTP server ────────────────────────────────
def _start_dashboard_server():
    port = int(os.getenv("PORT") or os.getenv("DASHBOARD_PORT") or 3000)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/api/status":
                body = json.dumps({**dash, "tickCount": tick_count}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(render_dashboard({**dash, "tickCount": tick_count}).encode())

    server = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info(f"📊 Dashboard: http://localhost:{port}")


def main():
    global start_balance, paper_balance, open_position, exchange
    print(f"[APEX BOT] Starting... Python {sys.version.split()[0]}")
    _load_runtime_config()
    exchange = get_exchange()  # re-init with any runtime-overridden exchange
    validate()

    if cfg.PAPER_TRADING:
        saved = state.load(cfg.PAPER_BALANCE)
        if saved:
            paper_balance = saved["paperBalance"]
            open_position = saved.get("openPosition")

    balance = get_balance()
    start_balance = balance
    dash["balance"] = balance
    dash["startBalance"] = balance
    logger.set_start_balance(balance)
    logger.print_banner(balance)

    is_testnet = cfg.BYBIT_TESTNET or cfg.BINANCE_TESTNET
    mode = "📝 PAPER TRADING" if cfg.PAPER_TRADING else ("🧪 TESTNET" if is_testnet else "🔴 LIVE")
    dash["mode"] = mode.replace("📝", "").replace("🧪", "").replace("🔴", "").strip()
    tg.alert_start(cfg.SYMBOL, cfg.TIMEFRAME, balance, mode)

    _start_dashboard_server()
    tg.start_polling(lambda: dash, exchange, control={
        "set_paused": set_paused,
        "get_paused": _is_paused,
        "reload_exchange": reload_exchange_connector,
    })

    verify_license()
    logger.info("🚀 First analysis...")
    tick()
    interval = cfg.LOOP_INTERVAL_MS / 1000
    logger.info(f"⏱️  Analysis every {cfg.LOOP_INTERVAL_MS / 60000} minutes.")
    while True:
        time.sleep(interval)
        tick()
