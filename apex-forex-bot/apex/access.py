"""Owner bootstrap + client grant/revoke access control."""
import json
import os

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "access.json")


def _read():
    try:
        d = json.loads(open(_FILE).read())
        d.setdefault("admins", [])
        d.setdefault("allowed", [])
        return d
    except Exception:
        return {"admins": [], "allowed": []}


def _write(d):
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
