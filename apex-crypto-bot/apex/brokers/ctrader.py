"""cTrader Open API connector — free, international, works with any cTrader broker.

cTrader is the sole broker. cTrader Open API is free for anyone with a cTrader
account and is offered by many international brokers (IC Markets, Pepperstone,
FxPro, ...), so a single integration covers clients worldwide.

Protocol reality: cTrader Open API is NOT REST. It is Protocol-Buffers messages
over a persistent TLS socket on port 5035. The official Python SDK uses Twisted
(async), which does not fit this bot's synchronous per-user-thread model, so this
module implements a small SYNCHRONOUS request/response client over a raw TLS
socket, reusing only the protobuf message definitions from `ctrader-open-api`.

Auth is two-stage:
    1. Application auth   — ProtoOAApplicationAuthReq(clientId, clientSecret)
    2. Account auth       — ProtoOAAccountAuthReq(ctidTraderAccountId, accessToken)
The accessToken comes from the OAuth2 web flow (see oauth.py / the Telegram
onboarding). clientId/clientSecret identify YOUR registered Open API application
(one per business, created once at openapi.ctrader.com/apps).

Setup (per business, once):
    CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET   (from openapi.ctrader.com/apps)
Setup (per client, via OAuth):
    access_token, ctid_trader_account_id, env (demo|live)

IMPORTANT: live order placement (volume scaling, fill handling) must be validated
against a real cTrader demo account before being used with real money. Paper mode
uses cTrader for DATA only and simulates fills locally, so it is safe to run now.
"""
import os
import ssl
import time
import socket
import struct
import threading

import requests

from apex import config as cfg

# Protobuf message definitions come from the official package. We use ONLY the
# generated message classes — not the Twisted-based Client.
try:
    from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import (
        ProtoMessage, ProtoHeartbeatEvent, ProtoErrorRes,
    )
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAApplicationAuthReq, ProtoOAApplicationAuthRes,
        ProtoOAAccountAuthReq, ProtoOAAccountAuthRes,
        ProtoOAGetAccountListByAccessTokenReq, ProtoOAGetAccountListByAccessTokenRes,
        ProtoOATraderReq, ProtoOATraderRes,
        ProtoOASymbolsListReq, ProtoOASymbolsListRes,
        ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes,
        ProtoOASubscribeSpotsReq, ProtoOASpotEvent,
        ProtoOANewOrderReq, ProtoOAExecutionEvent,
        ProtoOAReconcileReq, ProtoOAReconcileRes,
        ProtoOAClosePositionReq, ProtoOAErrorRes, ProtoOAOrderErrorEvent,
        ProtoOASymbolByIdReq, ProtoOASymbolByIdRes, ProtoOAAmendPositionSLTPReq,
    )
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
        ProtoOATrendbarPeriod, ProtoOAOrderType, ProtoOATradeSide,
    )
    _SDK_OK = True
    _SDK_ERR = ""
except Exception as e:  # pragma: no cover - import guard
    _SDK_OK = False
    _SDK_ERR = str(e)

# Live + demo proxy endpoints (protobuf, port 5035, TLS required).
_HOST = {"live": "live.ctraderapi.com", "demo": "demo.ctraderapi.com"}
_PORT = 5035

# Underscore/slash notation "EUR_USD" / "EUR/USD" → cTrader "EURUSD".
def _to_ct_symbol(sym: str) -> str:
    return (sym or "").replace("_", "").replace("/", "").upper()


def _period():
    return {
        "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
        "1h": "H1", "4h": "H4", "1d": "D1",
    }


# ── OAuth2 web flow (REST — simple requests) ─────────────────────────────────
# Used by the server-side callback + Telegram onboarding, not by the trading loop.

_OAUTH_AUTH = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
_OAUTH_TOKEN = "https://openapi.ctrader.com/apps/token"


def authorize_url(redirect_uri: str, state: str, scope: str = None) -> str:
    """Link the client opens to grant access. `state` carries the Telegram id
    (signed) so the callback knows which user authorized. Scope defaults to
    cfg.CTRADER_SCOPE — use "accounts" before KYC (paper mode), "trading" once
    the app is Active (live orders)."""
    from urllib.parse import urlencode
    q = urlencode({
        "client_id": cfg.CTRADER_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": scope or getattr(cfg, "CTRADER_SCOPE", "trading"),
        "state": state,
        "product": "web",
    })
    return f"{_OAUTH_AUTH}?{q}"


