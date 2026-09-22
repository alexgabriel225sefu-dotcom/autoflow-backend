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
from apex.platform import broker_read as _read
from apex.platform import ctrader_link as _link
from apex.platform import identity as _id
from apex.platform import journal_store as _jstore
from apex.platform import notifications as _notify
from apex.platform import preview as _preview
from apex.platform import licence as _lic
from apex.platform import ruledoc as _rd
from apex.platform import store as _store

PREFIX = "/api/v1/"

# Capabilities that arrive with the broker phase. Listed explicitly so the
# frontend can grey a button out instead of discovering a 404, and so that
# nothing here quietly returns a plausible empty answer in the meantime.
# Everything here is built. The map stays because the next capability to be
# wired will use it, and because an endpoint that answers 501 by design is
# better declared in one place than scattered through the dispatcher.
_NOT_YET = {}


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
_NOTIFY_RE = re.compile(r"^notifications/([A-Za-z0-9_-]{1,64})/read$")
_JOURNAL_RE = re.compile(r"^journal/([A-Za-z0-9_-]{1,64})$")
_ACCOUNT_RE = re.compile(
    r"^accounts/([A-Za-z0-9_-]{1,64})(?:/(positions|orders))?$")
_RULE_RE = re.compile(r"^rules/([A-Za-z0-9_-]{1,64})$")
_RULE_ACTION_RE = re.compile(
    r"^rules/([A-Za-z0-9_-]{1,64})/(validate|activate|pause|resume|archive"
    r"|version|preview)$")
_RULE_VERSION_RE = re.compile(
    r"^rules/([A-Za-z0-9_-]{1,64})/versions/(\d{1,9})$")


def _num(value, field):
    """A number from a query string, or a refusal. Never a silent default.

    A caller who writes ?limit=abc has a bug, and answering with the default
    50 hides it behind a page that looks right.
    """
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number, got {value!r}")


def _query(path):
    """The query string as a flat dict. Only the callback needs it."""
    from urllib.parse import parse_qs, urlparse
    return {k: v[0] for k, v in
            parse_qs(urlparse(path).query or "").items()}


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
        return _dispatch(method, route, headers or {}, body,
                         _query(path))
    except _id.AuthFailed as e:
        return _err(401, "AUTH_REQUIRED", str(e))
    except _id.AuthUnavailable as e:
        # 503, never 401. The client's session may be perfectly good; it is
        # the platform that cannot check right now, and telling them their
        # login is invalid would be a lie that also hides the real fault.
        return _err(503, "AUTH_UNAVAILABLE", str(e))
    except _link.LinkConfigError as e:
        # The platform is misconfigured, which is not the client's fault and
        # must not read as one. 503, like every other "we cannot", never 400.
        return _err(503, e.code, e.detail)
    except _link.LinkError as e:
        return _err(400, e.code, e.detail)
    except _lic.LicenceRequired as e:
        return _err(402, "LICENCE_REQUIRED", str(e), licenceState=e.state)
    except _preview.PreviewRefused as e:
        # INSUFFICIENT_DATA is a 422: the request was understood and the data
        # to answer it was not there. A 400 would say the client malformed it.
        return _err(422 if e.code == "INSUFFICIENT_DATA" else 400,
                    e.code, e.detail)
    except _notify.NotificationNotFound:
        return _err(404, "NOT_FOUND", "no such notification")
    except _jstore.JournalNotFound:
        return _err(404, "NOT_FOUND", "no such journal entry")
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


