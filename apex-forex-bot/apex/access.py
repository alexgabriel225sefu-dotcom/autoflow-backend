"""Owner bootstrap + client grant/revoke access control.

Dual-backend: Upstash Redis (survives redeploys) when UPSTASH_REDIS_REST_URL +
UPSTASH_REDIS_REST_TOKEN are set, else a local JSON file (wiped on redeploy).
"""
import json
import os

import requests as _req

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "access.json")

_UPD_URL   = (os.getenv("UPSTASH_REDIS_REST_URL")   or "").rstrip("/")
_UPD_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""
_USE_REDIS = bool(_UPD_URL and _UPD_TOKEN)

_ACCESS_KEY = f"{(os.getenv('PRODUCT') or 'forex').strip().lower()}:access"


def _redis(cmd_parts):
    try:
        url = f"{_UPD_URL}/{'/'.join(str(p) for p in cmd_parts)}"
        r = _req.get(url, headers={"Authorization": f"Bearer {_UPD_TOKEN}"}, timeout=8)
        r.raise_for_status()
        return r.json().get("result")
    except Exception as e:
        print(f"[ACCESS:Redis] command failed {cmd_parts[0]}: {e}")
        return None


def _read():
    if _USE_REDIS:
        raw = _redis(["GET", _ACCESS_KEY])
        if raw:
            try:
                d = json.loads(raw)
                d.setdefault("admins", [])
                d.setdefault("allowed", [])
                return d
            except Exception:
                pass
        # Empty here is ambiguous: either nobody is granted yet, or Redis just
        # failed. Callers that only need a bool cannot tell, and for a read-only
        # check that is fine. Anything about to STOP a paying client's bot must
        # tell the difference — see allowed_state.
        return {"admins": [], "allowed": [], "_degraded": True}
    try:
        d = json.loads(open(_FILE).read())
        d.setdefault("admins", [])
        d.setdefault("allowed", [])
        return d
    except Exception:
        # The local file is wiped on every redeploy, so a miss here says
        # nothing about entitlement.
        return {"admins": [], "allowed": [], "_degraded": True}


def _write(d):
    """Persist the access index. Returns True ONLY when the write landed.

    Returned nothing before, so `grant()` reported success whether or not the
    index was actually written. A Redis timeout during activation told the
    customer they had access while the store disagreed — and the next lookup
    said they did not.
    """
    d = {k: v for k, v in d.items() if k != "_degraded"}
    if _USE_REDIS:
        res = _redis(["SET", _ACCESS_KEY, json.dumps(d)])
        if res is None or str(res).upper() != "OK":
            print("[ACCESS] ⛔ write NOT confirmed — access index unchanged")
            return False
        return True
    try:
        with open(_FILE, "w") as f:
            json.dump(d, f, indent=2)
        return True
    except Exception as e:
        print(f"[ACCESS] ⛔ write error: {e}")
        return False



# Privileged identity is CONFIGURATION, not source. A Telegram id embedded
# here meant the repository carried a privileged identity, changing the
# operator required a code change and a deploy, and any fork or clone of this
# repo inherited an admin who may no longer be one.
#
# Startup validates that at least one is configured — an empty admin list is
# not a safe default, it is a bot nobody can administer.
_ADMIN_ENV_VARS = ("ADMIN_CHAT_IDS", "ADMIN_CHAT_ID", "TELEGRAM_CHAT_ID")


def _env_admins():
    ids = set()
    for var in _ADMIN_ENV_VARS:
        for part in (os.getenv(var) or "").split(","):
            if part.strip():
                ids.add(part.strip())
    return list(ids)


def admins_configured() -> bool:
    """True when at least one privileged operator is configured.

    Called at startup. Never logs the ids themselves — the count is enough to
    tell an operator whether their configuration took effect.
    """
    return bool(_env_admins())


def is_admin(chat_id):
    chat_id = str(chat_id)
    return chat_id in _env_admins() or chat_id in _read()["admins"]


def has_any_admin():
    return bool(_env_admins() or _read()["admins"])


