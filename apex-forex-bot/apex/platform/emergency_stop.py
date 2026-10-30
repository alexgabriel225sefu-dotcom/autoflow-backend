"""The client's own emergency button: stop trading, then get out — and say what
actually happened.

WHAT THIS IS NOT

`emergency.py` is the OPERATOR's switch: a global or per-client halt that
blocks the product from starting anything and that only an operator releases.
This is the CLIENT's panic button for their own demo account. It halts nothing
for anyone else and leaves nothing behind that a client cannot undo by pressing
Start again.

WHAT IT DOES, IN ORDER

1. Stops the client's automation (the same `automation.stop` the Stop button
   runs), so a loop cannot open a new position while the old ones are being
   closed.
2. Optionally closes every open position on the SELECTED DEMO account, one at
   a time, through `position_close.close_demo` — the single close path, with
   its demo check, its ownership check and its idempotency claim. There is no
   second way to close here.
3. Reads the account again and reports how many positions are STILL open.

WHY THE ANSWER IS SO CAREFUL

A panic button that says "all closed" when one position is not is the most
expensive sentence this product can print. So:

* each step is attempted whatever the one before it did. A stop that failed
  must not leave positions open that could have been closed; a close that
  failed must not hide that the stop worked.
* `allFlat` is True ONLY when the re-read succeeded and found nothing. A
  re-read that fails is "unverified", never "flat".
* a refusal is carried with its own code and sentence. The common one right
  after a restart is NOT_OWNER: another container still holds the lease for
  up to ten minutes. The stop-loss and take-profit at the broker stay in force
  meanwhile, and the sentence says so instead of leaving a panicking client to
  guess.
* the number of closes in one press is capped. Beyond the cap the answer says
  how many were not attempted.

All collaborators are parameters so a test can drive every branch without a
broker.
"""
import time

from apex import redact as _redact
from apex.platform import automation as _auto
from apex.platform import broker_read as _read
from apex.platform import position_close as _close

MAX_CLOSES = 20
# Stop STARTING new closes after this long (seconds). The browser waits a little
# longer than this plus the last close and the re-read.
CLOSE_BUDGET_S = 90.0

# Per-position outcomes.
CLOSED = "closed"
ALREADY_CLOSED = "already_closed"
PARTIAL = "partial"
REFUSED = "refused"
UNKNOWN = "unknown"
FAILED = "failed"

_DONE = (CLOSED, ALREADY_CLOSED)


def _scrub(e):
    # Redacted AND bounded, by the same function the journal uses. This text goes
    # to the browser (automation.error, positions.reason, closes[].detail), and
    # truncation alone leaves anything credential-shaped that happens to be in
    # the first 160 characters.
    return _auto._safe_cause(e)


def _list_positions(user_id, ctid, opener, connection_fn=None, broker_fn=None):
    """(rows, None) or (None, reason). Positions by id only — no quotes."""
    try:
        broker, other = opener(str(user_id), ctid=ctid,
                               connection_fn=connection_fn, broker_fn=broker_fn)
        if broker is None:
            return None, ((other or {}).get("reason")
                          or (other or {}).get("status")
                          or "the broker account is unavailable")
        rows = broker.get_all_positions()
        if not isinstance(rows, list):
            return None, "the broker returned an invalid positions list"
        return rows, None
    except Exception as e:                                   # noqa: BLE001
        return None, _scrub(e)


def _close_one(user_id, ctid, row, closer):
    base = {"positionId": str(row.get("positionId")),
            "symbol": row.get("symbol"), "side": row.get("side")}
    try:
        result = closer(user_id, ctid=ctid, position_id=base["positionId"])
    except _close.CloseRefused as e:
        return dict(base, outcome=REFUSED, code=e.code,
                    detail=_redact.scrub_for_client(e.detail, limit=200))
    except _close.CloseUnknown as e:
        return dict(base, outcome=UNKNOWN, detail=_redact.scrub_for_client(e, limit=200))
    except Exception as e:                                   # noqa: BLE001
        return dict(base, outcome=FAILED, detail=_scrub(e))
    status = str((result or {}).get("status") or "").upper()
    if status == "FILLED":
        return dict(base, outcome=CLOSED)
    if status == "ALREADY_CLOSED":
        return dict(base, outcome=ALREADY_CLOSED)
    if status == "PARTIAL":
        return dict(base, outcome=PARTIAL,
                    detail="only part of the position was closed")
    return dict(base, outcome=UNKNOWN,
                detail="the broker answered in a form this page cannot confirm")


