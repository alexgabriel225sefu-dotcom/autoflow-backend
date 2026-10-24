"""The hard gate in front of live trading for money.

A client reaches a live order only when every condition below is known and
met, on top of the locks that already exist (the release switch, the broker
account flag, the plan, the pilot, the emergency stop). Demo is not this
gate's business and is not blocked here.

Conditions, all of them server-side:

  the release switch and live-account flag, as the caller read them
  legal terms, refund terms and tax terms, published by an operator
  the client has accepted the versions that are published now
  a confirmed lifetime licence at the approved price, from a payment event
    or an operator action — a founder licence on its own is not this record
  an operator has approved this client's live-account request

A read that fails is not a "no". It is unknown, and unknown is closed.
Nothing here imports the audit trail, the entitlement module, or the order
path at import time: the audit trail refuses to import without a shared
backend, and those modules import this one.
"""

import os
import re
import time

from apex.platform import billing as _billing
from apex.platform import licence as _lic
from apex.platform import store as _store
from apex.platform.safe_errors import message as _safe

# The approved offer lives in billing.py. This module does not keep a second price.
PRICE_MINOR = _billing.APPROVED_PRICE_MINOR
CURRENCY = _billing.APPROVED_CURRENCY
PLAN = _billing.APPROVED_PLAN
TERM = "lifetime"

DOCUMENTS = ("terms", "refund", "tax")
_DOC_CODE = {"terms": "LEGAL_TERMS", "refund": "REFUND_TERMS", "tax": "TAX_TERMS"}
_DOC_NAME = {"terms": "Legal terms", "refund": "Refund terms", "tax": "Tax terms"}
_ACCEPT_DETAIL = {
    "terms": "You have not accepted the current legal terms.",
    "refund": "You have not accepted the current refund terms.",
    "tax": "You have not accepted the current tax terms.",
}

_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_USER = re.compile(r"^[A-Za-z0-9_.:@+-]{1,128}$")

_SUMMARY_CLOSED = (
    "Live trading is not available until every condition below is met.")
_SUMMARY_UNKNOWN = (
    "Live trading is not available. One or more conditions could not be "
    "read, so they are treated as closed.")
_SUMMARY_OPEN = (
    "All checked conditions are met. A live order is still sent only when "
    "the order gate allows it.")

OPERATOR_ENV = "A4T_OPERATOR_USER_IDS"


class LiveGateError(Exception):
    """A refusal this module can explain. Carries an HTTP status and a code."""

    def __init__(self, code, message, status=400):
        self.code = code
        self.status = int(status)
        super().__init__(message)


def _key(suffix):
    return f"{_store._ns()}:{_store._P}:livegate:{suffix}"


def _load(key):
    """(document or None, error or None). Absent is a fact; a failure is not."""
    try:
        doc = _store._read_strict(key)
    except Exception as e:                                   # noqa: BLE001
        return None, e
    if doc is None:
        return None, None
    if not isinstance(doc, dict):
        return None, ValueError("stored live-gate record is not an object")
    return doc, None


def _require_actor(actor):
    if not str(actor or "").strip():
        raise LiveGateError(
            "NO_ACTOR",
            "this change must record who made it",
            status=400)


def _audit_required(fn):
    """Run an audit write. If it cannot be written, the caller must not store."""
    from apex.platform import audit as _audit
    return fn(_audit)


def _audit_best_effort(fn):
    """A payment path must not 500 a webhook solely because the trail is down.

    The store write that follows is still strict. Losing the trail entry is
    logged as a type name only — the message can carry a payment id.
    """
    try:
        from apex.platform import audit as _audit
        fn(_audit)
    except Exception as e:                                   # noqa: BLE001
        print(f"[LiveGate] audit skipped ({type(e).__name__})")


def _scrub(exc):
    text = _safe(exc)
    return re.sub(r"(?i)\bbearer\b", "[redacted]", text)


def _cond(code, status, detail):
    return {"code": code, "status": status, "detail": detail}


def _flag(code, value, off_detail):
    if value is None:
        return _cond(code, "unknown", off_detail)
    if value is True:
        return _cond(code, "ok", "Met.")
    return _cond(code, "missing", off_detail)


def _checkout_open():
    try:
        return bool(_billing.checkout_enabled()
                    and _billing.authenticated_checkout_enabled()
                    and _billing.checkout_implemented())
    except Exception:                                        # noqa: BLE001
        return False


