"""Scrub credentials out of anything on its way to a log.

Every existing log line in this package was checked by hand and none of them
prints a secret. That is worth exactly as much as the next person's memory.

A redaction that depends on each author remembering to call it protects the
lines somebody thought about, which are not the lines that leak. The ones that
leak are the generic ones — `print(f"failed: {e}")` where the exception
happens to carry a request URL, a header dict repr in a traceback, a payload
echoed back on an error path.

So this works two ways, and the first one is the one that matters:

  BY VALUE    the actual secrets this process holds, read from the environment,
              are replaced wherever they appear. This catches a secret arriving
              through a path nobody anticipated, which is the whole problem.

  BY SHAPE    strings that look like credentials — a Telegram bot token, a
              Bearer header, an sk- key, a JWT, a licence key — are replaced
              even when this process has never seen that particular value.

`install()` routes stdout and stderr through it, so a `print` added later is
covered without its author knowing this module exists.

What is NOT attempted: scrubbing structured data before serialisation, or
guessing at high-entropy strings. The first belongs at each boundary; the
second produces false positives on order ids and symbols, and a redactor that
mangles ordinary output gets turned off.
"""
import os
import re
import sys

MASK = "***"

# Environment variables whose VALUE must never appear in output. Keys are
# matched by substring, so CTRADER_ACCESS_TOKEN is covered by "TOKEN".
_SECRET_NAME_PARTS = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "APIKEY", "API_KEY",
    "PRIVATE_KEY", "ACCESS_KEY", "SERVICE_KEY", "WEBHOOK_SECRET",
    "SIGNING", "ENCRYPTION_KEY", "CREDENTIAL", "DSN", "REDIS_URL",
    "DATABASE_URL",
)

# Values shorter than this are not treated as secrets: masking every "1" or
# "demo" that happens to be in an env var would destroy ordinary output.
_MIN_SECRET_LEN = 8

_SHAPES = (
    # Telegram bot token: 8-10 digits, colon, 30+ URL-safe characters.
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}"), MASK),
    # Authorization headers, whatever the scheme.
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*)(bearer|basic|telegram)?\s*\S+"),
     r"\1" + MASK),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{10,}"), "Bearer " + MASK),
    # OpenAI-style and Stripe-style keys.
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), MASK),
    (re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{10,}"), MASK),
    (re.compile(r"\bwhsec_[A-Za-z0-9]{10,}"), MASK),
    # A JWT, three base64url segments.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), MASK),
    # Telegram initData always carries hash= and auth_date=; mask the lot
    # rather than trying to keep the harmless fields.
    (re.compile(r"\b(?:query_id|user)=[^&\s]*&[^\s]*hash=[A-Fa-f0-9]{64}"), MASK),
    (re.compile(r"\bhash=[A-Fa-f0-9]{64}"), "hash=" + MASK),
    # A licence key in either format.
    (re.compile(r"\bFORX(?:-[A-Z2-9]{4,5}){3,7}\b"), MASK),
    # Cookies, including the dashboard session.
    (re.compile(r"(?i)\b(cookie\s*[:=]\s*)\S+"), r"\1" + MASK),
    (re.compile(r"\bapex_session=[A-Za-z0-9_-]+"), "apex_session=" + MASK),
    # A private key block, however it is embedded.
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.S), MASK),
)


def secret_values():
    """The literal secrets this process holds, longest first.

    Longest first matters: if one secret is a prefix of another, masking the
    short one first leaves the tail of the long one in the output.
    """
    out = []
    for name, value in os.environ.items():
        if not value or len(value) < _MIN_SECRET_LEN:
            continue
        upper = name.upper()
        if any(part in upper for part in _SECRET_NAME_PARTS):
            out.append(value)
    return sorted(set(out), key=len, reverse=True)


def scrub(text) -> str:
    """Return `text` with known secret values and credential shapes masked."""
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    if not s:
        return s
    for value in secret_values():
        if value in s:
            s = s.replace(value, MASK)
    for pattern, replacement in _SHAPES:
        s = pattern.sub(replacement, s)
    return s


class _ScrubbedStream:
    """A write-through stream that scrubs. Deliberately thin.

    It forwards every other attribute, so anything that inspects the stream —
    `isatty`, `fileno`, `encoding` — sees the real one underneath.
    """

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def write(self, data):
        try:
            return self._wrapped.write(scrub(data))
        except Exception:
            # Logging must never be the thing that breaks the process. If
            # scrubbing fails, the safe move is to drop the line rather than
            # print an unscrubbed one.
            return 0

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        return self._wrapped.flush()

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


_installed = False


def install():
    """Route stdout and stderr through the scrubber. Idempotent."""
    global _installed
    if _installed:
        return False
    sys.stdout = _ScrubbedStream(sys.stdout)
    sys.stderr = _ScrubbedStream(sys.stderr)
    _installed = True
    return True


def uninstall():
    """Restore the original streams. For tests."""
    global _installed
    if not _installed:
        return False
    if isinstance(sys.stdout, _ScrubbedStream):
        sys.stdout = sys.stdout._wrapped
    if isinstance(sys.stderr, _ScrubbedStream):
        sys.stderr = sys.stderr._wrapped
    _installed = False
    return True
