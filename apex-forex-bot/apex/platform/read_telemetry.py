"""Sanitized telemetry for one broker read.

A line is an allowlist. Balances, account numbers, emails, tokens and any
other field are dropped even when a caller passes them. The correlation id
is the handle a person can quote from the screen that failed.
"""
import json
import sys
import time

_ALLOWED = (
    "operation",
    "error_code",
    "http_status",
    "correlation_id",
    "duration_ms",
    "timestamp",
)


def record(*, operation, error_code, http_status, correlation_id,
           duration_ms, timestamp=None, **_ignored):
    """One stdout line. Never raises: a log must not fail the read."""
    try:
        payload = {
            "operation": _token(operation),
            "error_code": None if error_code is None else _token(error_code),
            "http_status": _status(http_status),
            "correlation_id": _token(correlation_id),
            "duration_ms": _duration(duration_ms),
            "timestamp": int(timestamp if timestamp is not None else time.time()),
        }
        safe = {key: payload[key] for key in _ALLOWED}
        sys.stdout.write("[broker-read] " + json.dumps(
            safe, separators=(",", ":"), sort_keys=True) + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


def _token(value):
    text = str(value or "").replace("\n", " ").replace("\r", " ").strip()
    return text[:64]


def _status(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if 0 <= number <= 599 else 0


def _duration(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if 0 <= number <= 600_000 else 0