def claim_admin(chat_id):
    """First-user bootstrap — makes chat_id the owner."""
    chat_id = str(chat_id)
    d = _read()
    if chat_id not in d["admins"]:
        d["admins"].append(chat_id)
    if chat_id not in d["allowed"]:
        d["allowed"].append(chat_id)
    _write(d)


def is_allowed(chat_id):
    chat_id = str(chat_id)
    return is_admin(chat_id) or chat_id in _read()["allowed"]


def allowed_state(chat_id):
    """"allowed" | "denied" | "unknown" — the three-way answer is_allowed cannot give.

    is_allowed() collapses "this chat is not entitled" and "the access store is
    unreachable" into the same False. That is safe for refusing a command (the
    worst case is one rejected message the client can retry) but not for
    deciding whether a trading loop may run: the same False would silently kill
    every paying client's bot during a Redis hiccup, and the local-JSON backend
    is wiped on every redeploy so a miss there means nothing at all.

    Callers should treat "unknown" as allow-and-log, and act only on "denied".
    THIS IS THE UI POLICY. For money see gates.live_entitlement, and for a
    first-time chat see new_user_state below — those must not inherit it.
    """
    chat_id = str(chat_id)
    if is_admin(chat_id):
        return "allowed"       # configured admins never depend on the store
    d = _read()
    if chat_id in d["allowed"] or chat_id in d["admins"]:
        return "allowed"
    return "unknown" if d.get("_degraded") else "denied"


def new_user_state(chat_id, has_local_record=False):
    """Entitlement for a chat we have never seen. UNKNOWN means DENY here.

    The generous reading of UNKNOWN exists to protect people who have already
    paid: their bot must not stop because a store lookup timed out. A brand-new
    chat has no such claim on us. Applying the same policy to both means an
    access-store outage hands the product away to whoever messages during it —
    the outage becomes the way in.

    `has_local_record` is what separates the two populations: a chat already
    provisioned locally is an existing user riding out an outage, and keeps the
    grace. A chat with nothing on file is new, and is refused until the store
    can actually answer.
    """
    chat_id = str(chat_id)
    if is_admin(chat_id):
        return "allowed"
    state = allowed_state(chat_id)
    if state == "allowed":
        return "allowed"
    if state == "denied":
        return "denied"
    if has_local_record:
        return "unknown"       # provisioned already — grace applies
    print(f"[ACCESS] new chat {chat_id} during a store outage — DENIED "
          f"(unknown entitlement is not access)")
    return "denied"


class GrantFailed(RuntimeError):
    """Entitlement could not be persisted. Do not tell the customer it was."""


def grant(chat_id, strict=False):
    """Add a client to the access index. True only if it is actually stored.

    Reading the index first and only writing when the id is missing means a
    DEGRADED read (Redis down) looks identical to "not yet granted" — so the
    write is attempted, fails, and the caller must hear about it. `strict=True`
    raises, for the provisioning path where reporting a false success leaves a
    paying customer locked out with nothing to retry.
    """
    chat_id = str(chat_id)
    d = _read()
    if chat_id in d["allowed"]:
        return False                      # already granted; nothing to persist
    d["allowed"].append(chat_id)
    if not _write(d):
        if strict:
            raise GrantFailed(f"could not persist access grant for {chat_id}")
        return False
    return True


def revoke(chat_id, strict=False):
    chat_id = str(chat_id)
    if is_admin(chat_id):
        return False  # cannot revoke admin
    d = _read()
    if chat_id not in d["allowed"]:
        return False
    d["allowed"].remove(chat_id)
    if not _write(d):
        # A revocation that did not persist is the dangerous direction: the
        # caller believes access is gone while the store still grants it.
        if strict:
            raise GrantFailed(f"could not persist revocation for {chat_id}")
        return False
    return True


def list_clients():
    d = _read()
    admins = set(_env_admins() + d["admins"])
    return [cid for cid in d["allowed"] if cid not in admins]


def list_admins():
    d = _read()
    return list(set(_env_admins() + d["admins"]))
