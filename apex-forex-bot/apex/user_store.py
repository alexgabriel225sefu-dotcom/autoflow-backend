"""Per-user settings and state storage.

Triple-backend (first match wins):
  1. Standard Redis via REDIS_URL (e.g. Redis Cloud — free, no command limit).
  2. Upstash Redis REST via UPSTASH_REDIS_REST_URL + token.
  3. Local JSON files — fallback for local dev.
"""
import json
import os
from urllib.parse import quote as _quote

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
    # anthropic_key is no longer read anywhere — Anthropic was removed as a
    # provider. It stays listed so any value a client already pasted keeps
    # being handled as a secret rather than silently reverting to plaintext
    # on the next save.
    "anthropic_key", "groq_key", "gemini_key",
}
_ENC_PREFIX = "enc:"

class EncryptionNotConfigured(RuntimeError):
    """Credentials would be stored in plaintext. Refuse to start instead."""


def _is_production() -> bool:
    """Production unless a developer has explicitly said otherwise.

    Deliberately inverted from the usual `if ENV == "production"`. That form
    fails OPEN — an unset variable, a typo, a new hosting provider that names
    the variable differently, and the process quietly decides it is a laptop.
    Here anything unrecognised is production, so the failure is a refused
    startup on a dev box rather than plaintext broker tokens on a live one.
    """
    env = (os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    if env in ("dev", "development", "local", "test"):
        return False
    # Render sets this on every real deployment; its presence is proof.
    if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"):
        return True
    return True


def _plaintext_allowed() -> bool:
    """Only a development box, only with an explicit opt-in, never both absent."""
    flag = (os.getenv("ALLOW_PLAINTEXT_DEV_STORAGE") or "").strip().lower()
    return flag in ("1", "true", "yes", "on") and not _is_production()


_fernet = None
_FERNET_ERROR = None

if cfg.TOKEN_ENCRYPTION_KEY:
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(cfg.TOKEN_ENCRYPTION_KEY.encode())
    except Exception as e:
        # The message only. The key itself must never reach a log line.
        _FERNET_ERROR = f"TOKEN_ENCRYPTION_KEY is set but not a valid Fernet key ({type(e).__name__})"
else:
    _FERNET_ERROR = "TOKEN_ENCRYPTION_KEY is not set"

if _fernet is None:
    if _plaintext_allowed():
        print(f"[Store] ⚠️  {_FERNET_ERROR}. ALLOW_PLAINTEXT_DEV_STORAGE is on and "
              f"this is not production — broker tokens and AI keys will be stored "
              f"in PLAINTEXT. Never set this flag on a deployed service.")
    else:
        # Fail closed. A warning was not enough: it scrolled past on every boot
        # and the bot kept running, so the deployment that mattered stored live
        # broker tokens in plaintext for as long as nobody read the logs.
        raise EncryptionNotConfigured(
            f"{_FERNET_ERROR}. Credentials at rest would be PLAINTEXT, so startup "
            f"is refused. Generate one with:\n"
            f"    python3 -c \"from cryptography.fernet import Fernet; "
            f"print(Fernet.generate_key().decode())\"\n"
            f"and set TOKEN_ENCRYPTION_KEY. For local development only, set "
            f"ALLOW_PLAINTEXT_DEV_STORAGE=true together with APP_ENV=dev."
        )


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


def encrypt_value(value):
    """Encrypt one secret for at-rest storage, or return it unchanged when no
    TOKEN_ENCRYPTION_KEY is configured.

    Exposed because runtime.json wrote broker secrets to disk in plaintext
    while this module had been encrypting the very same values for the user
    store all along — two stores, one threat model, one of them ignoring it.
    """
    if not _fernet or not isinstance(value, str) or not value:
        return value
    if value.startswith(_ENC_PREFIX):
        return value
    return _ENC_PREFIX + _fernet.encrypt(value.encode()).decode()


def decrypt_value(value):
    """Inverse of encrypt_value. Plaintext (legacy, or no key) passes through.

    Returns "" for a value that IS encrypted but cannot be opened — a missing
    or rotated key must not hand a caller ciphertext to use as a credential.
    """
    if not isinstance(value, str) or not value.startswith(_ENC_PREFIX):
        return value
    if not _fernet:
        print("[Store] ⛔ a runtime secret is encrypted but TOKEN_ENCRYPTION_KEY "
              "is not set — treating it as absent")
        return ""
    try:
        return _fernet.decrypt(value[len(_ENC_PREFIX):].encode()).decode()
    except Exception as e:
        print(f"[Store] ⛔ failed to decrypt a runtime secret ({e}) — treating "
              f"it as absent. If TOKEN_ENCRYPTION_KEY was rotated, restore the "
              f"old key or re-enter the secret.")
        return ""


def _decrypt_sensitive(data: dict) -> dict:
    """Decrypt sensitive fields in place. Values not in enc: form (legacy
    plaintext, or no key configured) are left untouched."""
    for field in _SENSITIVE_FIELDS:
        val = data.get(field)
        if isinstance(val, str) and val.startswith(_ENC_PREFIX):
            if not _fernet:
                # Encrypted data and no key to open it. Returning the value
                # unchanged hands the caller the literal string "enc:gAAAA..."
                # and lets it be used as a broker token — the bot then fails
                # authentication with no indication that the real cause is a
                # missing TOKEN_ENCRYPTION_KEY. That is the failure mode of
                # rotating or dropping the key after data has been encrypted,
                # and it must be loud.
                print(f"[Store] ⛔ {field} is ENCRYPTED but TOKEN_ENCRYPTION_KEY "
                      f"is not set — cannot decrypt. Restore the key that was "
                      f"used to write it, or the user must re-link their "
                      f"broker account.")
                data[field] = ""
                continue
            try:
                data[field] = _fernet.decrypt(val[len(_ENC_PREFIX):].encode()).decode()
            except Exception as e:
                # Wrong key, or corrupt value. Same reasoning: an unusable
                # credential must read as absent, never as itself.
                print(f"[Store] ⛔ failed to decrypt {field} ({e}) — treating as "
                      f"absent. If TOKEN_ENCRYPTION_KEY was rotated, restore "
                      f"the previous key.")
                data[field] = ""
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
    """Upstash REST: each command argument is one path segment.

    Arguments MUST be percent-encoded. Without it a key or value containing a
    slash silently becomes two arguments — "at max positions (1/1)" turns a
    3-argument SET into a 4-argument one, which either errors or writes under a
    truncated key. Spaces were being encoded by requests as a side effect;
    slashes never were. Every key used so far happened to be alphanumeric, so
    the bug stayed latent until a skip-alert key carried a human-readable
    reason.

    `safe=":"` is load-bearing: the namespace separator in `forex:user:123`
    must stay literal, or every existing key changes and the store looks empty.
    """
    try:
        url = f"{_UPD_URL}/{'/'.join(_quote(str(p), safe=':') for p in cmd_parts)}"
        r = _req.get(url, headers={"Authorization": f"Bearer {_UPD_TOKEN}"}, timeout=8)
        r.raise_for_status()
        return r.json().get("result")
    except Exception as e:
        print(f"[Redis] command failed {cmd_parts[0]}: {e}")
        return None


def _upstash_post(cmd_parts):
    """Upstash REST via POST with a JSON body.

    The GET form above puts each argument in a path segment, which cannot carry
    a Lua script: the script contains slashes, quotes and newlines, and even
    percent-encoded it runs into URL length limits and proxy normalisation. The
    POST form takes the command as a JSON array and has none of those problems.
    Used only where the GET form genuinely cannot express the command.
    """
    try:
        r = _req.post(_UPD_URL, json=[str(p) for p in cmd_parts],
                      headers={"Authorization": f"Bearer {_UPD_TOKEN}"}, timeout=8)
        r.raise_for_status()
        return r.json().get("result")
    except Exception as e:
        print(f"[Redis] POST command failed {cmd_parts[0]}: {e}")
        return None


def _eval(script, keys, args):
    """Run a Lua script server-side. None means the call itself failed.

    This is what makes compare-and-set possible at all. Without it, "renew the
    lease only if it is still mine" has to be a GET followed by a SET, and
    between those two calls the lease can expire and be taken by another
    container — which then has its lease silently overwritten by the process
    that just lost it. Two owners, no error anywhere.
    """
    if _BACKEND == "redis":
        try:
            return _r.eval(script, len(keys), *keys, *args)
        except Exception as e:
            print(f"[Redis] EVAL failed: {e}")
            return None
    return _upstash_post(["EVAL", script, len(keys), *keys, *args])


def _redis_get(key):
    if _BACKEND == "redis":
        try:
            return _r.get(key)
        except Exception as e:
            print(f"[Redis] GET failed: {e}")
            return None
    return _upstash(["GET", key])


def _redis_set(key, value_str):
    """Write a key. Returns True ONLY when the server confirmed the write.

    The old version returned whatever the driver handed back and callers threw
    it away, so a Redis outage looked exactly like a successful save: a licence
    key, a broker token or a risk setting would be "stored" and simply not
    exist. Every write now reports honestly and every failure is logged.
    """
    if _BACKEND == "redis":
        try:
            return bool(_r.set(key, value_str))
        except Exception as e:
            print(f"[Redis] SET failed for {key}: {e}")
            return False
    res = _upstash(["SET", key, value_str])
    if res is None:
        print(f"[Redis] SET returned no result for {key} — treating as FAILED")
        return False
    return str(res).upper() == "OK"


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


def claim_value(key, value, ttl_s=120):
    """Like claim(), but records WHO won so the winner can renew it.

    claim() writes a bare "1", which is enough to answer "is this taken" but
    not "is this still mine" — and a lease that cannot be renewed by its owner
    is a lease that expires under a healthy worker. Same tri-state contract:
    True (won), False (somebody else holds it), None (could not ask).
    """
    if not _USE_REDIS:
        return None
    try:
        if _BACKEND == "redis":
            return bool(_r.set(key, str(value), nx=True, ex=int(ttl_s)))
        res = _upstash(["SET", key, str(value), "NX", "EX", int(ttl_s)])
        if res is None:
            return None          # command failed — unknown, not "taken"
        return str(res).upper() == "OK"
    except Exception as e:
        print(f"[Redis] claim_value failed: {e}")
        return None


# Compare-and-set, server-side, so ownership cannot be decided by two calls
# with a gap in the middle. These are the standard Redlock primitives.
#
# The gap was not theoretical. renew was GET-then-SET: if the lease expired
# between the two, another container could win it with SET NX and then have
# that lease silently overwritten by the SET from the process that had just
# lost it. Both processes then believe they own the user, and the loser's
# heartbeat keeps renewing a lease that is no longer its own — the exact
# double-ownership the lease exists to prevent, produced by the lease itself.
_LUA_RENEW = ("if redis.call('GET', KEYS[1]) == ARGV[1] then "
              "return redis.call('EXPIRE', KEYS[1], ARGV[2]) else return 0 end")
_LUA_RELEASE = ("if redis.call('GET', KEYS[1]) == ARGV[1] then "
                "return redis.call('DEL', KEYS[1]) else return 0 end")


def renew_claim(key, value, ttl_s=120):
    """Extend a lease we already hold. True only if `value` is still the owner.

    Atomic: the check and the extension happen in one server-side step, so
    there is no window in which the key can change hands between them.
    Returns None when the call itself failed — unknown, not lost.
    """
    if not _USE_REDIS:
        return None
    res = _eval(_LUA_RENEW, [key], [str(value), int(ttl_s)])
    if res is None:
        return None              # transport failure — caller decides
    return int(res) == 1


def release_claim(key, value):
    """Drop a lease we hold, so a replacement worker need not wait out the TTL.

    Atomic for the same reason as renew: a GET-then-DEL could delete a lease
    that another container acquired in between, handing a third process a free
    key while two others think they own it.
    """
    if not _USE_REDIS:
        return None
    res = _eval(_LUA_RELEASE, [key], [str(value)])
    if res is None:
        return None
    return int(res) == 1


def incr(key, ttl_s=60):
    """Atomically bump a counter, giving it a TTL the first time it appears.

    Returns the new count, or None when there is no shared backend or the
    command failed — same contract as claim(): the caller can tell "I counted"
    from "I could not ask", and must not read a failure as a limit breach.

    INCR is the primitive a rate limit needs: read-modify-write on a JSON blob
    loses increments whenever two of anything race, and during a Render deploy
    two instances serve the same users at once.
    """
    if not _USE_REDIS:
        return None
    try:
        if _BACKEND == "redis":
            n = _r.incr(key)
            if n == 1:
                _r.expire(key, int(ttl_s))
            return int(n)
        n = _upstash(["INCR", key])
        if n is None:
            return None
        n = int(n)
        if n == 1:
            _upstash(["EXPIRE", key, int(ttl_s)])
        return n
    except Exception as e:
        print(f"[Redis] incr failed: {e}")
        return None


def get_blob(key):
    """Raw string at `key`, or None. For data that is not a user record."""
    if not _USE_REDIS:
        return None
    return _redis_get(key)


def set_blob(key, value_str, ttl_s=None):
    """Write a raw string, optionally expiring. No-op without a shared store."""
    if not _USE_REDIS:
        return None
    if not ttl_s:
        return _redis_set(key, value_str)
    if _BACKEND == "redis":
        try:
            return _r.set(key, value_str, ex=int(ttl_s))
        except Exception as e:
            print(f"[Redis] SET ex failed: {e}")
            return None
    return _upstash(["SET", key, value_str, "EX", int(ttl_s)])


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


class PersistenceError(RuntimeError):
    """A write that was asked to be certain, and was not."""


class ConflictError(RuntimeError):
    """Somebody else changed this record since it was read."""


# One user record is TWO Redis keys — the record itself and its membership of
# the active set — and they were written by two separate calls. A failure
# between them left the account in a state neither half describes: a record
# that says active with the set saying otherwise (the watchdog never restarts
# it) or the reverse (a revoked client keeps getting a loop). This does both,
# plus the version bump, in one server-side step.
#
# The version is a separate integer key rather than a field inside the JSON,
# because checking a field would mean parsing JSON inside Lua — cjson exists
# but its availability across Redis and Upstash is one more thing that has to
# be true for a credential write to land, and this needs no dependencies.
#
# Returns the new version, or -1 for a version mismatch (CONFLICT).
_LUA_SAVE_USER = """
local expected = ARGV[4]
if expected ~= '' then
  local cur = redis.call('GET', KEYS[3])
  if cur == false then cur = '0' end
  if cur ~= expected then return -1 end
end
redis.call('SET', KEYS[1], ARGV[1])
if ARGV[3] == '1' then
  redis.call('SADD', KEYS[2], ARGV[2])
else
  redis.call('SREM', KEYS[2], ARGV[2])
end
return redis.call('INCR', KEYS[3])
"""


def _vkey(user_id):
    return f"{_NS}:uver:{user_id}"


def version(user_id):
    """The record's current version, 0 when it has never been written."""
    if not _USE_REDIS:
        return int((load(user_id) or {}).get("_v") or 0)
    raw = _redis_get(_vkey(str(user_id)))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def save(user_id, data, strict=False, expect_version=None):
    """Persist a user record. Returns True only if the write actually landed.

    This used to return None unconditionally: `_redis_set`'s result was
    discarded, so a Redis outage was indistinguishable from a successful save.
    A licence minted during an outage, a broker token stored right after OAuth,
    a client turning risk down before the weekend — all of them would report
    success and be gone.

    `strict=True` raises instead of returning False. Use it wherever losing the
    write is worse than failing the operation: money, credentials, entitlement.
    The default stays non-raising because most callers are loop bookkeeping,
    and turning a Redis blip into an unhandled exception inside the trading
    loop trades a silent bug for a louder one.

    `expect_version` turns this into a compare-and-set. Pass the version read
    alongside the record and the write only lands if nobody changed it since;
    a mismatch raises ConflictError rather than overwriting. Without it the
    load/modify/save pattern silently loses whichever writer finished first —
    two operators adjusting risk, or a client tapping a button while the loop
    writes bookkeeping, and one of the changes is simply gone.
    """
    user_id = str(user_id)
    stored = _encrypt_sensitive(data)
    if _USE_REDIS:
        # Record, active-set membership and version in ONE step. Written as
        # three calls, a failure between them left the two halves disagreeing.
        res = _eval(_LUA_SAVE_USER,
                    [f"{_NS}:user:{user_id}", _ACTIVE_SET, _vkey(user_id)],
                    [json.dumps(stored), user_id,
                     "1" if data.get("active") else "0",
                     "" if expect_version is None else str(int(expect_version))])
        if res is None:
            print(f"[Store] WRITE LOST for user {user_id} — Redis did not "
                  f"confirm the save")
            if strict:
                raise PersistenceError(f"could not persist user {user_id}")
            return False
        if int(res) == -1:
            print(f"[Store] CONFLICT on user {user_id} — the record changed "
                  f"since it was read (expected v{expect_version})")
            raise ConflictError(
                f"user {user_id} changed since it was read "
                f"(expected v{expect_version}, now v{version(user_id)})")
        return True
    try:
        if expect_version is not None:
            cur = int((load(user_id) or {}).get("_v") or 0)
            if cur != int(expect_version):
                raise ConflictError(
                    f"user {user_id} changed since it was read "
                    f"(expected v{expect_version}, now v{cur})")
        stored["_v"] = int((load(user_id) or {}).get("_v") or 0) + 1
        with open(_path(user_id), "w") as f:
            json.dump(stored, f, indent=2)
        return True
    except ConflictError:
        raise
    except Exception as e:
        print(f"[Store] WRITE LOST for user {user_id}: {e}")
        if strict:
            raise PersistenceError(f"could not persist user {user_id}: {e}")
        return False


# Fields where a lost update is a correctness or safety problem rather than a
# stale number: entitlement, credentials, and the live/paper switch. A write
# touching any of these goes through the compare-and-set path automatically,
# so a caller cannot lose one by forgetting to ask.
CRITICAL_FIELDS = {
    "license_key", "active", "paper",
    "ctrader_access_token", "ctrader_refresh_token", "ctrader_account_id",
    "ctrader_env", "ctrader_accounts", "broker",
    "risk", "max_dd_pct", "max_daily_loss_pct", "maxpos", "max_total_risk",
    "automation", "copilot", "loss_streak",
}

# Concurrent writers are rare and the window is milliseconds, so a handful of
# retries resolves essentially all real contention. Failing after that is
# deliberate: at some point "somebody keeps changing this" is the answer, and
# looping forever would hide it.
_CAS_RETRIES = 5


def update(user_id, updates, strict=False, expect_version=None):
    """Merge `updates` into the record.

    A plain load/modify/save races: two writers both read v1, both write v2,
    and the first writer's change is gone with nothing reporting it. When the
    update touches a CRITICAL_FIELD this re-reads and retries under
    compare-and-set, so a concurrent write is merged rather than lost.

    `expect_version` forces the check for any field and does NOT retry — the
    caller has decided what it expected, so a mismatch is theirs to handle.
    """
    if expect_version is not None:
        d = load(user_id)
        d.update(updates)
        return save(user_id, d, strict=strict, expect_version=expect_version)

    if not (set(updates or {}) & CRITICAL_FIELDS) or not _USE_REDIS:
        d = load(user_id)
        d.update(updates)
        return save(user_id, d, strict=strict)

    last = None
    for _attempt in range(_CAS_RETRIES):
        v = version(user_id)
        d = load(user_id)
        d.update(updates)
        try:
            return save(user_id, d, strict=strict, expect_version=v)
        except ConflictError as e:
            last = e                      # somebody else won; re-read and redo
    print(f"[Store] gave up after {_CAS_RETRIES} conflicts on user {user_id}")
    if strict:
        raise last or ConflictError(f"user {user_id} is being written concurrently")
    return False


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
