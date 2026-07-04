"""Per-user settings and state storage.

Dual-backend:
  • Upstash Redis (recommended on Render) — survives every redeploy.
    Set UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN in Render env.
  • Local JSON files — fallback for local dev or when Upstash not configured.
"""
import json
import os

import requests as _req

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "users")

# Upstash Redis REST API — https://upstash.com (free tier: 256 MB, 10k cmds/day)
_UPD_URL   = (os.getenv("UPSTASH_REDIS_REST_URL")   or "").rstrip("/")
_UPD_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""
_USE_REDIS = bool(_UPD_URL and _UPD_TOKEN)

_ACTIVE_SET = "forex:active_users"   # Redis SET that tracks active user IDs


# ─── Redis helpers ────────────────────────────────────────
def _redis(cmd_parts):
    """Send a single Redis command via Upstash REST API. Returns the result."""
    try:
        url = f"{_UPD_URL}/{'/'.join(str(p) for p in cmd_parts)}"
        r = _req.get(url, headers={"Authorization": f"Bearer {_UPD_TOKEN}"}, timeout=8)
        r.raise_for_status()
        return r.json().get("result")
    except Exception as e:
        print(f"[Redis] command failed {cmd_parts[0]}: {e}")
        return None


def _redis_get(key):
    return _redis(["GET", key])


def _redis_set(key, value_str):
    return _redis(["SET", key, value_str])


def _redis_sadd(key, member):
    return _redis(["SADD", key, member])


def _redis_srem(key, member):
    return _redis(["SREM", key, member])


def _redis_smembers(key):
    result = _redis(["SMEMBERS", key])
    return result if isinstance(result, list) else []


# ─── File helpers (local fallback) ────────────────────────
def _path(user_id):
    os.makedirs(_DIR, exist_ok=True)
    return os.path.join(_DIR, f"{user_id}.json")


# ─── Public API ───────────────────────────────────────────
def load(user_id):
    user_id = str(user_id)
    if _USE_REDIS:
        raw = _redis_get(f"forex:user:{user_id}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return {}
    try:
        return json.loads(open(_path(user_id)).read())
    except Exception:
        return {}


def save(user_id, data):
    user_id = str(user_id)
    if _USE_REDIS:
        _redis_set(f"forex:user:{user_id}", json.dumps(data))
        if data.get("active"):
            _redis_sadd(_ACTIVE_SET, user_id)
        else:
            _redis_srem(_ACTIVE_SET, user_id)
        return
    with open(_path(user_id), "w") as f:
        json.dump(data, f, indent=2)


def update(user_id, updates):
    d = load(user_id)
    d.update(updates)
    save(user_id, d)


def clear_trades(user_id):
    """Wipe the closed-trade journal — used to start a clean performance run
    after a period polluted by bugs/test churn."""
    user_id = str(user_id)
    if _USE_REDIS:
        try:
            _redis_set(f"forex:trades:{user_id}", "[]")
        except Exception as e:
            print(f"[Store] clear_trades redis failed: {e}")
        return
    try:
        with open(_path(user_id) + ".trades", "w") as f:
            f.write("[]")
    except Exception as e:
        print(f"[Store] clear_trades failed: {e}")


def append_trade(user_id, record):
    """Append a closed-trade record to the user's tax journal (keeps last 500)."""
    user_id = str(user_id)
    trades = load_trades(user_id)
    trades.append(record)
    trades = trades[-500:]
    payload = json.dumps(trades)
    if _USE_REDIS:
        _redis_set(f"forex:trades:{user_id}", payload)
        return
    try:
        with open(_path(user_id) + ".trades", "w") as f:
            f.write(payload)
    except Exception as e:
        print(f"[Store] append_trade failed: {e}")


def load_trades(user_id):
    """Load the user's closed-trade journal, or [] if none."""
    user_id = str(user_id)
    if _USE_REDIS:
        raw = _redis_get(f"forex:trades:{user_id}")
    else:
        try:
            raw = open(_path(user_id) + ".trades").read()
        except Exception:
            raw = None
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return []


def all_active():
    """Return list of user_ids that have active=True."""
    if _USE_REDIS:
        return _redis_smembers(_ACTIVE_SET)
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
