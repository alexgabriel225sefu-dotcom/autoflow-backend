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
from apex.platform import automation as _auto
from apex.platform import broker_read as _read
from apex.platform import position_close as _close

MAX_CLOSES = 20

# Per-position outcomes.
CLOSED = "closed"
ALREADY_CLOSED = "already_closed"
PARTIAL = "partial"
REFUSED = "refused"
UNKNOWN = "unknown"
FAILED = "failed"

_DONE = (CLOSED, ALREADY_CLOSED)


def _scrub(e):
    # The exception text only; closers raise sentences, not credentials, but a
    # long message is cut so a stack of detail cannot reach the browser.
    return f"{type(e).__name__}: {str(e)[:160]}"


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
        return dict(base, outcome=REFUSED, code=e.code, detail=str(e.detail)[:200])
    except _close.CloseUnknown as e:
        return dict(base, outcome=UNKNOWN, detail=str(e)[:200])
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
                     f"(limit {MAX_CLOSES} per press); press again.")

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
        closer=None, connection_fn=None, broker_fn=None):
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

    # 2. find and close
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
    out["positions"] = {"readable": True, "reason": None, "found": len(rows),
                        "notAttempted": max(0, len(rows) - len(attempt))}
    out["closes"] = [_close_one(user_id, ctid, r, closer) for r in attempt]

    # 3. verify by looking again, never by trusting the closes
    again, why = _list_positions(user_id, ctid, opener, connection_fn, broker_fn)
    if again is None:
        out["verified"] = {"readable": False, "stillOpen": None, "reason": why}
        out["allFlat"] = False
    else:
        out["verified"] = {"readable": True, "stillOpen": len(again)}
        out["allFlat"] = len(again) == 0

    out["sentence"] = _sentence(out)
    return out