def _sentence(out):
    a = out["automation"]
    parts = []
    if a["stopped"]:
        parts.append("Automation is stopped.")
    elif a.get("alreadyStopped"):
        parts.append("Automation was already stopped.")
    else:
        parts.append("Automation could NOT be stopped"
                     + (f" ({a['error']})" if a.get("error") else "")
                     + " — press Stop on the dashboard.")

    if out["closes"] is None:
        parts.append("Open positions were left as they are: they keep the stop "
                     "and target they were given at your broker.")
        return " ".join(parts)

    pos = out["positions"]
    if pos.get("attempted") is False:
        parts.append(f"Closing positions was NOT attempted ({pos['reason']}). "
                     "They are NOT confirmed flat: they stay at your broker "
                     "with their stop and target; close them in cTrader if "
                     "needed.")
        return " ".join(parts)
    if not pos["readable"]:
        parts.append("Your open positions could not be read, so none were "
                     f"closed ({pos['reason']}). They stay at your broker with "
                     "their stop and target; close them in cTrader if needed.")
        return " ".join(parts)

    if pos["found"] == 0:
        parts.append("There were no open positions to close.")
    done = sum(1 for c in out["closes"] if c["outcome"] in _DONE)
    bad = [c for c in out["closes"] if c["outcome"] not in _DONE]
    if done:
        parts.append(f"{done} position{'s' if done != 1 else ''} closed.")
    if bad:
        parts.append(f"{len(bad)} could not be confirmed closed — see below.")
    if pos.get("notAttempted"):
        parts.append(f"{pos['notAttempted']} more were not attempted "
                     f"(at most {MAX_CLOSES} per press, within a time budget); press again.")

    v = out["verified"]
    if not v["readable"]:
        parts.append("The account could not be re-read, so it is NOT confirmed "
                     "flat. Check the Positions page.")
    elif v["stillOpen"] == 0:
        parts.append("Confirmed: no positions are open.")
    else:
        parts.append(f"{v['stillOpen']} position"
                     f"{'s are' if v['stillOpen'] != 1 else ' is'} still open. "
                     "Each keeps the stop and target it was given at your "
                     "broker.")
    if any(c.get("code") == "NOT_OWNER" for c in bad):
        parts.append("A refusal of NOT_OWNER right after a restart clears "
                     "within about ten minutes; try again then, or close the "
                     "position in cTrader.")
    return " ".join(parts)


def run(user_id, *, ctid, close_positions=True, stopper=None, opener=None,
        closer=None, connection_fn=None, broker_fn=None, mode_fn=None,
        budget_s=CLOSE_BUDGET_S, no_account_reason=None, not_attempted=False):
    """Stop automation and, if asked, close every position on `ctid`.

    Never raises for a step that failed: each failure is part of the answer.
    The caller has already authenticated freshly and confirmed the client's
    intent; this function trusts neither the browser nor its own earlier steps.
    """
    user_id = str(user_id)
    stopper = stopper or _auto.stop
    opener = opener or _read._open
    closer = closer or _close.close_demo

    # 1. stop
    automation = {"stopped": False, "alreadyStopped": False, "error": None}
    try:
        res = stopper(user_id) or {}
        automation["stopped"] = bool(res.get("stopped"))
        automation["alreadyStopped"] = bool(res.get("alreadyStopped"))
    except Exception as e:                                   # noqa: BLE001
        automation["error"] = _scrub(e)

    out = {"status": "ok", "automation": automation, "positions": None,
           "closes": None, "verified": None, "allFlat": None}

    if not close_positions:
        out["sentence"] = _sentence(out)
        return out

    # 1b. no account to close on. The stop above has already run; what is left
    # is to say plainly that nothing was closed and why, never "flat".
    if not ctid:
        out["positions"] = {"readable": False, "found": None,
                            "reason": no_account_reason
                            or "no cTrader account is selected"}
        if not_attempted:
            # Withheld on purpose (the press was throttled), not unreadable.
            out["positions"]["attempted"] = False
        out["closes"] = []
        out["verified"] = {"readable": False, "stillOpen": None}
        out["allFlat"] = False
        out["sentence"] = _sentence(out)
        return out

    # 2. the account must be DEMO before a single position is listed or closed.
    # `close_demo` checks this again per position; asking here as well means a
    # live selection never even has its positions read by this path, and the
    # answer says so instead of listing refusals one by one.
    try:
        mode = (mode_fn or _close._account_mode)(user_id, ctid)
    except Exception as e:                                   # noqa: BLE001
        mode, mode_err = None, _scrub(e)
    else:
        mode_err = None
    if mode != "demo":
        out["positions"] = {"readable": False, "found": None,
                            "reason": mode_err or "closing positions from here is available only on a demo account"}
        out["closes"] = []
        out["verified"] = {"readable": False, "stillOpen": None}
        out["allFlat"] = False
        out["sentence"] = _sentence(out)
        return out

    # 3. find and close
    rows, reason = _list_positions(user_id, ctid, opener,
                                   connection_fn, broker_fn)
    if rows is None:
        out["positions"] = {"readable": False, "reason": reason, "found": None}
        out["closes"] = []
        out["verified"] = {"readable": False, "stillOpen": None}
        out["allFlat"] = False
        out["sentence"] = _sentence(out)
        return out

    attempt = rows[:MAX_CLOSES]
    # A time budget on top of the count cap. Each close can wait on the broker
    # for tens of seconds; twenty of them in a row would hold one HTTP worker for
    # minutes and outlast the browser's patience. Once the budget is spent no
    # further close is STARTED (one already under way is never cut), and the
    # answer says how many were not attempted.
    started = time.monotonic()
    closes = []
    for r in attempt:
        if closes and time.monotonic() - started > budget_s:
            break
        closes.append(_close_one(user_id, ctid, r, closer))
    out["positions"] = {"readable": True, "reason": None, "found": len(rows),
                        "notAttempted": max(0, len(rows) - len(closes))}
    out["closes"] = closes

    # 4. verify by looking again, never by trusting the closes
    again, why = _list_positions(user_id, ctid, opener, connection_fn, broker_fn)
    if again is None:
        out["verified"] = {"readable": False, "stillOpen": None, "reason": why}
        out["allFlat"] = False
    else:
        out["verified"] = {"readable": True, "stillOpen": len(again)}
        out["allFlat"] = len(again) == 0

    out["sentence"] = _sentence(out)
    return out
