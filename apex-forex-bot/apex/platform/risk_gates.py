"""The gates every order passes, whoever asked for it. §5, written down.

ONE FUNCTION, AND THE REASON IT IS ONE

The legacy bot learned this the expensive way. Its automatic strategy path
checked entitlement, risk, ownership and idempotency; `/buy`, the assistant and
the control plane reached the broker with fewer checks, and one path reached it
with none of them. The fix was a single gate in `apex/gates.py` that every
origin calls, and the rule it states once is the rule here:

    A fact we could not establish is not a fact in our favour.

So `authorize()` is the only entry point, every limit in §5 is a gate inside
it, and a gate that cannot measure its own question REFUSES. That is what "fail
closed" means in this file, and it is checked gate by gate in
`tests/test_platform_risk_gates.py` section [12].

WHY IT REFUSES ON DEMO TOO, WHICH IS NOT WHAT emergency.py DOES

`emergency.check` deliberately lets a demo client carry on when the shared
store cannot be read: halting every free client over a Redis blip protects
nobody. The reasoning does not carry over to this file, and it is worth saying
why rather than leaving the inconsistency to look like an oversight.

That module decides whether the PRODUCT is available. This one decides whether
an ORDER is safe, and the demo path is the only place these gates will ever run
before real money runs through them. A gate that is permissive on demo is a
gate nobody has exercised, and it would first be exercised on the day it
matters. The cost of the strict reading is a refused simulated entry.

CAPS VERSUS COUNTS, BECAUSE THE BOUNDARY IS WHERE THESE GO WRONG

§5 names an off-by-one it has already seen: `5/4` in the legacy daily counter.
The cause was not the comparison but the fact being compared —
`strategies.record_trade` increments when a trade CLOSES, so four open
positions counted as zero and the loop opened a fifth. The fact this file reads
is `dailyTradesOpened`, and `REQUIRED_FACTS` says so out loud.

The comparisons themselves split two ways, on purpose:

    a COUNT limit refuses at >=     "max 4 trades" means the fifth is refused
    a CEILING refuses at >          "max 1% risk" means 1.00% is allowed
    a LOSS limit refuses at >=      "max 4% daily loss" means 4% stops you

A loss limit is a count-shaped thing wearing a percentage: the number is where
the client said to stop, so reaching it stops. Writing all three the same way
would be wrong twice whichever way it was written.

MONEY IS COMPARED IN MONEY

Every percentage here is turned back into an amount and rounded to cents
before it is compared. `40000 × 0.0001 × 25` is not reliably `100.0` in binary
floating point, and an order sitting exactly on a 1% cap must not be refused by
an artefact of the last bit. This is not a tolerance — cents are the precision
a broker balance actually has, and `forex.floor_risk_ok` exists for the sizing
path to decide whether a broker's minimum lot is worth taking. That decision
belongs before the gate; a gate with a tolerance is a cap that is not the
number it prints.

WHAT IS NOT HERE

The balance arrives as a CALLABLE and there is no parameter that takes a
number. §5 requires it read from the broker at decision time and never cached,
and the only shape that cannot be handed a stale figure is one with nowhere to
put it. Everything else — positions, today's loss, the spread — arrives in
`state`, read by the caller that owns the broker connection, because this
module performs no I/O and imports nothing that can.

It also does not import `apex/platform/bridge.py` or `execution.py`, and must
not. Nothing in production imports those, that is the live-execution review
gate, and a risk gate is not the thing that should quietly open it.
`SUPPORTED_ORDER_TYPES` below is therefore a COPY of the bridge's set, and
section [11] of the test reads the bridge's source to prove the copy still
agrees with the original.

NEWS AND SESSION FILTERS ARE ABSENT, AND THAT IS NOT AN OVERSIGHT

§5 lists them. They are the one row in that table this file does not answer:
the platform has no news feed of its own, and inventing a gate that always
passes because it has nothing to read would be the recorded-but-unenforced
failure this whole file exists to end. A gate is added when there is a fact to
feed it.
"""

from apex import forex
from apex.platform import ruledoc as _rd

# ── the capability, duplicated rather than imported ─────────────────────────
# See the module docstring. The original lives in the unwired execution
# boundary and importing it would wire that boundary to a module automation
# can reach.
SUPPORTED_ORDER_TYPES = frozenset({"MARKET"})

