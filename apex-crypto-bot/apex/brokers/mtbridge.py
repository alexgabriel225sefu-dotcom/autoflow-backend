"""MetaTrader bridge connector — drive any MT5 broker (IC Markets, etc.).

Architecture (3Commas-style):
    bot (cloud, this code)  ◄── HTTP sync every ~10 s ──  ApexBridge EA
    decides WHAT to trade                                  runs inside the
    based on EA-supplied data                              client's MetaTrader

The EA POSTs a plain-text snapshot (quotes, balance, candles, position,
acks) to /api/mt/sync and receives pending commands in the response.
Plain text keeps the MQL5 side trivial — no JSON parsing in the EA.

Wire format (request, one item per line):
    SECRET=...                          shared secret (MT_BRIDGE_SECRET)
    SYMBOL=EURUSD
    BID=1.08500 / ASK=1.08512
    BALANCE=10000.00 / EQUITY=10005.20
    POSITION=BUY|0.12|1.08400           or POSITION=NONE
    ACK=42|FILLED|1.08501               (repeated, optional)
    CANDLE=1718000000|o|h|l|c|v         (repeated, oldest→newest)

Response:
    OK
    CMD=42|OPEN|BUY|0.12|1.08350|1.08800   id|action|side|lots|sl|tp
    CMD=43|CLOSE
"""
import time
import threading
from apex import config as cfg

STALE_AFTER = 90          # seconds without a sync → bridge considered offline
UNITS_PER_LOT = 100_000

_lock = threading.Lock()
_state = {
    "symbol": None,        # bot notation, e.g. EUR_USD
    "bid": 0.0, "ask": 0.0,
    "balance": 0.0, "equity": 0.0,
    "position": None,      # {"side","lots","entry"} or None
    "candles": [],
    "last_sync": 0.0,
}
_commands = []             # [{"id","line"}]
_acks = {}                 # id -> (status, price)
_next_id = [1]


def _to_bot_symbol(mt_symbol: str) -> str:
    s = (mt_symbol or "").upper().split(".")[0]   # brokers suffix symbols: EURUSD.a
    return f"{s[:3]}_{s[3:6]}" if len(s) >= 6 else s


# ─── EA sync endpoint logic ───────────────────────────────

def handle_sync(body: str) -> tuple:
    """Process one EA sync. Returns (http_status, response_text)."""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    fields = {}
    candles = []
    acks = []
    for ln in lines:
        key, _, val = ln.partition("=")
        key = key.upper()
        if key == "CANDLE":
            p = val.split("|")
            if len(p) >= 6:
                try:
                    candles.append({"time": int(float(p[0])), "open": float(p[1]),
                                    "high": float(p[2]), "low": float(p[3]),
                                    "close": float(p[4]), "volume": float(p[5])})
                except ValueError:
                    pass
        elif key == "ACK":
            acks.append(val)
        else:
            fields[key] = val

    if not cfg.MT_BRIDGE_SECRET or fields.get("SECRET") != cfg.MT_BRIDGE_SECRET:
        return 403, "ERR=bad secret"

    with _lock:
        _state["symbol"] = _to_bot_symbol(fields.get("SYMBOL", ""))
        for src, dst in (("BID", "bid"), ("ASK", "ask"),
                         ("BALANCE", "balance"), ("EQUITY", "equity")):
            try:
                _state[dst] = float(fields.get(src, _state[dst]))
            except ValueError:
                pass
        pos = fields.get("POSITION", "NONE")
        if pos == "NONE" or not pos:
            _state["position"] = None
        else:
            p = pos.split("|")
            _state["position"] = {"side": p[0],
                                  "lots": float(p[1]) if len(p) > 1 else 0,
                                  "entry": float(p[2]) if len(p) > 2 else 0}
        if candles:
            _state["candles"] = candles
        _state["last_sync"] = time.time()

        for a in acks:
            p = a.split("|")
            try:
                _acks[int(p[0])] = (p[1] if len(p) > 1 else "FILLED",
                                    float(p[2]) if len(p) > 2 else 0.0)
            except (ValueError, IndexError):
                pass
        acked = set(_acks)
        _commands[:] = [c for c in _commands if c["id"] not in acked]
        out = "OK\n" + "".join(f"CMD={c['line']}\n" for c in _commands)
    return 200, out


# ─── Broker interface (same shape as oanda.py) ───────────

def _fresh():
    if time.time() - _state["last_sync"] > STALE_AFTER:
        raise RuntimeError(
            "MT bridge offline — is the ApexBridge EA running in MetaTrader? "
            "(no sync in the last 90s)")


def current_symbol():
    with _lock:
        return _state["symbol"]


def position_reported():
    """Position as last reported by the EA (None when flat)."""
    with _lock:
        return _state["position"]


def is_connected():
    return time.time() - _state["last_sync"] <= STALE_AFTER


def get_bid_ask(instrument=None):
    _fresh()
    with _lock:
        return _state["bid"], _state["ask"]


def get_price(instrument=None):
    bid, ask = get_bid_ask(instrument)
    return round((bid + ask) / 2, 6)


def get_candles(instrument=None, interval=None, limit=None):
    _fresh()
    with _lock:
        candles = list(_state["candles"])
    if not candles:
        raise RuntimeError("MT bridge: no candle data received from the EA yet")
    return candles[-(limit or cfg.CANDLES):]


def get_balance():
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    _fresh()
    with _lock:
        return _state["balance"]


def close_position(instrument=None):
    """Queue a CLOSE for whatever position the EA holds on its chart."""
    return place_order("CLOSE", 0, instrument)


def place_order(side, units, instrument=None, sl=None, tp=None):
    """Queue a command for the EA. OPEN includes lots + safety-net SL/TP."""
    if cfg.PAPER_TRADING:
        print(f"[PAPER][MT] {side} {units} {instrument} (not sent to EA)")
        return {"orderId": "PAPER_" + str(int(time.time() * 1000)), "status": "FILLED"}
    with _lock:
        cmd_id = _next_id[0]
        _next_id[0] += 1
        if side == "CLOSE":
            line = f"{cmd_id}|CLOSE"
        else:
            lots = max(0.01, round(units / UNITS_PER_LOT, 2))
            line = (f"{cmd_id}|OPEN|{side}|{lots:.2f}|"
                    f"{(sl or 0):.5f}|{(tp or 0):.5f}")
        _commands.append({"id": cmd_id, "line": line})
    print(f"[MT] queued → {line}")
    return {"orderId": cmd_id, "status": "QUEUED"}
