"""Turning a rule into the settings the loop actually reads.

THE PROBLEM THIS SOLVES

A client builds a rule — risk 1% per trade, a 25-pip stop, a 50-pip target —
activates it, presses Start, and the loop trades their account's own stored
settings instead. `automation.start` carried exactly two fields across, the
instrument and the timeframe, and the rest of the rule was a document the
product displayed and the engine ignored.

`tests/test_rule_reaches_engine.py` measures that gap. This file closes the
part of it that can be closed faithfully.

THE RULE THIS FILE FOLLOWS

**Translate only what maps exactly. Report everything else.**

The engine's configuration is not a superset of a RuleDoc. It has no key for a
reward-to-risk target, no key for an ATR multiple, and it forces one open
position on a practice account. For each of those, there are two wrong answers
and one right one:

  wrong   apply something near enough — the client asked for 2R and gets the
          engine's fixed 1:2, and nothing on any screen says so
  wrong   refuse to start — the builder's own default rule uses an ATR stop
          and an RR target, so this would refuse the product's own output
  right   apply what maps, and say which terms did not, per rule, in words
          the client can read on the screen that shows them

So `translate()` returns both halves and the caller is expected to carry the
second one to the client. `automation.start` records it; the rule page renders
it. A term that silently does nothing is the defect; a term that visibly does
nothing is a known limitation.

RESTORING

`snapshot_of()` captures the engine keys this module is about to overwrite, so
stopping can put them back. Without it, a rule that ran once leaves its
settings on the account for whatever runs next — which was already true of the
instrument and the timeframe before this file existed.
"""

from apex.platform import ruledoc as _rd

