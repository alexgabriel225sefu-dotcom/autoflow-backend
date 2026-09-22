"""The Apex4Traders platform API. Transport-free on purpose.

`handle()` takes a method, a path, headers and a body, and returns a status
and a dict. It never touches a socket, so every endpoint below is tested
directly rather than through a server, and mounting it costs bot.py one line.

THE RULES EVERY ENDPOINT OBEYS, ENFORCED IN ONE PLACE

  authenticated   no route is reachable without a verified session
  owned           every read and write is scoped to the caller's user id by
                  the storage key itself (see store.py)
  licensed        anything that could lead to an order needs a live licence
  honest          a capability that is not wired yet answers 501 UNSUPPORTED.
                  It never answers 200 with an empty list, because an empty
                  list is a claim — "you have no positions" — and this
                  platform does not yet know whether that is true.

WHY REFUSALS CARRY A CODE

The UI has to say different sentences for "your licence expired", "confirm
your email" and "we could not reach the login service", and those sentences
lead to different buttons. A single 403 with prose would force the frontend to
match on English text.
"""

import json
import re

from apex.platform import conditions as _cond
from apex.platform import identity as _id
from apex.platform import licence as _lic
from apex.platform import ruledoc as _rd
from apex.platform import store as _store

PREFIX = "/api/v1/"

# Capabilities that arrive with the broker phase. Listed explicitly so the
# frontend can grey a button out instead of discovering a 404, and so that
# nothing here quietly returns a plausible empty answer in the meantime.
_NOT_YET = {
    "accounts": "connecting a cTrader account",
    "positions": "reading open positions",
    "orders": "reading orders",
    "journal": "the decision journal",
    "notifications": "the notification centre",
}


def _err(status, code, message, **extra):
    body = {"ok": False, "error": dict({"code": code, "message": message},
                                       **extra)}
    return status, body


def _ok(payload=None, **kw):
    return 200, dict({"ok": True}, **dict(payload or {}, **kw))