def unreadable_verdict():
    """Used when the gate itself could not be asked. Closed, and said so."""
    return {
        "open": False,
        "status": "unknown",
        "summary": _SUMMARY_UNKNOWN,
        "conditions": [],
        "missing": [],
        "request": {"status": "unknown"},
        "checkoutOpen": False,
    }


def _paid_ok(rec):
    if not isinstance(rec, dict) or rec.get("confirmed") is not True:
        return False
    try:
        price = int(rec.get("priceMinor"))
    except (TypeError, ValueError):
        return False
    return (price == PRICE_MINOR
            and str(rec.get("currency") or "").lower() == CURRENCY
            and str(rec.get("term") or "") == TERM)


def _request_status(rec):
    status = str((rec or {}).get("status") or "")
    if status in ("pending", "approved", "rejected"):
        return status
    return "none"


def public_verdict(user_id, *, release_switch, live_accounts_allowed):
    """What the client may be shown. No payment reference and no actor."""
    uid = str(user_id or "")
    conditions = [
        _flag("RELEASE_SWITCH", release_switch,
              "The live-execution switch is off for this deployment."),
        _flag("LIVE_ACCOUNTS", live_accounts_allowed,
              "Live broker accounts are not allowed on this deployment."),
    ]
    published, pub_err = _load(_key("published"))
    accepted, acc_err = _load(_key(f"accept:{uid}"))
    paid, paid_err = _load(_key(f"paid:{uid}"))
    request, req_err = _load(_key(f"request:{uid}"))

    for doc in DOCUMENTS:
        code = _DOC_CODE[doc]
        name = _DOC_NAME[doc]
        if pub_err is not None:
            conditions.append(_cond(code, "unknown", _scrub(pub_err)))
            conditions.append(_cond(code + "_ACCEPTED", "unknown", _scrub(pub_err)))
            continue
        current = (published or {}).get(doc) if isinstance(published, dict) else None
        version = (current or {}).get("version") if isinstance(current, dict) else None
        if not version:
            conditions.append(_cond(
                code, "missing", f"{name} are not published."))
            conditions.append(_cond(
                code + "_ACCEPTED", "missing",
                f"{name} are not published, so there is no current version "
                f"to accept."))
            continue
        conditions.append(_cond(code, "ok", f"{name} {version} are published."))
        if acc_err is not None:
            conditions.append(_cond(
                code + "_ACCEPTED", "unknown", _scrub(acc_err)))
            continue
        got = ((accepted or {}).get(doc) or {}) if isinstance(accepted, dict) else {}
        if str(got.get("version") or "") == str(version):
            conditions.append(_cond(code + "_ACCEPTED", "ok", "Accepted."))
        else:
            conditions.append(_cond(
                code + "_ACCEPTED", "missing", _ACCEPT_DETAIL[doc]))

    if paid_err is not None:
        conditions.append(_cond("PAID_LICENCE", "unknown", _scrub(paid_err)))
    elif _paid_ok(paid):
        conditions.append(_cond("PAID_LICENCE", "ok", "A confirmed lifetime licence is on file."))
    else:
        conditions.append(_cond(
            "PAID_LICENCE", "missing",
            "No confirmed lifetime licence is on file."))

    if req_err is not None:
        req_status = "unknown"
        conditions.append(_cond("OPERATOR_APPROVAL", "unknown", _scrub(req_err)))
    else:
        req_status = _request_status(request)
        if req_status == "approved":
            conditions.append(_cond("OPERATOR_APPROVAL", "ok", "Approved."))
        elif req_status == "pending":
            conditions.append(_cond(
                "OPERATOR_APPROVAL", "missing",
                "An operator has not approved the live account request."))
        elif req_status == "rejected":
            conditions.append(_cond(
                "OPERATOR_APPROVAL", "missing",
                "An operator declined the live account request."))
        else:
            conditions.append(_cond(
                "OPERATOR_APPROVAL", "missing",
                "You have not requested a live account connection."))

    unknown = any(c["status"] == "unknown" for c in conditions)
    missing = [c for c in conditions if c["status"] != "ok"]
    if unknown:
        status, summary, open_ = "unknown", _SUMMARY_UNKNOWN, False
    elif missing:
        status, summary, open_ = "closed", _SUMMARY_CLOSED, False
    else:
        status, summary, open_ = "open", _SUMMARY_OPEN, True
    return {
        "open": open_,
        "status": status,
        "summary": summary,
        "conditions": conditions,
        "missing": missing,
        "request": {"status": req_status},
        "checkoutOpen": _checkout_open(),
    }


