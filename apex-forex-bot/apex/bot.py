"""APEX FOREX BOT — main loop."""
import os
import sys
import time
import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from apex import config as cfg
from apex import indicators, ai, logger, strategies, telegram as tg, state, forex
from apex.brokers import get_broker
from apex.dashboard import render as render_dashboard

broker = get_broker()


def broker_label():
    if cfg.BROKER == "mt":
        return "MT BRIDGE"
    if cfg.BROKER == "td":
        return "TWELVE DATA"
    return f"OANDA ({cfg.OANDA_ENV})"


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


def reload_broker_connector():
    global broker
    try:
        broker = get_broker()
        tg._broker = broker
        dash["broker"] = broker_label()
        print(f"[BOT] Broker reloaded → {broker_label()}")
    except Exception as e:
        print(f"[BOT] Broker reload error: {e}")


def _apply_config(data, source="config"):
    """Apply a {ENV_NAME: value} dict to os.environ and the live cfg module.

    Values arrive as strings (from the server) and are coerced to the type of
    the existing cfg attribute, so "false" doesn't stay a truthy string and
    "0.02" becomes a float. Shared by runtime.json and the remote loader.
    """
    applied = 0
    for k, v in data.items():
        if v is None or v == "":
            continue
        os.environ[k] = str(v)
        applied += 1

    # Env var name → cfg attribute name where they differ
    if "TRADE_SYMBOL" in data:
        cfg.SYMBOL = str(data["TRADE_SYMBOL"])
    if "SCAN_SYMBOLS" in data and data["SCAN_SYMBOLS"]:
        cfg.SCAN_SYMBOLS = str(data["SCAN_SYMBOLS"]).split(",")

    for k, v in data.items():
        if v is None or v == "" or not hasattr(cfg, k):
            continue
        cur = getattr(cfg, k)
        try:
            if isinstance(cur, bool):
                setattr(cfg, k, cfg._truthy(str(v)))
            elif isinstance(cur, int) and not isinstance(cur, bool):
                setattr(cfg, k, int(float(v)))
            elif isinstance(cur, float):
                setattr(cfg, k, float(v))
            elif isinstance(cur, str):
                setattr(cfg, k, str(v).lower() if k in ("BROKER", "OANDA_ENV") else str(v))
        except (ValueError, TypeError):
            pass  # leave the default if the value can't be coerced
    return applied


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
    n = _apply_config(data, "runtime.json")
    print(f"[BOT] runtime.json loaded ({n} settings)")


def load_remote():
    """Fetch the config the client saved in the configurator and apply it.

    Mirrors the crypto bot's cfg.loadRemote(): with only LICENSE_KEY set, the
    bot pulls broker keys, OANDA_ENV, risk and strategy from the license server
    so deployment is truly one-click. Falls back to env vars on any failure.
    """
    key = cfg.LICENSE_KEY
    server = cfg.LICENSE_SERVER
    if not key:
        print("⚠️   load_remote: LICENSE_KEY not set — skipping remote config.")
        return False
    try:
        r = requests.get(f"{server}/api/bot-config",
                         params={"key": key}, timeout=10,
                         headers={"User-Agent": "ApexForexBot/1.0"})
        if r.status_code != 200:
            print(f"⚠️   load_remote: server returned {r.status_code} — {r.text[:200]}")
            print('     → Did you complete the configurator and click "Save Config & Deploy"?')
            return False
        data = r.json()
        if not data.get("success") or not data.get("config"):
            print("⚠️   load_remote: no config in response.")
            return False
        # Env vars the user set explicitly in Railway take precedence over the
        # configurator's saved config — lets a power user flip PAPER_TRADING to
        # "false" to go live, or paste live broker keys, straight in Railway
        # without re-running the configurator (as the setup guide instructs).
        # runtime.json (Telegram overrides) is applied separately, after this,
        # and still wins — it is the live user-control layer.
        remote_cfg = {k: v for k, v in data["config"].items() if k not in os.environ}
        skipped = [k for k in data["config"] if k in os.environ]
        if skipped:
            print(f"ℹ️   Keeping Railway env values (override saved config): {', '.join(skipped)}")
        n = _apply_config(remote_cfg, "remote")
        print(f"✅  Remote config loaded from license server ({n} settings).")
        return True
    except Exception as e:
        print(f"⚠️   Could not load remote config ({e}) — using env vars only.")
        return False


