"""Per-user settings and state storage.

Triple-backend (first match wins):
  1. Standard Redis via REDIS_URL (e.g. Redis Cloud — free, no command limit).
  2. Upstash Redis REST via UPSTASH_REDIS_REST_URL + token.
  3. Local JSON files — fallback for local dev.
"""
import json
import os

import requests as _req

from apex import config as cfg

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "users")

# ─── Field-level encryption for credentials at rest ──────
# Broker tokens and user-supplied AI keys are the fields that matter if the
# store (Redis/Upstash) is ever compromised — same class of exposure as the
# 3Commas API-key breach. Encrypted with a key that lives only in env vars,
# never in the store itself.
_SENSITIVE_FIELDS = {
    "ctrader_access_token", "ctrader_refresh_token",
    "anthropic_key", "groq_key", "gemini_key",
}
_ENC_PREFIX = "enc:"

_fernet = None
if cfg.TOKEN_ENCRYPTION_KEY:
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(cfg.TOKEN_ENCRYPTION_KEY.encode())
    except Exception as e:
        print(f"[Store] TOKEN_ENCRYPTION_KEY set but invalid, storing in PLAINTEXT: {e}")
else:
    print("⚠️  WARNING: TOKEN_ENCRYPTION_KEY not set — broker tokens & AI keys "
          "are stored in PLAINTEXT. Set it in production (Fernet.generate_key()).")


def _encrypt_sensitive(data: dict) -> dict:
    """Return a copy of data with sensitive string fields encrypted."""
    if not _fernet:
        return data
    out = dict(data)
    for field in _SENSITIVE_FIELDS:
        val = out.get(field)
        if isinstance(val, str) and val and not val.startswith(_ENC_PREFIX):
            out[field] = _ENC_PREFIX + _fernet.encrypt(val.encode()).decode()
    return out


def _decrypt_sensitive(data: dict) -> dict:
    """Decrypt sensitive fields in place. Values not in enc: form (legacy
    plaintext, or no key configured) are left untouched."""
    for field in _SENSITIVE_FIELDS:
        val = data.get(field)
        if isinstance(val, str) and val.startswith(_ENC_PREFIX):
            if not _fernet:
                continue  # can't decrypt without the key; leave as-is
            try:
                data[field] = _fernet.decrypt(val[len(_ENC_PREFIX):].encode()).decode()
            except Exception as e:
                print(f"[Store] failed to decrypt {field}: {e}")
    return data

# ─── Backend selection ───────────────────────────────────
_REDIS_URL = os.getenv("REDIS_URL", "")

# Upstash REST
_UPD_URL   = (os.getenv("UPSTASH_REDIS_REST_URL")   or "").rstrip("/")
_UPD_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""

_BACKEND = "none"
_r = None

if _REDIS_URL:
    try:
        import redis as _redis_lib
        _r = _redis_lib.from_url(_REDIS_URL, decode_responses=True,
                                 socket_connect_timeout=5, socket_timeout=8,
                                 retry_on_timeout=True)
        _r.ping()
        _BACKEND = "redis"
        print(f"[Store] Using standard Redis")
    except Exception as e:
        print(f"[Store] REDIS_URL set but connection failed: {e}")
        _r = None

if _BACKEND == "none" and _UPD_URL and _UPD_TOKEN:
    _BACKEND = "upstash"
    print("[Store] Using Upstash REST")

if _BACKEND == "none":
    print("[Store] Using local JSON files (no Redis configured)")

_USE_REDIS = _BACKEND in ("redis", "upstash")

_NS = os.getenv("PRODUCT", "").strip().lower()
if not _NS:
    _NS = "forex"
    print("⚠️  WARNING: PRODUCT env var not set — defaulting to 'forex'. Set PRODUCT=forex explicitly!")
_ACTIVE_SET = f"{_NS}:active_users"


# ─── Redis helpers ────────────────────────────────────────
def _upstash(cmd_parts):
    try:
        url = f"{_UPD_URL}/{'/'.join(str(p) for p in cmd_parts)}"
        r = _req.get(url, headers={"Authorization": f"Bearer {_UPD_TOKEN}"}, timeout=8)
        r.raise_for_status()
        return r.json().get("result")
    except Exception as e:
        print(f"[Redis] command failed {cmd_parts[0]}: {e}")
        return None


