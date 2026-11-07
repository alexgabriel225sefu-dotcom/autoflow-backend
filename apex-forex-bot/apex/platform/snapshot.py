"""MarketSnapshot — everything the evaluator is allowed to know.

THE POINT OF THIS OBJECT IS WHAT IT FORBIDS.

The evaluator takes a RuleDoc and one of these, and nothing else. It cannot
read the clock, the environment, the network or the broker. That is not a
style preference — it is what makes a decision reproducible. Given the same
snapshot, the same RuleDoc must produce the same verdict today, in a test, and
in six months when someone asks why a position was opened.

So `ts` is a FIELD, not `time.time()`. `session` is a field, not derived from
the current hour. Every such value is captured once, at the edge, by whoever
builds the snapshot — and after that the decision is a pure function.

RELATIONSHIP TO strategy_api.Market: a Market carries roughly 60% of this
(candles, symbol, indicators, strat, open position, price, balance,
timeframe). It has no spread, session, pending orders, equity, exposure or
account state. So a snapshot CONTAINS a Market rather than replacing it —
existing strategies keep receiving exactly what they receive today.
"""

import time


class MarketSnapshot:
    """An immutable reading. Build it at the edge; pass it down."""

    __slots__ = ("symbol", "timeframe", "candles", "price", "spread_pips",
                 "ts", "session", "open_positions", "pending_orders",
                 "balance", "equity", "exposure_percent", "account_state",
                 "indicators", "strat", "_market")

    def __init__(self, *, symbol, timeframe, candles, price, ts,
                 spread_pips=None, session=None, open_positions=None,
                 pending_orders=None, balance=None, equity=None,
                 exposure_percent=None, account_state=None,
                 indicators=None, strat=None):
        if not symbol:
            raise ValueError("snapshot needs a symbol")
        if not timeframe:
            raise ValueError("snapshot needs a timeframe")
        if ts is None:
            # Refused rather than defaulted: a snapshot that stamps itself
            # with "now" is a snapshot whose decision cannot be replayed.
            raise ValueError("snapshot needs an explicit ts — the evaluator "
                             "must not read the clock")
        self.symbol = str(symbol)
        self.timeframe = str(timeframe)
        self.candles = list(candles or [])
        self.price = price
        self.ts = float(ts)
        self.spread_pips = spread_pips
        self.session = session
        self.open_positions = list(open_positions or [])
        self.pending_orders = list(pending_orders or [])
        self.balance = balance
        self.equity = equity
        self.exposure_percent = exposure_percent
        self.account_state = account_state or "unknown"
        self.indicators = dict(indicators or {})
        self.strat = dict(strat or {})
        self._market = None

    # ── derived reads, all from stored fields ────────────────────────────
    @property
    def open_count(self):
        return len(self.open_positions)

    def positions_for(self, symbol=None):
        want = (symbol or self.symbol)
        n = str(want).replace("_", "").replace("/", "").upper()
        return [p for p in self.open_positions
                if str(p.get("symbol", "")).replace("_", "")
                .replace("/", "").upper() == n]

    def as_market(self, **extra):
        """A strategy_api.Market over the same data, built lazily.

        Lets a RuleDoc rule and a legacy engine read one identical snapshot,
        which is the only way to compare them honestly.
        """
        if self._market is None:
            from apex import strategy_api
            self._market = strategy_api.Market(
                self.candles, symbol=self.symbol, indicators=self.indicators,
                strat=self.strat,
                open_position=(self.open_positions[0]
                               if self.open_positions else None),
                price=self.price, balance=self.balance,
                timeframe=self.timeframe, **extra)
        return self._market

    def as_dict(self):
        """Serialisable. Candles are omitted — a journal entry references a
        snapshot, and inlining 250 bars per decision would bury the reason
        under the data."""
        return {"symbol": self.symbol, "timeframe": self.timeframe,
                "price": self.price, "ts": self.ts,
                "spreadPips": self.spread_pips, "session": self.session,
                "candleCount": len(self.candles),
                "openPositions": self.open_count,
                "pendingOrders": len(self.pending_orders),
                "balance": self.balance, "equity": self.equity,
                "exposurePercent": self.exposure_percent,
                "accountState": self.account_state}

    def __repr__(self):
        return (f"<MarketSnapshot {self.symbol} {self.timeframe} "
                f"@{self.price} ts={self.ts:.0f} "
                f"pos={self.open_count}>")


def from_live(broker, cfg, symbol, *, candles, positions=None, balance=None,
              equity=None, now=None, indicators=None, strat=None,
              spread_pips=None, session=None, account_state=None,
              exposure_percent=None, pending_orders=None):
    """Build a snapshot at the edge, where I/O is allowed.

    This is the ONLY function in the platform package that is expected to be
    called with a broker in hand, and it does not evaluate anything. Reading
    and deciding are kept apart so the deciding half stays testable.
    """
    return MarketSnapshot(
        symbol=symbol,
        timeframe=getattr(cfg, "TIMEFRAME", "1h"),
        candles=candles,
        price=(candles[-1].get("close") if candles else None),
        ts=now if now is not None else time.time(),
        spread_pips=spread_pips, session=session,
        open_positions=positions or [], pending_orders=pending_orders or [],
        balance=balance, equity=equity, exposure_percent=exposure_percent,
        account_state=account_state, indicators=indicators, strat=strat)
