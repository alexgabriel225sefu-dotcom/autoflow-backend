"""RuleDoc — what the client configured, frozen once it goes live.

THE ONE RULE THIS FILE ENFORCES: an invalid RuleDoc cannot be activated.

`validate()` returns every problem it finds rather than the first, because a
client fixing a form wants the whole list, not one error at a time. `activate()`
calls it and refuses on any error — there is no force flag, and adding one
would defeat the point of the file.

IMMUTABILITY AFTER ACTIVATION. An active RuleDoc is frozen: changing it would
mean a position was opened under terms that no longer exist anywhere, and the
journal could not answer "what rule did this?" honestly. Editing an active doc
produces a NEW VERSION in `draft`; the old version stays exactly as it was.
"""

import json
import re
import time
import uuid

from apex import forex as _forex

# ── states ──────────────────────────────────────────────────────────────────
DRAFT = "draft"
ACTIVE = "active"
PAUSED = "paused"
ARCHIVED = "archived"
STATES = (DRAFT, ACTIVE, PAUSED, ARCHIVED)

# Only a draft may be edited. Everything else is history or a live commitment.
EDITABLE_STATES = (DRAFT,)

SIDES = ("BUY", "SELL", "BOTH")
ORDER_TYPES = ("MARKET", "LIMIT", "STOP")
COMBINE = ("AND", "OR")
# What happens when a limit is hit. "block" refuses new entries and keeps
# managing open ones; "flatten" closes out. Named rather than boolean because
# "stop" is ambiguous about existing positions.
ON_LIMIT = ("block", "flatten")

