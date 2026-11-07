"""Operator audit of the cTrader accounts this platform has connected.

GET only, and only for a signed-in operator. The operator list is
`A4T_OPERATOR_USER_IDS`, the same one the live approval routes use
(`live_gate.is_operator`). A client session, including the owner of the
account being read, is not enough.

The reads themselves are in `ctrader_readonly` and `ctrader_audit_view`.
This module finds the stored connection, passes the token the platform
already holds, and returns a document with no token in it. A broker failure
is scrubbed with those token values before it is written down or returned.
"""

import os
import re

from apex import redact, user_store
from apex.platform import ctrader_audit_view as _view
from apex.platform import ctrader_link as _link
from apex.platform import ctrader_readonly as _ro
from apex.platform import live_gate as _live
from apex.platform import store as _store

_ONE = re.compile(r"^admin/audit/accounts/([0-9]{1,20})$")
_SUB = re.compile(r"^admin/audit/accounts/([0-9]{1,20})/(open|deals|orders)$")
_BANNED_QUERY = ("token", "access_token", "accessToken",
                 "refresh_token", "refreshToken")
_DROP = {"accesstoken", "refreshtoken", "clientsecret"}
_MAX_SPAN_S = 366 * 86400


class AuditError(Exception):
    def __init__(self, code, message, status=400):
        self.code = code
        self.status = int(status)
        self.message = message
        super().__init__(message)


def time_window(query, *, now=None):
    """(start, end) as unix seconds. Absent bounds are the last seven days."""
    import time
    now = time.time() if now is None else float(now)
    raw_from = (query or {}).get("from")
    raw_to = (query or {}).get("to")
    if not raw_from and not raw_to:
        return now - 7 * 86400, now
    if not raw_from or not raw_to:
        raise ValueError("from and to must be given together")
    start, end = _parse_time(raw_from), _parse_time(raw_to)
    if end <= start:
        raise ValueError("to must be after from")
    if end - start > _MAX_SPAN_S:
        raise ValueError("the range cannot be longer than 366 days")
    return start, end


def _parse_time(value):
    from datetime import datetime
    text = str(value).strip()
    if re.fullmatch(r"\d{10,13}", text):
        n = int(text)
        return n / 1000.0 if n > 10_000_000_000 else float(n)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"could not read a time from {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_view.AMSTERDAM)
    return parsed.timestamp()


def _prefix():
    return f"{_store._ns()}:{_store._P}:ctrader:"


def _connection_keys():
    prefix = _prefix()
    if user_store._USE_REDIS:
        found = user_store.scan_keys(prefix + "*")
        return [k for k in found if str(k).startswith(prefix)]
    directory = os.path.join(user_store._DIR, _store._P)
    if not os.path.isdir(directory):
        return []
    marker = prefix.replace(":", "__")
    keys = []
    for name in sorted(os.listdir(directory)):
        if name.endswith(".json") and name.startswith(marker):
            keys.append(name[:-len(".json")].replace("__", ":"))
    return keys


def _load_connections():
    prefix = _prefix()
    out = []
    for key in _connection_keys():
        if not str(key).startswith(prefix):
            continue
        user_id = str(key)[len(prefix):]
        if not user_id or "/" in user_id or ":" in user_id:
            continue
        rec = _store._read_strict(key)
        if not isinstance(rec, dict):
            continue
        if str(rec.get("userId") or "") != user_id:
            continue
        if rec.get("disconnectedAt") or not rec.get("accessToken"):
            continue
        out.append((user_id, rec))
    return out


def _remember(rec, secrets):
    for field in ("accessToken", "refreshToken"):
        try:
            raw = user_store.decrypt_value(rec.get(field) or "")
        except Exception:                                    # noqa: BLE001
            raw = ""
        if isinstance(raw, str) and len(raw) >= 8 and raw not in secrets:
            secrets.append(raw)


def _status_for(err):
    if getattr(err, "code", "") in ("REFRESH_UNAVAILABLE", "REFRESH_FAILED"):
        return "reauth_required"
    return "unavailable"


def _stored_row(user_id, acc, selected, status):
    mode = str((acc or {}).get("mode") or "")
    label = (acc or {}).get("label") or None
    ctid = (acc or {}).get("ctid")
    return {
        "ctidTraderAccountId": int(ctid) if str(ctid or "").isdigit() else ctid,
        "login": None,
        "environment": mode if mode in ("demo", "live") else None,
        "broker": label,
        "platformUserId": user_id,
        "selected": str(ctid) == str(selected),
        "status": status,
    }