# ─── State ────────────────────────────────────────────────
open_position = None
paper_balance = cfg.PAPER_BALANCE
tick_count = 0
start_balance = 0.0
stop_alerted_at = 0.0
market_closed_alerted = False

dash = {
    "balance": 0, "startBalance": 0, "currentSymbol": cfg.SYMBOL, "currentPrice": 0,
    "openPosition": None, "trades": [], "lastTick": None,
    "mode": "PAPER" if cfg.PAPER_TRADING else cfg.OANDA_ENV.upper(),
    "broker": broker_label(),
    "marketOpen": True,
    "candles": [],
}


# ─── License ──────────────────────────────────────────────
def verify_license():
    """License checks are disabled — the bot always starts. Access is controlled
    via Telegram (ADMIN_CHAT_ID + grant-on-contact), not a license server."""
    key, server = cfg.LICENSE_KEY, cfg.LICENSE_SERVER
    if not key:
        print("ℹ️  No LICENSE_KEY — running open (access controlled via Telegram).")
        return
    # If a key is present, verify it for telemetry, but NEVER exit on failure.
    try:
        res = requests.post(f"{server}/api/verify-license", json={"key": key, "product": "apex-forex"}, timeout=10)
        data = res.json()
        if data.get("valid"):
            print(f"✅  Forex license verified — welcome, {data.get('email', 'trader')}!")
        else:
            print(f"⚠️  License not valid ({data.get('message')}) — continuing anyway.")
    except Exception as e:
        print(f"⚠️   License server unreachable ({e}) — continuing anyway.")


def validate():
    has_anthropic = bool(cfg.ANTHROPIC_API_KEY)
    has_groq = bool(cfg.GROQ_API_KEY)
    if not has_anthropic and not has_groq:
        print("⚠️  No AI key — using rule-based signals (RSI/MACD/EMA). "
              "Add ANTHROPIC_API_KEY or GROQ_API_KEY for AI-enhanced signals.")
    elif not has_anthropic and has_groq:
        print("ℹ️  ANTHROPIC_API_KEY missing — using Groq (free).")
    # Live trading e validat doar pe OANDA (SL/TP server-side + reconciliere).
    # MT bridge / altele: paper până la override explicit.
    if (not cfg.PAPER_TRADING and cfg.BROKER != "oanda"
            and os.getenv("ALLOW_EXPERIMENTAL_LIVE") != "true"):
        print(f"⚠️  Live trading on broker '{cfg.BROKER}' is not validated — "
              "forcing PAPER_TRADING.")
        print("    Supported live: OANDA. Override (at your own risk): "
              "ALLOW_EXPERIMENTAL_LIVE=true")
        cfg.PAPER_TRADING = True
    if cfg.BROKER == "mt":
        if not cfg.MT_BRIDGE_SECRET:
            print("⚠️  BROKER=mt needs MT_BRIDGE_SECRET — falling back to OANDA so the bot still starts.")
            cfg.BROKER = "oanda"
        else:
            print("🔗 MetaTrader bridge mode — waiting for the ApexBridge EA to sync.")
    elif cfg.BROKER == "td":
        if not cfg.TWELVE_DATA_KEY:
            print("⚠️  BROKER=td needs TWELVE_DATA_KEY — falling back to OANDA so the bot still starts.")
            cfg.BROKER = "oanda"
        else:
            print("📡 Twelve Data mode — paper trading with live forex prices.")
        if cfg.MULTI_SYMBOL and len(cfg.SCAN_SYMBOLS) > 3:
            print(f"⚠️  MULTI_SYMBOL with {len(cfg.SCAN_SYMBOLS)} pairs needs "
                  f"{len(cfg.SCAN_SYMBOLS) + 3}+ TD calls/cycle — the free tier allows 8/min.")
            print("    If you see rate-limit retries, set SCAN_SYMBOLS to max 3 pairs"
                  " or MULTI_SYMBOL=false.")
    elif not cfg.OANDA_API_TOKEN or not cfg.OANDA_ACCOUNT_ID:
        print("⚠️  OANDA credentials missing — market data unavailable.")
        print("    Create a FREE practice account at oanda.com, then send /setup")
        print("    to your Telegram bot (or set OANDA_API_TOKEN + OANDA_ACCOUNT_ID).")


