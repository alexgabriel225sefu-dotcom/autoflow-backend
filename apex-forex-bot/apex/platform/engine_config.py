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

from apex.platform import risk_gates as _rg
from apex.platform import ruledoc as _rd

# The strategy module that asks the rule. Declared here, as a plain string,
# because `apex.platform.rule_strategy` reads it to name itself and importing
# that module from here would close a cycle (it reaches automation, which
# reaches this file).
RULE_STRATEGY_ID = "platform_rule"

# Every engine key this module may write. Nothing outside this set is touched,
# and `snapshot_of` captures exactly these — the two have to be the same list
# or a restore puts back less than the start overwrote.
#
# The second line is the engine's own decision-making, switched off. A rule
# that reaches the loop is only driving it if nothing else can overrule it, so
# those keys are owned for the same reason the trading terms are: whatever the
# account held must come back when the rule stops.
OWNED_KEYS = (
    "symbol", "timeframe",
    "risk", "sl_pips", "tp_pips", "tp_target_pct", "atr_stops",
    "trailing", "breakeven_r", "max_trades_day", "max_spread_pips",
    # The day's loss ceiling. Owned so a rule that tightened it gives the
    # account's own number back when it stops.
    "max_daily_loss_pct",
    "strategy", "ai_confirm", "min_confidence", "htf", "autopilot",
    "watchlist", "session_filter",
    # Owned for the same reason as the rest: whatever level the account held
    # must come back when the rule stops. It is in OWNED_KEYS so `snapshot_of`
    # captures it — the two lists have to agree or a restore puts back less
    # than the start overwrote.
    #
    # `copilot` is the SAME setting, in the key the engine still reads first.
    # Both are written, and both therefore have to be restored: putting back
    # the level and leaving the boolean behind would hand the account to the
    # resolution described in `_automation_patch` — the two disagreeing, with
    # the boolean winning.
    "automation", "copilot",
)

# The engine levels, by name rather than by string literal at the call site.
# `apex.automation` owns these; they are repeated here rather than imported
# because importing it would close a cycle (it reaches this file).
LEVEL_SIGNALS = "signals"
LEVEL_APPROVAL = "approval"
LEVEL_FULL = "full"
# What the PLATFORM can service today. A level on this list is one a client
# can be ASKED at and can ANSWER on this product; a level that is not is how
# the loop went silent, so nothing goes on here before both halves exist.
#
# `approval` was absent for exactly that reason — the engine's approval step
# proposes through `alert_fn` and then waits, and `automation.start` passed no
# alert function while the only approve action in the codebase was a Telegram
# tap. Both halves exist now:
#
#   the ask      `automation._engine_starter` starts the loop with
#                `approvals.engine_alert`, which turns the engine's SUGGEST
#                into a notification the client can read
#   the answer   `approvals.approve` / `.reject`, reachable at
#                POST approvals/approve and POST approvals/reject, with the
#                proposal itself readable at GET approvals and rendered on
#                the dashboard
#
# `approve` places the trade through `user_loop.force_trade`, the controller
# every other order origin already converges on — there is no second
# execution path, which is the condition under which this list may grow at
# all. tests/test_platform_approvals.py measures the whole path, and
# tests/test_platform_live_invariants.py pins that `approvals` is the only
# platform module permitted to name that controller.
#
# `signals` is on the list for the same reason and on the same evidence. It
# proposes nothing and places nothing, so servicing it is a matter of
# REPORTING the setup rather than answering it:
#
#   the report   `automation.engine_alert` offers every alert to
#                `signals.engine_alert`, which files a journal entry and one
#                notification saying nothing was placed
#   the screens  the journal filters `status=signal` and the notification
#                list filters `type=signal`
#
# `automation.DELIVERED_LEVELS` is the list of levels that have a sink behind
# that alert function, and tests/test_signals_only.py asserts the rule this
# whole field exists for, over all three levels: a level that neither
# executes nor is delivered must not be serviceable. Checked by running that
# test and reading the path, not taken on report.
#
# HOW A RULE ASKS, AND WHAT IS STILL MISSING. `automationLevel` is not a
# field in `ruledoc.blank` and `api._create` does not copy it, so for a while
# this comment said no client could choose a level. That was wrong, and
# measuring it is what settled it: `PUT /api/v1/rules/{id}` reaches
# `store.save_draft`, which merges whatever keys the patch carries, and the
# key then survives `activate` into the frozen version the loop is started
# from. The whole chain runs today —
#
#   PUT {"automationLevel": "approval"} → activate → translate writes
#   {"automation": "approval", "copilot": True} → apex.automation.mode reads
#   "approval" and executes() is False
#
# What is missing is a CONTROL: the rule builder has no level selector, so
# every rule it produces omits the key and runs at `full`. Whoever builds one
# must offer only what this tuple holds — a selector showing "Signals Only"
# while `_automation_level` returns `full` would place orders for a client who
# asked to be told and nothing more, which is worse than no control at all.
# Declaring the field in `ruledoc.blank` belongs with that work.
SERVICEABLE_LEVELS = (LEVEL_SIGNALS, LEVEL_APPROVAL, LEVEL_FULL)


