"""Who is making this request. The authentication boundary, and nothing else.

THE ONE RULE THIS FILE ENFORCES: a misconfiguration is never a permission.

Every path that cannot prove who the caller is raises. There is no branch
where an unset variable, an unreachable Supabase or an unparseable answer ends
with a Principal. `http_session.verify_bootstrap` already states this rule for
the operator token; this is the same rule for clients.

WHY THE TOKEN IS CHECKED AGAINST SUPABASE INSTEAD OF VERIFIED LOCALLY

A Supabase access token is a JWT, and the usual advice is to verify its
signature offline. Three reasons this does the opposite:

  Revocation actually works. A locally verified JWT stays valid until it
  expires, so a client who signs out, or an account the operator bans, keeps
  trading until the clock catches up. On a platform that moves money that is
  the wrong default.

  It survives Supabase's signing migration. Older projects sign with a shared
  HS256 secret, newer ones with asymmetric keys served from JWKS. Code that
  hard-codes either breaks on the day the project is rotated, and it breaks
  open-ended: a verifier that cannot read the key must refuse every client.

  It adds no dependency. `requests` is already pinned; PyJWT is not, and
  requirements.txt says pins are bumped deliberately rather than by accident.

The cost is a network call per request, which the cache below makes bearable.

WHAT THE CACHE COSTS, STATED PLAINLY

A cached answer means a token revoked seconds ago still works until its entry
expires. TTL is therefore small, and anything destructive asks with
fresh=True, which skips the cache entirely. Entries are keyed by a SHA-256 of
the token, never the token, so neither a memory dump nor a debug print of the
cache keys hands anyone a live credential.
"""

import hashlib
import os
import threading
import time

# Small enough that a revoked session dies in about a minute, large enough
# that a dashboard polling a few endpoints does not hit Supabase every time.
CACHE_TTL_S = 60
_MAX_CACHE = 512

_cache = {}
_lock = threading.Lock()


class AuthFailed(Exception):
    """The caller is not authenticated. Becomes a 401.

    Distinct from AuthUnavailable on purpose. Collapsing the two would tell a
    client "your login is invalid" when in truth the platform could not check,
    and would leave the operator hunting a phantom auth bug instead of reading
    the misconfiguration this raises.
    """


class AuthUnavailable(Exception):
    """The platform cannot determine who this is. Becomes a 503, never a 200."""


class Principal:
    """An authenticated client. `user_id` is the Supabase user id.

    That id is the platform's identity everywhere downstream — user_store,
    RuleDocs, the journal. It is a string, which is all user_store ever
    required of a user_id, so the engine needs no change to carry it.
    """

    __slots__ = ("user_id", "email", "email_verified", "issued_at",
                 "app_metadata", "checked_at")

    def __init__(self, *, user_id, email=None, email_verified=False,
                 issued_at=None, app_metadata=None, checked_at=None):
        if not user_id:
            raise AuthFailed("Supabase returned a user with no id")
        self.user_id = str(user_id)
        self.email = email
        self.email_verified = bool(email_verified)
        self.issued_at = issued_at
        self.app_metadata = dict(app_metadata or {})
        self.checked_at = checked_at if checked_at is not None else time.time()

    def as_dict(self):
        """Safe to return to a browser. Carries no token and no service key."""
        return {"userId": self.user_id, "email": self.email,
                "emailVerified": self.email_verified}

    def __repr__(self):
        return f"<Principal {self.user_id} {self.email or ''}>"


def _config():
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_ANON_KEY") or "").strip()
    if not url or not key:
        missing = [n for n, v in (("SUPABASE_URL", url),
                                  ("SUPABASE_ANON_KEY", key)) if not v]
        raise AuthUnavailable(
            f"authentication is not configured: {', '.join(missing)} unset")
    return url, key


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _prune(now):
    for k in [k for k, (exp, _) in _cache.items() if exp <= now]:
        _cache.pop(k, None)


def bearer_token(header_value):
    """The token out of an Authorization header, or None.

    Deliberately strict: only `Bearer <token>`. Accepting a bare token, or a
    token in a query string, makes it far easier for a credential to end up in
    an access log or a referrer header.
    """
    v = (header_value or "").strip()
    if not v or " " not in v:
        return None
    scheme, _, rest = v.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return rest.strip() or None


def _fetch_user(url, key, token, timeout_s):
    import requests
    try:
        r = requests.get(
            f"{url}/auth/v1/user", timeout=timeout_s,
            headers={"apikey": key, "Authorization": f"Bearer {token}",
                     "Accept": "application/json"})
    except Exception as e:  # noqa: BLE001 — network, DNS, TLS, timeout
        # Unreachable is NOT unauthenticated. Turning an outage into a 401
        # would sign every client out of a working platform.
        raise AuthUnavailable(
            f"could not reach Supabase to verify the session "
            f"({type(e).__name__})")
    if r.status_code in (401, 403):
        raise AuthFailed("the session is invalid or has expired")
    if r.status_code != 200:
        raise AuthUnavailable(
            f"Supabase answered {r.status_code} while verifying the session")
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        raise AuthUnavailable("Supabase returned a body that is not JSON")


def verify_token(token, *, fresh=False, timeout_s=6.0):
    """A Principal, or raise. `fresh=True` skips the cache.

    Pass fresh=True for anything destructive or irreversible — starting
    automation, connecting a broker account, changing a credential. The point
    of the cache is to spare read traffic, not to keep a revoked session alive
    through an action the client cannot undo.
    """
    if not token or not isinstance(token, str):
        raise AuthFailed("no bearer token")
    url, key = _config()          # raises AuthUnavailable when unset
    h = _hash(token)
    now = time.time()

    if not fresh:
        with _lock:
            _prune(now)
            hit = _cache.get(h)
        if hit and hit[0] > now:
            return hit[1]

    data = _fetch_user(url, key, token, timeout_s)
    if not isinstance(data, dict):
        raise AuthUnavailable("Supabase returned an unexpected shape")

    # Supabase answers 200 with a user object. A 200 carrying no id is not a
    # login; treat the absence as a refusal rather than minting an anonymous
    # principal that every ownership check would then compare against.
    principal = Principal(
        user_id=data.get("id"),
        email=data.get("email"),
        email_verified=bool(data.get("email_confirmed_at")
                            or data.get("confirmed_at")),
        app_metadata=data.get("app_metadata"),
        checked_at=now)

    with _lock:
        _prune(now)
        if len(_cache) >= _MAX_CACHE:
            for old in sorted(_cache, key=lambda k: _cache[k][0])[
                    : len(_cache) // 2 + 1]:
                _cache.pop(old, None)
        _cache[h] = (now + CACHE_TTL_S, principal)
    return principal


def forget(token):
    """Drop a cached answer — call on sign-out so the session dies at once."""
    if token:
        with _lock:
            _cache.pop(_hash(token), None)


def forget_all():
    with _lock:
        _cache.clear()


def require_verified_email(principal):
    """Raise unless the address is confirmed.

    Connecting a broker account and running automation both hang off this
    identity; an unconfirmed address means nobody has shown they control the
    only channel the platform can use to reach the account's owner.
    """
    if not principal.email_verified:
        raise AuthFailed("confirm your email address before continuing")
    return principal
