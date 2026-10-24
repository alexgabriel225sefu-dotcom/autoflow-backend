"""Redact provider and storage exception text before it crosses a boundary.

This is the one helper for text that reaches a client, a journal entry or a
state/status response. It is the shape-based client redactor
(`apex.redact.scrub_for_client`: bearer headers, `name=value` credential pairs,
quoted dumps, unlabeled token-like runs, base64 padding) with two more shapes
added that only matter for an exception message: URLs and filesystem paths.
Error CODES and diagnostic ids survive, because the client needs them.
"""

import re

from apex import redact

_URL = re.compile(r"\b[a-z][a-z0-9+.\-]{0,20}://[^\s\"']+", re.IGNORECASE)
# `host='api.example.com'` in a connection-pool message names a provider too.
_HOST = re.compile(
    r"(?i)\b(host|hostname|server|endpoint)\b[\"']?\s*[=:]\s*[\"']?[^\s\"',)]+[\"']?")
_IP = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?(?![\d.])")
_USERINFO = re.compile(r"[\w.\-]{1,64}:[^\s@/:\"']{1,128}@[\w.\-]{1,255}")
_EMAIL = re.compile(r"[\w.+\-]{1,64}@[\w\-]{1,63}(?:\.[\w\-]{1,63})+")
# Short internal-looking hostnames (db.internal, redis.svc.cluster.local).
_FQDN = re.compile(
    r"\b(?:[a-z0-9][a-z0-9\-]{0,30}\.){1,5}"
    r"(?:internal|local|lan|corp|svc|cluster|localhost|test|example|invalid"
    r"|com|net|org|io|dev|app|cloud)\b", re.IGNORECASE)
# A relative path to a file of a kind that holds state or secrets.
_RELPATH = re.compile(
    r"(?<![\w/:.\-])(?:\.{1,2}/)?(?:[\w.\-~@+]+/)+[\w.\-~@+]*\."
    r"(?:json|py|log|txt|db|sqlite|yml|yaml|env|conf|cfg|ini|pem|key|crt)\b")
# A path has a root and at least two segments, so prose such as "and/or" or
# "Settings/Trading" is left alone: /home/app/x.py, /tmp/x, C:\\private\\trace.log
_PATH = re.compile(
    r"(?<![\w/:.\-])/(?:[\w.\-~@+]+/)+[\w.\-~@+]*"
    r"|(?<![\w])[A-Za-z]:[\\/](?:[^\s\"'\\/]+[\\/])*[^\s\"'\\/]*"
)


def message(exc, *secrets, fallback="request failed", limit=300):
    """Bounded diagnostic prose with no URL, path, header or credential in it."""
    raw = str(exc).strip() if exc is not None else ""
    raw = raw or fallback
    # Bounded first: this text can be chosen by a stranger, and every regex
    # below runs over all of it. Only `limit` characters are returned.
    raw = raw[:max(limit * 4, 1000)]
    raw = _URL.sub("[redacted-url]", raw)
    raw = _USERINFO.sub("[redacted-credentials]", raw)
    raw = _EMAIL.sub("[redacted-email]", raw)
    raw = _IP.sub("[redacted-host]", raw)
    raw = _FQDN.sub("[redacted-host]", raw)
    raw = _RELPATH.sub("[redacted-path]", raw)
    raw = _HOST.sub(lambda m: f"{m.group(1)}=[redacted-host]", raw)
    raw = _PATH.sub("[redacted-path]", raw)
    return redact.scrub_for_client(raw, *secrets, limit=limit)