def _automation_level(doc):
    """The engine level this rule runs at.

    Reads the rule rather than assuming, so the client's choice has somewhere
    to live the moment there is a control for it — but refuses to return a
    level the platform cannot actually service. A level nobody here can
    answer is how the loop went quiet in the first place.
    """
    want = str((doc or {}).get("automationLevel") or "").strip().lower()
    return want if want in SERVICEABLE_LEVELS else LEVEL_FULL


def _preset_strategy(doc):
    """The engine strategy id this rule should be run BY, or "".

    "" means a rule built from conditions, which `rule_strategy` runs.

    Only ever returns an id the platform both describes and the engine has
    registered — `strategy_catalog.ids()` is that intersection. An id outside
    it would be written onto the account as `cfg.STRATEGY` and the loop would
    hold every bar with "no strategy module is loaded for ...", which is the
    quiet failure this whole module exists to stop.

    Imported inside the function for the same reason `store._offered_strategy_ids`
    does it: `strategy_catalog` reaches the engine registry, which reaches
    `platform.rule_strategy`, which reaches this module. The cycle is resolved
    at call time and not at import time.

    A catalogue that cannot be read answers "" — the rule then runs as a
    condition rule and `translate` reports the preset as a term that is not
    being applied. Fail-closed, and visibly so.
    """
    named = str((doc or {}).get("strategy") or "").strip()
    if not named:
        return ""
    try:
        from apex.platform import strategy_catalog
        return named if named in strategy_catalog.ids() else ""
    except Exception as e:                                   # noqa: BLE001
        print(f"[ENGINE_CONFIG] the strategy catalogue could not be read "
              f"({type(e).__name__}) — not pointing the loop at {named!r}")
        return ""


