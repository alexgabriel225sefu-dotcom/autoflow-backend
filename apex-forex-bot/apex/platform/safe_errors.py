"""Redact provider and storage exception text before it crosses a boundary."""

import re

_URL = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
_PATH = re.compile(r"(?:[A-Za-z]:\\|/)(?:[^\s\"']+[/\\])*[^\s\"']+")
_TOKEN = re.compile(
    r"(?i)(?:bearer\s+|access[_ -]?token[=: ]+|refresh[_ -]?token[=: ]+)"
    r"[A-Za-z0-9._~+/=-]{8,}"
)


def message(exc, *, fallback="request failed"):
    """Return bounded diagnostic prose without URLs, paths, or credentials."""
    raw = str(exc).strip() or fallback
    raw = _TOKEN.sub("[redacted]", raw)
    raw = _URL.sub("[redacted-url]", raw)
    raw = _PATH.sub("[redacted-path]", raw)
    return raw[:300]

