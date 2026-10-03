"""Response headers and rate limiting, in one place so every route gets them.

Two primitives that were previously either absent or written per-route:

SECURITY HEADERS
    A dashboard that renders a live trading account had no CSP, no
    nosniff, no referrer policy and no frame protection. The referrer policy
    matters more than usual here: without it, every outbound link from a page
    whose URL carried `?token=` handed that token to the destination in the
    Referer header.

RATE LIMITING
    Nothing bounded how fast the dashboard token or a licence key could be
    guessed. A 32-character token is not brute-forceable, but the endpoints
    that check one should not be the reason we believe that.

The limiter keys on whatever the caller passes — usually the peer address.
Deliberately NOT on a client-supplied identifier: a limiter keyed on a header
the attacker controls is a limiter the attacker resets at will.
"""
import os
import threading
import time

# A Mini App and a dashboard that fetch their own origin only. `default-src
# 'self'` plus the two CDNs the pages actually load. 'unsafe-inline' is
# present for style and script because both pages are written as one inline
# document; tightening that means restructuring the pages, which is a change
# to make deliberately rather than as a side effect of adding a header.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://telegram.org https://unpkg.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors https://web.telegram.org https://telegram.org"
)

_BASE = {
    "X-Content-Type-Options": "nosniff",
    # no-referrer, not no-referrer-when-downgrade: the weaker value still
    # leaks the full URL to same-protocol destinations.
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "SAMEORIGIN",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Content-Security-Policy": _CSP,
}


def headers(*, https: bool = True, sensitive: bool = True):
    """The headers every response should carry.

    `sensitive` adds no-store. Authenticated JSON about a live account must
    never sit in a proxy or a browser cache; a stale balance is both a
    correctness bug and a disclosure one.
    """
    out = dict(_BASE)
    if https:
        # Two years, and subdomains. Not preload: preload is a one-way door
        # for a domain, and that is the domain owner's decision to make.
        out["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    if sensitive:
        out["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        out["Pragma"] = "no-cache"
    return out


def is_https(request_headers) -> bool:
    try:
        proto = (request_headers.get("X-Forwarded-Proto") or "").strip().lower()
    except Exception:
        return True
    return proto != "http"


def client_key(handler) -> str:
    """A rate-limit key the caller cannot choose for themselves.

    X-Forwarded-For is attacker-controlled unless the proxy is trusted AND the
    right element is taken. Render appends the real peer last, so the LAST
    entry is the one that is not spoofable — a client can prepend anything it
    likes to the front of that list, and a limiter that reads the front is a
    limiter with a bypass built in.
    """
    xff = ""
    try:
        xff = (handler.headers.get("X-Forwarded-For") or "").strip()
    except Exception:
        pass
    if xff:
        return xff.split(",")[-1].strip()
    try:
        return str(handler.client_address[0])
    except Exception:
        return "unknown"


class RateLimiter:
    """Fixed-window counter. Small, in memory, and good enough for one host.

    Not distributed: two instances of this bot do not share a window. That is
    stated rather than hidden — it bounds guessing per process, which is what
    a single-instance deployment needs, and it is the wrong tool the moment
    this runs on more than one instance.
    """

    def __init__(self, limit: int, window_s: int, name: str = ""):
        self.limit = int(limit)
        self.window_s = int(window_s)
        self.name = name
        self._lock = threading.Lock()
        self._hits: "dict[str, list]" = {}     # key -> [window_start, count]

    def check(self, key: str) -> bool:
        """True if allowed. Records the attempt."""
        if self.limit <= 0:
            return True
        now = time.time()
        with self._lock:
            if len(self._hits) > 4096:          # bounded: no unbounded growth
                cutoff = now - self.window_s
                for k in [k for k, v in self._hits.items() if v[0] < cutoff]:
                    self._hits.pop(k, None)
            slot = self._hits.get(key)
            if slot is None or now - slot[0] >= self.window_s:
                self._hits[key] = [now, 1]
                return True
            slot[1] += 1
            return slot[1] <= self.limit

    def reset(self, key: str = None):
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


def _env_int(name, default):
    try:
        return int(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


# Authentication endpoints get a tight limit; polling endpoints get a loose
# one, because the Mini App legitimately polls every two seconds.
LOGIN = RateLimiter(_env_int("RL_LOGIN_PER_MIN", 10), 60, "dashboard-login")
MINIAPP = RateLimiter(_env_int("RL_MINIAPP_PER_MIN", 240), 60, "miniapp")
WEBHOOK = RateLimiter(_env_int("RL_WEBHOOK_PER_MIN", 120), 60, "webhook")
# /go is public and writes a record per hit, so it is bounded. Generous: a
# campaign can legitimately push a burst through one carrier NAT.
GO = RateLimiter(_env_int("RL_GO_PER_MIN", 60), 60, "ad-click")