def _automation_patch(level):
    """EVERY key the engine reads to resolve the level, in agreement.

    THERE ARE TWO OF THEM, AND WRITING ONE IS A SILENT SUBSTITUTION.

    `apex.automation.mode()` reads `automation` and the legacy `copilot`
    boolean, and when the two CONTRADICT it honours the boolean — deliberately,
    because `/copilot` and the MCP control plane still write it and ignoring a
    client's instruction would be worse.

    An absent boolean is False. So a record carrying `automation: "approval"`
    and no `copilot` resolves to **full**: the loop would trade UNATTENDED on
    an account whose own record says it must ask first. Writing the level
    alone was harmless while `full` was the only level this file could write
    (False and False agree) and became the most expensive bug in the product
    the moment `approval` went on SERVICEABLE_LEVELS — and an invisible one,
    because every assertion about what `translate` WRITES still passed. It was
    caught by asking what the ENGINE RESOLVES, which is the question commit
    6f984dfe9 added for the same reason.

    `apex.automation.patch` is the one definition of the two keys agreeing, so
    it is called rather than restated here. It raises on a level it does not
    know; `_automation_level` only ever returns one from SERVICEABLE_LEVELS,
    which is a subset of its MODES.
    """
    # Imported inside the function rather than at the top of the file. The
    # module one letter away in that import line — `apex.platform.automation`
    # — reaches this file, so the cycle the header comment warns about is one
    # mistyped import away; keeping it here keeps module import order out of
    # it entirely.
    from apex import automation as _engine_automation
    return _engine_automation.patch(level)


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

    # ── the loop is pointed at the rule, and at nothing else ────────────────
    # `cfg.STRATEGY` is per-account, so this is what makes one account's loop
    # ask its running rule instead of choosing entries with the engine's own
    # strategies. Every key beside it is a gate that would otherwise decide
    # instead of the rule, and each is switched off for a specific reason:
    #
    #   ai_confirm      the loudest. With it on, the loop DISCARDS the
    #                   strategy's BUY and calls ai.get_signal() for its own,
    #                   which can hold or reverse it.
    #   min_confidence  a rule fires or it does not; there is no probability
    #                   behind it, so any threshold above zero refuses every
    #                   entry forever.
    #   htf             an H1-trend veto blocks entries the rule asked for.
    #   autopilot       the engine rotates its own instruments, overriding the
    #                   instrument the rule names.
    #   watchlist       the basket that rotation draws from.
    #
    # `session_filter` is deliberately NOT written. It is the account's own
    # setting and it is not this rule's schedule. A condition rule's days
    # and windows are enforced by the evaluator; a preset never goes
    # through that path, so its schedule is reported below when set.
    # Clearing the account filter would widen trading past what the client
    # chose.
    # A PRESET RULE IS POINTED AT ITS PRESET. THIS WAS THE MISSING HAND-OFF,
    # AND WITHOUT IT THE WHOLE STRATEGY PICKER PLACED NOTHING, FOREVER.
    #
    # `strategy_catalog.preset_of` says the field is judged "at the
    # boundaries that care — activation, and the engine hand-off". Activation
    # was wired. The hand-off was not: this line wrote RULE_STRATEGY_ID
    # unconditionally and never read the document's preset.
    #
    # So a client who chose "Choose a strategy", picked a preset, activated
    # and pressed Start got a loop pointed at `platform_rule`, which asks the
    # rule evaluator — and the evaluator refuses a preset document with
    # PRESET_STRATEGY on every bar, because a preset carries no conditions to
    # judge. The dashboard said "Watching market". The journal filled with
    # holds. Nothing ever traded, and no screen said why.
    #
    # That refusal was correct as a safety net while nothing routed presets.
    # It is not a substitute for routing them.
    #
    # The ids are the ENGINE's own registered strategies — `_registry` reads
    # `strategy_api.describe()` and `describe()` returns only the
    # intersection — so this points the loop at strategy modules that have
    # run in this engine for a long time, with the client's own risk terms
    # applied below. It is a route, not a new trading mechanism.
    _preset = _preset_strategy(doc)
    if _preset:
        applied["strategy"] = _preset
    else:
        applied["strategy"] = RULE_STRATEGY_ID
        # A document naming a preset the platform no longer offers must not
        # be pointed at it — the loop would hold every bar naming a strategy
        # no module is loaded for. Activation already refuses an unoffered
        # id, so this is the withdrawn-after-activation case, and it is
        # REPORTED rather than swallowed: falling back silently is what
        # produced the bug above.
        _named = str(doc.get("strategy") or "").strip()
        if _named:
            miss("Strategy", _named,
                 "this strategy is no longer offered on the platform, so the "
                 "rule is not being run by it. Open the rule and choose a "
                 "strategy that is still available, or rebuild it from "
                 "conditions.")
    applied["ai_confirm"] = False
    applied["min_confidence"] = 0
    applied["htf"] = False
    applied["autopilot"] = False
    applied["watchlist"] = []
    # ── THE ONE THAT WAS MISSING, AND IT STOPPED THE PRODUCT WORKING ───────
    #
    # `automation` is the engine's level: signals / approval / full. It was
    # not written here, so a platform client's record carried neither it nor
    # the legacy `copilot` boolean — and `automation.mode()` resolves THAT
    # state to "approval", deliberately, because for a Telegram client it
    # means nobody had chosen and unattended trading is the wrong default.
    #
    # For a platform client it meant something else entirely. In approval
    # mode the loop calls `_suggest_trade`, which stores a pending proposal,
    # calls `alert_fn` — None, because `automation.start` starts the loop
    # without one — and sets entry_ok = False. So every platform client,
    # demo and live, ran a loop that evaluated their rule, found setups,
    # wrote a suggestion nobody could see, notified nobody, and placed
    # NOTHING. Press Start, watch it say Running, and wait forever.
    #
    # Written as `full` because on this product pressing Start on a rule the
    # client wrote, validated, activated and then confirmed IS the
    # instruction to trade it — and unlike Telegram there is no second
    # channel to go back and ask on. The level a client can CHOOSE is the
    # next piece of work; what is fixed here is that the platform must never
    # leave it to a default it cannot service.
    #
    # BOTH keys, not just `automation`. The engine resolves the level from
    # that key AND the legacy `copilot` boolean, and an absent boolean beats a
    # stored "approval" — see `_automation_patch`, which is where this
    # resolution and what it costs are written down.
    applied.update(_automation_patch(_automation_level(doc)))

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
    # The day's loss ceiling: the engine stops entering once today's result is
    # this far below the day's opening balance (`strategies.should_stop`). The
    # platform's own ceiling still holds, so a rule asking for more than it is
    # held to it and says so, rather than being told a number it will not get.
    dl = limits.get("maxDailyLossPercent")
    if _num(dl) and dl > 0:
        ceiling = float(_rg.PLATFORM["maxDailyLossPercent"])
        applied["max_daily_loss_pct"] = min(float(dl), ceiling)
        if float(dl) > ceiling:
            miss("Max daily loss", f"{float(dl):g}%",
                 f"The platform stops a day at {ceiling:g}% whatever a rule "
                 f"asks for, so {ceiling:g}% is what applies.")
    mop = limits.get("maxOpenPositions")
    if _num(mop) and int(mop) > 1:
        # user_loop forces one open position on a practice account. Writing a
        # higher number would be a setting the client can see and the engine
        # will not honour, which is the whole class of defect this closes.
        miss("Max open positions", str(int(mop)),
             "A demo account holds one position at a time in this release, "
             "whatever the rule says.")

    # `onLimit: "flatten"` promises to close open positions when a limit is hit.
    # Nothing in the loop or the evaluator does that: a limit only refuses NEW
    # entries (`evaluator._limit_problem`), whichever way this is set. Named
    # per rule, because it is true only of a rule that asked for it.
    if limits.get("onLimit") == "flatten":
        miss("When a limit is hit", "close open positions",
             "This release only refuses new entries when a limit is hit. It "
             "does not close positions that are already open: they stay at "
             "your broker with their stop and target and keep being managed.")

    # ── what the engine simply does not take from a rule ────────────────────
    # Entry conditions, exit conditions and sides USED to be reported here:
    # the engine chose entries with its own strategies and a rule's conditions
    # were a document the product displayed and the loop ignored. They now
    # reach the loop through `rule_strategy`, so reporting them would tell a
    # client their terms do nothing when they do.
    #
    # What is left is about TIMING and SIZE, and it is still not exact. Each of
    # these is true of every rule, so each is reported for every rule rather
    # than inferred from the document.
    miss("Evaluation timing", str((doc.get("evaluateOn") or "bar_close")),
         "Your conditions are checked on closed candles, but the loop checks "
         "them on its own polling cycle rather than at the instant a candle "
         "closes. A rule can therefore act a few seconds into the next "
         "candle, at the price available then.")
    miss("Exit timing", "when the next check runs",
         "Your exit conditions are checked on the same cycle as entries, and "
         "the stop and the target sit at the broker where they act "
         "immediately. A stop or target can therefore close a position before "
         "an exit condition is next looked at.")
    miss("Position size", "derived from your risk percentage",
         "The engine sizes each position from your risk percentage and then "
         "rounds it to a volume the broker accepts, so the amount risked is "
         "close to the percentage you set rather than exactly it.")
    sched = doc.get("schedule") or {}
    if _preset and (sched.get("days") or sched.get("windows")):
        miss("Schedule", "set",
             "A strategy rule is not run by the condition evaluator, so "
             "its days and time windows are not applied. The engine's own "
             "session filter is left as the account already had it.")
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


