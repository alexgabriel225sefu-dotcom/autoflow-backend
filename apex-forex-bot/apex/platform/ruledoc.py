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


def _err(problems, field, msg):
    problems.append(f"{field}: {msg}")


def _check_conditions(problems, where, conditions):
    """Shape only. Whether a condition ID is real is the library's question,
    asked separately in validate() so this module does not import it."""
    if not isinstance(conditions, list):
        _err(problems, where, "must be a list")
        return
    if not conditions:
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


def validate(doc, *, known_condition_ids=None):
    """Every problem with `doc`, as a list. Empty list means valid.

    `known_condition_ids` is passed in rather than imported so this module
    stays free of the condition library — the library imports nothing from
    here either, and the two can be tested apart.
    """
    problems = []
    if not isinstance(doc, dict):
        return ["document: must be an object"]

    for field in ("ruleDocId", "userId", "accountId"):
        v = doc.get(field)
        if not v or not isinstance(v, str):
            _err(problems, field, "required")
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

    if not doc.get("timeframe"):
        _err(problems, "timeframe", "required")

    for half in ("entry", "exit"):
        block = doc.get(half)
        if not isinstance(block, dict):
            _err(problems, half, "must be an object")
            continue
        if block.get("combine") not in COMBINE:
            _err(problems, f"{half}.combine", "must be AND or OR")
        _check_conditions(problems, f"{half}.conditions",
                          block.get("conditions"))

    if doc.get("sides") not in SIDES:
        _err(problems, "sides", f"must be one of {', '.join(SIDES)}")

    order = doc.get("order") or {}
    if order.get("type") not in ORDER_TYPES:
        _err(problems, "order.type", f"must be one of {', '.join(ORDER_TYPES)}")

    sizing = doc.get("sizing") or {}
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
    sl = doc.get("stopLoss") or {}
    if sl.get("mode") not in ("atr", "pips"):
        _err(problems, "stopLoss.mode", "must be 'atr' or 'pips' — a rule "
                                        "without a stop has no defined risk")
    elif sl.get("mode") == "atr" and not _pos_num(sl.get("atrMultiple")):
        _err(problems, "stopLoss.atrMultiple", "must be a number > 0")
    elif sl.get("mode") == "pips" and not _pos_num(sl.get("pips")):
        _err(problems, "stopLoss.pips", "must be a number > 0")

    limits = doc.get("limits") or {}
    mop = limits.get("maxOpenPositions")
    if not isinstance(mop, int) or isinstance(mop, bool) or mop < 1:
        _err(problems, "limits.maxOpenPositions", "must be an integer >= 1")
    if limits.get("onLimit") not in ON_LIMIT:
        _err(problems, "limits.onLimit", f"must be one of {', '.join(ON_LIMIT)}")

    if known_condition_ids is not None:
        known = set(known_condition_ids)
        for half in ("entry", "exit"):
            for i, c in enumerate(((doc.get(half) or {}).get("conditions")
                                   or [])):
                if isinstance(c, dict) and c.get("id") and c["id"] not in known:
                    _err(problems, f"{half}.conditions[{i}].id",
                         f"unknown condition {c['id']!r}")
    return problems


def _pos_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def is_valid(doc, *, known_condition_ids=None):
    return not validate(doc, known_condition_ids=known_condition_ids)


def activate(doc, *, known_condition_ids=None, now=None):
    """A frozen ACTIVE copy, or RuleDocInvalid. Never mutates `doc`.

    Returning a copy rather than flipping the state in place is what makes the
    draft still exist afterwards: the client keeps editing their draft while a
    frozen version runs.
    """
    problems = validate(doc, known_condition_ids=known_condition_ids)
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