def order_block(user_id):
    """None when the gate is open. Otherwise (code, summary). Never raises.

    Re-reads the release switch and the live-account flag itself, so a stub
    on those functions applies and this door cannot skip them.
    """
    try:
        from apex.platform import ctrader_link as _link
        from apex.platform import entitlement as _ent
        verdict = public_verdict(
            user_id,
            release_switch=_ent.live_execution_enabled(),
            live_accounts_allowed=_link.live_allowed())
    except Exception as e:                                   # noqa: BLE001
        return ("LIVE_GATE_UNKNOWN", _scrub(e) or _SUMMARY_UNKNOWN)
    if verdict.get("open") is True and verdict.get("status") == "open":
        return None
    code = ("LIVE_GATE_UNKNOWN" if verdict.get("status") == "unknown"
            else "LIVE_GATE_CLOSED")
    return (code, verdict.get("summary") or _SUMMARY_CLOSED)


def operators():
    raw = os.getenv(OPERATOR_ENV) or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


def is_operator(user_id):
    return str(user_id or "") in operators()


def _require_operator(principal):
    if not is_operator(getattr(principal, "user_id", None)):
        raise LiveGateError(
            "NOT_OPERATOR", "this action is limited to an operator", status=403)


def _check_version(version):
    if not isinstance(version, str) or not _VERSION.match(version):
        raise LiveGateError(
            "BAD_VERSION",
            "a version is a short token of letters, digits, dots, underscores "
            "or hyphens",
            status=400)


def _check_user(user_id):
    if not isinstance(user_id, str) or not _USER.match(user_id):
        raise LiveGateError("BAD_USER", "that user id is not usable", status=400)
    return user_id


def publish(document, version, *, actor):
    """Operator: mark one document published at this version."""
    _require_actor(actor)
    if document not in DOCUMENTS:
        raise LiveGateError("BAD_DOCUMENT", "unknown document", status=400)
    _check_version(version)
    current, err = _load(_key("published"))
    if err is not None:
        raise LiveGateError("STORE_UNAVAILABLE", _scrub(err), status=503)
    current = dict(current or {})
    old = ((current.get(document) or {}).get("version")
           if isinstance(current.get(document), dict) else None)

    def write(audit):
        audit.record_entitlement_change(
            user_id=str(actor), actor=str(actor),
            field=f"publish:{document}",
            old_value=old, new_value=version,
            reason="operator published the current version")

    _audit_required(write)
    current[document] = {"version": version, "publishedAt": time.time(),
                         "actor": str(actor)}
    _store._write_strict(_key("published"), current)
    return current[document]


def accept_current(user_id):
    """The client accepts whatever versions are published. The body cannot pick one."""
    uid = _check_user(str(user_id))
    published, err = _load(_key("published"))
    if err is not None:
        raise LiveGateError("STORE_UNAVAILABLE", _scrub(err), status=503)
    published = published or {}
    targets = []
    for doc in DOCUMENTS:
        cur = published.get(doc)
        version = cur.get("version") if isinstance(cur, dict) else None
        if version:
            targets.append((doc, str(version)))
    if not targets:
        raise LiveGateError(
            "NOT_PUBLISHED",
            "nothing is published to accept yet",
            status=409)
    accepted, acc_err = _load(_key(f"accept:{uid}"))
    if acc_err is not None:
        raise LiveGateError("STORE_UNAVAILABLE", _scrub(acc_err), status=503)
    accepted = dict(accepted or {})
    for doc, version in targets:
        already = accepted.get(doc) if isinstance(accepted.get(doc), dict) else {}
        if str(already.get("version") or "") == version:
            continue

        def write(audit, doc=doc, version=version):
            audit.record_consent_change(
                user_id=uid, actor=uid, document=doc,
                version=version, granted=True)

        _audit_required(write)
        accepted[doc] = {"version": version, "acceptedAt": time.time()}
        _store._write_strict(_key(f"accept:{uid}"), accepted)
    return accepted


