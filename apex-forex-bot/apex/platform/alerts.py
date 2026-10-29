"""Operator alerts and structured logs. Best effort, and never a new failure.

WHY THIS EXISTS

The supervisor revives a client's dead loop silently, and silently failing to
revive one is worse: the dashboard says RUNNING over nothing. Until now the
only trace was a `print` that somebody had to be reading the Render log to see.
`notify_ops` puts the few events an operator must hear about on a phone.

WHAT IT GUARANTEES

  * Optional. With `OPS_ALERT_WEBHOOK_URL` unset it does nothing at all.
    The URL must be https; it is a secret (Slack/Discord/Telegram webhook
    paths are credentials) and is never logged or placed in a payload.
  * De-duplicated: one alert per (user, cause) per 30 minutes, held in this
    process. With N containers the worst case is N alerts, not a storm.
  * Rate limited: at most MAX_PER_WINDOW alerts per WINDOW_S across everything,
    so a platform-wide fault pages a handful of times rather than once per
    client.
  * Redacted: the user is a short hash, the cause is a code, free-text detail
    goes through apex.redact and is cut short. Callers pass codes and
    exception TYPE names, not exception messages.
  * Unable to raise. Every path is wrapped; a dead webhook, a bad URL or a
    garbage argument costs one swallowed exception. The default sender runs on
    a daemon thread with a short timeout, so a slow webhook cannot stall the
    supervisor either.

PAYLOAD

`{"text": "...", "content": "..."}`. Slack and Telegram read `text`, Discord
reads `content`; the unknown key is ignored by each. For Telegram, put the
chat id in the URL: https://api.telegram.org/bot<token>/sendMessage?chat_id=<id>

STRUCTURED LOGS

`log_event(level, event, **fields)` prints one JSON line. See `set_error_hook`
for attaching Sentry (or anything else) later WITHOUT a dependency today.
"""

import hashlib
import json
import os
import threading
import time
import urllib.request

from apex import redact

WEBHOOK_ENV = "OPS_ALERT_WEBHOOK_URL"
DEDUP_WINDOW_S = 30 * 60
WINDOW_S = 10 * 60
MAX_PER_WINDOW = 10
SEND_TIMEOUT_S = 3.0
MAX_DETAIL = 120

_lock = threading.Lock()
_seen = {}          # (user hash, cause) -> last sent at
_window = []        # timestamps of alerts sent in the current window
_threads = []
_error_hook = None

# Field names never written to a log line, whatever their value.
_SECRET_FIELD_PARTS = ("token", "secret", "password", "passwd", "authorization",
                       "cookie", "apikey", "api_key", "key", "dsn", "webhook")
_USER_FIELDS = ("user_id", "uid", "user")


def reset():
    """For tests."""
    with _lock:
        _seen.clear()
        del _window[:]
        del _threads[:]


def short_user(user_id):
    """A short, stable, non-reversible handle. Enough to correlate, no more."""
    text = str(user_id or "")
    if not text:
        return "-"
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:8]


def _webhook():
    url = (os.getenv(WEBHOOK_ENV) or "").strip()
    return url if url.lower().startswith("https://") else ""


def _clean(value, limit=MAX_DETAIL):
    try:
        return redact.scrub_for_client(str(value), limit=limit)
    except Exception:                                        # noqa: BLE001
        return ""


def _cause_text(cause, limit=80):
    """A cause is a code, so keep to code characters rather than guess."""
    text = redact.scrub(str(cause))
    return "".join(c for c in text if c.isalnum() or c in "_:.-*")[:limit]


def _default_sender(url, body, timeout):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "apex4traders-ops-alert"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        resp.read(256)


def _deliver(sender, url, body):
    try:
        sender(url, body, SEND_TIMEOUT_S)
    except Exception as e:                                   # noqa: BLE001
        # Type only: the message of a urllib error can carry the URL.
        try:
            print(f"[Alerts] delivery failed ({type(e).__name__})")
        except Exception:                                    # noqa: BLE001
            pass


