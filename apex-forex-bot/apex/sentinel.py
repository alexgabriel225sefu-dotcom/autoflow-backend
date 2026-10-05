"""Permanent Market Sentinel — a persistent, expiring view of each symbol.

The bot's AI opinion used to exist for exactly the length of one function call:
`ai.get_signal()` was invoked on a candidate entry, its verdict was consumed
immediately, and nothing survived the tick. There was no such thing as "what
the AI currently thinks about EURUSD" — only "what it thought during the call
we happened to make".

This module holds that missing thing: a MarketState per symbol, published when
the information actually changes, and — the part that matters — one that
EXPIRES. A stale opinion is not a weaker opinion, it is a different market, and
acting on last hour's BUY because no fresher read exists is how a system trades
a chart that is no longer there.

Design constraints, matching ev.py:
  * pure functions and plain dicts — no I/O, no third-party imports, nothing
    that can fail at import time in the deploy image
  * every gate is opt-in via a mode (off / shadow / enforce), because a filter
    that silently stops a live account from trading is worse than no filter

What this module deliberately does NOT do: run its own async event loop. The
spec sketches `asyncio.sleep(1.0)`; this bot's engine is a thread per user with
its own tick, and rewriting that to asyncio would risk the whole execution path
for no behavioural gain. `should_refresh()` is the part that mattered — it lets
the existing tick decide when a new AI read is warranted instead of paying for
one on every pass.
"""
import time

# Action vocabulary. Anything else is a malformed signal, not a HOLD.
ACTIONS = ("BUY", "SELL", "HOLD")

# Refusal reasons the decision gate can return. Typed rather than free text so
# the journal can count them: "the AI disagreed 40 times this week" is a fact
# you can act on, "blocked" is not.
APPROVED = "APPROVED"
NO_SIGNAL = "NO_FRESH_AI_SIGNAL"
DISAGREES = "AI_DISAGREES"
LOW_CONF = "LOW_CONFIDENCE"
LOW_EV = "LOW_EV"
RISK_BLOCK = "RISK_BLOCK"
HOLD_CALLED = "AI_SAYS_HOLD"

_TF_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
}

# A signal may not outlive its own candle, and never more than this. Half an
# hour is already generous for an intraday read.
_TTL_CAP_S = 1800
_TTL_FLOOR_S = 60


def timeframe_seconds(timeframe, default=300):
    """Candle length in seconds, for anything the bot calls a timeframe."""
    return _TF_SECONDS.get(str(timeframe or "").strip().lower(), default)


def default_ttl(timeframe):
    """How long an AI read stays usable, derived from the candle it read.

    The spec's example expires a signal 60 seconds after publication. That is
    right for a one-second sentinel loop and catastrophic here: this engine
    ticks every few minutes on a 15m chart, so a 60s TTL would leave every
    signal stale at the moment of use, the gate would refuse everything, and
    the bot would silently stop trading. Tie the lifetime to the chart instead
    — one candle, floored and capped.
    """
    return max(_TTL_FLOOR_S, min(_TTL_CAP_S, timeframe_seconds(timeframe)))


def build_state(symbol, action, confidence=None, probability=None,
                expected_value_r=None, regime=None, sl=None, tp=None,
                risk_pct=None, reasoning="", ttl_s=300, now=None,
                **extra):
    """One MarketState record — what the AI currently believes about a symbol.

    `confidence` is accepted either as the engine's 0-100 score or as a 0-1
    fraction, and normalised to 0-1, because the two conventions already coexist
    in this codebase (ai.get_signal returns 0-100, the spec's contract uses
    0-1) and mixing them silently would make every confidence threshold wrong
    by a factor of a hundred.
    """
    now = time.time() if now is None else float(now)
    c = confidence
    try:
        c = float(c)
        if c > 1.0:
            c = c / 100.0
        c = max(0.0, min(1.0, c))
    except (TypeError, ValueError):
        c = None
    return {
        "symbol": symbol,
        "action": action if action in ACTIONS else "HOLD",
        "confidence": c,
        "probability": probability,
        "expected_value_r": expected_value_r,
        "regime": regime,
        "sl": sl,
        "tp": tp,
        "risk_pct": risk_pct,
        "reasoning": reasoning,
        "timestamp": now,
        "expires_at": now + max(1.0, float(ttl_s)),
        **extra,
    }


def valid_signal(signal, now=None):
    """Is this signal fresh and well-formed enough to act on?

    Returns (bool, reason). No fresh signal means HOLD — never "reuse the last
    BUY". That is the whole point of the expiry.
    """
    if not signal:
        return False, NO_SIGNAL
    now = time.time() if now is None else float(now)
    try:
        if now >= float(signal["expires_at"]):
            return False, NO_SIGNAL
    except (KeyError, TypeError, ValueError):
        return False, NO_SIGNAL
    if signal.get("action") not in ACTIONS:
        return False, NO_SIGNAL
    return True, APPROVED


def age(signal, now=None):
    """Seconds since publication, or None. For logging and Telegram."""
    try:
        now = time.time() if now is None else float(now)
        return max(0.0, now - float(signal["timestamp"]))
    except (KeyError, TypeError, ValueError):
        return None


# ── Change detection ─────────────────────────────────────────────────────

