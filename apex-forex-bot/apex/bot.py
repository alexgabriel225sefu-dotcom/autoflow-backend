"""APEX FOREX BOT — main loop."""
import os
import sys
import time
import hmac
import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from apex import config as cfg
from apex import indicators, ai, logger, strategies, telegram as tg, state, forex
from apex import settings_policy, http_session, http_security
from apex.brokers import get_broker
from apex.dashboard import render as render_dashboard, render_login

broker = get_broker()


def broker_label():
    # cTrader is the only execution path this build has, and config.py now
    # refuses to import with BROKER set to anything else. The MT BRIDGE and
    # TWELVE DATA branches below this were unreachable, and an unreachable
    # branch that names a broker reads like a supported one.
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


def _apply_config(data, source="config", validate=None):
    """Apply a {ENV_NAME: value} dict to os.environ and the live cfg module.

    Every key is checked against an allowlist BEFORE it reaches os.environ.
    This used to be an unfiltered `os.environ[k] = str(v)` over whatever the
    licence server returned, which is a remote write onto the process
    environment — PATH, LD_PRELOAD and PYTHONPATH included, and each of those
    turns a configuration fetch into code execution. See apex/settings_policy.

    `validate` picks which allowlist applies, because the two callers do not
    have the same trust: runtime.json holds what an authenticated admin set,
    the remote loader holds whatever answered for the licence server.

    Rejected keys are reported by NAME and never by value — a refused key can
    still be carrying a credential.
    """
    if validate is None:
        validate = settings_policy.validate_operator

    applied, refused = 0, []
    for raw_key, raw_value in data.items():
        if raw_value is None or raw_value == "":
            continue
        try:
            key, value = validate(raw_key, raw_value)
        except settings_policy.SettingRejected as e:
            # Named, not swallowed: a security-relevant refusal that nobody
            # can see is indistinguishable from one that never happened.
            refused.append(str(e))
            continue

        os.environ[key] = str(value).lower() if isinstance(value, bool) else str(value)
        applied += 1

        attr = settings_policy.cfg_attr(key)
        if attr == "SCAN_SYMBOLS":
            cfg.SCAN_SYMBOLS = str(value).split(",")
        elif attr and hasattr(cfg, attr):
            setattr(cfg, attr, value)

    if refused:
        print(f"[BOT] {source}: refused {len(refused)} setting(s) — "
              + "; ".join(refused[:10]))
    return applied