# ── platform floors ─────────────────────────────────────────────────────────
# Not the client's to raise. A rule may ask for something TIGHTER and the gate
# takes the stricter of the two; a rule asking for something looser is held to
# these. The numbers are the ones the product already runs on, so this file
# introduces no new policy:
#
#   maxRiskPercentLive   telegram._LIVE_INITIAL_RISK_CAP (1%), the ceiling the
#                        legacy bot applies when an account is switched to real
#                        money whatever it was configured with while simulating.
#   maxRiskPercentDemo   ruledoc's own ceiling on sizing.riskPercent. The
#                        RULE's number still binds on demo — this is only the
#                        outer bound, so the arithmetic and the comparison are
#                        exercised in both modes and the live cap is not the
#                        first time either one runs.
#   maxDailyLossPercent  user_loop's MAX_DAILY_LOSS_PCT.
#   maxDrawdownPercent   user_loop's MAX_DD_PCT.
#   maxSameUsdSide       portfolio.DEFAULT_MAX_SAME_USD_SIDE, which is the
#                        number the autonomous loop refused at.
PLATFORM = {
    "maxRiskPercentLive": 1.0,
    "maxRiskPercentDemo": 100.0,
    "maxDailyLossPercent": 4.0,
    "maxDrawdownPercent": 25.0,
    "maxSameUsdSide": 2,
}

# ── gates, in the order they run ────────────────────────────────────────────
# The order is load-bearing and follows `gates.authorize_order`: the cheapest
# and most decisive first, so a misconfigured rule never costs a broker read.
#
# Within that, configuration errors come before account state, and account
# state before market conditions. The reason is what the client is told. "This
# rule asks for a LIMIT order and we place MARKET orders" is something they
# can fix; "the spread is too wide" is something they wait out; and a halted
# account outranks both, because "you have hit your daily loss" is the more
# useful thing to learn than "you already hold two dollar shorts".
GATES = ("inputs", "order_type", "stop", "balance", "risk_per_trade",
         "daily_loss", "drawdown", "daily_trades", "open_positions",
         "exposure", "correlated_exposure", "spread", "slippage")

# What each gate reads out of `state`. Declared rather than implied so the
# test can drive its fail-closed loop from the module's own list — a gate added
# without a line here is a gate whose fail-closed behaviour nobody proved.
REQUIRED_FACTS = {
    "daily_loss": ("dailyRealisedPnl",),
    "drawdown": ("peakBalance",),
    "daily_trades": ("dailyTradesOpened",),
    "open_positions": ("positions",),
    "exposure": ("positions",),
    "correlated_exposure": ("positions",),
    "spread": ("spreadPips",),
    "slippage": ("slippagePoints",),
}

# Per-gate outcome. WAIVED is distinct from PASSED on purpose: "the rule set no
# spread ceiling" and "the spread was inside the ceiling" are different
# sentences, and a refusal nobody can read is a refusal nobody can debug.
PASSED = "passed"
WAIVED = "waived"
REFUSED = "refused"
SKIPPED = "skipped"

# Every refusal this module can answer with. Stable strings, because a stored
# verdict is read back by its code, and listed here so the test can assert
# there are no duplicates — two gates sharing a code is two refusals nobody
# can tell apart.
CODES = (
    # inputs
    "NO_RULE", "MODE_NOT_STATED", "BALANCE_NOT_CALLABLE", "NO_SYMBOL",
    "SIDE_NOT_TRADEABLE",
    # order type
    "ORDER_TYPE_UNSTATED", "ORDER_TYPE_UNSUPPORTED",
    # stop
    "NO_STOP", "NO_ENTRY_PRICE", "STOP_NOT_PRICED", "STOP_AT_ENTRY",
    "STOP_WRONG_SIDE",
    # balance
    "BALANCE_UNAVAILABLE", "BALANCE_NOT_A_NUMBER",
    # risk per trade
    "RISK_UNSIZED", "RISK_UNMEASURABLE", "RISK_OVER_RULE",
    "RISK_OVER_PLATFORM_CAP",
    # the account-wide money limits
    "DAILY_PNL_UNKNOWN", "DAILY_LOSS_REACHED",
    "PEAK_BALANCE_UNKNOWN", "DRAWDOWN_REACHED",
    "DAILY_TRADES_UNKNOWN", "DAILY_TRADES_REACHED",
    # exposure
    "POSITIONS_UNKNOWN", "MAX_POSITIONS_UNSTATED", "AT_POSITION_LIMIT",
    "EXPOSURE_UNKNOWN", "INSTRUMENT_EXPOSURE_EXCEEDED", "CORRELATED_EXPOSURE",
    # market conditions
    "SPREAD_UNKNOWN", "SPREAD_TOO_WIDE",
    "SLIPPAGE_UNKNOWN", "SLIPPAGE_OVER_CEILING",
)