def _token_request(params: dict) -> dict:
    """cTrader's /apps/token reads QUERY-STRING params (not a form body) and
    returns JSON with an in-band errorCode even on HTTP 200. Send params in the
    query string and surface errorCode as an exception."""
    r = requests.get(_OAUTH_TOKEN, params=params,
                     headers={"Accept": "application/json"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("errorCode"):
        raise RuntimeError(f"cTrader token error: {data.get('errorCode')} — {data.get('description', '')}")
    return data


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Authorization code → {accessToken, refreshToken, expiresIn}."""
    return _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": cfg.CTRADER_CLIENT_ID,
        "client_secret": cfg.CTRADER_CLIENT_SECRET,
    })


def refresh_access_token(refresh_token: str) -> dict:
    """Refresh an expired access token (cTrader tokens last ~30 days)."""
    return _token_request({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": cfg.CTRADER_CLIENT_ID,
        "client_secret": cfg.CTRADER_CLIENT_SECRET,
    })


# ── Synchronous protobuf client ──────────────────────────────────────────────

class _Conn:
    """One synchronous, authenticated TLS connection to a cTrader proxy.

    Send a request, block until the matching response (by clientMsgId) arrives.
    Heartbeats and unsolicited events are drained transparently. Not safe for
    concurrent use from multiple threads — guard with the broker-level lock.
    """

    def __init__(self, env, access_token, ctid):
        self.env = "live" if str(env).lower() == "live" else "demo"
        self.access_token = access_token
        self.ctid = int(ctid)
        self._sock = None
        self._buf = b""
        self._mid = 0
        self._last_io = 0.0
        self._lock = threading.Lock()

    # -- framing --------------------------------------------------------------
    def _send(self, msg):
        self._mid += 1
        cid = str(self._mid)
        pm = ProtoMessage()
        pm.payloadType = msg.payloadType
        pm.payload = msg.SerializeToString()
        pm.clientMsgId = cid
        data = pm.SerializeToString()
        self._sock.sendall(struct.pack(">I", len(data)) + data)
        self._last_io = time.time()
        return cid

    def _read_frame(self, timeout=15):
        self._sock.settimeout(timeout)
        while len(self._buf) < 4:
            self._buf += self._recv_some()
        (length,) = struct.unpack(">I", self._buf[:4])
        self._buf = self._buf[4:]
        while len(self._buf) < length:
            self._buf += self._recv_some()
        raw, self._buf = self._buf[:length], self._buf[length:]
        pm = ProtoMessage()
        pm.ParseFromString(raw)
        return pm

    def _recv_some(self):
        chunk = self._sock.recv(8192)
        if not chunk:
            raise ConnectionError("cTrader connection closed")
        return chunk

    def _await(self, want_client_id, res_cls, timeout=15):
        """Read frames until the response for want_client_id arrives. Raises on
        ProtoOAErrorRes. Transparently skips heartbeats and spot/exec events the
        caller did not ask for (caller handles those explicitly when needed)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            pm = self._read_frame(timeout=max(1, int(deadline - time.time())))
            if pm.payloadType == ProtoHeartbeatEvent().payloadType:
                # Reply in kind — the proxy drops connections that stay silent.
                try:
                    hb = ProtoMessage()
                    hb.payloadType = ProtoHeartbeatEvent().payloadType
                    hb.payload = ProtoHeartbeatEvent().SerializeToString()
                    self._sock.sendall(struct.pack(">I", len(hb.SerializeToString())) + hb.SerializeToString())
                except Exception:
                    pass
                continue
            if pm.payloadType == ProtoOAErrorRes().payloadType:
                err = ProtoOAErrorRes()
                err.ParseFromString(pm.payload)
                raise RuntimeError(f"cTrader error: {err.errorCode} {err.description}")
            # Common-layer error (bad app credentials, throttling, protocol issue).
            # Without this branch the frame is skipped and the server's follow-up
            # close surfaces as a bare "connection closed" with no cause.
            if pm.payloadType == ProtoErrorRes().payloadType:
                err = ProtoErrorRes()
                err.ParseFromString(pm.payload)
                raise RuntimeError(f"cTrader error: {err.errorCode} {err.description}")
            # Order rejections arrive as a DEDICATED event type — skipping it
            # leaves the caller waiting for an ExecutionEvent until timeout.
            if pm.payloadType == ProtoOAOrderErrorEvent().payloadType:
                err = ProtoOAOrderErrorEvent()
                err.ParseFromString(pm.payload)
                raise RuntimeError(f"cTrader order error: {err.errorCode} {err.description}")
            if want_client_id and pm.clientMsgId and pm.clientMsgId != want_client_id:
                continue
            if pm.payloadType == res_cls().payloadType:
                out = res_cls()
                out.ParseFromString(pm.payload)
                return out
        raise TimeoutError(f"cTrader: no response for {res_cls.__name__}")

    def _request(self, req, res_cls, timeout=15):
        with self._lock:
            cid = self._send(req)
            return self._await(cid, res_cls, timeout)

    # -- lifecycle ------------------------------------------------------------
    def connect(self):
        if not _SDK_OK:
            raise RuntimeError(f"ctrader-open-api not installed: {_SDK_ERR}")
        ctx = ssl.create_default_context()
        raw = socket.create_connection((_HOST[self.env], _PORT), timeout=15)
        self._sock = ctx.wrap_socket(raw, server_hostname=_HOST[self.env])
        # 1. application auth
        try:
            app = ProtoOAApplicationAuthReq()
            app.clientId = cfg.CTRADER_CLIENT_ID
            app.clientSecret = cfg.CTRADER_CLIENT_SECRET
            self._request(app, ProtoOAApplicationAuthRes)
        except Exception as e:
            self.close()
            raise RuntimeError(f"app auth failed ({self.env}): {e}") from e
        # 2. account auth
        try:
            acc = ProtoOAAccountAuthReq()
            acc.ctidTraderAccountId = self.ctid
            acc.accessToken = self.access_token
            self._request(acc, ProtoOAAccountAuthRes)
        except Exception as e:
            self.close()
            raise RuntimeError(f"account auth failed ({self.env} #{self.ctid}): {e}") from e
        return self

    def close(self):
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None


# Connection pool keyed by (env, ctid) — one persistent socket per account.
_conns: dict = {}
_pool_lock = threading.Lock()


def _conn_for(env, access_token, ctid) -> _Conn:
    key = (str(env).lower(), int(ctid))
    with _pool_lock:
        c = _conns.get(key)
        if c and c._sock is not None:
            return c
        c = _Conn(env, access_token, ctid).connect()
        _conns[key] = c
        return c


def _drop_conn(env, ctid):
    key = (str(env).lower(), int(ctid))
    with _pool_lock:
        c = _conns.pop(key, None)
    if c:
        c.close()


# ── Per-user broker class ────────────────────────────────────────────────────

class CtraderBroker:
    """cTrader connector with per-user config (token + account id + env).

    Mirrors the OandaBroker interface so user_loop / bot.py can use it unchanged.
    Symbol id and price digits are resolved once and cached per connection.
    """

    def __init__(self, user_cfg):
        self._c = user_cfg
        self._sym_id: dict = {}     # "EURUSD" -> symbolId
        self._sym_digits: dict = {}  # symbolId -> price digits
        self._spot_cache: dict = {}  # symbolId -> (bid, ask, ts)

    # -- helpers --------------------------------------------------------------
    def _conn(self):
        return _conn_for(
            getattr(self._c, "CTRADER_ENV", "demo"),
            self._c.CTRADER_ACCESS_TOKEN,
            self._c.CTRADER_ACCOUNT_ID,
        )

    def _ctid(self):
        return int(self._c.CTRADER_ACCOUNT_ID)

    def _rpc(self, req, res_cls, timeout=15):
        """Read-only request with one transparent reconnect. The proxy closes
        idle sockets and the pool can't tell a dead socket from a live one —
        without this, one idle period kills every later call with
        'connection closed'. Order placement must NOT use this (a blind retry
        could double-fill); orders ride the connection get_candles just warmed."""
        try:
            return self._conn()._request(req, res_cls, timeout)
        except (ConnectionError, OSError, TimeoutError):
            _drop_conn(getattr(self._c, "CTRADER_ENV", "demo"), self._ctid())
            return self._conn()._request(req, res_cls, timeout)

    def _load_symbols(self):
        if self._sym_id:
            return
        req = ProtoOASymbolsListReq()
        req.ctidTraderAccountId = self._ctid()
        res = self._rpc(req, ProtoOASymbolsListRes)
        for s in res.symbol:
            self._sym_id[s.symbolName.replace("/", "").replace("_", "").upper()] = s.symbolId
            # symbol digits live on the detailed symbol; default 5 (3 for JPY)
        # store nothing else here — digits resolved lazily from name

    def _vol_rules(self, sid):
        """(minVolume, stepVolume) in hundredths-of-a-unit, from the symbol's
        full details. FX is 0.01 lots = 100k hundredths, but gold is 1 oz and
        indices 1 contract — a hard-coded FX step breaks every other class.
        Also caches the symbol's price DIGITS (used to round SL/TP)."""
        if not hasattr(self, "_vol_cache"):
            self._vol_cache = {}
        if not hasattr(self, "_digits_cache"):
            self._digits_cache = {}
        if sid in self._vol_cache:
            return self._vol_cache[sid]
        req = ProtoOASymbolByIdReq()
        req.ctidTraderAccountId = self._ctid()
        req.symbolId.append(sid)
        res = self._rpc(req, ProtoOASymbolByIdRes)
        sym = res.symbol[0] if res.symbol else None
        mn = int(getattr(sym, "minVolume", 0) or 0) or 100_000
        st = int(getattr(sym, "stepVolume", 0) or 0) or mn
        dg = int(getattr(sym, "digits", 0) or 0)
        self._vol_cache[sid] = (mn, st)
        if dg:
            self._digits_cache[sid] = dg
        return mn, st

    def _symbol_id(self, instrument):
        self._load_symbols()
        name = _to_ct_symbol(instrument or self._c.SYMBOL)
        if name not in self._sym_id:
            raise ValueError(f"cTrader: symbol {name} not offered by this account")
        return self._sym_id[name]

    def _digits(self, instrument):
        """Price decimal places for rounding SL/TP, taken from the broker's
        symbol details. A hard-coded 5 makes cTrader reject the SL/TP amend on
        instruments with fewer digits (BTCUSD is 2) as 'invalid precision' —
        the position then reads back unprotected and gets closed 'for safety',
        so EVERY crypto trade opens and instantly closes."""
        if not hasattr(self, "_digits_cache"):
            self._digits_cache = {}
        try:
            sid = self._symbol_id(instrument)
            if sid not in self._digits_cache:
                self._vol_rules(sid)  # populates _digits_cache from symbol details
            if sid in self._digits_cache:
                return self._digits_cache[sid]
        except Exception:
            pass
        return 3 if "JPY" in _to_ct_symbol(instrument) else 5

    @staticmethod
    def _scale(instrument):
        # cTrader transmits prices as integers scaled by 1e5 for FX.
        return 100000.0

    # -- market data ----------------------------------------------------------
    def get_bid_ask(self, instrument=None):
        sym = _to_ct_symbol(instrument or self._c.SYMBOL)
        sid = self._symbol_id(instrument)
        now = time.time()
        cached = self._spot_cache.get(sid)
        if cached and now - cached[2] < 3:
            return cached[0], cached[1]
        conn = self._conn()
        with conn._lock:
            req = ProtoOASubscribeSpotsReq()
            req.ctidTraderAccountId = self._ctid()
            req.symbolId.append(sid)
            cid = conn._send(req)
            # wait for the first spot event carrying bid+ask for this symbol
            deadline = now + 8
            bid = ask = None
            while time.time() < deadline:
                pm = conn._read_frame(timeout=8)
                if pm.payloadType == ProtoOASpotEvent().payloadType:
                    ev = ProtoOASpotEvent()
                    ev.ParseFromString(pm.payload)
                    if ev.symbolId == sid:
                        if ev.bid:
                            bid = ev.bid / self._scale(sym)
                        if ev.ask:
                            ask = ev.ask / self._scale(sym)
                        if bid and ask:
                            break
                elif pm.payloadType == ProtoHeartbeatEvent().payloadType:
                    continue
        if not bid or not ask:
            raise RuntimeError(f"cTrader: no spot price for {sym}")
        self._spot_cache[sid] = (bid, ask, time.time())
        return bid, ask

    def get_price(self, instrument=None):
        bid, ask = self.get_bid_ask(instrument)
        return round((bid + ask) / 2, 6)

    def get_candles(self, instrument=None, interval=None, limit=None):
        sym = _to_ct_symbol(instrument or self._c.SYMBOL)
        sid = self._symbol_id(instrument)
        period_name = _period().get(interval or self._c.TIMEFRAME, "M5")
        count = min(limit or getattr(self._c, "CANDLES", 200), 1000)
        req = ProtoOAGetTrendbarsReq()
        req.ctidTraderAccountId = self._ctid()
        req.symbolId = sid
        req.period = getattr(ProtoOATrendbarPeriod, period_name)
        req.count = count
        # fromTimestamp/toTimestamp are REQUIRED protobuf fields — omitting
        # `from` rejects every request. Window = count bars back from now.
        period_sec = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                      "H1": 3600, "H4": 14400, "D1": 86400}.get(period_name, 300)
        now_ms = int(time.time() * 1000)
        req.toTimestamp = now_ms
        req.fromTimestamp = now_ms - (count + 5) * period_sec * 1000
        res = self._rpc(req, ProtoOAGetTrendbarsRes, timeout=20)
        scale = self._scale(sym)
        out = []
        for tb in res.trendbar:
            low = tb.low / scale
            out.append({
                "time": tb.utcTimestampInMinutes * 60,
                "open": (tb.low + tb.deltaOpen) / scale,
                "high": (tb.low + tb.deltaHigh) / scale,
                "low": low,
                "close": (tb.low + tb.deltaClose) / scale,
                "volume": float(tb.volume),
            })
        out.sort(key=lambda x: x["time"])
        return out

    def get_balance(self):
        if getattr(self._c, "PAPER_TRADING", True):
            return self._c.PAPER_BALANCE
        req = ProtoOATraderReq()
        req.ctidTraderAccountId = self._ctid()
        res = self._rpc(req, ProtoOATraderRes)
        # balance is in cents of the deposit currency (moneyDigits)
        money_digits = getattr(res.trader, "moneyDigits", 2) or 2
        bal = res.trader.balance / (10 ** money_digits)
        # Raw log — if this ever disagrees with the cTrader app, the line
        # pins down whether the API sent it or we mis-scaled it.
        print(f"[cTrader] balance ctid={self._ctid()} raw={res.trader.balance} digits={money_digits} -> {bal:.2f}")
        return bal

    # -- positions ------------------------------------------------------------
    def get_open_position(self, instrument=None):
        """Open position for the symbol, or None when the account is FLAT.

        MUST raise on failure instead of returning None: a swallowed error here
        told the loop "you're flat" while a position was open, so it stacked a
        fresh entry every tick (2.72 lots of AUDUSD from 0.34-lot orders)."""
        if getattr(self._c, "PAPER_TRADING", True):
            return None
        sym = _to_ct_symbol(instrument or self._c.SYMBOL)
        sid = self._symbol_id(instrument)
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self._ctid()
        res = self._rpc(req, ProtoOAReconcileRes)
        for p in res.position:
            td = p.tradeData
            if td.symbolId != sid:
                continue
            side = "BUY" if td.tradeSide == ProtoOATradeSide.BUY else "SELL"
            return {
                "instrument": sym,
                "side": side,
                "units": round(td.volume / 100.0, 8),  # cTrader volume = units × 100; fractional for crypto
                "symbol": instrument or self._c.SYMBOL,
                # position price/SL/TP are plain doubles (unlike trendbar ints)
                "entryPrice": p.price if p.price else None,
                "stopLoss": p.stopLoss if p.HasField("stopLoss") else None,
                "takeProfit": p.takeProfit if p.HasField("takeProfit") else None,
                "sl": p.stopLoss if p.HasField("stopLoss") else None,
                "tp": p.takeProfit if p.HasField("takeProfit") else None,
                "openTime": td.openTimestamp,
                "positionId": p.positionId,
            }
        return None

    def get_all_positions(self):
        """Every open position on the account (multi-position mode). Maps the
        cTrader symbolId back to a name via the loaded symbol table."""
        if getattr(self._c, "PAPER_TRADING", True):
            return []
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self._ctid()
        res = self._rpc(req, ProtoOAReconcileRes)
        self._load_symbols()
        id2name = {v: k for k, v in self._sym_id.items()}
        out = []
        for p in res.position:
            td = p.tradeData
            out.append({
                "symbol": id2name.get(td.symbolId, str(td.symbolId)),
                "side": "BUY" if td.tradeSide == ProtoOATradeSide.BUY else "SELL",
                "units": round(td.volume / 100.0, 8),  # fractional for crypto (0.34 BTC)
                "entryPrice": p.price if p.price else None,
                "stopLoss": p.stopLoss if p.HasField("stopLoss") else None,
                "takeProfit": p.takeProfit if p.HasField("takeProfit") else None,
                "positionId": p.positionId,
            })
        return out

    def get_open_trades(self):
        pos = self.get_open_position(self._c.SYMBOL)
        return [pos] if pos else []

    def amend_sltp(self, position_id, sl=None, tp=None, instrument=None):
        """Move SL/TP on an existing position — used by the trailing-stop /
        break-even manager. Fail-soft: a failed amend never raises into the loop
        (the existing stop stays attached), so it can't close a good trade."""
        try:
            am = ProtoOAAmendPositionSLTPReq()
            am.ctidTraderAccountId = self._ctid()
            am.positionId = int(position_id)
            dg = self._digits(instrument or self._c.SYMBOL)
            if sl is not None:
                am.stopLoss = round(float(sl), dg)
            if tp is not None:
                am.takeProfit = round(float(tp), dg)
            self._conn()._request(am, ProtoOAExecutionEvent, timeout=15)
            return True
        except Exception as e:
            print(f"[cTrader] amend_sltp failed: {e}")
            return False

    # -- orders ---------------------------------------------------------------
    def place_order(self, side, units, instrument=None, sl=None, tp=None):
        sym = _to_ct_symbol(instrument or self._c.SYMBOL)
        if getattr(self._c, "PAPER_TRADING", True):
            print(f"[PAPER][cTrader] {side} {units} {sym} sl={sl} tp={tp}")
            return {"orderId": f"CT_PAPER_{int(time.time()*1000)}", "status": "FILLED"}
        sid = self._symbol_id(instrument)
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self._ctid()
        req.symbolId = sid
        req.orderType = ProtoOAOrderType.MARKET
        req.tradeSide = ProtoOATradeSide.BUY if side == "BUY" else ProtoOATradeSide.SELL
        # cTrader volume is in units × 100 (hundredths of a unit). Min/step
        # differ per instrument class (FX 0.01 lot = 1,000 units; gold 1 oz;
        # indices 1 contract) — ask the broker instead of assuming FX.
        vol_h = int(round(float(units) * 100))
        try:
            mn, st = self._vol_rules(sid)
        except Exception:
            # Fail SAFE per class: the FX 0.01-lot floor (100k) on a crypto
            # symbol would turn a 0.34 BTC order into 1,000 BTC (~$100M) if the
            # symbol-details RPC hiccups. For non-FX never inflate — use the
            # requested size and let the broker reject a sub-minimum order.
            from apex import forex as _fx
            if _fx._is_fx(_fx._norm(instrument or self._c.SYMBOL)):
                mn, st = 100_000, 100_000
            else:
                mn, st = 1, 1
        req.volume = max(mn, (vol_h // st) * st)
        # NOTE: we do NOT put relativeStopLoss/TP on the order — its 1e-5 unit
        # doesn't match every instrument's tick size (gold moves in 0.01, so
        # the relative value fails 'invalid precision'). Instead the position
        # is amended with ABSOLUTE prices (rounded to the symbol's digits)
        # immediately after the fill, then verified — see below.
        res = self._conn()._request(req, ProtoOAExecutionEvent, timeout=20)
        fill = None
        if res.HasField("order") and res.order.HasField("executionPrice"):
            fill = res.order.executionPrice
        # ── HARD GUARANTEE: the stop must live AT THE BROKER. We attach it via
        # an ABSOLUTE-price amend right after the fill (relative SL/TP on the
        # order failed 'invalid precision' on non-FX). We only PANIC
        # (close the position) if, after everything, the broker still shows NO
        # stop on the position. A failed amend on an already-protected position
        # must NOT close a valid trade (the false-negative that rejected
        # EURUSD buys).
        if sl or tp:
            pid = res.position.positionId if res.HasField("position") else None
            if not pid:
                for _try in range(3):
                    time.sleep(0.3 * (_try + 1))
                    try:
                        pos = self.get_open_position(instrument)
                        pid = (pos or {}).get("positionId")
                        if pid:
                            break
                    except Exception:
                        pass
            amend_ok = False
            if pid:
                for _try in range(3):
                    try:
                        if _try > 0:
                            time.sleep(0.5 * _try)
                        am = ProtoOAAmendPositionSLTPReq()
                        am.ctidTraderAccountId = self._ctid()
                        am.positionId = int(pid)
                        dg = self._digits(instrument)
                        if sl:
                            am.stopLoss = round(float(sl), dg)
                        if tp:
                            am.takeProfit = round(float(tp), dg)
                        self._conn()._request(am, ProtoOAExecutionEvent, timeout=15)
                        amend_ok = True
                        break
                    except Exception as e:
                        print(f"[cTrader] SL/TP amend attempt {_try+1}/3 failed: {e}")
            else:
                print(f"[cTrader] WARNING: no positionId after fill for {sym}")
            protected = amend_ok
            if not protected:
                time.sleep(1.0)
                try:
                    pos2 = self.get_open_position(instrument)
                    protected = bool(pos2 and pos2.get("stopLoss"))
                except Exception:
                    protected = True
            if not protected and sl:
                try:
                    self.close_position(instrument)
                finally:
                    raise RuntimeError("could not attach stop-loss at the broker — "
                                       "position closed immediately for safety")
        return {"orderId": str(getattr(res.order, "orderId", "")),
                "status": "FILLED", "fillPrice": fill}

    def close_position(self, instrument=None):
        sym = _to_ct_symbol(instrument or self._c.SYMBOL)
        if getattr(self._c, "PAPER_TRADING", True):
            return {"status": "FILLED"}
        pos = self.get_open_position(instrument)
        if not pos:
            return {"status": "FLAT"}
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = self._ctid()
        req.positionId = pos["positionId"]
        req.volume = int(round(pos["units"] * 100))  # fractional-safe (0.34 BTC → 34)
        res = self._conn()._request(req, ProtoOAExecutionEvent, timeout=20)
        fill = None
        if res.HasField("order") and res.order.HasField("executionPrice"):
            fill = res.order.executionPrice
        return {"orderId": str(getattr(res.order, "orderId", "")),
                "status": "FILLED", "fillPrice": fill}


# ── Module-level helpers (parity with other connectors) ──────────────────────

def is_configured() -> bool:
    return bool(getattr(cfg, "CTRADER_CLIENT_ID", "")
                and getattr(cfg, "CTRADER_CLIENT_SECRET", ""))


def account_balance(access_token: str, ctid, env: str = "demo") -> float:
    """Real balance of a linked account (demo or live). Read-only — works with
    the `accounts` scope too, so it doubles as a connection health check right
    after OAuth: if this fails, candles/orders will fail the same way."""
    req = ProtoOATraderReq()
    req.ctidTraderAccountId = int(ctid)
    try:
        res = _conn_for(env, access_token, int(ctid))._request(req, ProtoOATraderRes)
    except (ConnectionError, OSError, TimeoutError):
        _drop_conn(env, int(ctid))  # pooled socket may be dead — one clean retry
        res = _conn_for(env, access_token, int(ctid))._request(req, ProtoOATraderRes)
    money_digits = getattr(res.trader, "moneyDigits", 2) or 2
    return res.trader.balance / (10 ** money_digits)


def list_accounts(access_token: str) -> list:
    """Trading accounts authorized by this token — used after OAuth to let the
    client pick which account to trade. Opens a short-lived demo connection."""
    if not _SDK_OK:
        raise RuntimeError(f"ctrader-open-api not installed: {_SDK_ERR}")
    ctx = ssl.create_default_context()
    raw = socket.create_connection((_HOST["demo"], _PORT), timeout=15)
    sock = ctx.wrap_socket(raw, server_hostname=_HOST["demo"])
    try:
        tmp = _Conn("demo", access_token, 0)
        tmp._sock = sock
        app = ProtoOAApplicationAuthReq()
        app.clientId = cfg.CTRADER_CLIENT_ID
        app.clientSecret = cfg.CTRADER_CLIENT_SECRET
        tmp._request(app, ProtoOAApplicationAuthRes)
        req = ProtoOAGetAccountListByAccessTokenReq()
        req.accessToken = access_token
        res = tmp._request(req, ProtoOAGetAccountListByAccessTokenRes)
        return [{"ctid": a.ctidTraderAccountId,
                 "live": bool(a.isLive)} for a in res.ctidTraderAccount]
    finally:
        try:
            sock.close()
        except Exception:
            pass