def notify_ops(cause, user_id=None, detail="", *, sender=None, now=None):
    """Tell the operator. True if an alert was handed to the sender.

    Never raises. `sender(url, body, timeout)` is injectable for tests; when
    omitted the post happens on a daemon thread.
    """
    try:
        url = _webhook()
        if not url:
            return False
        now = time.time() if now is None else float(now)
        cause_s = _cause_text(cause) or "unspecified"
        handle = short_user(user_id) if user_id is not None else "-"
        key = (handle, cause_s)
        with _lock:
            last = _seen.get(key)
            if last is not None and 0 <= now - last < DEDUP_WINDOW_S:
                return False
            _window[:] = [t for t in _window if 0 <= now - t < WINDOW_S]
            if len(_window) >= MAX_PER_WINDOW:
                return False
            _seen[key] = now
            _window.append(now)
            if len(_seen) > 2000:                    # bound memory
                for k in sorted(_seen, key=_seen.get)[:1000]:
                    _seen.pop(k, None)
        env = "production" if _is_production() else "dev"
        text = f"[apex4traders/{env}] {cause_s} user={handle}"
        extra = _clean(detail) if detail else ""
        if extra:
            text += f" - {extra}"
        body = {"text": text, "content": text}
        if sender is not None:
            _deliver(sender, url, body)
        else:
            t = threading.Thread(
                target=_deliver, args=(_default_sender, url, body),
                name="ops-alert", daemon=True)
            with _lock:
                _threads[:] = [x for x in _threads if x.is_alive()]
                _threads.append(t)
            t.start()
        return True
    except Exception:                                        # noqa: BLE001
        return False


def drain(timeout=2.0):
    """Wait for in-flight default-sender threads. For tests and shutdown."""
    with _lock:
        pending = list(_threads)
    for t in pending:
        t.join(timeout)


def _is_production():
    try:
        from apex import user_store
        return bool(user_store._is_production())
    except Exception:                                        # noqa: BLE001
        return True


# ── structured logs ─────────────────────────────────────────────────────────

def set_error_hook(fn):
    """Register `fn(event, fields)`, called for every level=error event.

    THIS IS HOW TO ATTACH SENTRY LATER, WITH NO DEPENDENCY NOW:

        import sentry_sdk
        sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], send_default_pii=False)
        alerts.set_error_hook(
            lambda event, fields: sentry_sdk.capture_message(
                event, level="error", extras=fields))

    Put that in platform_server.main() behind `if os.getenv("SENTRY_DSN")`
    and add `sentry-sdk` to requirements.txt in the same change. `fields` has
    already been redacted and user ids are already hashed. A hook that raises
    is swallowed. Pass None to remove it.
    """
    global _error_hook
    _error_hook = fn


def _safe_field(name, value):
    low = str(name).lower()
    if any(p in low for p in _SECRET_FIELD_PARTS):
        return None
    if low in _USER_FIELDS:
        return short_user(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact.scrub(str(value))[:300]


def log_event(level, event, **fields):
    """Print one JSON line: {ts, level, event, fields}. Never raises."""
    try:
        clean = {}
        for name, value in fields.items():
            if str(name).lower() in _USER_FIELDS:
                clean["user"] = short_user(value)
                continue
            if any(p in str(name).lower() for p in _SECRET_FIELD_PARTS):
                continue
            clean[str(name)] = _safe_field(name, value)
        rec = {"ts": round(time.time(), 3), "level": str(level),
               "event": str(event), "fields": clean}
        print(redact.scrub(json.dumps(rec, default=str, sort_keys=True)),
              flush=True)
        hook = _error_hook
        if hook is not None and str(level).lower() == "error":
            try:
                hook(str(event), dict(clean))
            except Exception:                                # noqa: BLE001
                pass
    except Exception:                                        # noqa: BLE001
        pass
