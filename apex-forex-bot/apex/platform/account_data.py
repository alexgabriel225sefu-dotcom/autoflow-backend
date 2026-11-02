"""A client's own data: export it, or erase it. (GDPR art. 15, 17 and 20.)

THE ONE RULE THIS FILE ENFORCES: it only ever touches keys that belong to the
caller, and it never hands out a credential.

WHAT "BELONGS TO THE CALLER" MEANS HERE

Every per-user record on the platform carries the Supabase user id as one
colon-separated segment of its storage key — `a4t:rule:<uid>:<rid>`,
`a4t:licence:<uid>`, `forex:user:<uid>`, `a4t:rl:user:emergency_user:<uid>:…`.
So the set of keys a client owns is the set of keys in the product namespace
with the id as a whole segment. That is found by scanning rather than by a
list of key builders, on purpose: a list is correct until the next module adds
a per-user record and forgets to add it here, and an erasure that misses a
table is exactly the failure an erasure must not have.

The id is validated to `[A-Za-z0-9_-]` before it goes anywhere near a scan
pattern, and matched as a WHOLE segment, so one id can never select another
client's keys by being a substring of theirs.

Two record kinds carry the id in the VALUE rather than the key, and are found
by reading: `billing:ref:<payment>` (which payment granted whom) and the
engine's active-user set. Both are handled explicitly below.

WHAT IS NOT ERASED HERE, SAID PLAINLY

  * The Supabase auth user. Removing it needs the service-role key; without
    `SUPABASE_SERVICE_ROLE_KEY` the answer says `authUserDeleted: false` and
    names the manual step.
  * Access at cTrader. The platform forgets the tokens; cTrader offers no
    revoke call this code uses, so the client is told to withdraw the app's
    access there.
  * Positions already open at the broker. Automation is stopped first; open
    demo positions stay at the broker, where the client can close them.
  * Shared records that mention the client inside a list (the live-access
    review queue). They are operator records, not the client's documents.

This module does not import the trading engine. Stopping automation is done
by the caller, through `automation.stop`, and handed in as a function.
"""

import json
import os
import re
import time
from datetime import datetime, timezone

from apex import user_store
from apex.platform import ctrader_link as _link
from apex.platform import licence as _lic
from apex.platform import store as _store

CONFIRM_WORD = "DELETE"
SERVICE_ROLE_ENV = "SUPABASE_SERVICE_ROLE_KEY"

_UID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# Segment after "<ns>:a4t:" -> the category reported to the client.
_A4T_CATEGORY = {
    "rule": "rules", "rulev": "rules", "rules": "rules",
    "jentry": "journal", "jindex": "journal", "jlock": "journal",
    "notify": "notifications", "notifylock": "notifications",
    "licence": "licence",
    "ctrader": "ctraderLink", "ctlink": "ctraderLink",
    "automation": "automation", "autolock": "automation",
    "suggestion": "approvals", "suggclaim": "approvals",
    "audit": "audit", "referral": "referral", "livegate": "liveAccess",
    "billing": "billing", "rl": "caches", "orderrate": "caches",
}
# Segment after "<ns>:" for the engine's own per-user keys.
_ENGINE_CATEGORY = {"user": "settings", "uver": "settings",
                    "trades": "trades", "tver": "trades"}

# Always present in a deletion answer, zero when nothing was there, so the UI
# can render a stable list.
_REPORTED = ("rules", "journal", "notifications", "licence", "ctraderLink",
             "settings", "trades", "automation", "caches")

# Never exported: locks, indexes, counters, and the raw broker link (its
# public metadata is exported through `ctrader_link.public_status`, which
# carries no token).
_NOT_EXPORTED = {"rules", "jindex", "jlock", "notifylock", "autolock",
                 "suggclaim", "rl", "orderrate", "ctrader", "ctlink",
                 "licence", "uver", "tver"}

_SECRET_NAME = re.compile(
    r"(token|secret|password|passwd|api_?key|private_?key|signature|nonce)",
    re.IGNORECASE)
# `anthropic_key`, `masked_key`, `serviceKey`: a name ENDING in key.
_KEY_NAME = re.compile(r"(^|_)key$|[a-z]Key$")