def _queue_update(user_id, status):
    queue, err = _load(_key("queue"))
    if err is not None:
        return
    queue = dict(queue or {})
    prev = queue.get(user_id) if isinstance(queue.get(user_id), dict) else {}
    queue[user_id] = {
        "status": status,
        "requestedAt": prev.get("requestedAt") or time.time(),
    }
    try:
        _store._write_strict(_key("queue"), queue)
    except Exception as e:                                   # noqa: BLE001
        print(f"[LiveGate] queue was not updated ({type(e).__name__})")


def request_live(user_id):
    """The client asks for a live account connection. This does not connect one."""
    uid = _check_user(str(user_id))
    current, err = _load(_key(f"request:{uid}"))
    if err is not None:
        raise LiveGateError("STORE_UNAVAILABLE", _scrub(err), status=503)
    status = _request_status(current)
    if status in ("pending", "approved"):
        return current
    old = status

    def write(audit):
        audit.record_entitlement_change(
            user_id=uid, actor=uid, field="live_request",
            old_value=old, new_value="pending",
            reason="client requested a live account connection")

    _audit_required(write)
    rec = {"status": "pending", "requestedAt": time.time()}
    _store._write_strict(_key(f"request:{uid}"), rec)
    _queue_update(uid, "pending")
    return rec


def decide(user_id, decision, *, actor, reason=None):
    """Operator approves or rejects an existing request."""
    _require_actor(actor)
    uid = _check_user(str(user_id))
    if decision not in ("approved", "rejected"):
        raise LiveGateError("BAD_DECISION", "decision must be approved or rejected",
                            status=400)
    current, err = _load(_key(f"request:{uid}"))
    if err is not None:
        raise LiveGateError("STORE_UNAVAILABLE", _scrub(err), status=503)
    if _request_status(current) == "none":
        raise LiveGateError(
            "NO_REQUEST", "this client has not requested a live account",
            status=409)
    clean = _scrub(str(reason or ""))[:500]
    old = _request_status(current)

    def write(audit):
        audit.record_entitlement_change(
            user_id=uid, actor=str(actor), field="operator_approval",
            old_value=old, new_value=decision, reason=clean or None)

    _audit_required(write)
    rec = dict(current or {})
    rec.update({"status": decision, "decidedAt": time.time(),
                "actor": str(actor), "reason": clean})
    _store._write_strict(_key(f"request:{uid}"), rec)
    _queue_update(uid, decision)
    return {"status": decision}


def _write_paid(user_id, *, source, actor, payment_ref=None):
    rec = {
        "confirmed": True,
        "priceMinor": PRICE_MINOR,
        "currency": CURRENCY,
        "term": TERM,
        "source": source,
        "recordedAt": time.time(),
    }
    if actor:
        rec["actor"] = str(actor)
    if payment_ref:
        rec["paymentRef"] = str(payment_ref)
    _store._write_strict(_key(f"paid:{user_id}"), rec)
    return rec


def grant_operator_licence(user_id, *, actor):
    """Operator: record the confirmed licence and grant the founder plan.

    The paid record is the gate. The plan grant is what the existing
    entitlement check reads. Neither one is enough on its own.
    """
    _require_actor(actor)
    uid = _check_user(str(user_id))

    def write(audit):
        audit.record_entitlement_change(
            user_id=uid, actor=str(actor), field="paid_licence",
            old_value=None, new_value=f"{TERM}:{PRICE_MINOR}:{CURRENCY}",
            reason="operator recorded a confirmed lifetime licence")

    _audit_required(write)
    rec = _write_paid(uid, source="operator", actor=actor)
    _lic.grant(uid, plan=PLAN, expires_at=None)
    return rec


def _explicit_charge(obj):
    """(amount, currency) only when the object itself states both."""
    if not isinstance(obj, dict):
        return None, None
    amount = None
    for key in ("amount_total", "amount_received", "amount_paid", "amount"):
        value = obj.get(key)
        if isinstance(value, (int, float)):
            amount = int(value)
            break
    currency = str(obj.get("currency") or "").strip().lower()
    if amount is None or not currency:
        return None, None
    return amount, currency


