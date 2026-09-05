"""Short-lived dashboard sessions, so the operator token stops living in URLs.

The dashboard authenticated with `?token=DASHBOARD_TOKEN`. A credential in a
URL is a credential in:

    browser history          reverse-proxy and web-server access logs
    the Referer header       bookmarks, screenshots, pasted links
    monitoring and APM       anything that samples request paths

Render logs request paths. So does every proxy in front of it. The token that
reads the trade journal and the live account was written into all of them on
every page load, and rotating it means rotating something already copied to
places nobody controls.

What replaces it:

    POST /api/session   { "token": "<DASHBOARD_TOKEN>" }
        -> Set-Cookie: apex_session=<id>; HttpOnly; Secure; SameSite=Strict

The long-lived operator token is presented ONCE, in a request body, and is
exchanged for a session id that expires. The cookie is HttpOnly so page script
cannot read it, SameSite=Strict so another origin cannot ride it, and Secure
so it never crosses plain HTTP.

Scripts and ops tooling keep using `Authorization: Bearer <DASHBOARD_TOKEN>` —
a header is not logged by default the way a path is.

Sessions live in memory. A restart logs everyone out, which for a single
operator is the correct trade: no session survives a deploy, and there is no
session store to steal.
"""
import hmac
import os
import secrets
import threading
import time

# 30 minutes. Long enough to read a dashboard, short enough that a stolen
# cookie is a narrow window rather than a standing key.
TTL_S = int(os.getenv("DASHBOARD_SESSION_TTL_S") or 1800)

COOKIE = "apex_session"

# A cap, so a login endpoint cannot be turned into unbounded memory growth.
_MAX_SESSIONS = 64

_lock = threading.Lock()
_sessions: "dict[str, float]" = {}   # session id -> expiry (epoch seconds)


def _prune(now=None):
    now = now or time.time()
    for sid in [s for s, exp in _sessions.items() if exp <= now]:
        _sessions.pop(sid, None)


def verify_bootstrap(supplied: str, token: str) -> bool:
    """Constant-time check of the operator token. Fails closed on no token.

    `==` on a secret leaks its length and matching prefix through timing;
    compare_digest does not. An unset DASHBOARD_TOKEN is a misconfiguration,
    never a permission — the caller turns that into a 503.
    """
    if not token or not supplied:
        return False
    return hmac.compare_digest(str(supplied), str(token))


def create() -> str:
    """Mint a session id. Caller must have verified the bootstrap token first."""
    sid = secrets.token_urlsafe(32)          # 256 bits from the OS CSPRNG
    with _lock:
        _prune()
        if len(_sessions) >= _MAX_SESSIONS:
            # Drop the oldest rather than refuse the operator a login.
            for old in sorted(_sessions, key=_sessions.get)[: len(_sessions) // 2 + 1]:
                _sessions.pop(old, None)
        _sessions[sid] = time.time() + TTL_S
    return sid


def valid(sid: str) -> bool:
    if not sid:
        return False
    with _lock:
        _prune()
        exp = _sessions.get(sid)
    return bool(exp and exp > time.time())


def revoke(sid: str) -> None:
    with _lock:
        _sessions.pop(sid, None)


def revoke_all() -> None:
    with _lock:
        _sessions.clear()


def parse_cookie(header: str) -> str:
    """The session id out of a Cookie header, or ''. No parsing surprises."""
    if not header:
        return ""
    for part in str(header).split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE:
            return value.strip()
    return ""


def _secure_ok(headers) -> bool:
    """Whether this request arrived over TLS.

    Render terminates TLS and forwards X-Forwarded-Proto. Absent that header
    we assume TLS anyway: marking a cookie Secure when the connection is
    actually plaintext costs a failed login, while omitting it when the
    connection IS plaintext leaks the session. Only an explicit development
    opt-out turns it off.
    """
    if (os.getenv("ALLOW_INSECURE_DASHBOARD_COOKIE") or "").strip().lower() == "true":
        return False
    proto = ""
    try:
        proto = (headers.get("X-Forwarded-Proto") or "").strip().lower()
    except Exception:
        pass
    return proto != "http"


def set_cookie_value(sid: str, headers=None) -> str:
    attrs = [f"{COOKIE}={sid}", "Path=/", "HttpOnly", "SameSite=Strict",
             f"Max-Age={TTL_S}"]
    if _secure_ok(headers):
        attrs.append("Secure")
    return "; ".join(attrs)


def clear_cookie_value(headers=None) -> str:
    attrs = [f"{COOKIE}=", "Path=/", "HttpOnly", "SameSite=Strict", "Max-Age=0"]
    if _secure_ok(headers):
        attrs.append("Secure")
    return "; ".join(attrs)