def _num(d, k):
    try:
        return float((d or {}).get(k))
    except (TypeError, ValueError):
        return None


def should_refresh(prev, features, now=None, ttl_s=300,
                   price_move_atr=0.5, spread_change_pips=0.5):
    """Has enough changed to be worth another AI read?

    Returns (bool, reason). The AI is the expensive part of a tick — calling it
    every pass costs money and tells us nothing new when the market has not
    moved. Refresh on: no state at all, expiry, a new candle, a price move
    worth a fraction of ATR, a regime flip, or a spread change big enough to
    alter the cost side of the EV maths.

    Conservative by construction: anything it cannot evaluate results in a
    refresh, because a missed refresh means acting on a stale opinion, while a
    surplus refresh only costs one API call.
    """
    now = time.time() if now is None else float(now)
    if not prev:
        return True, "no_state"

    try:
        if now >= float(prev["expires_at"]):
            return True, "expired"
    except (KeyError, TypeError, ValueError):
        return True, "no_expiry"

    # New candle — the bar the last read was based on has closed.
    p_bar, n_bar = (prev or {}).get("bar_time"), (features or {}).get("bar_time")
    if n_bar is not None and p_bar is not None and n_bar != p_bar:
        return True, "new_candle"

    if (features or {}).get("regime") != prev.get("regime"):
        return True, "regime_change"

    # Thresholds are compared with a relative slack. Subtracting two prices
    # that differ by exactly half an ATR lands a fraction of a bit under it
    # (1.1005 - 1.1000 = 0.0004999999999999449), and a move sitting on the
    # threshold should not be decided by which subtraction produced it. The
    # slack points toward refreshing, which is the safe direction here: a
    # surplus refresh costs one API call, a missed one acts on a stale read.
    _EPS = 1e-9

    p_px, n_px = _num(prev, "price"), _num(features, "price")
    atr = _num(features, "atr") or _num(prev, "atr")
    if p_px is not None and n_px is not None and atr and atr > 0:
        if abs(n_px - p_px) >= price_move_atr * atr - _EPS:
            return True, "price_moved"

    p_sp, n_sp = _num(prev, "spread_pips"), _num(features, "spread_pips")
    if p_sp is not None and n_sp is not None:
        if abs(n_sp - p_sp) >= spread_change_pips - _EPS:
            return True, "spread_change"

    return False, "unchanged"


# ── Signal store ─────────────────────────────────────────────────────────

class SignalStore:
    """Last published MarketState per symbol.

    In-process and deliberately not persisted: a signal that outlives the
    process it was computed in is by definition stale, and reloading one after
    a restart would reintroduce exactly the bug the expiry exists to prevent.
    """

    def __init__(self):
        self._by_symbol = {}

    @staticmethod
    def _key(symbol):
        return str(symbol or "").replace("_", "").replace("/", "").upper()

    def publish(self, state):
        if state and state.get("symbol"):
            self._by_symbol[self._key(state["symbol"])] = state
        return state

    def get(self, symbol):
        return self._by_symbol.get(self._key(symbol))

    def fresh(self, symbol, now=None):
        """The state, but only if it is still valid. Otherwise None."""
        s = self.get(symbol)
        ok, _ = valid_signal(s, now)
        return s if ok else None

    def drop(self, symbol):
        return self._by_symbol.pop(self._key(symbol), None)

    def clear(self):
        self._by_symbol.clear()


# ── Decision gate ────────────────────────────────────────────────────────

def decide(signal, requested_action, now=None, min_confidence=None,
           min_ev_r=None, risk_ok=True):
    """Does the Sentinel approve this specific order?

    Returns (approved, reason) with `reason` from the typed vocabulary above.
    The order of the checks is the order in which they are cheap and decisive:
    freshness, then agreement, then the thresholds, then risk.

    A threshold that was not configured is not enforced — passing
    min_confidence=None means "no confidence requirement", not "requires 0",
    so an unconfigured gate can never be the thing that stops a trade.
    """
    ok, why = valid_signal(signal, now)
    if not ok:
        return False, why

    if signal["action"] == "HOLD":
        return False, HOLD_CALLED
    if requested_action not in ("BUY", "SELL"):
        return False, DISAGREES
    if signal["action"] != requested_action:
        return False, DISAGREES

    if min_confidence is not None:
        c = signal.get("confidence")
        if c is None or c < float(min_confidence):
            return False, LOW_CONF

    if min_ev_r is not None:
        ev = signal.get("expected_value_r")
        if ev is None or ev <= float(min_ev_r):
            return False, LOW_EV

    if not risk_ok:
        return False, RISK_BLOCK

    return True, APPROVED


def describe(signal, now=None):
    """One human line for Telegram / the dashboard."""
    if not signal:
        return "no AI signal"
    a = age(signal, now)
    ok, _ = valid_signal(signal, now)
    bits = [f"{signal.get('symbol')} {signal.get('action')}"]
    if signal.get("confidence") is not None:
        bits.append(f"conf {signal['confidence']:.0%}")
    if signal.get("expected_value_r") is not None:
        bits.append(f"EV {signal['expected_value_r']}R")
    if signal.get("regime"):
        bits.append(str(signal["regime"]))
    bits.append(f"{a:.0f}s old" if a is not None else "age unknown")
    if not ok:
        bits.append("STALE")
    return " · ".join(bits)