# A bug in a gate must not become a way to open a position. Each gate gets its
# own crash code so a failure is attributable: "something threw" is not a
# refusal anybody can act on.
CHECK_FAILED = {g: f"{g.upper()}_CHECK_FAILED" for g in GATES}


class OrderIntent:
    """The order being asked for, before anything has agreed to place it.

    Deliberately NOT validating in `__init__`, which is the opposite of
    `execution.ExecutionRequest`. That class raises on a bad side because by
    the time one is built every gate has already passed, so a bad value there
    is a bug and should be loud. Here a bad value is the ordinary case this
    module exists to answer, and an exception would surface as a 500 where a
    refusal with a code is what the caller needs. The `inputs` gate checks it.

    `volume` is units, matching `forex.calc_units` and the broker connector.
    """

    __slots__ = ("symbol", "side", "entry_price", "stop_price", "volume")

    def __init__(self, *, symbol, side, entry_price=None, stop_price=None,
                 volume=None):
        self.symbol = symbol
        self.side = side
        self.entry_price = entry_price
        self.stop_price = stop_price
        self.volume = volume

    def as_dict(self):
        return {"symbol": self.symbol, "side": self.side,
                "entryPrice": self.entry_price, "stopPrice": self.stop_price,
                "volume": self.volume}

    def __repr__(self):
        return (f"<OrderIntent {self.side} {self.volume} {self.symbol} "
                f"@{self.entry_price} stop {self.stop_price}>")


class Verdict:
    """Allowed or refused, with everything needed to journal either one.

    `checks` carries every gate and what it did, including the ones that never
    ran. §7 of the specification wants every refusal recorded with its gate and
    its code; knowing which gates were SKIPPED is half of reading that record,
    because it says what has and has not been established about the order.
    """

    __slots__ = ("allowed", "gate", "code", "detail", "checks", "facts",
                 "mode")

    def __init__(self, allowed, *, gate=None, code="AUTHORIZED", detail="",
                 checks=None, facts=None, mode=None):
        self.allowed = bool(allowed)
        self.gate = gate
        self.code = code
        self.detail = detail
        self.checks = list(checks or [])
        self.facts = dict(facts or {})
        self.mode = mode

    def __bool__(self):
        return self.allowed

    def as_dict(self):
        return {"allowed": self.allowed, "gate": self.gate, "code": self.code,
                "detail": self.detail, "checks": self.checks,
                "facts": self.facts, "mode": self.mode}

    def __repr__(self):
        return (f"<Verdict {'ALLOW' if self.allowed else 'DENY'} {self.code}"
                f"{' at ' + self.gate if self.gate else ''}>")


# ── helpers ─────────────────────────────────────────────────────────────────
_MISSING = object()


