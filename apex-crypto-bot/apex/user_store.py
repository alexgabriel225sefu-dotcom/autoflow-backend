"""Per-user settings and state storage."""
import json
import os

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "users")


def _path(user_id):
    os.makedirs(_DIR, exist_ok=True)
    return os.path.join(_DIR, f"{user_id}.json")


def load(user_id):
    try:
        return json.loads(open(_path(str(user_id))).read())
    except Exception:
        return {}


def save(user_id, data):
    with open(_path(str(user_id)), "w") as f:
        json.dump(data, f, indent=2)


def update(user_id, updates):
    d = load(user_id)
    d.update(updates)
    save(user_id, d)


def all_active():
    """Return list of user_ids that have active=True."""
    if not os.path.isdir(_DIR):
        return []
    result = []
    for fname in os.listdir(_DIR):
        if fname.endswith(".json"):
            uid = fname[:-5]
            d = load(uid)
            if d.get("active"):
                result.append(uid)
    return result
