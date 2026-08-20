"""APEX FOREX BOT — main loop."""
import os
import sys
import time
import hmac
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
    if cfg.BROKER == "ctrader":
        return f"cTrader ({cfg.CTRADER_ENV})"
    if cfg.BROKER == "mt":
        return "MT BRIDGE"
    if cfg.BROKER == "td":
        return "TWELVE DATA"
    return f"cTrader ({cfg.CTRADER_ENV})"


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
                setattr(cfg, k, str(v).lower() if k == "BROKER" else str(v))
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
    # Broker secrets in this file are encrypted at rest (see
    # telegram._save_runtime). Applying the ciphertext as a credential would
    # fail broker auth in a way that looks like a wrong password.
    try:
        from apex import user_store as _us
        from apex import telegram as _tg
        for _k in list(data):
            if _tg.is_secret_key(_k):
                data[_k] = _us.decrypt_value(data[_k])
    except Exception as e:
        print(f"[BOT] runtime.json: could not decrypt secrets ({e})")
    n = _apply_config(data, "runtime.json")
    print(f"[BOT] runtime.json loaded ({n} settings)")


def load_remote():
    """Fetch the config the client saved in the configurator and apply it.

    Mirrors the crypto bot's cfg.loadRemote(): with only LICENSE_KEY set, the
    bot pulls broker keys, CTRADER_ENV, risk and strategy from the license server
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
                         headers={"User-Agent": f"{cfg.BOT_NAME.replace(' ', '')}/1.0"})
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
    "mode": "PAPER" if cfg.PAPER_TRADING else cfg.CTRADER_ENV.upper(),
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
        res = requests.post(f"{server}/api/verify-license", json={"key": key, "product": cfg.LICENSE_PRODUCT}, timeout=10)
        data = res.json()
        if data.get("valid"):
            print(f"✅  {cfg.BOT_NAME} license verified — welcome, {data.get('email', 'trader')}!")
        else:
            print(f"⚠️  License not valid ({data.get('message')}) — continuing anyway.")
    except Exception as e:
        print(f"⚠️   License server unreachable ({e}) — continuing anyway.")


def validate():
    if not cfg.GROQ_API_KEY:
        print("⚠️  No GROQ_API_KEY — using rule-based signals (RSI/MACD/EMA). "
              "Add GROQ_API_KEY for the AI second opinion.")
    # Say where each AI credential came from. "Which key am I trading on, and
    # who can revoke it" is not answerable from the outside once a value can
    # arrive from an env var, an env group, or a mounted secret file.
    for _k in ("GROQ_API_KEY", "GEMINI_API_KEY"):
        _src = cfg.secret_provenance(_k)
        if _src != "unset":
            print(f"[Keys] {_k} ← {_src}")
    if cfg.BROKER == "ctrader":
        if cfg.CTRADER_CLIENT_ID and cfg.CTRADER_CLIENT_SECRET:
            print("🔗 cTrader mode — clients connect via /ctrader (OAuth).")
        else:
            print("⚠️  cTrader credentials missing (CTRADER_CLIENT_ID / CTRADER_CLIENT_SECRET).")
            print("    Clients won't be able to link accounts. Set them in Render env vars.")
    elif cfg.BROKER == "mt":
        if not cfg.MT_BRIDGE_SECRET:
            print("⚠️  BROKER=mt needs MT_BRIDGE_SECRET.")
        else:
            print("🔗 MetaTrader bridge mode — waiting for the ApexBridge EA to sync.")
    elif cfg.BROKER == "td":
        if not cfg.TWELVE_DATA_KEY:
            print("⚠️  BROKER=td needs TWELVE_DATA_KEY.")
        else:
            print("📡 Twelve Data mode.")


def get_balance():
    if cfg.PAPER_TRADING:
        return paper_balance
    if cfg.BROKER == "ctrader":
        return 0
    try:
        return broker.get_balance()
    except Exception as e:
        logger.warn(f"[BALANCE] API error: {e}")
        return 0


# Exit management — implementat în apex/position.py, partajat cu backtest.py,
# ca backtest-ul să ruleze EXACT codul care tranzacționează live
from apex.position import calc_sltp, check_position as _check_position  # noqa: E402


# Legacy single-user trading path (tick / open_trade / close_trade /
# best_symbol) REMOVED — it was dead code never scheduled by main().
# Production is per-user: every client trades in an isolated user_loop
# thread (started by main() below), with the strategy mode, risk and
# broker they chose themselves.


# ─── Dashboard HTTP server ────────────────────────────────
def _start_dashboard_server():
    from urllib.parse import urlparse, parse_qs
    port = int(os.getenv("PORT") or os.getenv("DASHBOARD_PORT") or 3000)
    token = os.getenv("DASHBOARD_TOKEN") or ""
    if not token:
        print("🔒 DASHBOARD_TOKEN not set — the dashboard and its data APIs are "
              "DISABLED (503). Set DASHBOARD_TOKEN to enable them.")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _authorized(self):
            """Fail CLOSED.

            This used to `return True` whenever DASHBOARD_TOKEN was unset, so a
            single missing environment variable silently published /api/status
            — balance, open position and the trade journal — to anyone who
            knew the URL, with no warning beyond one startup line. Verified
            live: an unauthenticated GET returned 200.

            A missing secret is a misconfiguration, not permission. The caller
            turns that into a 503 so the operator can tell "I forgot to set the
            token" apart from "my token is wrong".

            compare_digest keeps the comparison constant-time: plain `==` on
            secrets leaks their length and prefix through timing.
            """
            if not token:
                return False
            qs = parse_qs(urlparse(self.path).query)
            supplied = qs.get("token", [""])[0]
            if not supplied:
                supplied = (self.headers.get("Authorization") or
                            "").removeprefix("Bearer ").strip()
            return hmac.compare_digest(supplied, token)

        def _json(self, status, obj):
            """A JSON reply with no cache and an explicit length.

            The Mini App polls; a cached 200 would show a client a stale
            account long after it changed, which is the one thing a terminal
            must never do.
            """
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _deny(self):
            """401 when the token is wrong, 503 when there is no token at all."""
            if not token:
                body = (b"503 - dashboard disabled. DASHBOARD_TOKEN is not set "
                        b"on this deployment, so these endpoints serve nothing.")
                self.send_response(503)
            else:
                body = b"401 - unauthorized. Open with ?token=YOUR_DASHBOARD_TOKEN"
                self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path == "/api/stripe/webhook":
                from apex import stripe_license
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(min(length, 1_000_000))
                status, text = stripe_license.handle_webhook(
                    raw, self.headers.get("Stripe-Signature", ""))
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(text)))
                self.end_headers()
                self.wfile.write(text)
            elif self.path == "/api/mt/sync":
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
                from apex import account_mode as _account_mode
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
                    # Auto-Pilot rotates the traded symbol live, in-memory,
                    # without ever persisting it back to the user record —
                    # ucfg.SYMBOL is only the ORIGINAL stored default. Reading
                    # candles/position/P&L off ucfg.SYMBOL here made the
                    # Terminal show a stale symbol with no position the moment
                    # Auto-Pilot moved to anything else — which is most of the
                    # time. dash["symbol"] is what the loop is ACTUALLY
                    # watching/trading right now.
                    live_symbol = udash.get("symbol") or ucfg.SYMBOL
                    # The client may pick a timeframe. An unrecognised one falls
                    # back to the loop's own rather than being passed to the
                    # broker, so a junk value cannot become a silent M5.
                    from apex import miniapp_api as _mapi
                    _tf = (qs.get("tf") or [""])[0].lower()
                    tf_used = _tf if _tf in _mapi.TIMEFRAMES else ucfg.TIMEFRAME
                    candles = br.get_candles(live_symbol, tf_used, 150) or []
                    pos = udash.get("openPosition")
                    from apex import stats as stats_mod, forex as fx_mod
                    balance_live = udash.get("balance", u.get("paper_balance", 0))
                    # REAL mode: the loop ticks every 5 minutes — far too stale
                    # for a terminal. Read position + balance live per poll.
                    if not u.get("paper", True):
                        try:
                            pos = br.get_open_position(live_symbol)
                        except Exception:
                            pass
                        try:
                            balance_live = br.get_balance()
                        except Exception:
                            pass
                    try:
                        _digits = int(br._digits(live_symbol))
                    except Exception:
                        _digits = 3 if "JPY" in str(live_symbol).upper() else 5
                    try:
                        _pip = float(fx_mod.pip_size(live_symbol))
                    except Exception:
                        _pip = 0.01 if "JPY" in str(live_symbol).upper() else 0.0001
                    # Live unrealized P&L from the freshest candle close.
                    last_px = candles[-1]["close"] if candles else None
                    if pos and last_px and pos.get("entryPrice"):
                        d_ = 1 if pos.get("side") == "BUY" else -1
                        pos = dict(pos)
                        pos["pnlPips"] = round(fx_mod.to_pips(
                            (last_px - pos["entryPrice"]) * d_, live_symbol, last_px), 1)
                        units_ = pos.get("units") or pos.get("quantity") or 0
                        if units_:
                            pos["pnlUsd"] = round(fx_mod.pnl_usd(
                                pos["side"], pos["entryPrice"], last_px, units_, live_symbol), 2)
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
                            if ap.get("symbol") == live_symbol:
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
                    news_today = news_mod.today() or []
                    journal = user_store.load_trades(chat_id)
                    st = stats_mod.compute(journal, udash.get("skipsToday", 0))
                    body = json.dumps({
                        "symbol": live_symbol, "timeframe": ucfg.TIMEFRAME,
                        "mode": udash.get("mode", "📝 PAPER" if u.get("paper", True) else "🔴 REAL"),
                        # The badge the terminal renders. Resolved from the
                        # BROKER's own isLive where reachable, not from the
                        # stored flag — and reported as unverified rather than
                        # guessed, so a demo account can never be shown as LIVE
                        # because a lookup failed. See apex/account_mode.py.
                        "account": (lambda _m: {
                            "mode": _m[0], "source": _m[1],
                            "badge": _account_mode.badge(_m[0]),
                            "realMoney": _account_mode.is_real_money(_m[0]),
                        })(_account_mode.resolve(u)),
                        "timeframeUsed": tf_used,
                        # Price precision, from the broker's own symbol details.
                        # Without it Lightweight Charts formats to 2 decimals and
                        # a GBPUSD entry of 1.36078 renders as "1.36" — three
                        # digits of the number that actually matters, gone.
                        "digits": _digits,
                        "pipSize": _pip,
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
                        "newsToday": news_today,
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
            # ── Mini App: the fast tick ─────────────────────────────────
            # /api/app/data rebuilds everything — candles, stats, news, journal —
            # which is far too heavy to ask for at the rate a price moves. This
            # returns only what changes tick to tick: the bid/ask, the open
            # position's live P&L, and the money. Small enough to poll about
            # once a second, which is what makes the screen feel like a terminal
            # instead of a page that refreshes.
            if self.path.startswith("/api/app/tick"):
                from apex import webapp, user_loop, user_store
                from apex import forex as fx_mod
                qs = parse_qs(urlparse(self.path).query)
                init = (qs.get("init") or [""])[0]
                tg_user = webapp.validate(init, cfg.TELEGRAM_BOT_TOKEN or "")
                if not tg_user or not tg_user.get("id"):
                    self._json(401, {"error": "unauthorized",
                                     "code": "TELEGRAM_AUTH_FAILED"})
                    return
                chat_id = str(tg_user["id"])
                try:
                    u = user_store.load(chat_id) or {}
                    udash = user_loop.get_dash(chat_id) or {}
                    br, ucfg = user_loop._make_broker(u)
                    sym = udash.get("symbol") or ucfg.SYMBOL
                    paper = u.get("paper", True)

                    bid = ask = None
                    try:
                        bid, ask = br.get_bid_ask(sym)
                    except Exception:
                        pass
                    price = None
                    if bid is not None and ask is not None:
                        price = (float(bid) + float(ask)) / 2.0
                    if price is None:
                        try:
                            price = float(br.get_price(sym))
                        except Exception:
                            price = None

                    pos = udash.get("openPosition")
                    if not paper:
                        try:
                            pos = br.get_open_position(sym)
                        except Exception:
                            pass

                    pnl_pips = pnl_usd = None
                    if pos and price and pos.get("entryPrice"):
                        d_ = 1 if pos.get("side") == "BUY" else -1
                        pnl_pips = round(fx_mod.to_pips(
                            (price - float(pos["entryPrice"])) * d_, sym, price), 1)
                        units_ = pos.get("units") or pos.get("quantity") or 0
                        if units_:
                            pnl_usd = round(fx_mod.pnl_usd(
                                pos["side"], float(pos["entryPrice"]), price,
                                units_, sym), 2)

                    balance = udash.get("balance", u.get("paper_balance", 0))
                    if not paper:
                        try:
                            balance = br.get_balance()
                        except Exception:
                            pass
                    floating = float(pnl_usd or 0)

                    self._json(200, {
                        "symbol": sym, "price": price, "bid": bid, "ask": ask,
                        # Server time, so the page can tell a still price from a
                        # stopped feed instead of showing the last one as live.
                        "ts": int(time.time()),
                        "balance": balance,
                        "equityLive": (float(balance) + floating) if balance is not None else None,
                        "floatingPnl": floating,
                        "position": (None if not pos else {
                            "side": pos.get("side"),
                            "entryPrice": pos.get("entryPrice"),
                            "stopLoss": pos.get("stopLoss") or pos.get("sl"),
                            "takeProfit": pos.get("takeProfit") or pos.get("tp"),
                            "pnlPips": pnl_pips, "pnlUsd": pnl_usd}),
                    })
                except Exception as e:
                    print(f"[MiniApp] tick failed: {e}")
                    self._json(502, {"error": "UNAVAILABLE", "code": "UNAVAILABLE"})
                return
            # ── Mini App: history + replay ──────────────────────────────
            # Same authentication as /api/app/data above: the chat id comes
            # ONLY from initData whose HMAC we verified. No route here reads a
            # user id from the query string, so a client cannot ask for
            # somebody else's account by editing a parameter.
            if self.path.startswith("/api/app/history") or self.path.startswith("/api/app/replay"):
                from apex import webapp, miniapp_api
                qs = parse_qs(urlparse(self.path).query)
                init = (qs.get("init") or [""])[0]
                tg_user = webapp.validate(init, cfg.TELEGRAM_BOT_TOKEN or "")
                if not tg_user or not tg_user.get("id"):
                    self._json(401, {"error": "unauthorized",
                                     "code": "TELEGRAM_AUTH_FAILED"})
                    return
                chat_id = str(tg_user["id"])
                try:
                    if self.path.startswith("/api/app/history"):
                        body = miniapp_api.history(
                            chat_id,
                            limit=(qs.get("limit") or ["25"])[0],
                            offset=(qs.get("offset") or ["0"])[0])
                    else:
                        body = miniapp_api.replay(
                            chat_id,
                            (qs.get("trade") or [""])[0],
                            (qs.get("timeframe") or ["15m"])[0])
                    self._json(200, body)
                except miniapp_api.ReplayError as e:
                    # A missing trade and somebody else's trade are the SAME
                    # answer on purpose: distinguishing them would turn this
                    # into an oracle for which trade ids exist on other
                    # accounts. 404 for both, one code.
                    status = 404 if e.code in ("TRADE_NOT_FOUND", "TRADE_INCOMPLETE") else 502
                    if e.code == "INVALID_TIMEFRAME":
                        status = 400
                    self._json(status, {"error": e.code, "code": e.code})
                except Exception as e:
                    print(f"[MiniApp] {self.path.split('?')[0]} failed: {e}")
                    self._json(502, {"error": "UNAVAILABLE", "code": "UNAVAILABLE"})
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
                self._deny()
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

    # Privileged operator configuration. The admin id used to be a constant in
    # access.py, which meant the repository carried a privileged identity and
    # changing the operator needed a deploy. It now comes from ADMIN_CHAT_IDS /
    # ADMIN_CHAT_ID / TELEGRAM_CHAT_ID.
    #
    # This WARNS rather than refusing to start, and the asymmetry is deliberate:
    # a bot with no configured admin is recoverable — the first /start claims
    # ownership through the existing bootstrap — while a bot that refuses to
    # boot over a missing variable is not recoverable from Telegram at all. The
    # count is printed, never the ids.
    # Give leases back when the platform stops us. Without this, Render's
    # deploy left the retiring container's leases held for their full TTL and
    # the incoming container — which correctly refuses to trade a user it does
    # not own — sat idle waiting for them to expire.
    try:
        import signal as _signal

        def _graceful(signum, _frame):
            print(f"[Bot] signal {signum} — releasing ownership leases")
            try:
                from apex import ownership as _own
                _own.release_all()
            except Exception as e:
                print(f"[Bot] lease release on shutdown failed: {e}")
            raise SystemExit(0)

        for _sig in (_signal.SIGTERM, _signal.SIGINT):
            _signal.signal(_sig, _graceful)
    except Exception as e:
        print(f"[Bot] could not install shutdown handler: {e}")

    try:
        from apex import access as _access
        _n = len(_access._env_admins())
        if _n:
            print(f"[Bot] {_n} privileged operator(s) configured")
        else:
            print("[Bot] ⚠️  NO ADMIN CONFIGURED — set ADMIN_CHAT_IDS to your "
                  "Telegram chat id. Until then nobody is an operator and the "
                  "first /start will claim ownership.")
    except Exception as e:
        print(f"[Bot] could not check operator configuration: {e}")
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

    mode = ("📝 PAPER TRADING" if cfg.PAPER_TRADING else
            f"🔗 cTrader ({cfg.CTRADER_ENV})" if cfg.BROKER == "ctrader" else
            "🔴 LIVE")
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

    # Overnight resilience: after ANY restart, bring every previously-active
    # user's loop back immediately (don't wait for them to message), then run a
    # self-healing watchdog that restarts any loop that dies. Both live in the
    # bot process, so recovery is 24/7 and needs no operator/session.
    try:
        from apex import user_loop as _ul
        _ul.start_all(alert_fn=tg._user_alert)
        _ul.start_watchdog(alert_fn=tg._user_alert)
    except Exception as e:
        logger.warn(f"boot auto-start / watchdog failed: {e}")

    # Market open/close edge. Separate from the trading loops on purpose: they
    # are gated behind is_market_open() and are asleep at exactly the moment
    # the close has to be announced and the broker session dropped.
    try:
        from apex import session_watch
        session_watch.start()
    except Exception as e:
        logger.warn(f"session watcher failed to start: {e}")

    verify_license()
    # Per-user cTrader architecture: each client runs their own isolated loop
    # (started by the Telegram poller after /ctrader OAuth).
    logger.info("Per-user mode — each client trades on their own cTrader loop. Send /ctrader to connect.")
    while True:
        time.sleep(3600)