# Every engine key this module may write. Nothing outside this set is touched,
# and `snapshot_of` captures exactly these — the two have to be the same list
# or a restore puts back less than the start overwrote.
OWNED_KEYS = (
    "symbol", "timeframe",
    "risk", "sl_pips", "tp_pips", "tp_target_pct", "atr_stops",
    "trailing", "breakeven_r", "max_trades_day", "max_spread_pips",
)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def translate(doc):
    """(applied, not_applied) for one RuleDoc.

    `applied` is engine keys to write. `not_applied` is a list of
    {term, value, why} — each one a term the client set that this release will
    not act on, with the reason stated the way they would need it explained.
    """
    doc = doc or {}
    applied = {}
    missed = []

    def miss(term, value, why):
        missed.append({"term": term, "value": value, "why": why})

    # ── instrument and timeframe ────────────────────────────────────────────
    symbols = [s for s in (doc.get("symbols") or []) if s]
    if symbols:
        applied["symbol"] = symbols[0]
        if len(symbols) > 1:
            miss("Instruments", ", ".join(symbols[1:]),
                 f"The engine trades one instrument at a time, so only "
                 f"{symbols[0]} is traded. The others are recorded on the "
                 f"rule and are not watched.")
    if doc.get("timeframe"):
        applied["timeframe"] = doc["timeframe"]

    # ── sizing ──────────────────────────────────────────────────────────────
    # The most consequential field in the document. A client who sets 1% and
    # gets the account's stored 4% is risking four times what they chose.
    sizing = doc.get("sizing") or {}
    if sizing.get("mode") == _rd.SIZING_RISK and _num(sizing.get("riskPercent")):
        applied["risk"] = float(sizing["riskPercent"]) / 100.0
    elif sizing.get("mode") == _rd.SIZING_FIXED:
        miss("Sizing", f"fixed volume {sizing.get('fixedVolume')}",
             "The engine sizes every position from a risk percentage and has "
             "no setting for a fixed volume, so your account's risk "
             "percentage is used instead.")

    # ── stop ────────────────────────────────────────────────────────────────
    sl = doc.get("stopLoss") or {}
    if sl.get("mode") == "pips" and _num(sl.get("pips")):
        applied["sl_pips"] = float(sl["pips"])
        applied["atr_stops"] = False
    elif sl.get("mode") == "atr":
        # The engine can be told to use ATR stops; it cannot be told WHICH
        # multiple. Applying the switch and dropping the number would be the
        # near-enough answer this file exists to avoid, so the switch is
        # applied and the number is reported.
        applied["atr_stops"] = True
        if _num(sl.get("atrMultiple")):
            miss("Stop loss", f"{sl['atrMultiple']}× ATR",
                 "The engine places stops from ATR, but its multiple is not "
                 "configurable per rule, so it uses its own. Set the stop in "
                 "pips to have this rule's number used exactly.")

    # ── target ──────────────────────────────────────────────────────────────
    tp = doc.get("takeProfit") or {}
    if tp.get("mode") == "pips" and _num(tp.get("pips")):
        applied["tp_pips"] = float(tp["pips"])
        # A balance-percentage target would override the pip target silently.
        applied["tp_target_pct"] = 0
    elif tp.get("mode") == "rr":
        miss("Take profit", f"{tp.get('rr')}R",
             "The engine has no setting for a reward-to-risk target; it "
             "derives the target from the stop. Set the target in pips to "
             "have this rule's number used exactly.")

    # ── management ──────────────────────────────────────────────────────────
    trail = doc.get("trailingStop") or {}
    if isinstance(trail.get("enabled"), bool):
        applied["trailing"] = bool(trail["enabled"])
        if trail["enabled"] and _num(trail.get("atrMultiple")):
            miss("Trailing stop", f"{trail['atrMultiple']}× ATR",
                 "Trailing is switched on, but its distance is not "
                 "configurable per rule — the engine uses its own.")

    be = doc.get("breakEven") or {}
    if isinstance(be.get("enabled"), bool):
        # 0 is the engine's "off", so this expresses both states in one key.
        applied["breakeven_r"] = (float(be["atR"])
                                  if be["enabled"] and _num(be.get("atR"))
                                  else 0.0)

    # ── limits ──────────────────────────────────────────────────────────────
    limits = doc.get("limits") or {}
    if _num(limits.get("maxDailyTrades")):
        applied["max_trades_day"] = int(limits["maxDailyTrades"])
    if _num(limits.get("maxSpreadPips")):
        applied["max_spread_pips"] = float(limits["maxSpreadPips"])
    mop = limits.get("maxOpenPositions")
    if _num(mop) and int(mop) > 1:
        # user_loop forces one open position on a practice account. Writing a
        # higher number would be a setting the client can see and the engine
        # will not honour, which is the whole class of defect this closes.
        miss("Max open positions", str(int(mop)),
             "A demo account holds one position at a time in this release, "
             "whatever the rule says.")

    # ── what the engine simply does not take from a rule ────────────────────
    entry = (doc.get("entry") or {}).get("conditions") or []
    if entry:
        miss("Entry conditions", f"{len(entry)} condition(s)",
             "The engine chooses entries with its own strategies. Your "
             "conditions are recorded on the rule and are not what it looks "
             "for — carrying them through is the next milestone.")
    exits = (doc.get("exit") or {}).get("conditions") or []
    if exits:
        miss("Exit conditions", f"{len(exits)} condition(s)",
             "The engine closes on its own exits, the stop and the target. "
             "Your exit conditions are recorded and not acted on.")
    if doc.get("sides") and doc["sides"] != "BOTH":
        miss("Sides", str(doc["sides"]),
             "The engine takes both directions when its strategy signals "
             "them; it has no per-rule setting for one side only.")
    sched = doc.get("schedule") or {}
    if sched.get("days") or sched.get("windows"):
        miss("Schedule", "set",
             "The engine filters by trading session, not by the days and "
             "time windows a rule records, so this rule's schedule is not "
             "applied.")
    order = doc.get("order") or {}
    if order.get("maxSlippagePoints") or order.get("expiresAfterSec"):
        miss("Order constraints", "set",
             "Slippage ceilings and order expiry are recorded on the rule and "
             "are not applied by this release's execution path.")

    return applied, missed


def snapshot_of(record):
    """The current value of every key `translate` may write.

    Keys that are absent are captured as absent, so a restore removes what the
    start added rather than leaving a default behind that was never there.
    """
    record = record or {}
    return {k: record[k] for k in OWNED_KEYS if k in record}


def restore_patch(snapshot):
    """A patch that puts `snapshot` back and clears what it did not contain.

    `None` for a key the snapshot did not hold — the caller's store treats
    that as "set to nothing", which is as close to "absent" as a patch gets,
    and is honest: the account had no such setting before the rule ran.
    """
    snapshot = snapshot or {}
    return {k: snapshot.get(k) for k in OWNED_KEYS}
