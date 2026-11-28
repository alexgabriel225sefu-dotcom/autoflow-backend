"""What an LLM is allowed to say back, and what happens when it says otherwise.

WHY A SCHEMA AND NOT A PARSE

`ai.py` already asks Groq for JSON and checks that the action is one of four
words. That is enough to keep a malformed reply from crashing the loop, and it
is not enough for the engine, because the failure it cannot catch is the one
that matters: a reply that is perfectly well-formed and refers to a symbol
nobody asked about, a direction the rule engine never proposed, or a price the
model produced itself.

§40 lists those explicitly — hallucinated symbol, hallucinated price,
unsupported action, missing evidence — and §41 is the rule underneath: the
model must not be the source of any number the platform can compute. So this
module validates against the REQUEST as well as against the shape. A reply is
checked for whether it is an answer to the question that was asked.

FAIL CLOSED MEANS THE PROPOSAL DIES, NOT THE TRADING

An invalid reply is rejected and the decision falls back to the deterministic
path. §68 is explicit that the AI being unavailable does not have to stop a
strategy that is safe without it — and §28 is explicit that AI text is never
authoritative system state. Both are satisfied by the same behaviour: the
proposal is dropped, the reason is recorded, and the rule engine's own verdict
stands.
"""

import json
import re

# ── The only actions a model may return ──────────────────────────────────
ENTER_PROPOSED = "ENTER_PROPOSED"
NO_TRADE = "NO_TRADE"
WATCH = "WATCH"
HOLD = "HOLD"
EXIT_PROPOSED = "EXIT_PROPOSED"
REDUCE_PROPOSED = "REDUCE_PROPOSED"
TIGHTEN_STOP_PROPOSED = "TIGHTEN_STOP_PROPOSED"

ENTRY_ACTIONS = frozenset({ENTER_PROPOSED, NO_TRADE, WATCH})
MANAGE_ACTIONS = frozenset({HOLD, EXIT_PROPOSED, REDUCE_PROPOSED,
                            TIGHTEN_STOP_PROPOSED})

# Rejection codes, recorded so an AI that starts misbehaving is visible in the
# journal rather than showing up as a quiet drop in proposals.
BAD_JSON = "AI_BAD_JSON"
NOT_OBJECT = "AI_NOT_OBJECT"
BAD_ACTION = "AI_BAD_ACTION"
SYMBOL_MISMATCH = "AI_SYMBOL_MISMATCH"
DIRECTION_MISMATCH = "AI_DIRECTION_MISMATCH"
NO_EVIDENCE = "AI_NO_EVIDENCE"
FORBIDDEN_FIELD = "AI_FORBIDDEN_FIELD"
TOO_LONG = "AI_TOO_LONG"
EMPTY = "AI_EMPTY"

# Fields a model may never set, because the platform computes them and §41
# forbids the model calculating financial truth. A reply carrying one of these
# is rejected outright rather than having the field stripped: a model that is
# inventing prices is not a model whose OTHER fields should be trusted on the
# same call.
FORBIDDEN = frozenset({
    "price", "entry", "entry_price", "entryPrice", "exit", "exit_price",
    "stop_loss", "stopLoss", "sl", "take_profit", "takeProfit", "tp",
    "units", "size", "quantity", "lots", "volume", "risk", "risk_pct",
    "leverage", "balance", "equity", "margin", "pnl", "position_size",
    "probability", "win_rate", "expectancy",
})

_MAX_TEXT = 600            # one field's worth of prose
_MAX_LIST = 12             # reason codes / evidence / uncertainties
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,39}$")


class Rejected(Exception):
    """An AI reply that must not be used. Carries the code for the journal."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}"[:200])
        self.code = code
        self.detail = detail[:200]


def _strings(value, *, limit=_MAX_LIST, upper=False):
    """A bounded list of short strings, or []. Never raises on odd input."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for v in value[:limit]:
        if not isinstance(v, (str, int, float)):
            continue
        s = str(v).strip()[:120]
        if s:
            out.append(s.upper() if upper else s)
    return out