def _body(raw):
    if not raw:
        return {}
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    try:
        parsed = json.loads(raw)
    except Exception:
        raise ValueError("the request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise ValueError("the request body must be a JSON object")
    return parsed


def _authenticate(headers, *, fresh=False):
    token = _id.bearer_token((headers or {}).get("Authorization")
                             or (headers or {}).get("authorization"))
    if not token:
        raise _id.AuthFailed("this endpoint needs a signed-in session")
    return _id.verify_token(token, fresh=fresh)


# ── routes ──────────────────────────────────────────────────────────────────
_RULE_RE = re.compile(r"^rules/([A-Za-z0-9_-]{1,64})$")
_RULE_ACTION_RE = re.compile(
    r"^rules/([A-Za-z0-9_-]{1,64})/(validate|activate|pause|resume|archive"
    r"|version|preview)$")
_RULE_VERSION_RE = re.compile(
    r"^rules/([A-Za-z0-9_-]{1,64})/versions/(\d{1,9})$")


def handle(method, path, headers=None, body=None):
    """(status, payload), or None when the path is not ours.

    Returning None rather than a 404 lets this mount inside an existing server
    whose other routes must keep working.
    """
    if not path or not path.startswith(PREFIX):
        return None
    route = path[len(PREFIX):].split("?", 1)[0].strip("/")
    method = (method or "GET").upper()
    try:
        return _dispatch(method, route, headers or {}, body)
    except _id.AuthFailed as e:
        return _err(401, "AUTH_REQUIRED", str(e))
    except _id.AuthUnavailable as e:
        # 503, never 401. The client's session may be perfectly good; it is
        # the platform that cannot check right now, and telling them their
        # login is invalid would be a lie that also hides the real fault.
        return _err(503, "AUTH_UNAVAILABLE", str(e))
    except _lic.LicenceRequired as e:
        return _err(402, "LICENCE_REQUIRED", str(e), licenceState=e.state)
    except _store.NotFound:
        return _err(404, "NOT_FOUND", "no such rule")
    except _store.OwnershipViolation:
        # Only reachable through a key-construction bug. Loud, and never
        # rendered as a normal "not found".
        return _err(500, "OWNERSHIP_VIOLATION",
                    "a stored document failed its ownership check")
    except _rd.RuleDocInvalid as e:
        return _err(422, "RULE_INVALID", "this rule cannot be activated",
                    problems=e.problems)
    except ValueError as e:
        return _err(400, "BAD_REQUEST", str(e))


def _dispatch(method, route, headers, body):
    head = route.split("/", 1)[0]
    if head in _NOT_YET:
        _authenticate(headers)          # still refuse anonymous callers first
        return _err(501, "UNSUPPORTED",
                    f"{_NOT_YET[head]} is not connected yet",
                    capability=head)

    if route == "me" and method == "GET":
        p = _authenticate(headers)
        return _ok({"user": p.as_dict(),
                    "licence": _lic.status_for(p.user_id)})

    # The Rule Builder renders its form from this, so the UI can never offer a
    # condition the evaluator does not implement.
    if route == "conditions" and method == "GET":
        _authenticate(headers)
        return _ok({"conditions": _cond.describe()})

    if route == "rules":
        p = _authenticate(headers)
        if method == "GET":
            return _ok({"rules": [_summary(d) for d in
                                  _store.list_docs(p.user_id)]})
        if method == "POST":
            return _create(p, _body(body))
        return _err(405, "METHOD_NOT_ALLOWED", f"{method} is not allowed here")

    m = _RULE_RE.match(route)
    if m:
        p = _authenticate(headers)
        rid = m.group(1)
        if method == "GET":
            return _ok({"rule": _store.get(p.user_id, rid)})
        if method == "PUT":
            doc = dict(_body(body))
            doc["ruleDocId"] = rid
            return _ok({"rule": _store.save_draft(p.user_id, doc)})
        return _err(405, "METHOD_NOT_ALLOWED", f"{method} is not allowed here")

    m = _RULE_VERSION_RE.match(route)
    if m and method == "GET":
        p = _authenticate(headers)
        return _ok({"rule": _store.get_version(p.user_id, m.group(1),
                                               int(m.group(2)))})

    m = _RULE_ACTION_RE.match(route)
    if m:
        if method != "POST":
            return _err(405, "METHOD_NOT_ALLOWED", f"{method} is not allowed")
        return _rule_action(m.group(2), m.group(1), headers, body)

    return _err(404, "NOT_FOUND", "no such endpoint")


def _summary(doc):
    """What a list shows. The whole document is a lot of JSON, and a list of
    rules does not need every condition's parameters."""
    return {"ruleDocId": doc.get("ruleDocId"), "name": doc.get("name"),
            "state": doc.get("state"), "version": doc.get("version"),
            "symbols": doc.get("symbols"), "timeframe": doc.get("timeframe"),
            "updatedAt": doc.get("updatedAt"),
            "accountId": doc.get("accountId")}


def _create(principal, payload):
    """A new draft. The blank is built here, not accepted from the browser, so
    a document can never arrive missing fields the evaluator later assumes."""
    doc = _rd.blank(user_id=principal.user_id,
                    account_id=str(payload.get("accountId") or ""),
                    symbols=payload.get("symbols") or [],
                    timeframe=payload.get("timeframe") or "1h")
    for field in ("name", "sides", "entry", "exit", "order", "sizing",
                  "stopLoss", "takeProfit", "trailingStop", "breakEven",
                  "limits", "schedule", "evaluateOn"):
        if field in payload:
            doc[field] = payload[field]
    return _ok({"rule": _store.create(principal.user_id, doc)}, created=True)


def _rule_action(action, rid, headers, body):
    # Activation is the moment a configuration becomes capable of producing
    # orders, so it is the one that re-checks the session against Supabase
    # instead of trusting a cached answer, insists on a confirmed address, and
    # requires a live licence.
    sensitive = action == "activate"
    p = _authenticate(headers, fresh=sensitive)

    if action == "validate":
        doc = _store.get(p.user_id, rid)
        problems = _rd.validate(doc, known_condition_ids=_cond.available())
        return _ok({"valid": not problems, "problems": problems})

    if action == "activate":
        # Ownership and existence are settled BEFORE the licence, so an
        # unlicensed client asking about a rule that is not theirs gets the
        # same 404 as for one that never existed, rather than a 402 that
        # confirms the platform got as far as looking.
        _store.get(p.user_id, rid)
        _id.require_verified_email(p)
        _lic.require(p.user_id)
        return _ok({"rule": _store.activate(
            p.user_id, rid, known_condition_ids=_cond.available())})

    if action in ("pause", "resume", "archive"):
        want = {"pause": _rd.PAUSED, "resume": _rd.ACTIVE,
                "archive": _rd.ARCHIVED}[action]
        return _ok({"rule": _store.set_state(p.user_id, rid, want)})

    if action == "version":
        return _ok({"rule": _store.next_version(p.user_id, rid)})

    if action == "preview":
        # Deliberately 501 rather than a fabricated decision. A preview needs
        # a real MarketSnapshot, which needs the broker connection that has
        # not been built yet, and a made-up one would be the single most
        # misleading screen on the platform.
        return _err(501, "UNSUPPORTED",
                    "previewing a decision needs a connected cTrader account",
                    capability="preview")

    return _err(404, "NOT_FOUND", "no such action")