SIZING_FIXED = "fixed_volume"
SIZING_RISK = "risk_percent"
SIZING = (SIZING_FIXED, SIZING_RISK)

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class RuleDocInvalid(ValueError):
    """Raised on activation. Carries every problem, not just the first."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def new_id():
    return uuid.uuid4().hex


def normalise_symbols(doc):
    """The doc with its instruments in ONE canonical spelling.

    THE PROBLEM THIS SOLVES, SEEN ON A PHONE

    The instruments field is free text and was stored exactly as typed. An
    autocorrect produced `EURUSd` and the rule saved with it; `eurusd`,
    `EUR_USD` and `eur/usd` would each have stored differently too. Same
    instrument, four documents that do not compare equal — and the rule
    summary, the journal and the engine config all print back whatever was
    typed, so the client sees their own typo quoted as if it were a product
    term.

    `forex._norm` is the form the rest of this codebase already compares on:
    uppercase, separators removed. Normalising HERE rather than at each
    reader means there is one spelling in the store, which is the only way
    two rules on the same instrument can ever be recognised as such.

    Returns a new dict; the input is not mutated. Anything that is not a
    list of strings is left exactly as it was, so validation still reports
    the real problem instead of this function hiding it behind a TypeError.
    """
    syms = (doc or {}).get("symbols")
    if not isinstance(syms, list):
        return dict(doc or {})
    out, seen = [], set()
    for s in syms:
        if not isinstance(s, str):
            return dict(doc)            # let validate() report it properly
        # Stripped first: a phone keyboard adds a trailing space and
        #  does not remove whitespace, so " EURUSD " survived as its
        # own spelling. Found by the test that asserts all forms collapse.
        norm = _forex._norm(s.strip())
        if not norm or norm in seen:
            # A duplicate after normalising — `EURUSD, eurusd` — is one
            # instrument written twice, not two.
            continue
        seen.add(norm)
        out.append(norm)
    return dict(doc, symbols=out or syms)


def _err(problems, field, msg):
    problems.append(f"{field}: {msg}")


def _check_conditions(problems, where, conditions, *, required=True):
    """Shape only. Whether a condition ID is real is the library's question,
    asked separately in validate() so this module does not import it.

    `required` is False for the EXIT block, and that is not a relaxation.
    A stop is mandatory (see below: "a rule without a stop has no defined
    risk"), so every valid rule already has a guaranteed way out, sitting at
    the broker where a disconnect cannot cancel it. An exit CONDITION is an
    additional, earlier way out — useful, not necessary.

    Requiring one anyway made the product's own default unusable: the builder
    offers "managed by stop and target only" as a complete configuration and
    writes exactly that, and activation then refused it. A client could build
    a rule the UI called finished and never activate it.
    """
    if not isinstance(conditions, list):
        _err(problems, where, "must be a list")
        return
    if not conditions:
        if required:
            _err(problems, where, "at least one condition is required")
        return
    for i, c in enumerate(conditions):
        at = f"{where}[{i}]"
        if not isinstance(c, dict):
            _err(problems, at, "must be an object")
            continue
        cid = c.get("id")
        if not cid or not isinstance(cid, str):
            _err(problems, at, "missing 'id'")
        params = c.get("params", {})
        if not isinstance(params, dict):
            _err(problems, f"{at}.params", "must be an object")


def blank(*, user_id, account_id, symbols=None, timeframe="1h"):
    """A draft with every field present, so the UI never guesses a shape."""
    return {
        "ruleDocId": new_id(),
        "version": 1,
        "state": DRAFT,
        "userId": str(user_id),
        "accountId": str(account_id),
        "name": "",
        "createdAt": time.time(),
        "updatedAt": time.time(),
        "activatedAt": None,

        "symbols": list(symbols or []),
        "timeframe": timeframe,
        # When the rule is evaluated. "bar_close" is the honest default: an
        # intrabar evaluation can fire on a price that the bar never closes at.
        "evaluateOn": "bar_close",

        # WHICH ENGINE STRATEGY DECIDES, or None for "my conditions do".
        #
        # The platform exposed exactly one way to trade — write a rule — while
        # the engine ships fifteen ready-made strategies that a Telegram
        # client could pick from a menu. Those were unreachable here, so a
        # client who wanted Trend Following had to reproduce it in conditions,
        # and could not.
        #
        # It lives in the RuleDoc rather than beside it because everything
        # downstream of "what is running" is a RuleDoc: the frozen version the
        # journal points at, the risk gates that read the rule's own terms,
        # the engine snapshot Stop restores from. A preset has no conditions
        # and every other term, so it is one more term — not a second kind of
        # thing for all of that to learn.
        #
        # None, not "": None is "no preset chosen", and an empty string would
        # have to mean the same thing while also being a value somebody could
        # write by accident. `validate` refuses a blank string for that reason.
        "strategy": None,

        "entry": {"combine": "AND", "conditions": []},
        "exit": {"combine": "OR", "conditions": []},
        "sides": "BOTH",

        "order": {"type": "MARKET", "expiresAfterSec": None,
                  "maxSlippagePoints": None},

        "sizing": {"mode": SIZING_RISK, "riskPercent": 1.0,
                   "fixedVolume": None},
        "stopLoss": {"mode": "atr", "atrMultiple": 1.5, "pips": None},
        "takeProfit": {"mode": "rr", "rr": 2.0, "pips": None},
        "trailingStop": {"enabled": False, "atrMultiple": None},
        "breakEven": {"enabled": False, "atR": None},

        "limits": {"maxOpenPositions": 1, "maxDailyTrades": None,
                   "maxExposurePercent": None, "maxSpreadPips": None,
                   "onLimit": "block"},

        "schedule": {"timezone": "UTC", "days": [], "windows": []},
    }


def _as_object(problems, doc, field):
    """The object at `field`, reporting a non-object instead of crashing.

    This used to be written `doc.get(field) or {}`, which is right for an
    absent field and wrong for one a client chooses: `{"limits": "none"}`
    keeps the string, and the next `.get` raises AttributeError. The effect
    at the boundary is a 500 on a malformed body — a crash where the whole
    point of this function is to answer with the field that is wrong.

    Absent stays {} rather than one complaint about the block, so the checks
    below still name each missing field. That is the more useful message, and
    it is what a client building a rule from nothing already receives.
    """
    value = doc.get(field)
    if value is None:
        return {}
    if not isinstance(value, dict):
        _err(problems, field, "must be an object")
        return {}
    return value


def validate(doc, *, known_condition_ids=None, known_strategy_ids=None):
    """Every problem with `doc`, as a list. Empty list means valid.

    `known_condition_ids` is passed in rather than imported so this module
    stays free of the condition library — the library imports nothing from
    here either, and the two can be tested apart.

    `known_strategy_ids` is passed in for the same reason, and there is a
    second one: the strategy registry lives in the engine
    (`apex/strategy_api.py`) and reaching it from here would close an import
    cycle through `platform.rule_strategy`. Pass the ids the PLATFORM offers —
    `strategy_catalog.ids()` — not everything the engine registers: `grid`,
    `martingale` and `platform_rule` are registered and must not be selectable
    as presets. Omitting it checks the field's SHAPE only, which is what the
    evaluator does on every bar; the boundary that decides whether a rule may
    go live (`store.activate`) passes the list.
    """
    problems = []
    if not isinstance(doc, dict):
        return ["document: must be an object"]

    for field in ("ruleDocId", "userId", "accountId"):
        v = doc.get(field)
        if not v or not isinstance(v, str):
            # accountId is the one of these three a client can actually do
            # something about, so it says what to do. "required" is a fine
            # message for an internal field and a dead end on a screen.
            _err(problems, field,
                 "no cTrader account is attached to this rule — connect and "
                 "select an account, then save the rule again"
                 if field == "accountId" else "required")
        elif field == "ruleDocId" and not _ID_RE.match(v):
            _err(problems, field, "must be 1-64 chars of [A-Za-z0-9_-]")

    ver = doc.get("version")
    if not isinstance(ver, int) or isinstance(ver, bool) or ver < 1:
        _err(problems, "version", "must be an integer >= 1")

    if doc.get("state") not in STATES:
        _err(problems, "state", f"must be one of {', '.join(STATES)}")

    syms = doc.get("symbols")
    if not isinstance(syms, list) or not syms:
        _err(problems, "symbols", "at least one instrument is required")
    elif not all(isinstance(s, str) and s.strip() for s in syms):
        _err(problems, "symbols", "every entry must be a non-empty string")
    else:
        # WHICH INSTRUMENT, ASKED HERE RATHER THAN DISCOVERED AT THE ORDER.
        #
        # This accepted any non-empty string. A client could save, activate
        # and start a rule naming something this product does not trade, and
        # the first sign would be automation that ran and never did anything
        # — the engine refuses it far downstream, where no screen is looking.
        # Saying so at the point the rule is written is the whole difference.
        #
        # `is_tradeable` is a positive allowlist (FX with a USD leg, plus
        # metals), so the refusal names what IS accepted instead of listing
        # what is not.
        bad = [s for s in syms if not _forex.is_tradeable(s)]
        if bad:
            _err(problems, "symbols",
                 f"this platform trades forex majors with a USD leg and "
                 f"metals — {', '.join(sorted(set(bad)))} "
                 f"{'is' if len(set(bad)) == 1 else 'are'} outside that. "
                 f"Try EURUSD, USDJPY or XAUUSD")

    if not doc.get("timeframe"):
        _err(problems, "timeframe", "required")

    # ── which engine strategy decides ───────────────────────────────────────
    # A preset-backed rule and a condition-built rule are the same document
    # with one field different, and that field changes what the CONDITION
    # blocks are allowed to contain. Checked before the blocks, so the message
    # about them can be the right one.
    preset = doc.get("strategy")
    has_preset = isinstance(preset, str) and bool(preset.strip())
    if preset is not None and not has_preset:
        _err(problems, "strategy",
             "must be the id of a strategy, or null to use the entry and exit "
             "conditions you built yourself")
    elif has_preset and not _ID_RE.match(preset):
        _err(problems, "strategy", "must be 1-64 chars of [A-Za-z0-9_-]")
    elif has_preset and known_strategy_ids is not None \
            and preset not in set(known_strategy_ids):
        # Fail closed. An id nothing offers would be written onto the account
        # as cfg.STRATEGY, and the loop would hold every bar naming a strategy
        # the client cannot find on any screen.
        _err(problems, "strategy",
             f"unknown strategy {preset!r} — it is not one this release offers")

    # Kept so the condition-library check below reads the blocks this loop
    # already proved are objects, rather than reaching into `doc` again and
    # meeting the string this loop just rejected.
    halves = {}
    for half in ("entry", "exit"):
        block = doc.get(half)
        if not isinstance(block, dict):
            _err(problems, half, "must be an object")
            continue
        halves[half] = block
        if block.get("combine") not in COMBINE:
            _err(problems, f"{half}.combine", "must be AND or OR")
        if has_preset:
            # A PRESET DECIDES ITS OWN ENTRIES AND EXITS, so a condition on
            # the document is a term the client reads on their rule page and
            # the engine never consults. That is the exact defect this
            # codebase was rewritten to stop, so the document is refused
            # rather than activated with a decoration on it.
            #
            # It also closes a hole. `evaluator._eval_block` treats an empty
            # AND block as satisfied — vacuously true — and until now nothing
            # could reach that state because this check required an entry
            # condition. A preset document has none by construction, so the
            # evaluator refuses a preset outright (see `evaluator.evaluate`)
            # and this half of the pair makes sure there is nothing else in
            # there for anything to judge.
            conditions = block.get("conditions")
            if not isinstance(conditions, list):
                _err(problems, f"{half}.conditions", "must be a list")
            elif conditions:
                _err(problems, f"{half}.conditions",
                     f"this rule runs the {preset!r} strategy, which decides "
                     f"its own entries and exits — remove these conditions, "
                     f"or clear the strategy to build the rule yourself")
        else:
            _check_conditions(problems, f"{half}.conditions",
                              block.get("conditions"),
                              required=(half == "entry"))

    if doc.get("sides") not in SIDES:
        _err(problems, "sides", f"must be one of {', '.join(SIDES)}")

    order = _as_object(problems, doc, "order")
    if order.get("type") not in ORDER_TYPES:
        _err(problems, "order.type", f"must be one of {', '.join(ORDER_TYPES)}")

    sizing = _as_object(problems, doc, "sizing")
    mode = sizing.get("mode")
    if mode not in SIZING:
        _err(problems, "sizing.mode", f"must be one of {', '.join(SIZING)}")
    elif mode == SIZING_RISK:
        rp = sizing.get("riskPercent")
        if not isinstance(rp, (int, float)) or isinstance(rp, bool) or rp <= 0:
            _err(problems, "sizing.riskPercent", "must be a number > 0")
        elif rp > 100:
            _err(problems, "sizing.riskPercent", "cannot exceed 100")
    elif mode == SIZING_FIXED:
        fv = sizing.get("fixedVolume")
        if not isinstance(fv, (int, float)) or isinstance(fv, bool) or fv <= 0:
            _err(problems, "sizing.fixedVolume", "must be a number > 0")

    # A stop is not optional. Without one, position size cannot be derived
    # from risk and the account has no defined worst case on the trade.
    sl = _as_object(problems, doc, "stopLoss")
    if sl.get("mode") not in ("atr", "pips"):
        _err(problems, "stopLoss.mode", "must be 'atr' or 'pips' — a rule "
                                        "without a stop has no defined risk")
    elif sl.get("mode") == "atr" and not _pos_num(sl.get("atrMultiple")):
        _err(problems, "stopLoss.atrMultiple", "must be a number > 0")
    elif sl.get("mode") == "pips" and not _pos_num(sl.get("pips")):
        _err(problems, "stopLoss.pips", "must be a number > 0")

    tp = _as_object(problems, doc, "takeProfit")
    tp_mode = tp.get("mode")
    if tp_mode not in ("rr", "pips", None):
        _err(problems, "takeProfit.mode", "must be 'rr', 'pips', or null")
    elif tp_mode == "rr" and not _pos_num(tp.get("rr")):
        _err(problems, "takeProfit.rr", "must be a number > 0")
    elif tp_mode == "pips" and not _pos_num(tp.get("pips")):
        _err(problems, "takeProfit.pips", "must be a number > 0")

    # THESE WERE REFUSED WHEN ENABLED, AND THAT STOPPED BEING TRUE.
    #
    # The refusal was added on the grounds that "no platform runtime path
    # trails broker stops yet". That was right about the platform and wrong
    # about the product: the engine the platform starts has always trailed and
    # moved stops to break even, from the account's own settings — the
    # STOP_MOVED lines in any day's logs are it doing so.
    #
    # Since `engine_config.translate`, the rule's own switches are what the
    # engine is given (`trailing`, `breakeven_r`). Refusing them now would
    # refuse two settings that work, so what is left is shape validation, and
    # the distances — which the engine has no per-rule setting for — are
    # reported to the client by `engine_config`, not refused here.
    trailing = _as_object(problems, doc, "trailingStop")
    trailing_enabled = trailing.get("enabled", False)
    if not isinstance(trailing_enabled, bool):
        _err(problems, "trailingStop.enabled", "must be true or false")
    trailing_multiple = trailing.get("atrMultiple")
    if trailing_multiple is not None and not _pos_num(trailing_multiple):
        _err(problems, "trailingStop.atrMultiple", "must be a number > 0")

    be = _as_object(problems, doc, "breakEven")
    be_enabled = be.get("enabled", False)
    if not isinstance(be_enabled, bool):
        _err(problems, "breakEven.enabled", "must be true or false")
    be_at_r = be.get("atR")
    if be_at_r is not None and not _pos_num(be_at_r):
        _err(problems, "breakEven.atR", "must be a number > 0")
    if be_enabled and be_at_r is None:
        # The engine expresses "off" as 0, so an enabled break-even with no R
        # would be written as off and silently do nothing.
        _err(problems, "breakEven.atR",
             "is required when break even is enabled")

    _check_schedule(problems, _as_object(problems, doc, "schedule"))

    limits = _as_object(problems, doc, "limits")
    mop = limits.get("maxOpenPositions")
    if not isinstance(mop, int) or isinstance(mop, bool) or mop < 1:
        _err(problems, "limits.maxOpenPositions", "must be an integer >= 1")
    if limits.get("onLimit") not in ON_LIMIT:
        _err(problems, "limits.onLimit", f"must be one of {', '.join(ON_LIMIT)}")

    if known_condition_ids is not None:
        known = set(known_condition_ids)
        for half in ("entry", "exit"):
            conditions = halves.get(half, {}).get("conditions")
            for i, c in enumerate(conditions if isinstance(conditions, list)
                                  else []):
                if isinstance(c, dict) and c.get("id") and c["id"] not in known:
                    _err(problems, f"{half}.conditions[{i}].id",
                         f"unknown condition {c['id']!r}")
    return problems


def _pos_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def _minutes(value):
    if not isinstance(value, str) or not re.match(r"^\d{2}:\d{2}$", value):
        return None
    hh, mm = [int(part) for part in value.split(":")]
    if hh > 23 or mm > 59:
        return None
    return hh * 60 + mm


def _check_schedule(problems, sched):
    if sched.get("timezone") != "UTC":
        _err(problems, "schedule.timezone", "must be UTC")

    days = sched.get("days", [])
    if not isinstance(days, list):
        _err(problems, "schedule.days", "must be a list")
    else:
        for i, day in enumerate(days):
            if (not isinstance(day, int) or isinstance(day, bool)
                    or day < 0 or day > 6):
                _err(problems, f"schedule.days[{i}]",
                     "must be an integer from 0 to 6")

    windows = sched.get("windows", [])
    if not isinstance(windows, list):
        _err(problems, "schedule.windows", "must be a list")
        return
    for i, window in enumerate(windows):
        at = f"schedule.windows[{i}]"
        if not isinstance(window, dict):
            _err(problems, at, "must be an object")
            continue
        start = _minutes(window.get("from"))
        end = _minutes(window.get("to"))
        if start is None:
            _err(problems, f"{at}.from", "must be HH:MM in UTC")
        if end is None:
            _err(problems, f"{at}.to", "must be HH:MM in UTC")
        if start is not None and end is not None and start == end:
            _err(problems, at, "from and to cannot be the same time")


def is_valid(doc, *, known_condition_ids=None, known_strategy_ids=None):
    return not validate(doc, known_condition_ids=known_condition_ids,
                        known_strategy_ids=known_strategy_ids)


def activate(doc, *, known_condition_ids=None, known_strategy_ids=None,
             now=None):
    """A frozen ACTIVE copy, or RuleDocInvalid. Never mutates `doc`.

    Returning a copy rather than flipping the state in place is what makes the
    draft still exist afterwards: the client keeps editing their draft while a
    frozen version runs.
    """
    problems = validate(doc, known_condition_ids=known_condition_ids,
                        known_strategy_ids=known_strategy_ids)
    if problems:
        raise RuleDocInvalid(problems)
    if doc.get("state") not in (DRAFT, PAUSED):
        raise RuleDocInvalid([f"state: cannot activate from "
                              f"{doc.get('state')!r}"])
    out = json.loads(json.dumps(doc))
    out["state"] = ACTIVE
    out["activatedAt"] = now if now is not None else time.time()
    out["updatedAt"] = out["activatedAt"]
    return out


def next_version(doc, *, now=None):
    """A DRAFT copy at version+1. How an active rule is edited.

    The active document is left untouched, so anything already journalled
    against it still points at terms that exist.
    """
    out = json.loads(json.dumps(doc))
    out["version"] = int(doc.get("version") or 1) + 1
    out["state"] = DRAFT
    out["activatedAt"] = None
    out["updatedAt"] = now if now is not None else time.time()
    return out


def assert_editable(doc):
    """Raise unless `doc` may be edited in place."""
    st = (doc or {}).get("state")
    if st not in EDITABLE_STATES:
        raise RuleDocInvalid([
            f"state: a {st!r} RuleDoc is immutable — call next_version() to "
            f"edit it"])