def parse(raw):
    """Text -> dict, or raise Rejected. Tolerant only about wrapping.

    Models fence JSON in ```json blocks and add a sentence before it often
    enough that refusing those would reject good answers for a formatting
    habit. Nothing else is repaired: a truncated object is not guessed at.
    """
    if raw is None:
        raise Rejected(EMPTY, "no reply")
    if isinstance(raw, dict):
        return raw
    text = str(raw).strip()
    if not text:
        raise Rejected(EMPTY, "empty reply")
    if len(text) > 20000:
        raise Rejected(TOO_LONG, f"{len(text)} chars")
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        obj = json.loads(text)
    except Exception as e:
        raise Rejected(BAD_JSON, str(e)[:120])
    if not isinstance(obj, dict):
        raise Rejected(NOT_OBJECT, type(obj).__name__)
    return obj


def validate(raw, *, allowed_actions, symbol=None, direction=None,
             require_evidence=True):
    """The one entry point. Returns a clean dict, or raises Rejected.

    `symbol` and `direction` are what was ASKED about. Passing them is what
    turns this from a shape check into an answer check — without them a reply
    proposing a different instrument passes every structural test.
    """
    obj = parse(raw)

    bad = sorted(set(obj) & FORBIDDEN)
    if bad:
        raise Rejected(FORBIDDEN_FIELD, ", ".join(bad[:5]))

    action = str(obj.get("action") or "").strip().upper()
    if action not in allowed_actions:
        raise Rejected(BAD_ACTION, f"{action or '(none)'} not in "
                                   f"{sorted(allowed_actions)}")

    got_sym = str(obj.get("symbol") or "").replace("_", "").replace("/", "").upper()
    if symbol:
        want = str(symbol).replace("_", "").replace("/", "").upper()
        if got_sym and got_sym != want:
            raise Rejected(SYMBOL_MISMATCH, f"asked {want}, answered {got_sym}")

    got_dir = str(obj.get("direction") or "").strip().upper()
    if got_dir and got_dir not in ("BUY", "SELL"):
        raise Rejected(DIRECTION_MISMATCH, got_dir)
    if direction and got_dir and got_dir != str(direction).upper():
        raise Rejected(DIRECTION_MISMATCH,
                       f"asked {direction}, answered {got_dir}")

    reasons = [r for r in _strings(obj.get("reason_codes")
                                   or obj.get("reasonCodes"), upper=True)
               if _CODE_RE.match(r)]
    evidence = _strings(obj.get("supporting_evidence")
                        or obj.get("supportingEvidence")
                        or obj.get("evidence"))
    invalidation = _strings(obj.get("invalidation_conditions")
                            or obj.get("invalidationConditions"))
    uncertainties = _strings(obj.get("uncertainties"))

    # A proposal with nothing behind it is the shape §12 exists to refuse. A
    # NO_TRADE with no evidence is merely unhelpful, so the bar is only applied
    # where the model is asking for something to happen.
    if require_evidence and action in (ENTER_PROPOSED, EXIT_PROPOSED,
                                       REDUCE_PROPOSED) and not evidence:
        raise Rejected(NO_EVIDENCE, f"{action} with no supporting evidence")

    note = str(obj.get("reasoning") or obj.get("note") or "").strip()[:_MAX_TEXT]

    return {
        "action": action,
        "symbol": got_sym or (str(symbol).upper() if symbol else None),
        "direction": got_dir or (str(direction).upper() if direction else None),
        "reason_codes": reasons,
        "supporting_evidence": evidence,
        "invalidation_conditions": invalidation,
        "uncertainties": uncertainties,
        "reasoning": note,
    }


def safe_validate(raw, **kw):
    """(result, None) or (None, code). For callers that must not raise.

    The loop is one of them: an AI that starts returning nonsense must degrade
    the proposal, not take the trading process down with it.
    """
    try:
        return validate(raw, **kw), None
    except Rejected as e:
        return None, e.code
    except Exception as e:                        # a validator bug is still a rejection
        return None, f"AI_VALIDATOR_ERROR:{type(e).__name__}"