class AccountDataError(Exception):
    """A refusal safe to show the client. Becomes `{code, message}`."""

    def __init__(self, code, message, status=400):
        self.code, self.status = code, int(status)
        super().__init__(message)


def _uid(user_id):
    uid = str(user_id or "")
    if not _UID_RE.match(uid):
        # Not a 400: the id came from Supabase, not the client.
        raise AccountDataError("UNSUPPORTED_ACCOUNT_ID",
                               "this account id cannot be processed "
                               "automatically — contact support", status=409)
    return uid


def scrub(value):
    """A copy with every credential-shaped field and every ciphertext removed.

    Names, not values, decide: a field called `accessToken` is dropped
    whatever it holds. A string that is a stored ciphertext (`enc:…`) is
    dropped too, whatever it is called.
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            name = str(k)
            if (_SECRET_NAME.search(name) or _KEY_NAME.search(name)
                    or name in user_store._SENSITIVE_FIELDS):
                continue
            if isinstance(v, str) and v.startswith(user_store._ENC_PREFIX):
                continue
            out[k] = scrub(v)
        return out
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


# ── which keys are the caller's ─────────────────────────────────────────────
def _category(key):
    """(category, kind) for an owned key; kind is the segment that named it."""
    parts = key.split(":")
    if len(parts) >= 3 and parts[1] == _store._P:
        kind = parts[2]
        return _A4T_CATEGORY.get(kind, "other"), kind
    if len(parts) >= 2 and parts[1] in _ENGINE_CATEGORY:
        return _ENGINE_CATEGORY[parts[1]], parts[1]
    return "other", parts[1] if len(parts) > 1 else ""


def _owned(key, uid):
    return uid in key.split(":")


def owned_keys(user_id):
    """[(key, category, kind)] for every stored key that is this user's."""
    uid = _uid(user_id)
    ns = _store._ns()
    if user_store._USE_REDIS:
        candidates = user_store.scan_keys(f"{ns}:*{uid}*")
    else:
        candidates = _store.all_keys()
    out = []
    for key in candidates:
        if key.startswith(f"{ns}:") and _owned(key, uid):
            cat, kind = _category(key)
            out.append((key, cat, kind))
    return sorted(out)


def _billing_refs_of(uid):
    """Payment-reference records whose VALUE names this user."""
    prefix = f"{_store.namespace_prefix()}billing:ref:"
    if user_store._USE_REDIS:
        keys = user_store.scan_keys(prefix + "*")
    else:
        keys = [k for k in _store.all_keys() if k.startswith(prefix)]
    if not keys:
        return []
    docs = _store._read_many_strict(keys)
    return [k for k, d in zip(keys, docs)
            if isinstance(d, dict) and str(d.get("userId")) == uid]


def _engine_files(uid):
    """The engine's local JSON files, development backend only."""
    if user_store._USE_REDIS:
        return []
    base = user_store._path(uid)
    return [(p, cat) for p, cat in ((base, "settings"),
                                    (base + ".trades", "trades"))
            if os.path.exists(p)]


# ── export ──────────────────────────────────────────────────────────────────
def _read_doc(key):
    if user_store._USE_REDIS and user_store.key_type(key) == "set":
        return None
    try:
        return _store._read_strict(key)
    except ValueError:
        return {"unreadable": True}