def _apply_provisioning(data):
    """Apply first-deploy credentials. Never overwrite one already set.

    This exists so one-click deployment keeps working — a fresh container has
    no Telegram token, and the configurator is how it gets one — without
    letting every subsequent configuration fetch rotate it. A bot that already
    holds a credential has been provisioned; a response carrying a different
    one is either a mistake or a takeover, and neither deserves a silent yes.

    Values are never printed. A refusal names the key and says why.
    """
    applied, refused, held = 0, [], []
    for raw_key, raw_value in (data or {}).items():
        if raw_value is None or raw_value == "":
            continue
        try:
            key, value = settings_policy.validate_provisioning(raw_key, raw_value)
        except settings_policy.SettingRejected as e:
            refused.append(str(e))
            continue
        if not settings_policy.provisioning_allowed(key, os.environ.get(key)):
            held.append(key)
            continue
        os.environ[key] = str(value)
        attr = settings_policy.cfg_attr(key)
        if attr and hasattr(cfg, attr):
            setattr(cfg, attr, value)
        applied += 1

    if held:
        print(f"[BOT] provisioning: {len(held)} credential(s) already set, "
              f"left alone — {', '.join(held)}")
    if refused:
        print(f"[BOT] provisioning: refused {len(refused)} — "
              + "; ".join(refused[:5]))
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

    With only LICENSE_KEY set, the
    bot pulls broker keys, CTRADER_ENV, risk and strategy from the license server
    so deployment is truly one-click. Falls back to env vars on any failure.
    """
    key = cfg.LICENSE_KEY
    server = cfg.LICENSE_SERVER
    if not key:
        print("⚠️   load_remote: LICENSE_KEY not set — skipping remote config.")
        return False
    try:
        # Two steps, because the licence key is an entitlement rather than a
        # bearer token. It used to be sent as ?key=<licence> — a permanent
        # credential in a query string, so it reached every proxy and access
        # log between here and the licence server, and anything that read one
        # of those logs held standing access to this client's broker
        # configuration.
        #
        # Now it is POSTed once and exchanged for a token that expires in ten
        # minutes and carries one scope: bot:config:read.
        ua = {"User-Agent": f"{cfg.BOT_NAME.replace(' ', '')}/1.0"}
        sr = requests.post(f"{server}/api/bot-session",
                           json={"licenseKey": key}, timeout=10, headers=ua)
        if sr.status_code != 200:
            # Never log the body of a failed auth response and never the key.
            print(f"⚠️   load_remote: licence exchange returned {sr.status_code}.")
            return False
        session_token = (sr.json() or {}).get("token")
        if not session_token:
            print("⚠️   load_remote: licence exchange returned no token.")
            return False

        r = requests.get(f"{server}/api/bot-config", timeout=10,
                         headers={**ua, "Authorization": f"Bearer {session_token}"})
        if r.status_code != 200:
            print(f"⚠️   load_remote: config fetch returned {r.status_code}.")
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
        # Env vars set explicitly on the host win over the saved config, so a
        # power user can flip a setting in Render without re-running the
        # configurator.
        incoming = {k: v for k, v in data["config"].items() if k not in os.environ}
        skipped = [k for k in data["config"] if k in os.environ]
        if skipped:
            print(f"ℹ️   Keeping host env values (override saved config): {', '.join(skipped)}")

        # Two paths, because "change my stop loss" and "replace my Telegram
        # token" are not the same request. Runtime settings apply freely;
        # provisioning credentials are delivered only where nothing is set
        # yet, so a later response cannot silently rotate this bot's identity.
        # See apex/settings_policy.
        runtime = {k: v for k, v in incoming.items()
                   if k.strip().upper() not in settings_policy.REMOTE_PROVISIONING}
        provisioning = {k: v for k, v in incoming.items()
                        if k.strip().upper() in settings_policy.REMOTE_PROVISIONING}

        n = _apply_config(runtime, "remote",
                          validate=settings_policy.validate_remote)
        p = _apply_provisioning(provisioning)
        print(f"✅  Remote config loaded from license server "
              f"({n} setting(s), {p} credential(s) provisioned).")
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
            """Fail CLOSED, and never from the URL.

            Two things were wrong here, fixed in order of when they were found.

            First, this used to `return True` whenever DASHBOARD_TOKEN was
            unset, so one missing environment variable silently published
            /api/status — balance, open position, trade journal — to anyone
            who knew the URL. A missing secret is a misconfiguration, not
            permission.

            Second, and the reason for the session layer: it accepted
            `?token=`. A credential in a URL is a credential in the browser
            history, in every proxy and access log along the way, in the
            Referer header of any outbound link, and in any screenshot of the
            address bar. Render logs request paths. Rotating a token that has
            already been copied into all of those is not a rotation.

            Query tokens are now REFUSED rather than ignored, because a
            request carrying one has already leaked it and the operator needs
            to find out from a failure rather than from a log review.

            What is accepted:
              Authorization: Bearer <DASHBOARD_TOKEN>   scripts and ops
              Cookie: apex_session=<id>                 browsers, after login
            """
            if not token:
                return False
            if "token" in parse_qs(urlparse(self.path).query):
                return False
            supplied = (self.headers.get("Authorization") or
                        "").removeprefix("Bearer ").strip()
            if supplied:
                return http_session.verify_bootstrap(supplied, token)
            return http_session.valid(
                http_session.parse_cookie(self.headers.get("Cookie") or ""))

        def _used_query_token(self):
            return "token" in parse_qs(urlparse(self.path).query)

        def _telegram_identity(self):
            """The verified Telegram user, or None. Never from the query string.

            The Mini App sent `/api/app/data?init=<initData>`. initData IS the
            credential — it is Telegram's HMAC over the user's identity, and
            anyone holding a fresh one can act as that user until it ages out.
            Putting it in a URL put it in exactly the places a URL goes:
            proxy and access logs, the browser's own history, Referer headers.

            It now travels in a header. A query `init` is REFUSED rather than
            ignored, for the same reason as the dashboard token: a request
            carrying one has already leaked it.

            Accepted:
                Authorization: Telegram <initData>
                X-Telegram-Init-Data: <initData>

            The identity returned is the one webapp.validate recovered from
            the signed payload. No caller may pass a user id alongside it —
            that is the whole point of verifying a signature.
            """
            from apex import webapp
            if "init" in parse_qs(urlparse(self.path).query):
                return None
            if not http_security.MINIAPP.check(http_security.client_key(self)):
                return None
            raw = (self.headers.get("X-Telegram-Init-Data") or "").strip()
            if not raw:
                auth = (self.headers.get("Authorization") or "").strip()
                if auth.lower().startswith("telegram "):
                    raw = auth[9:].strip()
            if not raw:
                return None
            tg_user = webapp.validate(raw, cfg.TELEGRAM_BOT_TOKEN or "")
            if not tg_user or not tg_user.get("id"):
                return None
            return tg_user

        def _used_query_init(self):
            return "init" in parse_qs(urlparse(self.path).query)

        def _telegram_denied(self):
            """One refusal shape for every Mini App route."""
            if self._used_query_init():
                return self._json(401, {
                    "error": "unauthorized",
                    "code": "INIT_DATA_IN_URL",
                    "detail": ("Telegram initData must be sent as the header "
                               "'Authorization: Telegram <initData>'. A URL "
                               "leaks it into history and proxy logs.")})
            return self._json(401, {"error": "unauthorized",
                                    "code": "TELEGRAM_AUTH_FAILED"})

        def _json(self, status, obj, cache=None, cache_key=None):
            """A JSON reply with no cache and an explicit length.

            The Mini App polls; a cached 200 would show a client a stale
            account long after it changed, which is the one thing a terminal
            must never do.
            """
            if cache is not None and status == 200 and cache_key is not None:
                try:
                    cache(cache_key, obj)
                except Exception:
                    pass
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for h, v in http_security.headers(
                    https=http_security.is_https(self.headers)).items():
                self.send_header(h, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _reply(self, status, obj, extra_headers=()):
            """JSON with the security headers and any extra header (Set-Cookie)."""
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for h, v in http_security.headers(
                    https=http_security.is_https(self.headers)).items():
                self.send_header(h, v)
            for h, v in extra_headers:
                self.send_header(h, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, status, markup):
            body = markup.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            for h, v in http_security.headers(
                    https=http_security.is_https(self.headers)).items():
                self.send_header(h, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _deny(self):
            """401 when the token is wrong, 503 when there is no token at all."""
            if not token:
                body = (b"503 - dashboard disabled. DASHBOARD_TOKEN is not set "
                        b"on this deployment, so these endpoints serve nothing.")
                self.send_response(503)
            elif self._used_query_token():
                # Say plainly why this failed. Silently ignoring the parameter
                # would leave an operator retrying a URL that cannot ever work.
                body = (b"401 - unauthorized. A token in the URL is refused: it "
                        b"leaks into browser history, proxy logs and Referer "
                        b"headers. POST it to /api/session, or send "
                        b"'Authorization: Bearer <token>'.")
                self.send_response(401)
            else:
                body = (b"401 - unauthorized. POST {\"token\":\"...\"} to "
                        b"/api/session, or send 'Authorization: Bearer <token>'.")
                self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            # ── Dashboard login: the ONLY place the operator token is
            # presented, and it arrives in a body rather than a URL. What goes
            # back is a short-lived session id in an HttpOnly cookie.
            if self.path == "/api/session":
                if not token:
                    return self._deny()
                if not http_security.LOGIN.check(http_security.client_key(self)):
                    # Generic on purpose: a different message for "too many
                    # attempts" than for "wrong token" tells someone guessing
                    # that they had otherwise reached the right endpoint.
                    return self._reply(429, {"error": "Too many attempts. Try again shortly."})
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(min(length, 8192))
                    supplied = (json.loads(raw or b"{}") or {}).get("token") or ""
                except Exception:
                    supplied = ""
                if not http_session.verify_bootstrap(supplied, token):
                    # No detail. "wrong token" and "malformed body" look the
                    # same to the caller, and neither is written to the log.
                    return self._reply(401, {"error": "Authorization failed."})
                sid = http_session.create()
                return self._reply(
                    200, {"ok": True, "expiresInSeconds": http_session.TTL_S},
                    [("Set-Cookie", http_session.set_cookie_value(sid, self.headers))])

            if self.path == "/api/session/logout":
                http_session.revoke(
                    http_session.parse_cookie(self.headers.get("Cookie") or ""))
                return self._reply(
                    200, {"ok": True},
                    [("Set-Cookie", http_session.clear_cookie_value(self.headers))])

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
            elif self.path == "/api/voice/say":
                # Same turn, answered as PLAIN TEXT rather than JSON.
                #
                # This exists to make the shortcut three actions instead of
                # five. With JSON the phone needs a Get Dictionary Value step
                # and then a variable hand-wired into Speak Text — and hand-
                # wiring a variable is precisely what kept breaking: the field
                # silently lost its link and the shortcut spoke nothing. With
                # plain text, Shortcuts chains Speak Text to the response on
                # its own and there is nothing to wire.
                #
                # Apple closed the other door: unsigned .shortcut files can no
                # longer be imported at all, so a ready-built file cannot be
                # handed over and the shortcut has to be assembled by hand.
                # Then it must be as short as it can possibly be.
                from apex import voice_api
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(min(length, 64_000)).decode("utf-8", "replace")
                hdr_tok = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
                try:
                    req = json.loads(raw or "{}")
                    if not isinstance(req, dict):
                        raise ValueError("not an object")
                except Exception:
                    req = {}
                if req:
                    tok, said = req.get("token") or hdr_tok, req.get("text")
                else:
                    # The body was not JSON, so it IS the question, and the key
                    # came in the header. This is the shape that needs no
                    # variable picked by hand: Shortcuts fills a raw request
                    # body with the previous action's output on its own, while
                    # a JSON field has to be wired, and wiring it is what kept
                    # silently coming undone.
                    tok, said = hdr_tok, raw
                out = voice_api.ask(tok, said)
                payload = str(out.get("reply") or "").encode("utf-8")
                # 200 whatever happened. A non-2xx makes Shortcuts raise
                # instead of speaking, so a refusal the client could act on —
                # "that link is not valid any more" — would be swallowed into
                # a generic error banner.
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/api/voice":
                # The phone channel. Auth is the per-client voice token in the
                # body — deliberately NOT the operator DASHBOARD_TOKEN, which
                # reads every account, and not Telegram initData, which a
                # Shortcut cannot produce.
                from apex import voice_api
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(min(length, 64_000)).decode("utf-8", "replace")
                try:
                    req = json.loads(raw or "{}")
                except Exception:
                    req = {}
                tok = req.get("token") or (
                    self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
                if req.get("confirmId"):
                    out = voice_api.confirm(tok, req.get("confirmId"),
                                            bool(req.get("agreed", True)))
                else:
                    out = voice_api.ask(tok, req.get("text"))
                payload = json.dumps(out).encode()
                self.send_response(int(out.get("status", 200)))
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            # /api/mt/sync is gone. It handed the request body to the
            # MetaTrader bridge — an execution path for a broker this build no
            # longer supports, reachable over HTTP and bypassing the BROKER
            # allowlist that config.py enforces at import. One production
            # trading path means one, including the ones that answer on a
            # different route.
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
            # ── /go — the ad-click bridge ────────────────────────────────
            # An ad cannot link straight into Telegram and keep its click
            # identifier: the deep-link payload is 64 characters of
            # [A-Za-z0-9_-] and a Meta click id is neither short enough nor
            # made of those. So the click lands here first, in a browser,
            # where the identifier still exists. We store it under a token
            # that does fit, and send the visitor on.
            #
            # This must not fail closed. A visitor who clicked a paid ad gets
            # redirected whatever happens to the store — losing the
            # measurement costs a data point, losing the visitor costs a sale.
            if self.path == "/go" or self.path.startswith("/go?"):
                # Aliased, and every local here is prefixed. do_GET is nested
                # inside _start_dashboard_server and closes over `urlparse`,
                # `parse_qs` and `token` from it — binding any of those names
                # here would make them local to the WHOLE method and break
                # every branch above that reads them.
                from urllib.parse import urlparse as _go_urlparse
                from urllib.parse import parse_qs as _go_parse_qs
                from urllib.parse import quote as _go_quote
                from apex import attribution as _go_attr
                _go_handle = cfg.TELEGRAM_BOT_USERNAME
                _go_target = f"https://t.me/{_go_handle}"
                try:
                    if not http_security.GO.check(http_security.client_key(self)):
                        # Still a redirect: a rate-limited visitor is far more
                        # likely to be a shared IP than an attack, and the
                        # trade-off of a missed click record beats a lost sale.
                        raise RuntimeError("rate limited")
                    _go_q = _go_parse_qs(_go_urlparse(self.path).query)
                    _go_one = lambda k: (_go_q.get(k) or [""])[0]
                    _go_token = _go_attr.record_click(
                        fbclid=_go_one("fbclid"),
                        fbp=_go_one("fbp"),
                        utm={k: _go_one(k) for k in
                             ("utm_source", "utm_medium", "utm_campaign",
                              "utm_content", "utm_term", "ref")},
                        ip=http_security.client_key(self),
                        user_agent=self.headers.get("User-Agent") or "",
                        url=f"https://{self.headers.get('Host') or ''}{self.path}",
                    )
                    _go_target = (f"https://t.me/{_go_handle}"
                                  f"?start={_go_quote(_go_token, safe='')}")
                except Exception as e:
                    print(f"[Attribution] /go fell through to a plain "
                          f"redirect: {e}")
                self.send_response(302)
                self.send_header("Location", _go_target)
                # A click record is per-visitor and short-lived; a cache in
                # front of this would hand one visitor's token to the next.
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                return
            # The voice endpoint is POST-only. Without this, a GET fell through
            # to the dashboard gate and answered "503 — dashboard disabled,
            # DASHBOARD_TOKEN is not set", which is true of the dashboard and
            # says nothing about the endpoint that was actually asked for. It
            # also wrote no log line, so a client whose shortcut was sending
            # GET looked identical to one whose request never arrived at all —
            # two very different problems wearing the same silence.
            if self.path.startswith("/api/voice"):
                print("[Voice] GET on /api/voice — this endpoint is POST-only")
                payload = json.dumps({
                    "ok": False, "status": 405,
                    "reply": "This address only accepts POST. In your shortcut, "
                             "open Get Contents of URL and set Method to POST.",
                }).encode()
                self.send_response(405)
                self.send_header("Content-Type", "application/json")
                self.send_header("Allow", "POST")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
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
            # The chart library, served from here instead of unpkg. A
            # third-party CDN round-trip was on the critical path of every
            # cold open: nothing could be drawn until ~160KB arrived from
            # somebody else's host. Immutable, so the browser fetches it once.
            if self.path.startswith("/static/lightweight-charts.js"):
                import os as _os
                _lib = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     "static", "lightweight-charts.js")
                try:
                    with open(_lib, "rb") as fh:
                        payload = fh.read()
                except OSError:
                    self.send_response(404); self.end_headers(); return
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
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
                tg_user = self._telegram_identity()
                if not tg_user:
                    self._telegram_denied()
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
                    # The panel's own view: a rolling window, medium impact
                    # included. `upcoming()`/`today()` answer the trading
                    # guard's question (is a HIGH-impact release near?) and a
                    # normal week holds ~8 of those against ~90 other releases,
                    # so a panel built on them is empty on most days.
                    news_feed = news_mod.feed() or []
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
                        # badge() takes BOTH values. resolve() returns
                        # (mode, source), and the source is what turns
                        # "🔴 LIVE" into "🔴 LIVE (unconfirmed)" when the
                        # answer came from our own stored flag rather than
                        # from the broker just now. Passing only the mode
                        # threw that distinction away and rendered a stale
                        # reading as a fact the client can act on — which is
                        # precisely the case the source field exists for.
                        "account": (lambda _m: {
                            "mode": _m[0], "source": _m[1],
                            "badge": _account_mode.badge(_m[0], _m[1]),
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
                        "newsFeed": news_feed,
                        # Kept so a page still cached from before this change
                        # keeps rendering something rather than going blank.
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
            # ── Markets snapshot ────────────────────────────────────
            # Every tradeable instrument with its close and change on the day.
            # The snapshot is built once and shared: eight daily-bar fetches
            # per client would spend cTrader's whole historical allowance on
            # a handful of people reading the same eight numbers. Scoped to an
            # authenticated client anyway — the universe is not public, and an
            # unauthenticated caller must not be able to make us poll a broker.
            # ── Risk Centre ─────────────────────────────────────────
            # Presentation only. Every number is read from the risk engine's
            # own published state — the screen computes no limit, applies no
            # limit, and decides nothing. gates.authorize_order remains the
            # only thing that can permit an order, and strategies.should_stop
            # is never called from here: it advances the peak-balance and
            # daily-reset state as a side effect, so drawing a badge with it
            # would move the circuit breakers.
            if self.path.startswith("/api/app/risk"):
                from apex import user_loop, user_store, strategies as _st
                from apex import forex as _fx, config as _cfg, ui_state as _ui
                tg_user = self._telegram_identity()
                if not tg_user:
                    self._telegram_denied()
                    return
                chat_id = str(tg_user["id"])
                try:
                    dash = user_loop.get_dash(chat_id) or {}
                    u = user_store.load(chat_id) or {}
                except Exception as e:
                    self._json(200, {"available": False,
                                     "reason": "RISK_STATE_UNAVAILABLE",
                                     "detail": str(e)[:120]})
                    return

                guard = dash.get("riskGuard")
                state, reasons = _ui.risk_state(chat_id)
                sess = {}
                try:
                    sess = _st.get_session(chat_id) or {}
                except Exception as e:
                    print(f"[Risk] session unreadable for {chat_id}: {e}")

                positions = [p for p in (dash.get("positions") or []) if p.get("symbol")]
                exposure = []
                for pos in positions:
                    try:
                        bias = _fx.usd_exposure(pos["symbol"], pos.get("side") or "")
                    except Exception:
                        bias = 0
                    exposure.append({
                        "symbol": pos["symbol"],
                        "side": pos.get("side"),
                        "usdBias": bias,
                        "pnlUsd": pos.get("pnlUsd"),
                    })

                stats = dash.get("stats") or {}
                self._json(200, {
                    "available": True,
                    # UNKNOWN is a third answer and never renders as OK.
                    "engine": state,
                    "halted": bool((guard or {}).get("halted")),
                    "reasons": reasons or list((guard or {}).get("reasons") or []),
                    "guardSeen": bool(guard),
                    "limits": {
                        "riskPerTradePct": round(float(
                            u.get("risk_per_trade") or getattr(_cfg, "RISK_PER_TRADE", 0)) * 100, 3),
                        "maxDailyLossPct": float(getattr(_cfg, "MAX_DAILY_LOSS_PCT", 3.0)),
                        "maxDrawdownPct": float(getattr(_cfg, "MAX_DD_PCT", 20.0)),
                    },
                    "today": {
                        "pnl": sess.get("dailyPnL"),
                        "pnlPct": sess.get("dailyPnLPct"),
                        "trades": sess.get("dailyTrades"),
                    },
                    "drawdownPct": stats.get("maxDrawdownPct"),
                    "peakBalance": sess.get("peakBalance"),
                    "openPositions": len(positions),
                    "exposure": exposure,
                })
                return
            if self.path.startswith("/api/app/markets"):
                from apex import user_loop, user_store, markets as _mk
                tg_user = self._telegram_identity()
                if not tg_user:
                    self._telegram_denied()
                    return
                chat_id = str(tg_user["id"])
                try:
                    u = user_store.load(chat_id) or {}
                    br, _uc = user_loop._make_broker(u)
                except Exception as e:
                    # No broker, no prices. Said plainly rather than as an
                    # empty list, which reads as "the market has nothing".
                    self._json(200, {"rows": [], "available": False,
                                     "reason": "MARKET_DATA_UNAVAILABLE",
                                     "detail": str(e)[:120]})
                    return
                snap = _mk.snapshot(br)
                forex, metals = _mk.universe()
                self._json(200, {"rows": snap["rows"], "asOf": snap["asOf"],
                                 "stale": bool(snap.get("stale")),
                                 "forex": forex, "metals": metals,
                                 "available": True})
                return
            if self.path.startswith("/api/app/tick"):
                from apex import webapp, user_loop, user_store
                from apex import forex as fx_mod
                from apex import miniapp_cache as _mc
                qs = parse_qs(urlparse(self.path).query)
                tg_user = self._telegram_identity()
                if not tg_user:
                    self._telegram_denied()
                    return
                chat_id = str(tg_user["id"])
                # Serve a very recent answer rather than asking the broker again.
                # Every read below rides ONE pooled cTrader socket behind a lock,
                # so two overlapping polls do not go twice as fast — they queue,
                # and /api/app/data queues behind them. That is what turned a
                # 1s tick into "market data unavailable".
                _hit = _mc.get_tick(chat_id)
                if _hit is not None:
                    self._json(200, _hit)
                    return
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
                    # EVERY open position, not just the focused symbol. The
                    # account can hold up to `maxpos` at once and the terminal
                    # was showing one of them, so a client with two trades open
                    # could see only the one Auto-Pilot happened to be watching.
                    # One RPC returns them all; pricing is what costs, so only
                    # the first few are priced live per tick.
                    all_pos = []
                    if not paper:
                        # WHICH positions exist changes on a trade, not on a
                        # tick. Their PRICES change constantly. Re-listing them
                        # every poll was a whole extra round-trip for an answer
                        # that is almost always identical.
                        all_pos = _mc.get_positions(chat_id)
                        if all_pos is None:
                            try:
                                all_pos = list(br.get_all_positions() or [])
                            except Exception:
                                all_pos = []
                            _mc.put_positions(chat_id, all_pos)
                        _focus = next((p for p in all_pos
                                       if str(p.get("symbol", "")).replace("_", "").upper()
                                       == str(sym).replace("_", "").upper()), None)
                        if _focus:
                            pos = _focus

                    def _price_for(psym):
                        if str(psym).replace("_", "").upper() == str(sym).replace("_", "").upper():
                            return price
                        try:
                            b, a = br.get_bid_ask(psym)
                            return (float(b) + float(a)) / 2.0
                        except Exception:
                            return None

                    def _pnl(p, px_):
                        if not px_ or not p.get("entryPrice"):
                            return None, None
                        d = 1 if p.get("side") == "BUY" else -1
                        psym = p.get("symbol") or sym
                        pips = round(fx_mod.to_pips(
                            (px_ - float(p["entryPrice"])) * d, psym, px_), 1)
                        u = p.get("units") or p.get("quantity") or 0
                        usd = (round(fx_mod.pnl_usd(p["side"], float(p["entryPrice"]),
                                                    px_, u, psym), 2) if u else None)
                        return pips, usd

                    PRICE_BUDGET = 4          # bounded: this runs once a second
                    positions_out, priced = [], 0
                    for p in all_pos:
                        psym = p.get("symbol") or sym
                        px_ = None
                        if priced < PRICE_BUDGET:
                            px_ = _price_for(psym); priced += 1
                        pp, pu = _pnl(p, px_)
                        positions_out.append({
                            "symbol": psym, "side": p.get("side"),
                            "entryPrice": p.get("entryPrice"),
                            "stopLoss": p.get("stopLoss"), "takeProfit": p.get("takeProfit"),
                            "positionId": p.get("positionId"),
                            "currentPrice": px_, "pnlPips": pp, "pnlUsd": pu,
                            "focused": str(psym).replace("_", "").upper()
                                       == str(sym).replace("_", "").upper()})

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
                        # Balance only moves when a trade CLOSES. Floating P&L
                        # is what moves tick to tick, and that is computed from
                        # price below — so this does not need a round-trip per
                        # poll. The log showed it firing every 2-3 seconds.
                        _bal = _mc.get_balance(chat_id)
                        if _bal is None:
                            try:
                                _bal = br.get_balance()
                                _mc.put_balance(chat_id, _bal)
                            except Exception:
                                _bal = None
                        if _bal is not None:
                            balance = _bal
                    # Floating is the sum across EVERY position we could price,
                    # not just the focused one — otherwise equity silently
                    # ignores the other open trade.
                    if positions_out:
                        floating = float(sum(p["pnlUsd"] or 0 for p in positions_out))
                    else:
                        floating = float(pnl_usd or 0)

                    self._json(200, {
                        "symbol": sym, "price": price, "bid": bid, "ask": ask,
                        # Server time, so the page can tell a still price from a
                        # stopped feed instead of showing the last one as live.
                        "ts": int(time.time()),
                        "balance": balance,
                        "equityLive": (float(balance) + floating) if balance is not None else None,
                        "floatingPnl": floating,
                        "positions": positions_out,
                        "openCount": len(positions_out) or (1 if pos else 0),
                        "position": (None if not pos else {
                            "side": pos.get("side"),
                            "entryPrice": pos.get("entryPrice"),
                            "stopLoss": pos.get("stopLoss") or pos.get("sl"),
                            "takeProfit": pos.get("takeProfit") or pos.get("tp"),
                            "pnlPips": pnl_pips, "pnlUsd": pnl_usd}),
                    }, cache=_mc.put_tick, cache_key=chat_id)
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
                tg_user = self._telegram_identity()
                if not tg_user:
                    self._telegram_denied()
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
                # A browser asking for the dashboard PAGE gets a login form;
                # only the data APIs get a bare 401. Returning 401 for the page
                # left the operator with a dead end and no way to present the
                # token except by putting it back in the URL.
                wants_page = not self.path.startswith("/api/")
                if wants_page and token and not self._used_query_token():
                    self._html(200, render_login())
                else:
                    self._deny()
                return
            if self.path.startswith("/api/status"):
                # No Access-Control-Allow-Origin. This endpoint is
                # authenticated and returns the live account; it carried "*",
                # which invites any origin to read it. Same-origin only, so
                # there is no CORS header to get wrong.
                self._json(200, {**dash, "tickCount": tick_count, "candles": []})
            elif self.path.startswith("/api/candles"):
                self._json(200, {"candles": dash.get("candles", []),
                                 "symbol": dash["currentSymbol"],
                                 "timeframe": cfg.TIMEFRAME})
            else:
                self._html(200, render_dashboard({**dash, "tickCount": tick_count}))

    # THREADING, not HTTPServer. The plain one handles exactly one request at a
    # time, so a single slow call froze the whole HTTP surface behind it: the
    # Mini App asks for /app, then /api/app/data (broker connect, 150 candles,
    # stats, news, journal), and every tick, the dashboard and the OAuth
    # callback queued behind that one response. The terminal appeared to load
    # slowly because it was waiting in line behind itself.
    #
    # The reads it serves are already safe to overlap: the cTrader socket has
    # its own lock, user_store writes are atomic, and the Mini App routes are
    # read-only.
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True      # a hung request must not block shutdown
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

    # Configuration that would be unsafe in production is refused HERE, before
    # anything can arrive. Checking it at the point of use would mean the
    # service starts, looks healthy, and only reveals the problem when a real
    # client's OAuth callback is already in flight — at which point refusing
    # is a broken onboarding rather than a caught misconfiguration.
    from apex import ctrader_oauth as _oauth
    _oauth.assert_safe_config()

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
