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
    # A Fernet token — everything this platform encrypts at rest, including
    # every stored cTrader access and refresh token. Version byte 0x80 plus a
    # timestamp always base64url-encodes to a leading "gAAAAA", and the
    # shortest possible ciphertext is far longer than this bound. The runbook
    # has told operators to grep logs for exactly this shape since before it
    # was masked here, which is the wrong way round.
    (re.compile(r"\bgAAAAA[A-Za-z0-9_-]{20,}={0,2}"), MASK),
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
    # Credentials carried in a QUERY STRING. cTrader's /apps/token reads its
    # params from the query string rather than a body, so a URL for that
    # endpoint contains the application's client_secret — the credential behind
    # every client's broker connection, not one client's — alongside the
    # authorization code or the client's refresh token.
    #
    # This is defence in depth, not the fix. requests puts the full URL into the
    # message of the HTTPError that raise_for_status() raises, and that message
    # used to reach the logs verbatim; apex/brokers/ctrader.py no longer lets it
    # escape. This catches the next place somebody prints a URL.
    #
    # The parameter name is kept and only the value masked, because "which
    # credential was in the line" is the one thing an operator reading a log
    # actually needs.
    (re.compile(r"(?i)\b(client_secret|client_id|refresh_token|access_token"
                r"|code|id_token|api_key|apikey|token|password|passwd|secret)"
                r"=([^&\s\"'\]<>]{4,})"),
     r"\1=" + MASK),
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


# ── text that is going to a CLIENT ──────────────────────────────────────────
# `scrub` above is for logs, and says so: it masks the secrets this process
# holds and the shapes it knows, and it deliberately does not guess at
# high-entropy strings, because a log line that has had every order id
# mangled gets turned off. Text that goes to a client's screen has the opposite
# trade: nothing that merely LOOKS like a credential is worth showing, and a
# refresh token or an app secret that this process never held (it arrived in an
# upstream error) has no known value or known shape to match on.
_CLIENT_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+\S+")
# The name may be quoted (a JSON or repr dump: 'refresh_token': 'x') and so may
# the value; the value runs to the next quote, space, comma or closing brace.
_CLIENT_KEYED = re.compile(
    r"(?i)\b(access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"authorization|api[_-]?key|password|secret|token)\b[\"']?\s*[=:]\s*"
    r"[\"']?[^\"'\s,}]+")
# "=" is not part of the class: a `name=value` pair is split so a short code
# after it (errorCode=POSITION_NOT_FOUND) is judged on its own, and a long value
# after it is still caught as a run of its own.
# Three shapes: a long run; a shorter run that ends in base64 padding (a 16-byte
# secret is 22 characters and "=="); two runs joined by "=" (each under 24, so
# neither is caught alone).
_CLIENT_TOKEN_LIKE = re.compile(
    r"[A-Za-z0-9_\-\.+/]{24,}"
    r"|[A-Za-z0-9_\-\.+/]{12,}={1,2}(?![A-Za-z0-9])"
    r"|[A-Za-z0-9_\-\.+/]{12,}=[A-Za-z0-9_\-\.+/]{12,}")
# A broker or API error CODE is not a credential and the client needs it:
# POSITION_NOT_FOUND, CH_CLIENT_AUTH_FAILURE, an order id such as CT_PAPER_17297...
# Upper-case words joined by underscores only; a real token carries lower-case
# letters or hyphens, or has no underscore at all.
# A word segment is short letters with at most a few trailing digits (V2,
# HTTP2); a long digit segment is an order id. A secret that merely contains an
# underscore alternates letters and digits or runs on, so it does not fit.
_CLIENT_CODE_LIKE = re.compile(
    r"(?=.{1,48}\Z)[A-Z]{1,14}[0-9]{0,4}"
    r"(?:_(?:[A-Z]{1,14}[0-9]{0,4}|[0-9]{1,16}))+")


def _benign_part(part):
    return bool(_CLIENT_CODE_LIKE.fullmatch(part)
                or (part.isdigit() and len(part) <= 30)
                or (part.isalpha() and len(part) <= 20))


def _client_token_sub(m):
    text = m.group(0)
    if _CLIENT_CODE_LIKE.fullmatch(text):
        return text
    if text.isdigit() and len(text) <= 30:
        return text
    if "=" in text and not text.endswith("="):
        # name=value of two short runs: kept when both sides read as an
        # identifier, a code or a number, not as a credential.
        if all(_benign_part(part) for part in text.split("=", 1)):
            return text
    return "[redacted]"


def scrub_for_client(text, *secrets, limit=160) -> str:
    """Bounded text with anything credential-shaped removed, for a client.

    Every given secret and every held secret is replaced, then bearer headers,
    `name=value` pairs for credential names, and any unbroken run of 24 or more
    token characters. Whitespace is collapsed and the result cut to `limit`.
    """
    if text is None:
        return ""
    out = text if isinstance(text, str) else str(text)
    for sec in secrets:
        if sec and isinstance(sec, str) and len(sec) >= 8:
            out = out.replace(sec, "[redacted]")
    out = scrub(out)
    out = _CLIENT_BEARER.sub(r"\1 [redacted]", out)
    out = _CLIENT_KEYED.sub(lambda m: f"{m.group(1)}=[redacted]", out)
    out = _CLIENT_TOKEN_LIKE.sub(_client_token_sub, out)
    return " ".join(out.split())[:limit]


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