def export(user_id, *, now=None):
    """Everything this client owns, as JSON, with no credential in it."""
    uid = _uid(user_id)
    data = {cat: [] for cat in ("rules", "ruleVersions", "journal",
                                "notifications", "approvals", "automation",
                                "audit", "referral", "liveAccess", "billing",
                                "other")}
    for key, cat, kind in owned_keys(uid):
        if kind in _NOT_EXPORTED or kind == "rule":
            continue
        doc = _read_doc(key)
        if doc is None:
            continue
        if kind == "rulev":
            cat = "ruleVersions"
        if kind == "notify" and isinstance(doc, list):
            data["notifications"].extend(
                r for r in doc
                if isinstance(r, dict) and str(r.get("userId")) == uid)
            continue
        # Second line of defence, as in store._owned: a document that names a
        # different owner is not exported, whatever key it was found under.
        if isinstance(doc, dict) and doc.get("userId") not in (None, uid):
            continue
        data.setdefault(cat, []).append(doc)
    data["rules"] = _store.list_docs(uid)
    data["licence"] = _lic.status_for(uid)
    data["ctraderLink"] = _link.public_status(uid)
    data["settings"] = user_store.load(uid) or {}
    data["trades"] = list(user_store.load_trades(uid) or [])
    stamp = datetime.fromtimestamp(time.time() if now is None else now,
                                   tz=timezone.utc)
    return {"exportedAt": stamp.isoformat().replace("+00:00", "Z"),
            "data": scrub(data)}


# ── erasure ─────────────────────────────────────────────────────────────────
def _default_auth_deleter(url, service_key, uid):
    import requests
    r = requests.delete(
        f"{url}/auth/v1/admin/users/{uid}", timeout=10,
        headers={"apikey": service_key,
                 "Authorization": f"Bearer {service_key}"})
    return r.status_code


def _delete_auth_user(uid, deleter=None):
    """(deleted, note). Never logs or returns the key."""
    key = (os.getenv(SERVICE_ROLE_ENV) or "").strip()
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    manual = ("your sign-in account itself still exists and will be "
              "removed by support; signing in again would start a new, "
              "empty account")
    if not key or not url:
        return False, manual
    try:
        status = (deleter or _default_auth_deleter)(url, key, uid)
    except Exception as e:                                   # noqa: BLE001
        print(f"[ACCOUNT] auth user deletion failed ({type(e).__name__})")
        return False, manual
    # 404: already gone, which is the state asked for (idempotent).
    if status in (200, 204, 404):
        return True, None
    print(f"[ACCOUNT] auth user deletion answered {status}")
    return False, manual


def delete(user_id, body, *, stop_automation, auth_deleter=None):
    """Erase everything this client owns. Idempotent.

    `stop_automation(uid)` runs FIRST, and a stop that fails erases nothing:
    deleting the records under a loop that may still be trading would remove
    the very state that tells it to stop, and the client's ability to see it.
    """
    uid = _uid(user_id)
    if not isinstance(body, dict) or body.get("confirm") != CONFIRM_WORD:
        raise AccountDataError(
            "CONFIRMATION_REQUIRED",
            f'send {{"confirm": "{CONFIRM_WORD}"}} to erase this account')
    try:
        stop_automation(uid)
    except Exception as e:                                   # noqa: BLE001
        print(f"[ACCOUNT] stop before erasure failed for {uid} "
              f"({type(e).__name__}) — nothing erased")
        raise AccountDataError(
            "AUTOMATION_STOP_FAILED",
            "automation could not be confirmed stopped, so nothing was "
            "deleted — try again in a minute", status=503)

    deleted = {cat: 0 for cat in _REPORTED}

    def _count(cat, removed):
        if removed:
            deleted[cat] = deleted.get(cat, 0) + 1

    for key, cat, _kind in owned_keys(uid):
        _count(cat, _store._delete(key))
    for key in _billing_refs_of(uid):
        _count("billing", _store._delete(key))
    for path, cat in _engine_files(uid):
        os.remove(path)
        _count(cat, True)
    if user_store._USE_REDIS:
        user_store._redis_srem(user_store._ACTIVE_SET, uid)

    auth_deleted, note = _delete_auth_user(uid, auth_deleter)
    notes = ["Stored cTrader tokens were deleted from this platform; to "
             "withdraw the app's access at cTrader as well, revoke it in "
             "your cTrader account. Positions already open at the broker "
             "were not closed."]
    if note:
        notes.insert(0, note[0].upper() + note[1:] + ".")
    return {"deleted": deleted, "authUserDeleted": auth_deleted,
            "note": " ".join(notes)}


def describe_deleted(deleted):
    """One line for an operator log. Counts only, never a key."""
    return json.dumps({k: v for k, v in sorted(deleted.items()) if v},
                      separators=(",", ":"))