def get_balance():
    if cfg.PAPER_TRADING:
        return paper_balance
    try:
        return broker.get_balance()
    except Exception as e:
        logger.warn(f"[BALANCE] API error: {e}")
        return 0


# Exit management — implementat în apex/position.py, partajat cu backtest.py,
# ca backtest-ul să ruleze EXACT codul care tranzacționează live
from apex.position import calc_sltp, check_position as _check_position  # noqa: E402


def check_position(price):
    return _check_position(open_position, price)


def _quote_usd_rate(symbol):
    """USD value of the quote currency, for cross-pair sizing (EUR_JPY etc.)."""
    base, _, quote = symbol.upper().partition("_")
    if quote == "USD" or base == "USD":
        return None
    try:
        return broker.get_price(f"{quote}_USD")
    except Exception:
        pass
    try:
        return 1.0 / broker.get_price(f"USD_{quote}")
    except Exception:
        logger.warn(f"No USD rate for {quote} — cross-pair sizing approximated for {symbol}")
        return None


def open_trade(side, price, balance, atr_value=0, symbol=None, druck_mult=1.0, signal=None):
    global open_position
    symbol = symbol or cfg.SYMBOL

    # Spread guard — wide spreads eat the edge
    bid = ask = None
    try:
        bid, ask = broker.get_bid_ask(symbol)
        spread = forex.spread_pips(bid, ask, symbol)
        if spread > cfg.MAX_SPREAD_PIPS:
            logger.warn(f"Spread too wide ({spread:.1f} pips > {cfg.MAX_SPREAD_PIPS}) — skip entry")
            return
    except Exception:
        pass

    # Paper: intrarea plătește spread-ul (fill la ask pe BUY / bid pe SELL),
    # altfel rezultatele simulate ies sistematic mai bune decât realitatea
    if cfg.PAPER_TRADING and bid and ask:
        price = ask if side == "BUY" else bid

    sltp = calc_sltp(side, price, atr_value, symbol)
    stop_pips = forex.to_pips(abs(price - sltp["stopLoss"]), symbol)
    units = forex.calc_units(balance, cfg.RISK_PER_TRADE, stop_pips, symbol, price,
                             cfg.LEVERAGE, cfg.MARGIN_CAP, druck_mult,
                             quote_usd_rate=_quote_usd_rate(symbol))
    if units <= 0:
        logger.warn(f"Position size 0 for {symbol} @ {price} — skip")
        return
    if druck_mult != 1.0:
        logger.info(f"🎯 Druckenmiller: position size ×{druck_mult:.2f}")
    result = broker.place_order(side, units, symbol,
                                sl=sltp["stopLoss"], tp=sltp["takeProfit"])
    if result.get("status") == "REJECTED":
        logger.warn(f"Order rejected by broker: {result.get('reason')}")
        return
    # Live: prețul real de fill (poate diferi de semnal cu 0.5-2 pips)
    if not cfg.PAPER_TRADING and result.get("fillPrice"):
        price = result["fillPrice"]
    rr = abs(sltp["takeProfit"] - price) / abs(price - sltp["stopLoss"]) if (price - sltp["stopLoss"]) else 0
    open_position = {
        "symbol": symbol, "side": side, "entryPrice": price, "quantity": units,
        "stopLoss": sltp["stopLoss"], "takeProfit": sltp["takeProfit"],
        "initialStop": sltp["stopLoss"],  # referință pentru breakeven (+1R)
        "openedAt": datetime.utcnow().isoformat(), "pnlPips": 0,
        "trailHigh": price if side == "BUY" else None, "trailLow": price if side == "SELL" else None,
    }
    dash["openPosition"] = open_position
    logger.print_trade(side, symbol, price, units)
    logger.info(f"SL: {sltp['stopLoss']:.5f} | TP: {sltp['takeProfit']:.5f} | "
                f"{stop_pips:.0f} pips risk | R:R = 1:{rr:.2f} | margin: "
                f"${forex.required_margin(units, symbol, price, cfg.LEVERAGE):.2f}")
    tg.alert_open(side, symbol, price, units, sltp["stopLoss"], sltp["takeProfit"], druck_mult,
                  reasoning=(signal or {}).get("reasoning", ""),
                  key_factors=(signal or {}).get("keyFactors", []))
    state.save(paper_balance, open_position)