# The risk per trade the engine uses when a rule does not state one, which is
# `user_loop`'s own default for an account that holds no `risk` key.
ENGINE_DEFAULT_RISK = 0.025


def names_capital(doc):
    """True when the rule names a positive capital allocation.

    Absent means the engine sizes against the whole balance, which is what
    every rule written before the field existed already does.
    """
    limits = (doc or {}).get("limits") if isinstance(doc, dict) else None
    if not isinstance(limits, dict):
        return False
    value = limits.get("capitalAllocated")
    return _num(value) and value > 0


def scale_risk_to_capital(applied, doc, balance):
    """(applied, state). Rebase `risk` onto the allocated capital.

    The engine sizes `risk` as a fraction of the whole balance. A client who
    allocated 1,000 of a 5,000 balance at 1% asked to risk 10, not 50. The
    fraction written to the account is scaled by min(balance, allocated) /
    balance so the money at risk is the money they named.

    `state` is None when nothing had to change or the scale was applied, and
    "unchecked" when the rule names an allocation and the balance cannot be
    used. The caller must not start in that case: leaving the unscaled
    fraction in place would risk more than the allocation.
    Never mutates `applied`.
    """
    if not names_capital(doc):
        return applied, None
    risk = (applied or {}).get("risk")
    if not _num(risk):
        return applied, None
    if not _num(balance) or balance <= 0:
        return dict(applied or {}), "unchecked"
    allocated = float(doc["limits"]["capitalAllocated"])
    base = min(float(balance), allocated)
    out = dict(applied)
    out["risk"] = float(risk) * (base / float(balance))
    return out, None