def list_accounts(secrets):
    rows = []
    for user_id, rec in _load_connections():
        selected = rec.get("selectedCtid")
        _remember(rec, secrets)
        try:
            token = _link.access_token_for(user_id)
        except _link.LinkError as e:
            for acc in rec.get("accounts") or []:
                rows.append(_stored_row(user_id, acc, selected, _status_for(e)))
            continue
        if isinstance(token, str) and token not in secrets:
            secrets.append(token)
        try:
            live = _ro.describe_token(token)
        except _link.LinkError as e:
            for acc in rec.get("accounts") or []:
                rows.append(_stored_row(user_id, acc, selected, _status_for(e)))
            continue
        except Exception:                                    # noqa: BLE001
            for acc in rec.get("accounts") or []:
                rows.append(_stored_row(user_id, acc, selected, "unavailable"))
            continue
        seen = set()
        for acc in live or []:
            ctid = acc.get("ctidTraderAccountId")
            rows.append({
                "ctidTraderAccountId": ctid,
                "login": acc.get("login"),
                "environment": acc.get("environment"),
                "broker": acc.get("broker"),
                "platformUserId": user_id,
                "selected": str(ctid) == str(selected),
                "status": "ok",
            })
            seen.add(str(ctid))
        for acc in rec.get("accounts") or []:
            if str(acc.get("ctid")) not in seen:
                rows.append(_stored_row(user_id, acc, selected, "unavailable"))
    rows.sort(key=lambda row: (str(row.get("platformUserId")),
                               str(row.get("ctidTraderAccountId"))))
    return rows


def _find(ctid):
    found = []
    for user_id, rec in _load_connections():
        for acc in rec.get("accounts") or []:
            if str(acc.get("ctid")) == str(ctid):
                found.append((user_id, rec, acc))
    found.sort(key=lambda item: str(item[1].get("selectedCtid")) != str(ctid))
    return found


def _open(ctid, secrets):
    found = _find(ctid)
    if not found:
        raise AuditError("NOT_FOUND",
                         "no connected cTrader account with that id", 404)
    user_id, rec, acc = found[0]
    env = str(acc.get("mode") or "")
    if env not in ("demo", "live"):
        raise AuditError("UNAVAILABLE",
                         "the stored account has no demo or live mode", 503)
    if env == "live" and not _link.live_allowed():
        raise _link.LinkError(
            "LIVE_BLOCKED",
            "live accounts are blocked in this environment")
    _remember(rec, secrets)
    token = _link.access_token_for(user_id)
    if isinstance(token, str) and token not in secrets:
        secrets.append(token)
    return user_id, env, token


def _err(status, code, message, secrets):
    text = redact.scrub_for_client(str(message or ""), *secrets, limit=300)
    return status, _clean(
        {"ok": False, "error": {"code": code, "message": text}}, secrets)


def _ok(payload, secrets):
    body = {"ok": True}
    body.update(payload or {})
    return 200, _clean(body, secrets)


def _clean(value, secrets):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            folded = str(key).replace("_", "").lower()
            if folded in _DROP:
                continue
            out[key] = _clean(item, secrets)
        return out
    if isinstance(value, list):
        return [_clean(item, secrets) for item in value]
    if isinstance(value, str):
        cleaned = value
        for sec in secrets:
            if isinstance(sec, str) and len(sec) >= 8 and sec in cleaned:
                cleaned = cleaned.replace(sec, "[redacted]")
        return cleaned
    return value


def _stamp(seconds):
    return _view.iso_amsterdam(seconds)


def handle(method, route, principal, query):
    """(status, body). Authenticated callers only; the API checks that first."""
    secrets = []
    try:
        return _handle(method, route, principal, query or {}, secrets)
    except _link.LinkConfigError:
        raise
    except user_store.StoreUnavailable:
        raise
    except _link.LinkError as e:
        return _err(400, e.code, e.detail, secrets)
    except AuditError as e:
        return _err(e.status, e.code, e.message, secrets)
    except ValueError as e:
        return _err(400, "BAD_REQUEST", str(e), secrets)
    except _ro.ReadOnlyViolation:
        return _err(500, "READ_ONLY_VIOLATION",
                    "the audit client refused a request that is not read-only",
                    secrets)
    except Exception as e:                                   # noqa: BLE001
        return _err(503, "BROKER_UNAVAILABLE", str(e), secrets)


def _handle(method, route, principal, query, secrets):
    if not _live.is_operator(getattr(principal, "user_id", None)):
        return 403, {"ok": False, "error": {
            "code": "NOT_OPERATOR",
            "message": "this action is limited to an operator"}}
    if (method or "GET").upper() != "GET":
        return 405, {"ok": False, "error": {
            "code": "METHOD_NOT_ALLOWED",
            "message": f"{method} is not allowed here"}}
    for key in _BANNED_QUERY:
        if key in query:
            raise AuditError(
                "BAD_REQUEST",
                "credentials are not accepted on this endpoint", 400)
    if route == "admin/audit/accounts":
        return _ok({"accounts": list_accounts(secrets)}, secrets)
    sub = _SUB.match(route or "")
    one = _ONE.match(route or "")
    if not sub and not one:
        raise AuditError("NOT_FOUND", "no such audit endpoint", 404)
    ctid = (sub or one).group(1)
    user_id, env, token = _open(ctid, secrets)
    if one:
        summary = _ro.describe_summary(env, token, int(ctid))
        summary.update(environment=env, platformUserId=user_id)
        return _ok({"account": summary}, secrets)
    kind = sub.group(2)
    if kind == "open":
        body = _view.describe_open(env, token, int(ctid))
    else:
        start, end = time_window(query)
        reader = _view.describe_deals if kind == "deals" else _view.describe_orders
        body = reader(env, token, int(ctid), start, end)
        body["from"] = _stamp(start)
        body["to"] = _stamp(end)
    body["ctidTraderAccountId"] = int(ctid)
    body["environment"] = env
    body["platformUserId"] = user_id
    return _ok(body, secrets)