def close_trade(price, reason, send_order=True, signal=None):
    global open_position, paper_balance
    if not open_position:
        return
    side = open_position["side"]
    entry_price = open_position["entryPrice"]
    units = open_position["quantity"]
    symbol = open_position.get("symbol", cfg.SYMBOL)
    close_side = "SELL" if side == "BUY" else "BUY"
    if send_order:
        if hasattr(broker, "close_position"):
            result = broker.close_position(symbol)
        else:
            result = broker.place_order(close_side, units, symbol)
        # Live: PnL pe prețul real de execuție, nu pe ticker
        if not cfg.PAPER_TRADING and isinstance(result, dict) and result.get("fillPrice"):
            price = result["fillPrice"]
    pnl = forex.pnl_usd(side, entry_price, price, units, symbol,
                        quote_usd_rate=_quote_usd_rate(symbol))
    if cfg.PAPER_TRADING:
        paper_balance += pnl
    pips = forex.to_pips(price - entry_price if side == "BUY" else entry_price - price, symbol)
    logger.print_trade(close_side, symbol, price, units, pnl)
    logger.info(f"Reason: {reason} | {pips:+.1f} pips | PnL: {'+' if pnl >= 0 else ''}${pnl:.2f}")
    strategies.record_trade(pnl > 0, pnl, start_balance or cfg.PAPER_BALANCE)
    bal = get_balance()
    tg.alert_close(reason, symbol, side, entry_price, price, pnl, bal,
                   reasoning=(signal or {}).get("reasoning", ""))
    dash["trades"].insert(0, {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "symbol": symbol, "side": side,
        "entry": entry_price, "exit": price, "qty": units, "pnl": round(pnl, 2),
        "pips": round(pips, 1), "pnlPct": round(pnl / (start_balance or 1) * 100, 2),
        "reason": reason, "win": pnl > 0,
    })
    dash["trades"] = dash["trades"][:50]
    dash["openPosition"] = None
    dash["balance"] = bal
    open_position = None
    state.save(paper_balance, None)


def best_symbol():
    if cfg.BROKER == "mt":          # the EA only sees its own chart
        return cfg.SYMBOL
    if not cfg.MULTI_SYMBOL or len(cfg.SCAN_SYMBOLS) <= 1:
        return cfg.SYMBOL
    results = []
    for sym in cfg.SCAN_SYMBOLS:
        sym = sym.strip()
        try:
            candles = broker.get_candles(sym, cfg.TIMEFRAME, 50)
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
        logger.info(f"📡 Scanner: best pair → {best['sym']} (score: {best['score']:.2f})")
    return best["sym"]