def live_refusals(doc, account):
    """Why a rule must NOT start on a LIVE account, as [(code, detail)].

    `translate` applies what maps and reports the rest, which is the right
    answer on a practice account: a term that visibly does nothing costs
    nothing there. On real money it is not enough, for two reasons that this
    function exists to close.

    1. THE RISK CAP WAS NOT ON THIS PATH. `risk_gates` holds the platform's
       live ceiling (1% per trade) and enforces it in `live_execution.place`,
       a door nothing in production calls. A live order from the loop takes the
       other door, `authorize_order`, which has no rule in hand. So a rule
       asking for 5% risk, or a rule with a fixed volume (which the engine
       cannot take, and which falls back to the ACCOUNT's own risk, 2.5% by
       default), reached a live broker at that size. The cap is therefore
       asked here, once, where the rule and the account are both in hand.

    2. A TERM THAT DOES NOTHING IS A PROMISE THAT IS NOT KEPT. An exposure
       ceiling, a slippage ceiling, an order expiry, or "close positions when a
       limit is hit" are recorded and not applied. Reporting that is honest on
       demo. A client who set a ceiling on real money is relying on it, and the
       loop would run without it.

    Refusing is the fail-closed answer, and the message names what to change so
    the client can start. Pure: no I/O, so it can be asked on every start,
    including a revive.
    """
    out = []
    doc = doc if isinstance(doc, dict) else {}
    account = account if isinstance(account, dict) else {}

    applied, _ = translate(doc)
    risk = applied.get("risk")
    source, fix = "this rule", "Lower the risk percentage"
    if not _num(risk):
        raw = account.get("risk")
        risk = float(raw) if _num(raw) else ENGINE_DEFAULT_RISK
        source = "this account's own setting (the rule has no risk percentage)"
        fix = "Size the rule by risk percentage"
    pct = round(float(risk) * 100.0, 6)
    cap = float(_rg.PLATFORM["maxRiskPercentLive"])
    if pct > cap:
        out.append((
            "LIVE_RISK_OVER_CAP",
            f"{source} risks {pct:g}% per trade and a live account is capped "
            f"at {cap:g}%. {fix} at {cap:g}% or less to start on a live "
            f"account."))

    limits = doc.get("limits") if isinstance(doc.get("limits"), dict) else {}
    order = doc.get("order") if isinstance(doc.get("order"), dict) else {}
    if _num(limits.get("maxExposurePercent")) and limits["maxExposurePercent"] > 0:
        out.append((
            "LIVE_TERM_NOT_ENFORCED",
            "The maximum exposure limit is recorded on the rule and is not "
            "enforced by the engine, so it cannot protect a live account. "
            "Clear it to start."))
    if _num(order.get("maxSlippagePoints")) or _num(order.get("expiresAfterSec")):
        out.append((
            "LIVE_TERM_NOT_ENFORCED",
            "The slippage ceiling and the order expiry are recorded on the "
            "rule and are not applied to orders, so they cannot protect a "
            "live account. Clear them to start."))
    if limits.get("onLimit") == "flatten":
        out.append((
            "LIVE_TERM_NOT_ENFORCED",
            "\"Close open positions when a limit is hit\" is not something "
            "the engine does: a limit only stops new entries. Set the limit "
            "action to block to start on a live account."))
    return out