def note_confirmed_payment(user_id, obj, *, payment_ref=None, lifetime=False):
    """Write the paid record only for an explicit 49700 usd lifetime charge.

    A missing amount does not count, even though the licence grant treats a
    missing amount as not a mismatch. Returns False when nothing was written.
    Raises only when a write that should have happened did not.
    """
    if not lifetime:
        return False
    amount, currency = _explicit_charge(obj)
    if amount != PRICE_MINOR or currency != CURRENCY:
        return False
    uid = str(user_id or "").strip()
    if not uid:
        return False

    def write(audit):
        audit.record_entitlement_change(
            user_id=uid, actor="system:billing", field="paid_licence",
            old_value=None, new_value=f"{TERM}:{PRICE_MINOR}:{CURRENCY}",
            reason="confirmed payment")

    _audit_best_effort(write)
    _write_paid(uid, source="payment", actor="system:billing",
                payment_ref=payment_ref)
    return True


def clear_paid_licence(user_id):
    """Remove the paid record. Missing is success. Does not stop a running loop."""
    uid = str(user_id or "").strip()
    if not uid:
        return False
    return bool(_store._delete(_key(f"paid:{uid}")))


def _verdict_for(user_id):
    from apex.platform import ctrader_link as _link
    from apex.platform import entitlement as _ent
    return public_verdict(
        user_id,
        release_switch=_ent.live_execution_enabled(),
        live_accounts_allowed=_link.live_allowed())


def _public_request(user_id):
    """Status only. The actor and the reason stay on the operator read."""
    rec, err = _load(_key(f"request:{user_id}"))
    if err is not None:
        raise LiveGateError("STORE_UNAVAILABLE", _scrub(err), status=503)
    return {"status": _request_status(rec)}


def _operator_request(user_id):
    rec, err = _load(_key(f"request:{user_id}"))
    if err is not None:
        raise LiveGateError("STORE_UNAVAILABLE", _scrub(err), status=503)
    out = {"status": _request_status(rec), "verdict": _verdict_for(user_id)}
    if isinstance(rec, dict) and rec.get("reason"):
        out["reason"] = _scrub(rec.get("reason"))
    return out


def _queue():
    queue, err = _load(_key("queue"))
    if err is not None:
        raise LiveGateError("STORE_UNAVAILABLE", _scrub(err), status=503)
    rows = []
    for uid, rec in (queue or {}).items():
        if not isinstance(rec, dict):
            continue
        rows.append({"userId": uid, "status": rec.get("status"),
                     "requestedAt": rec.get("requestedAt")})
    rows.sort(key=lambda row: row.get("requestedAt") or 0)
    return rows


def http(method, route, principal, body):
    """(status, body) for the live routes. AuthFailed propagates."""
    try:
        return _http(method, route, principal, body or {})
    except LiveGateError as e:
        return e.status, {"ok": False, "error": {
            "code": e.code, "message": _scrub(e)}}


def _http(method, route, principal, body):
    uid = str(getattr(principal, "user_id", "") or "")
    if route == "live/status" and method == "GET":
        return 200, dict({"ok": True}, **_verdict_for(uid))
    if route == "live/accept" and method == "POST":
        accept_current(uid)
        return 200, dict({"ok": True}, **_verdict_for(uid))
    if route == "live/request" and method == "POST":
        # `mode` in the body is ignored. This records a request; it does not
        # select an account or start anything.
        request_live(uid)
        return 200, dict({"ok": True}, **_verdict_for(uid))
    if route == "live/queue" and method == "GET":
        _require_operator(principal)
        return 200, {"ok": True, "requests": _queue()}
    if route == "live/terms/publish" and method == "POST":
        _require_operator(principal)
        publish(body.get("document"), body.get("version"), actor=uid)
        return 200, {"ok": True, "published": True}
    if route == "live/licence/grant" and method == "POST":
        _require_operator(principal)
        grant_operator_licence(body.get("userId"), actor=uid)
        return 200, {"ok": True, "granted": True}
    match = re.fullmatch(r"live/requests/([^/]+)", route or "")
    if match and method == "GET":
        _require_operator(principal)
        target = _check_user(match.group(1))
        return 200, dict({"ok": True}, **_operator_request(target))
    match = re.fullmatch(r"live/requests/([^/]+)/decide", route or "")
    if match and method == "POST":
        _require_operator(principal)
        target = _check_user(match.group(1))
        decide(target, body.get("decision"), actor=uid, reason=body.get("reason"))
        return 200, dict({"ok": True}, **_operator_request(target))
    if (route or "").startswith("live"):
        return 405, {"ok": False, "error": {
            "code": "METHOD_NOT_ALLOWED", "message": f"{method} is not allowed here"}}
    return 404, {"ok": False, "error": {
        "code": "NOT_FOUND", "message": "no such live route"}}