def tick():
    global tick_count, stop_alerted_at, market_closed_alerted
    if _is_paused():
        return
    tick_count += 1
    try:
        # ── Forex market hours (closed on weekends) ──────
        market_open = forex.is_market_open()
        dash["marketOpen"] = market_open
        if not market_open:
            if not market_closed_alerted:
                logger.info("🕐 Market closed (weekend) — waiting for Sunday open (21:00 UTC)")
                tg.alert_market_closed()
                market_closed_alerted = True
            return
        market_closed_alerted = False

        # ── MT bridge: the EA's chart dictates the symbol; reconcile
        #    positions the EA closed natively (its safety-net SL/TP) ──
        if cfg.BROKER == "mt":
            ea_symbol = broker.current_symbol()
            if ea_symbol:
                cfg.SYMBOL = ea_symbol
            if open_position and not cfg.PAPER_TRADING and broker.position_reported() is None:
                last_price = dash.get("currentPrice") or open_position["entryPrice"]
                logger.warn("MT reports flat — position closed inside MetaTrader (SL/TP)")
                close_trade(last_price, "MT_SLTP", send_order=False)
                return

        active_symbol = open_position["symbol"] if open_position else None
        symbol = active_symbol or best_symbol()

        if tick_count % 5 == 0:
            try:
                logger.print_stats(get_balance(), open_position, broker.get_price(symbol))
            except Exception:
                logger.print_stats(get_balance(), open_position, None)
        if tick_count % 6 == 0:
            hb_balance = get_balance()
            try:
                hb_price = broker.get_price(symbol)
            except Exception:
                hb_price = None
            tg.alert_heartbeat(tick_count, hb_balance, open_position, hb_price)

        logger.info(f"[{tick_count}] Analyzing {symbol} ({broker_label()})"
                    f"{' 🔒 active position' if active_symbol else ''}...")

        candles = broker.get_candles(symbol, cfg.TIMEFRAME, cfg.CANDLES)
        price = broker.get_price(symbol)
        balance = get_balance()
        logger.update_balance(balance)

        dash["balance"] = balance
        dash["currentSymbol"] = symbol
        dash["currentPrice"] = price
        dash["lastTick"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dash["candles"] = candles[-150:] if candles else []
        if open_position:
            pos_pnl = forex.pnl_usd(open_position["side"], open_position["entryPrice"],
                                    price, open_position["quantity"], symbol)
            dash["openPosition"] = {**open_position, "currentPnl": round(pos_pnl, 2)}

        trigger = check_position(price)
        if trigger:
            logger.warn(f"{trigger} hit at {price}")
            close_trade(price, trigger)
            logger.print_stats(get_balance(), None, None)
            return

        ind = indicators.analyze(candles)
        strat_data = strategies.analyze(candles)

        portfolio_value = balance
        if open_position and price:
            portfolio_value = balance + forex.pnl_usd(
                open_position["side"], open_position["entryPrice"], price,
                open_position["quantity"], symbol)
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
        criteria_ok = (signal.get("criteriaScore", 0) or 0) >= min_criteria

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

        # Seykota: cooldown după pierdere — fără revenge trading
        cd_min = strategies.cooldown_remaining(cfg.COOLDOWN_AFTER_LOSS_MIN)
        if not open_position and cd_min > 0 and signal["action"] in ("BUY", "SELL"):
            logger.info(f"⏸️ Post-loss cooldown: {cd_min} min before re-entry")
            signal["action"] = "HOLD"

        # Filtru trend HTF: nu tranzacționa 5m contra trendului 1h
        # (skip pe MT — EA-ul trimite un singur timeframe)
        if (cfg.HTF_FILTER and cfg.BROKER != "mt" and not open_position
                and signal["action"] in ("BUY", "SELL")):
            try:
                htf = strategies.htf_trend(broker.get_candles(symbol, cfg.HTF_TIMEFRAME, 60))
            except Exception:
                htf = "NEUTRAL"
            if cfg.HTF_STRICT:
                # strict mode (tuning r3 best forex): intră DOAR pe direcția HTF, NEUTRAL=HOLD
                if htf != ("BULLISH" if signal["action"] == "BUY" else "BEARISH"):
                    logger.warn(f"⚡ HTF strict: {signal['action']} needs {htf} → HOLD")
                    signal["action"] = "HOLD"
            elif ((signal["action"] == "BUY" and htf == "BEARISH")
                    or (signal["action"] == "SELL" and htf == "BULLISH")):
                logger.warn(f"⚡ {cfg.HTF_TIMEFRAME} filter: {signal['action']} against {htf} trend — HOLD (trade with the tape)")
                signal["action"] = "HOLD"

        if signal["action"] == "HOLD" or signal["confidence"] < cfg.MIN_CONFIDENCE or not criteria_ok:
            logger.info(f"HOLD — confidence: {signal['confidence']}% | "
                        f"criteria: {signal.get('criteriaScore', '?')}/5")
        elif signal["action"] == "CLOSE" and open_position:
            close_trade(price, "AI_CLOSE", signal=signal)
        elif signal["action"] == "BUY" and not open_position:
            open_trade("BUY", price, balance, float(ind["atr"]), symbol, druck_mult, signal=signal)
        elif signal["action"] == "SELL" and not open_position:
            open_trade("SELL", price, balance, float(ind["atr"]), symbol, druck_mult, signal=signal)
        else:
            logger.info("Skip — position already open/closed")

        logger.print_stats(get_balance(), open_position, price)
    except Exception as err:
        logger.error(f"Tick error: {err}")


# ─── Dashboard HTTP server ────────────────────────────────
def _start_dashboard_server():
    from urllib.parse import urlparse, parse_qs
    port = int(os.getenv("PORT") or os.getenv("DASHBOARD_PORT") or 3000)
    token = os.getenv("DASHBOARD_TOKEN") or ""
    if not token:
        print("⚠️  DASHBOARD_TOKEN not set — the dashboard (balance + trade history) "
              "is PUBLIC on your Railway URL.")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _authorized(self):
            if not token:
                return True
            qs = parse_qs(urlparse(self.path).query)
            if qs.get("token", [""])[0] == token:
                return True
            bearer = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            return bearer == token

        def do_POST(self):
            if self.path == "/api/mt/sync":
                from apex.brokers import mtbridge
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(min(length, 1_000_000)).decode("utf-8", "replace")
                status, text = mtbridge.handle_sync(body)
                payload = text.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

        def do_GET(self):
            # Railway healthcheck — fără auth, nu expune date
            if self.path.startswith("/health"):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")
                return
            # Telegram Mini App — the page is public; every DATA call inside it
            # carries Telegram's signed initData, validated per user below.
            if self.path == "/guide-app" or self.path.startswith("/guide-app?"):
                from apex import webapp
                payload = webapp.guide_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path == "/app" or self.path.startswith("/app?"):
                from apex import webapp
                payload = webapp.terminal_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path.startswith("/api/app/data"):
                from apex import webapp, user_loop, user_store, news as news_mod
                qs = parse_qs(urlparse(self.path).query)
                init = (qs.get("init") or [""])[0]
                tg_user = webapp.validate(init, cfg.TELEGRAM_BOT_TOKEN or "")
                if not tg_user or not tg_user.get("id"):
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error":"unauthorized"}')
                    return
                chat_id = str(tg_user["id"])
                try:
                    u = user_store.load(chat_id)
                    udash = user_loop.get_dash(chat_id) or {}
                    br, ucfg = user_loop._make_broker(u)
                    candles = br.get_candles(ucfg.SYMBOL, ucfg.TIMEFRAME, 150) or []
                    pos = udash.get("openPosition")
                    from apex import stats as stats_mod, forex as fx_mod
                    balance_live = udash.get("balance", u.get("paper_balance", 0))
                    # REAL mode: the loop ticks every 5 minutes — far too stale
                    # for a terminal. Read position + balance live per poll.
                    if not u.get("paper", True):
                        try:
                            pos = br.get_open_position(ucfg.SYMBOL)
                        except Exception:
                            pass
                        try:
                            balance_live = br.get_balance()
                        except Exception:
                            pass
                    # Live unrealized P&L from the freshest candle close.
                    last_px = candles[-1]["close"] if candles else None
                    if pos and last_px and pos.get("entryPrice"):
                        d_ = 1 if pos.get("side") == "BUY" else -1
                        pos = dict(pos)
                        pos["pnlPips"] = round(fx_mod.to_pips(
                            (last_px - pos["entryPrice"]) * d_, ucfg.SYMBOL, last_px), 1)
                        units_ = pos.get("units") or pos.get("quantity") or 0
                        if units_:
                            pos["pnlUsd"] = round(fx_mod.pnl_usd(
                                pos["side"], pos["entryPrice"], last_px, units_, ucfg.SYMBOL), 2)
                    # Live account money, exactly like a cTrader terminal:
                    #   Equity = Balance + floating (unrealized) P&L.
                    # Floating from every open position, priced at the freshest
                    # close we can read (focused symbol is already priced above).
                    floating = float(pos.get("pnlUsd") or 0) if pos else 0.0
                    if pos is not None:
                        try:
                            all_pos = br.get_all_positions() if not u.get("paper", True) else []
                        except Exception:
                            all_pos = []
                        for ap in all_pos or []:
                            if ap.get("symbol") == ucfg.SYMBOL:
                                continue  # already counted via the focused pos
                            try:
                                apx = br.get_candles(ap["symbol"], ucfg.TIMEFRAME, 2)
                                apx = apx[-1]["close"] if apx else None
                                un = ap.get("units") or 0
                                if apx and ap.get("entryPrice") and un:
                                    floating += float(fx_mod.pnl_usd(
                                        ap["side"], ap["entryPrice"], apx, un, ap["symbol"]))
                            except Exception:
                                pass
                    equity_live = round(float(balance_live or 0) + floating, 2)
                    events = news_mod.upcoming(hours=24) or []
                    journal = user_store.load_trades(chat_id)
                    st = stats_mod.compute(journal, udash.get("skipsToday", 0))
                    body = json.dumps({
                        "symbol": ucfg.SYMBOL, "timeframe": ucfg.TIMEFRAME,
                        "mode": udash.get("mode", "📝 PAPER" if u.get("paper", True) else "🔴 REAL"),
                        "strategy": udash.get("strategy", "Mean Reversion"),
                        "broker": udash.get("broker", ""),
                        "balance": balance_live,
                        "equityLive": equity_live,
                        "floatingPnl": round(floating, 2),
                        "price": last_px,
                        "regime": udash.get("regime"),
                        "sessions": fx_mod.active_sessions(),
                        "position": pos, "trades": (udash.get("trades") or [])[:12],
                        "skips": (udash.get("skips") or [])[:15],
                        "stats": {k: (None if isinstance(v, float) and v != v or v == float("inf") else v)
                                  for k, v in st.items() if k != "equity"},
                        "equity": st.get("equity") or [],
                        "events": events,
                        "candles": [{"time": c["time"], "open": c["open"], "high": c["high"],
                                     "low": c["low"], "close": c["close"]} for c in candles],
                    }).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as e:
                    err = json.dumps({"error": str(e)[:200]}).encode()
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(err)
                return
            # cTrader OAuth callback — no auth (state is HMAC-signed), public by design
            if self.path.startswith("/api/ctrader/callback"):
                from apex import ctrader_oauth
                qs = parse_qs(urlparse(self.path).query)
                status, html = ctrader_oauth.handle_callback(qs)
                payload = html.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if not self._authorized():
                self.send_response(401)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Unauthorized - open with ?token=YOUR_DASHBOARD_TOKEN")
                return
            if self.path.startswith("/api/status"):
                body = json.dumps({**dash, "tickCount": tick_count, "candles": []}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/api/candles"):
                body = json.dumps({"candles": dash.get("candles", []), "symbol": dash["currentSymbol"], "timeframe": cfg.TIMEFRAME}).encode()
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

    # Self-ping keeps Render's free tier awake 24/7. Without this the service
    # spins down after ~15 min of no inbound HTTP, the Telegram poll loop stops,
    # and the bot stops responding to every command (the "dead bot" symptom).
    render_url = (os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if render_url:
        def _keepalive():
            while True:
                time.sleep(60)  # every 1 min — never let the idle timer fire
                try:
                    requests.get(f"{render_url}/health", timeout=10)
                except Exception:
                    pass
        threading.Thread(target=_keepalive, daemon=True).start()
        logger.info(f"✅ Self-ping every 1 min → {render_url}/health")
    else:
        logger.warn("⚠️  RENDER_EXTERNAL_URL not set — self-ping disabled. "
                    "On Render free tier the bot may sleep and stop responding.")


def main():
    global start_balance, paper_balance, open_position, broker
    print(f"[{getattr(cfg, 'BOT_NAME', 'Apex Forex Bot').upper()}] Starting... Python {sys.version.split()[0]}")
    load_remote()           # config saved in the configurator (broker keys, env, risk)
    _load_runtime_config()  # Telegram-saved overrides take precedence
    broker = get_broker()   # re-init with the now-loaded settings
    dash["broker"] = broker_label()  # dash dict was built at import time, before load_remote()
    tg.refresh_from_config()  # tg.TOKEN/CHAT_ID were also frozen at import time, before load_remote()
    validate()
    paper_balance = cfg.PAPER_BALANCE  # re-sync after remote config loaded

    if cfg.PAPER_TRADING:
        saved = state.load(cfg.PAPER_BALANCE)
        if saved:
            paper_balance = saved["paperBalance"]
            open_position = saved.get("openPosition")
    elif hasattr(broker, "get_open_trades"):
        # Live: brokerul e sursa de adevăr — fără reconciliere, botul ar uita
        # poziția existentă și ar deschide alta peste ea (dublă expunere)
        try:
            trades = broker.get_open_trades()
            if trades:
                t = trades[0]
                sltp = calc_sltp(t["side"], t["entryPrice"], 0, t["instrument"])
                open_position = {
                    "symbol": t["instrument"], "side": t["side"],
                    "entryPrice": t["entryPrice"], "quantity": t["units"],
                    "stopLoss": t["sl"] or sltp["stopLoss"],
                    "takeProfit": t["tp"] or sltp["takeProfit"],
                    "initialStop": t["sl"] or sltp["stopLoss"],
                    "openedAt": t.get("openTime") or datetime.utcnow().isoformat(),
                    "pnlPips": 0,
                    "trailHigh": t["entryPrice"] if t["side"] == "BUY" else None,
                    "trailLow": t["entryPrice"] if t["side"] == "SELL" else None,
                }
                dash["openPosition"] = open_position
                logger.warn(f"♻️ Live position reconciled from broker: "
                            f"{t['side']} {t['units']} {t['instrument']} @ {t['entryPrice']}")
                if len(trades) > 1:
                    logger.warn(f"⚠️ {len(trades)} open trades at the broker — "
                                f"managing the first, close the rest manually!")
        except Exception as e:
            logger.warn(f"Open-trade reconciliation failed: {e}")

    balance = get_balance()
    start_balance = balance
    dash["balance"] = balance
    dash["startBalance"] = balance
    logger.set_start_balance(balance)
    logger.print_banner(balance)

    mode = "📝 PAPER TRADING" if cfg.PAPER_TRADING else (
        "🔗 METATRADER" if cfg.BROKER == "mt" else (
            "📡 TWELVE DATA" if cfg.BROKER == "td" else (
                "🧪 PRACTICE" if cfg.OANDA_ENV == "practice" else "🔴 LIVE")))
    dash["mode"] = mode.replace("📝", "").replace("🧪", "").replace("🔴", "").strip()
    tg.alert_start(cfg.SYMBOL, cfg.TIMEFRAME, balance, mode)

    _start_dashboard_server()
    tg.start_polling(lambda: dash, broker, control={
        "set_paused": set_paused,
        "get_paused": _is_paused,
        "reload_broker": reload_broker_connector,
    })

    # Remote control plane (Ruflo MCP) — lets the operator read live state and
    # (when MCP_CONTROL_ENABLED) act on the bot, over the shared Redis bus.
    try:
        from apex import control, control_actions
        control.start_consumer(control_actions.build())
    except Exception as e:
        logger.warn(f"MCP control plane failed to start: {e}")

    verify_license()
    # The global single-account tick() loop is legacy: it analyzes ONE instrument
    # via the global broker (OANDA). In the per-user cTrader architecture each
    # client runs their own isolated loop (started by the Telegram poller), so
    # when no global OANDA data source is configured the global loop has no valid
    # feed and would just error every tick (e.g. 'BTCUSD on OANDA 400') while
    # burning the AI quota. Skip it and keep the process alive for the poller.
    if cfg.OANDA_API_TOKEN and cfg.OANDA_ACCOUNT_ID:
        logger.info("🚀 First analysis...")
        tick()
        interval = cfg.LOOP_INTERVAL_MS / 1000
        logger.info(f"⏱️  Analysis every {cfg.LOOP_INTERVAL_MS / 60000} minutes.")
        while True:
            time.sleep(interval)
            tick()
    else:
        logger.info("Per-user mode: global analysis loop OFF — each client trades on their own cTrader loop.")
        while True:
            time.sleep(3600)