def _num(v):
    """A real number. `bool` is excluded because `True` is not a price."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _pos(v):
    return _num(v) and v > 0


def _cents(v):
    """Money, at the precision a broker balance actually has."""
    return round(float(v), 2)


def _cap(rule_value, floor):
    """The stricter of what the rule asked for and what the platform allows."""
    return min(float(rule_value), floor) if _pos(rule_value) else floor


def _risk_money(symbol, price, stop_price, units):
    """What `units` loses if the stop is hit, in account currency.

    One implementation, used by both the per-trade gate and the per-instrument
    exposure gate, and it is the engine's own: `forex.floor_risk_at` is what
    the legacy sizing path measures risk with. Measuring it a second way here
    would produce two numbers that must agree forever.
    """
    stop_pips = abs(forex.to_pips(price - stop_price, symbol, price))
    if stop_pips <= 0:
        return None
    return _cents(forex.floor_risk_at(abs(float(units)), symbol, price,
                                      stop_pips))


def _fact(state, key):
    return (state or {}).get(key, _MISSING)


# ── the gates ───────────────────────────────────────────────────────────────
# Each returns None to pass, a (code, detail) pair to refuse, or the string
# WAIVED when the rule set no limit for it to enforce. They read `ctx`, a plain
# dict, and write their measurements into `ctx["facts"]` so a refusal three
# gates later still carries what was established before it.
def _g_inputs(ctx):
    if not isinstance(ctx["rule"], dict):
        return ("NO_RULE",
                "there is no rule document to read the limits from")
    if ctx["mode"] not in ("demo", "live"):
        # Not defaulted, for the same reason ExecutionRequest refuses to
        # default it: an order whose environment nobody stated is an order
        # that might be real money by accident.
        return ("MODE_NOT_STATED",
                f"the account mode must be 'demo' or 'live', not "
                f"{ctx['mode']!r} — an order's environment is never assumed")
    if not callable(ctx["balance_reader"]):
        return ("BALANCE_NOT_CALLABLE",
                "the balance must arrive as a callable read at decision "
                "time; a number here would be a figure of unknown age")
    if not isinstance(ctx["intent"].symbol, str) or \
            not ctx["intent"].symbol.strip():
        return ("NO_SYMBOL", "the order names no instrument")
    if ctx["intent"].side not in ("BUY", "SELL"):
        return ("SIDE_NOT_TRADEABLE",
                f"{ctx['intent'].side!r} is not a side that opens a position")
    return None


def _g_order_type(ctx):
    order = ctx["rule"].get("order")
    otype = order.get("type") if isinstance(order, dict) else None
    if not otype:
        # `bridge.build` defaults an absent type to MARKET. A gate must not:
        # defaulting is approving a document it did not read, and every rule
        # `ruledoc.validate` accepts states its order type.
        return ("ORDER_TYPE_UNSTATED",
                "this rule does not say what kind of order to place")
    ctx["facts"]["orderType"] = otype
    if otype not in SUPPORTED_ORDER_TYPES:
        return ("ORDER_TYPE_UNSUPPORTED",
                f"this rule asks for a {otype} order and the connected broker "
                f"path places "
                f"{', '.join(sorted(SUPPORTED_ORDER_TYPES))} orders only — "
                f"refusing rather than placing a different kind of order than "
                f"the one configured")
    return None


def _g_stop(ctx):
    """A stop exists, and it is a price on the right side of the entry.

    `ruledoc.validate` already refuses to ACTIVATE a rule whose stopLoss has
    no mode — "a rule without a stop has no defined risk" — and this asks the
    same question again at order time. Not redundantly: activation happened
    once and possibly months ago, and the thing that decides the account's
    worst case on THIS order is the price, not the mode on the document.
    """
    sl = ctx["rule"].get("stopLoss")
    sl = sl if isinstance(sl, dict) else {}
    mode = sl.get("mode")
    if mode == "atr" and not _pos(sl.get("atrMultiple")) or \
            mode == "pips" and not _pos(sl.get("pips")) or \
            mode not in ("atr", "pips"):
        return ("NO_STOP",
                "this rule has no stop, so the trade has no defined risk and "
                "no position size can be derived from it")

    it = ctx["intent"]
    if not _pos(it.entry_price):
        return ("NO_ENTRY_PRICE",
                "there is no entry price to measure the stop against")
    if not _pos(it.stop_price):
        return ("STOP_NOT_PRICED",
                "the rule has a stop and this order does not carry its price")
    if it.stop_price == it.entry_price:
        return ("STOP_AT_ENTRY",
                "the stop is the entry price, which is a stop distance of "
                "zero and a position size of infinity")
    if (it.side == "BUY") == (it.stop_price > it.entry_price):
        # A BUY stop above the entry, or a SELL stop below it, is already
        # through the market: it would be hit immediately, and the distance it
        # implies would size the position as if there were risk the wrong way.
        return ("STOP_WRONG_SIDE",
                f"a {it.side} stop at {it.stop_price} is on the wrong side of "
                f"an entry at {it.entry_price}")
    ctx["facts"]["stopDistance"] = abs(it.entry_price - it.stop_price)
    return None


def _g_balance(ctx):
    """Read the broker. Once per authorisation, and never from a cache.

    One read feeds four gates below. Doing it here rather than inside each of
    them is not an optimisation: four reads could return four different
    balances, and then "1% of balance" and "4% of balance" would be
    percentages of different accounts.
    """
    try:
        bal = ctx["balance_reader"]()
    except Exception as e:                                  # noqa: BLE001
        return ("BALANCE_UNAVAILABLE",
                f"the account balance could not be read from the broker, so "
                f"no risk percentage can be computed — {type(e).__name__}: "
                f"{str(e)[:120]}")
    if not _pos(bal):
        return ("BALANCE_NOT_A_NUMBER",
                f"the broker answered {bal!r}, which is not a balance an "
                f"order can be sized against")
    ctx["facts"]["balance"] = float(bal)
    return None


def _g_risk_per_trade(ctx):
    it, bal = ctx["intent"], ctx["facts"]["balance"]
    if not _pos(it.volume):
        return ("RISK_UNSIZED",
                "this order carries no size, so the money it risks cannot be "
                "measured")
    money = _risk_money(it.symbol, it.entry_price, it.stop_price, it.volume)
    if money is None or money <= 0:
        return ("RISK_UNMEASURABLE",
                f"the risk on {it.symbol} could not be measured from an entry "
                f"of {it.entry_price} and a stop of {it.stop_price}")

    sizing = ctx["rule"].get("sizing")
    sizing = sizing if isinstance(sizing, dict) else {}
    rule_pct = (sizing.get("riskPercent")
                if sizing.get("mode") == _rd.SIZING_RISK else None)
    mode_pct = PLATFORM["maxRiskPercentLive" if ctx["mode"] == "live"
                        else "maxRiskPercentDemo"]
    cap_pct = _cap(rule_pct, mode_pct)

    ctx["facts"]["riskMoney"] = money
    ctx["facts"]["riskPercent"] = round(money / bal * 100.0, 6)
    ctx["facts"]["riskCapPercent"] = cap_pct
    if money > _cents(cap_pct / 100.0 * bal):
        # Which cap bit decides what the client can do about it. Their own
        # number is editable; the platform's is not, and telling them to edit
        # a rule that is already inside its own limit would be wrong.
        over_rule = _pos(rule_pct) and cap_pct == float(rule_pct)
        return (("RISK_OVER_RULE" if over_rule else "RISK_OVER_PLATFORM_CAP"),
                f"this order risks {money:.2f} of a {bal:.2f} balance "
                f"({ctx['facts']['riskPercent']:.4g}%), over the "
                f"{'rule' if over_rule else 'platform'} limit of {cap_pct:g}%")
    return None


def _g_daily_loss(ctx):
    """Today's realised loss against the limit. Enforced, finally.

    §5 records this as "recorded in the RuleDoc today and not enforced by any
    engine consumer". The denominator is the balance the day OPENED at, which
    is derived as today's balance minus today's realised result rather than
    taken as another input. What that assumes is no deposit or withdrawal
    today; what it buys is one less fact a caller can forget to supply, and
    the alternative — measuring against the balance as it falls — makes the
    limit tighten as the day goes badly, which is a different limit than the
    one the client was shown.
    """
    pnl = _fact(ctx["state"], "dailyRealisedPnl")
    if not _num(pnl):
        return ("DAILY_PNL_UNKNOWN",
                "today's realised result could not be read, so the daily loss "
                "limit cannot be checked")
    bal = ctx["facts"]["balance"]
    start = _cents(bal - float(pnl))
    ctx["facts"]["dayStartBalance"] = start
    if start <= 0:
        return ("DAILY_PNL_UNKNOWN",
                f"today's opening balance works out as {start:.2f}, which "
                f"cannot be the denominator of a loss percentage")
    cap_pct = _cap((ctx["rule"].get("limits") or {}).get("maxDailyLossPercent"),
                   PLATFORM["maxDailyLossPercent"])
    lost = _cents(-float(pnl))
    ctx["facts"]["dailyLossPercent"] = round(max(0.0, lost) / start * 100.0, 6)
    ctx["facts"]["dailyLossCapPercent"] = cap_pct
    # >= and not >: the number is where the client said to stop, so arriving
    # at it stops. A limit that only bites once it has been passed lets the
    # account through the figure it promised to hold.
    if lost > 0 and lost >= _cents(cap_pct / 100.0 * start):
        return ("DAILY_LOSS_REACHED",
                f"today is down {lost:.2f} on an opening balance of "
                f"{start:.2f} ({ctx['facts']['dailyLossPercent']:.4g}%), at "
                f"or past the {cap_pct:g}% daily loss limit")
    return None


def _g_drawdown(ctx):
    """Balance against its own high-water mark.

    The gate does NOT update the peak. `gates.authorize_order` makes the same
    point about the risk guard: a check must not move the thing it is
    checking, or the first call quietly redefines what the second one measures.
    Whoever owns the peak advances it.
    """
    peak = _fact(ctx["state"], "peakBalance")
    if not _pos(peak):
        return ("PEAK_BALANCE_UNKNOWN",
                "the account's high-water balance could not be read, so the "
                "drawdown limit cannot be checked")
    bal = ctx["facts"]["balance"]
    ctx["facts"]["peakBalance"] = float(peak)
    down = _cents(max(0.0, float(peak) - bal))
    cap_pct = _cap((ctx["rule"].get("limits") or {}).get("maxDrawdownPercent"),
                   PLATFORM["maxDrawdownPercent"])
    ctx["facts"]["drawdownPercent"] = round(down / float(peak) * 100.0, 6)
    ctx["facts"]["drawdownCapPercent"] = cap_pct
    if down > 0 and down >= _cents(cap_pct / 100.0 * float(peak)):
        return ("DRAWDOWN_REACHED",
                f"the balance is {down:.2f} below its peak of {peak:.2f} "
                f"({ctx['facts']['drawdownPercent']:.4g}%), at or past the "
                f"{cap_pct:g}% drawdown limit")
    return None


def _g_daily_trades(ctx):
    """How many orders were OPENED today, against the rule's cap.

    The fact is deliberately not "trades closed today". See the module
    docstring: that is the `5/4` the specification names, and it is a fact
    bug rather than a comparison bug.
    """
    cap = (ctx["rule"].get("limits") or {}).get("maxDailyTrades")
    if not _pos(cap):
        # The rule form says in so many words: "Leave a field empty for no
        # cap". Substituting a default would enforce a number the client never
        # saw, which is the mirror image of the defect this file closes.
        return WAIVED
    opened = _fact(ctx["state"], "dailyTradesOpened")
    if not _num(opened) or opened < 0:
        return ("DAILY_TRADES_UNKNOWN",
                "the number of orders opened today could not be read, so the "
                "daily trade cap cannot be checked")
    ctx["facts"]["dailyTradesOpened"] = int(opened)
    ctx["facts"]["dailyTradesCap"] = int(cap)
    if int(opened) >= int(cap):
        return ("DAILY_TRADES_REACHED",
                f"{int(opened)} of {int(cap)} orders allowed today have "
                f"already been opened")
    return None


def _positions(ctx):
    """The open positions, or a (code, detail) refusal. Never a guess.

    An absent list is not an empty one. `broker_read` makes the same
    distinction for the same reason: "you have nothing open" is a claim, and
    it is only true when the broker was actually asked.
    """
    rows = _fact(ctx["state"], "positions")
    if not isinstance(rows, list):
        return None, ("POSITIONS_UNKNOWN",
                      "the account's open positions could not be read, so the "
                      "position and exposure limits cannot be checked")
    return [r for r in rows if isinstance(r, dict) and r.get("symbol")], None


def _g_open_positions(ctx):
    rows, refusal = _positions(ctx)
    if refusal:
        return refusal
    cap = (ctx["rule"].get("limits") or {}).get("maxOpenPositions")
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        # `ruledoc.validate` requires an integer >= 1, so a rule arriving here
        # without one did not come through activation. Refusing beats
        # defaulting: a default would silently supply the one limit the rule
        # is guaranteed to carry.
        return ("MAX_POSITIONS_UNSTATED",
                "this rule does not state a maximum number of open positions")
    ctx["facts"]["openPositions"] = len(rows)
    ctx["facts"]["maxOpenPositions"] = cap
    if len(rows) >= cap:
        return ("AT_POSITION_LIMIT",
                f"the account is holding {len(rows)} of {cap} positions this "
                f"rule allows")
    return None


def _g_exposure(ctx):
    """Exposure on this instrument, measured as money at risk.

    NOT notional. 40,000 units of EUR_USD at 1.10 is $44,000 of notional and
    $100 of risk, so against a 10,000 account the two readings are 440% and
    1%. A client writing "max exposure 12%" in a product that sizes everything
    from risk percentages means the second number; enforcing the first would
    refuse essentially every leveraged order and look like a broken gate.

    A position whose stop cannot be read is refused rather than counted as
    zero. An open position with no stop has no bounded worst case at all,
    which is the thing the product refuses at activation — counting it as
    nothing would be the most wrong possible answer.
    """
    rows, refusal = _positions(ctx)
    if refusal:
        return refusal
    cap_pct = (ctx["rule"].get("limits") or {}).get("maxExposurePercent")
    if not _pos(cap_pct):
        return WAIVED
    it, bal = ctx["intent"], ctx["facts"]["balance"]
    total = ctx["facts"]["riskMoney"]
    sym = forex._norm(it.symbol)
    for r in rows:
        if forex._norm(r.get("symbol")) != sym:
            continue
        price, stop, units = (r.get("entryPrice"), r.get("stopLoss"),
                              r.get("units"))
        if not (_pos(price) and _pos(stop) and _pos(units)):
            return ("EXPOSURE_UNKNOWN",
                    f"an open {r.get('symbol')} position carries no stop or "
                    f"no size, so exposure on this instrument cannot be "
                    f"measured")
        money = _risk_money(r["symbol"], price, stop, units)
        if money is None:
            return ("EXPOSURE_UNKNOWN",
                    f"the risk on an open {r.get('symbol')} position could "
                    f"not be measured")
        total = _cents(total + money)
    ctx["facts"]["instrumentExposureMoney"] = total
    ctx["facts"]["instrumentExposurePercent"] = round(total / bal * 100.0, 6)
    ctx["facts"]["instrumentExposureCapPercent"] = float(cap_pct)
    if total > _cents(float(cap_pct) / 100.0 * bal):
        return ("INSTRUMENT_EXPOSURE_EXCEEDED",
                f"this order would put {total:.2f} at risk on {it.symbol}, "
                f"{ctx['facts']['instrumentExposurePercent']:.4g}% of a "
                f"{bal:.2f} balance, over the {float(cap_pct):g}% this rule "
                f"allows on one instrument")
    return None


def _g_correlated_exposure(ctx):
    """Positions that are the same bet wearing different tickets.

    BUY EUR_USD, BUY GBP_USD and SELL EUR_GBP are not three independent
    risks — two of them are the same bet against the dollar. The model is the
    dollar leg, and the primitive is `forex.usd_exposure`, which the legacy
    loop's correlation guard already uses through `apex/portfolio.py`.

    `portfolio.check` is deliberately not called. It bundles three policies —
    this one, a position cap, and a refusal of any second position on the same
    instrument — and reads an exposure dict built from the engine's published
    dash, which the platform does not publish. Sharing the function would mean
    sharing the dash; sharing the primitive shares the thing worth sharing,
    which is the definition of "same bet".

    It is a proxy and not a correlation matrix. It says nothing about EUR_GBP
    against EUR_CHF and it puts gold in its own bucket. Estimating real
    covariance from the history this platform keeps would produce a number
    that looks authoritative and is not.
    """
    rows, refusal = _positions(ctx)
    if refusal:
        return refusal
    it = ctx["intent"]
    bias = forex.usd_exposure(it.symbol, it.side)
    ctx["facts"]["usdSide"] = bias
    if not bias:
        # No dollar leg: a cross or a metal, which this proxy cannot speak
        # about. Recorded as waived rather than passed, so nobody reads an
        # authorisation here as "we checked the correlation and it was fine".
        return WAIVED
    cap = (ctx["rule"].get("limits") or {}).get("maxSameUsdSide")
    cap = int(cap) if _pos(cap) else PLATFORM["maxSameUsdSide"]
    same = sum(1 for r in rows
               if forex.usd_exposure(r.get("symbol") or "",
                                     r.get("side") or "") == bias)
    ctx["facts"]["sameUsdSide"] = same
    ctx["facts"]["maxSameUsdSide"] = cap
    if same >= cap:
        way = "long USD" if bias > 0 else "short USD"
        return ("CORRELATED_EXPOSURE",
                f"this would be another {way} position on top of {same}, and "
                f"this rule allows {cap} on one side of the dollar")
    return None


def _g_spread(ctx):
    cap = (ctx["rule"].get("limits") or {}).get("maxSpreadPips")
    if not _pos(cap):
        return WAIVED
    spread = _fact(ctx["state"], "spreadPips")
    if not _num(spread) or spread < 0:
        return ("SPREAD_UNKNOWN",
                "the current spread could not be read, so the spread ceiling "
                "cannot be checked")
    ctx["facts"]["spreadPips"] = float(spread)
    ctx["facts"]["maxSpreadPips"] = float(cap)
    # Strictly wider, which is what the rule form promises the client:
    # "entries are blocked while the spread is wider".
    if float(spread) > float(cap):
        return ("SPREAD_TOO_WIDE",
                f"the spread is {float(spread):g} pips and this rule stops "
                f"entering above {float(cap):g}")
    return None


def _g_slippage(ctx):
    """How far the price has moved since the decision, against the ceiling.

    This is the half of a slippage ceiling the platform CAN enforce, and it is
    not the same question `execution.from_decision` answers. That one refuses
    a rule asking for `maxSlippagePoints` because the connector cannot bind
    the ceiling to the FILL — it would send a plain market order and the client
    would believe a protection applied that never did. This one checks, before
    anything is sent, that the price we are about to trade is still near the
    price the decision was made at. Both are needed and neither replaces the
    other: one is about what the broker guarantees, the other about what we
    already know.
    """
    order = ctx["rule"].get("order")
    cap = (order or {}).get("maxSlippagePoints") if isinstance(order, dict) \
        else None
    if not _pos(cap):
        return WAIVED
    slip = _fact(ctx["state"], "slippagePoints")
    if not _num(slip) or slip < 0:
        return ("SLIPPAGE_UNKNOWN",
                "the price movement since the decision could not be measured, "
                "so the slippage ceiling cannot be checked")
    ctx["facts"]["slippagePoints"] = float(slip)
    ctx["facts"]["maxSlippagePoints"] = float(cap)
    if float(slip) > float(cap):
        return ("SLIPPAGE_OVER_CEILING",
                f"the price has moved {float(slip):g} points since this "
                f"decision was made and this rule accepts {float(cap):g}")
    return None


_RUN = {
    "inputs": _g_inputs,
    "order_type": _g_order_type,
    "stop": _g_stop,
    "balance": _g_balance,
    "risk_per_trade": _g_risk_per_trade,
    "daily_loss": _g_daily_loss,
    "drawdown": _g_drawdown,
    "daily_trades": _g_daily_trades,
    "open_positions": _g_open_positions,
    "exposure": _g_exposure,
    "correlated_exposure": _g_correlated_exposure,
    "spread": _g_spread,
    "slippage": _g_slippage,
}


def authorize(rule_doc, intent, *, mode, balance_reader, state=None,
              platform=None):
    """The one gate. Returns a `Verdict`; never raises, never places anything.

    Args:
        rule_doc: the frozen ACTIVE RuleDoc whose limits are being enforced.
        intent: an `OrderIntent` — what is being asked for.
        mode: 'demo' or 'live'. Not defaulted, and anything else refuses.
        balance_reader: callable returning the account balance, read now. §5
            requires it live and uncached, so there is no parameter that takes
            a number instead.
        state: the facts the gates measure against — positions,
            dailyRealisedPnl, dailyTradesOpened, peakBalance, spreadPips,
            slippagePoints. A fact that is absent refuses the gate that needs
            it; see `REQUIRED_FACTS`.
        platform: overrides for the floors in `PLATFORM`, for an operator or a
            test that needs to state them exactly.

    Stops at the first refusal. The remaining gates are reported SKIPPED
    rather than run, because a gate's measurement is only meaningful if
    everything before it held — and because running the rest would mean a
    refusal carrying nine codes, of which the caller could act on one.
    """
    ctx = {
        "rule": rule_doc,
        "intent": intent if isinstance(intent, OrderIntent)
        else OrderIntent(symbol=None, side=None),
        "mode": mode,
        "balance_reader": balance_reader,
        "state": state if isinstance(state, dict) else {},
        "facts": {},
    }
    saved = dict(PLATFORM)
    if platform:
        PLATFORM.update(platform)
    checks = []
    try:
        for i, gate in enumerate(GATES):
            try:
                out = _RUN[gate](ctx)
            except Exception as e:                          # noqa: BLE001
                # A bug in a gate is not a way to open a position. Every other
                # branch in this file fails closed; so does this one.
                out = (CHECK_FAILED[gate],
                       f"this check could not be completed — "
                       f"{type(e).__name__}: {str(e)[:120]}")
            if out is None or out == WAIVED:
                checks.append({"gate": gate,
                               "state": WAIVED if out == WAIVED else PASSED})
                continue
            code, detail = out
            checks.append({"gate": gate, "state": REFUSED})
            checks += [{"gate": g, "state": SKIPPED} for g in GATES[i + 1:]]
            return Verdict(False, gate=gate, code=code, detail=detail,
                           checks=checks, facts=ctx["facts"], mode=mode)
    finally:
        PLATFORM.clear()
        PLATFORM.update(saved)
    return Verdict(True, code="AUTHORIZED",
                   detail=f"every gate in §5 held for {ctx['intent'].side} "
                          f"{ctx['intent'].symbol}",
                   checks=checks, facts=ctx["facts"], mode=mode)
