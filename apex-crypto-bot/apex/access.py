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
        return {"admins": [], "allowed": []}
    try:
        d = json.loads(open(_FILE).read())
        d.setdefault("admins", [])
        d.setdefault("allowed", [])
        return d
    except Exception:
        return {"admins": [], "allowed": []}


def _write(d):
    if _USE_REDIS:
        _redis(["SET", _ACCESS_KEY, json.dumps(d)])
        return
    try:
        with open(_FILE, "w") as f:
            json.dump(d, f, indent=2)
    except Exception as e:
        print(f"[ACCESS] write error: {e}")


def _env_admins():
    ids = set()
    for var in ("ADMIN_CHAT_ID", "TELEGRAM_CHAT_ID"):
        for s in (os.getenv(var) or "").split(","):
            if s.strip():
                ids.add(s.strip())
    return list(ids)


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


def grant(chat_id):
    chat_id = str(chat_id)
    d = _read()
    if chat_id in d["allowed"]:
        return False
    d["allowed"].append(chat_id)
    _write(d)
    return True


def revoke(chat_id):
    chat_id = str(chat_id)
    if is_admin(chat_id):
        return False  # cannot revoke admin
    d = _read()
    if chat_id not in d["allowed"]:
        return False
    d["allowed"].remove(chat_id)
    _write(d)
    return True


def list_clients():
    d = _read()
    admins = set(_env_admins() + d["admins"])
    return [cid for cid in d["allowed"] if cid not in admins]


def list_admins():
    d = _read()
    return list(set(_env_admins() + d["admins"]))