def _dispatch(method, route, headers, body, query=None):
    head = route.split("/", 1)[0]
    if head in _NOT_YET:
        _authenticate(headers)          # still refuse anonymous callers first
        return _err(501, "UNSUPPORTED",
                    f"{_NOT_YET[head]} is not connected yet",
                    capability=head)

    # ── cTrader linking ─────────────────────────────────────────────────
    # The callback is the ONLY unauthenticated route on this API, and it has
    # to be: cTrader redirects the client's browser here, and a browser
    # arriving from a redirect carries no bearer token. It is safe because it
    # finishes nothing — it parks the code and hands back a nonce, and the
    # link is completed by an authenticated call below.
    if route == "ctrader/callback" and method == "GET":
        return _ok(_link.handle_callback(query or {}), pendingOnly=True)

    if route.startswith("ctrader/"):
        action = route.split("/", 1)[1]
        if method != "POST" and action not in ("status",):
            return _err(405, "METHOD_NOT_ALLOWED", f"{method} not allowed")
        # Connecting a broker account and disconnecting one are both
        # irreversible from the client's point of view, so neither trusts a
        # cached session.
        p = _authenticate(headers, fresh=action in ("complete", "disconnect"))
        if action == "status":
            return _ok({"ctrader": _link.public_status(p.user_id)})
        if action == "connect":
            _id.require_verified_email(p)
            return _ok(_link.begin(p.user_id))
        if action == "complete":
            _id.require_verified_email(p)
            nonce = (_body(body) or {}).get("nonce")
            return _ok({"ctrader": _link.complete(p.user_id, nonce)})
        if action == "select":
            return _ok({"ctrader": _link.select_account(
                p.user_id, (_body(body) or {}).get("ctid"))})
        if action == "disconnect":
            return _ok(_link.disconnect(p.user_id))
        return _err(404, "NOT_FOUND", "no such cTrader action")

    # Accounts are the connected ones, read from the link. Never fabricated:
    # a client with nothing connected gets connected=false and an empty list
    # that is a FACT, not a placeholder.
    if route == "accounts" and method == "GET":
        p = _authenticate(headers)
        return _ok(_link.public_status(p.user_id))

    # ── read-only broker views ──────────────────────────────────────────
    # Every one of these answers {connected, status, ...} and omits its data
    # key unless status is "ok". An empty list of positions is a claim, and it
    # is only made when the broker was actually asked and actually answered.
    m = _ACCOUNT_RE.match(route)
    if m:
        if method != "GET":
            return _err(405, "METHOD_NOT_ALLOWED", f"{method} not allowed")
        p = _authenticate(headers)
        ctid, sub_route = m.group(1), m.group(2)
        if sub_route == "positions":
            return _ok(_read.positions(p.user_id, ctid=ctid))
        if sub_route == "orders":
            return _ok(_read.orders(p.user_id, ctid=ctid))
        return _ok(_read.account(p.user_id, ctid=ctid))

    if route in ("positions", "orders") and method == "GET":
        p = _authenticate(headers)
        fn = _read.positions if route == "positions" else _read.orders
        return _ok(fn(p.user_id))

    # ── notifications ───────────────────────────────────────────────────
    if route == "notifications":
        p = _authenticate(headers)
        q = query or {}
        if method == "GET":
            return _ok(_notify.query(
                p.user_id, type=q.get("type"),
                unread_only=str(q.get("unread", "")).lower()
                in ("1", "true", "yes"),
                limit=_num(q.get("limit"), "limit") or 50,
                offset=_num(q.get("offset"), "offset") or 0))
        return _err(405, "METHOD_NOT_ALLOWED", f"{method} not allowed")

    if route == "notifications/read-all" and method == "POST":
        p = _authenticate(headers)
        return _ok(_notify.mark_all_read(
            p.user_id, type=(_body(body) or {}).get("type")))

    m = _NOTIFY_RE.match(route)
    if m and method == "POST":
        p = _authenticate(headers)
        return _ok(_notify.mark_read(p.user_id, m.group(1)))

    # ── journal ─────────────────────────────────────────────────────────
    if route == "journal" and method == "GET":
        p = _authenticate(headers)
        q = query or {}
        return _ok(_jstore.query(
            p.user_id,
            account_id=q.get("accountId"), symbol=q.get("symbol"),
            since=_num(q.get("since"), "since"),
            until=_num(q.get("until"), "until"),
            rule_doc_id=q.get("ruleDocId"), status=q.get("status"),
            limit=_num(q.get("limit"), "limit") or 50,
            offset=_num(q.get("offset"), "offset") or 0))

    m = _JOURNAL_RE.match(route)
    if m and method == "GET":
        p = _authenticate(headers)
        return _ok({"entry": _jstore.get(p.user_id, m.group(1))})

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
        # Read-only, and it stays that way because of what it does NOT touch:
        # no broker is built, force_trade is never called, no gate is entered
        # and no ExecutionRequest is created. The bars come from the caller,
        # so a preview can never be a verdict reached on invented data.
        doc = _store.get(p.user_id, rid)
        return _ok(_preview.preview(doc,
                                    (_body(body) or {}).get("snapshot")))

    return _err(404, "NOT_FOUND", "no such action")