def _redis_get(key):
    if _BACKEND == "redis":
        try:
            return _r.get(key)
        except Exception as e:
            print(f"[Redis] GET failed: {e}")
            return None
    return _upstash(["GET", key])


def _redis_set(key, value_str):
    if _BACKEND == "redis":
        try:
            return _r.set(key, value_str)
        except Exception as e:
            print(f"[Redis] SET failed: {e}")
            return None
    return _upstash(["SET", key, value_str])


def claim(key, ttl_s=120):
    """Atomically claim `key` for `ttl_s` seconds. True only for the winner.

    SET NX is the one primitive that works across PROCESSES, which is the
    entire point: this service runs more than one instance during a Render
    deploy (observed live — the old instance was still ticking seven seconds
    after the new one started its loop), and both drive the same cTrader
    account. An in-process guard cannot see the other instance at all.

    Returns None — neither True nor False — when there is no shared backend or
    the backend errored, so the caller can tell "somebody else has it" from
    "I could not ask" and decide accordingly rather than reading a failure as
    a denial.
    """
    if not _USE_REDIS:
        return None
    try:
        if _BACKEND == "redis":
            got = _r.set(key, "1", nx=True, ex=int(ttl_s))
            return bool(got)
        res = _upstash(["SET", key, "1", "NX", "EX", int(ttl_s)])
        if res is None:
            return None          # command failed — unknown, not "taken"
        return str(res).upper() == "OK"
    except Exception as e:
        print(f"[Redis] claim failed: {e}")
        return None


def _redis_sadd(key, member):
    if _BACKEND == "redis":
        try:
            return _r.sadd(key, member)
        except Exception as e:
            print(f"[Redis] SADD failed: {e}")
            return None
    return _upstash(["SADD", key, member])


def _redis_srem(key, member):
    if _BACKEND == "redis":
        try:
            return _r.srem(key, member)
        except Exception as e:
            print(f"[Redis] SREM failed: {e}")
            return None
    return _upstash(["SREM", key, member])


def _redis_smembers(key):
    if _BACKEND == "redis":
        try:
            result = _r.smembers(key)
            return list(result) if result else []
        except Exception as e:
            print(f"[Redis] SMEMBERS failed: {e}")
            return []
    result = _upstash(["SMEMBERS", key])
    return result if isinstance(result, list) else []


# ─── File helpers (local fallback) ────────────────────────
def _path(user_id):
    os.makedirs(_DIR, exist_ok=True)
    return os.path.join(_DIR, f"{user_id}.json")


# ─── Public API ───────────────────────────────────────────
def load(user_id):
    user_id = str(user_id)
    if _USE_REDIS:
        raw = _redis_get(f"{_NS}:user:{user_id}")
        if raw:
            try:
                return _decrypt_sensitive(json.loads(raw))
            except Exception:
                pass
        return {}
    try:
        return _decrypt_sensitive(json.loads(open(_path(user_id)).read()))
    except Exception:
        return {}


def save(user_id, data):
    user_id = str(user_id)
    stored = _encrypt_sensitive(data)
    if _USE_REDIS:
        _redis_set(f"{_NS}:user:{user_id}", json.dumps(stored))
        if data.get("active"):
            _redis_sadd(_ACTIVE_SET, user_id)
        else:
            _redis_srem(_ACTIVE_SET, user_id)
        return
    with open(_path(user_id), "w") as f:
        json.dump(stored, f, indent=2)


def update(user_id, updates):
    d = load(user_id)
    d.update(updates)
    save(user_id, d)


def clear_trades(user_id):
    """Wipe the closed-trade journal."""
    user_id = str(user_id)
    if _USE_REDIS:
        try:
            _redis_set(f"{_NS}:trades:{user_id}", "[]")
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
        _redis_set(f"{_NS}:trades:{user_id}", payload)
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
        raw = _redis_get(f"{_NS}:trades:{user_id}")
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
