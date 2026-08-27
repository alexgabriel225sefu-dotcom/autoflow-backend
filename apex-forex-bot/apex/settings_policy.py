"""What may change a setting, and from where. One allowlist, no denylist.

Two sources can change this bot's configuration at runtime, and they do NOT
deserve the same trust:

  OPERATOR   an admin typing /setkeys into Telegram. Authenticated as the
             account that owns the bot, and every change is audited.
  REMOTE     the licence server's saved configuration, fetched at startup by
             `bot.load_remote()`. Whoever controls that response — the server,
             anyone who can write the `bot_configs` row, anyone who can answer
             for that hostname — controls what arrives here.

Before this module, REMOTE was applied by:

    for k, v in data.items():
        os.environ[k] = str(v)

with no filter at all. That is not "remote configuration", it is a remote
write primitive onto the process environment, and the environment decides
things far outside trading:

    PATH         where the next subprocess resolves its executable from
    LD_PRELOAD   a shared object mapped into every child process
    PYTHONPATH   which module `import` finds first

Any one of those turns a configuration fetch into code execution. None of them
is a trading setting, and no denylist would have caught the fourth one nobody
thought of. So the rule here is an ALLOWLIST: a key that is not named below is
refused, whatever it is called.

`REMOTE_SETTABLE` is deliberately SMALLER than `OPERATOR_SETTABLE`. Settings
that pick a network destination, an identity, or a signing key are absent from
it even where an operator may set them by hand, because the whole point is
that the remote source is the untrusted one:

    LICENSE_SERVER        where the next config comes from — self-perpetuating
    LICENSE_KEY           which licence this bot claims to be
    DASHBOARD_URL         }
    VOICE_SHORTCUT_URL    } outbound destinations — SSRF
    AI_GATEWAY_URL        }
    CTRADER_REDIRECT_URI  where an OAuth code is delivered — account takeover
    TOKEN_ENCRYPTION_KEY  the key every stored credential is sealed with
    STRIPE_WEBHOOK_SECRET the signature the payment webhook is checked against
    EV_GATE_MODE          shadow → enforce is an operator decision, on purpose
    CTRADER_ACCESS_TOKEN  } broker credentials arrive from OAuth and live in
    CTRADER_REFRESH_TOKEN } the per-user store — never from a config blob
    CTRADER_CLIENT_SECRET

Values are validated, not merely accepted: a key being settable does not make
RISK_PER_TRADE=50 a sensible number.
"""
import re

__all__ = [
    "OPERATOR_SETTABLE", "OPERATOR_SECRETS", "REMOTE_SETTABLE",
    "SECRET_KEYS", "is_secret_key", "validate_operator", "validate_remote",
    "SettingRejected", "cfg_attr",
]


class SettingRejected(ValueError):
    """A setting was refused. The message names the KEY, never the value."""


# ─── Validators ──────────────────────────────────────────
# Shared by both allowlists so a value means the same thing wherever it
# arrives from. Each returns the coerced value or raises.

def _num(cast, lo, hi):
    def check(v):
        try:
            x = cast(str(v).strip())
        except (TypeError, ValueError):
            raise SettingRejected(f"expected a number between {lo} and {hi}")
        if not (lo <= x <= hi):
            raise SettingRejected(f"must be between {lo} and {hi}, got {x}")
        return x
    return check


def _choice(*allowed):
    def check(v):
        s = str(v).strip().lower()
        if s not in allowed:
            raise SettingRejected("must be one of: " + ", ".join(allowed))
        return s
    return check


def _flag(v):
    s = str(v).strip().lower()
    if s not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
        raise SettingRejected("must be true or false")
    return s in ("true", "1", "yes", "on")


def _symbol(v):
    s = re.sub(r"[^A-Z0-9]", "", str(v).strip().upper())
    if not (5 <= len(s) <= 8) or not s.isalnum():
        raise SettingRejected("expected a symbol like EURUSD or XAUUSD")
    return s


def _symbol_list(v):
    """Comma-separated symbols. Bounded, so one field cannot become a payload."""
    parts = [p for p in re.split(r"[,\s]+", str(v).strip()) if p]
    if not parts:
        raise SettingRejected("expected at least one symbol")
    if len(parts) > 40:
        raise SettingRejected(f"too many symbols ({len(parts)}, max 40)")
    return ",".join(_symbol(p) for p in parts)


def _text(pattern, max_len, what):
    """A bounded string matching an explicit pattern.

    Anchored and length-capped: an unbounded string reaching os.environ is how
    a setting becomes an injection point for whatever reads it next.
    """
    rx = re.compile(pattern)

    def check(v):
        s = str(v).strip()
        if not s or len(s) > max_len:
            raise SettingRejected(f"expected {what} (1-{max_len} characters)")
        if not rx.fullmatch(s):
            raise SettingRejected(f"expected {what}")
        return s
    return check


def _secret(min_len, max_len=512):
    def check(v):
        s = str(v).strip()
        if len(s) < min_len:
            raise SettingRejected(f"too short — expected at least {min_len} characters")
        if len(s) > max_len:
            raise SettingRejected(f"too long — expected at most {max_len} characters")
        if any(c.isspace() for c in s):
            raise SettingRejected("must not contain whitespace")
        # A credential is opaque. Anything that reads as a control character
        # is either a mistake or an attempt to break out of whatever consumes
        # it, and neither is worth accepting.
        if any(ord(c) < 32 or ord(c) == 127 for c in s):
            raise SettingRejected("must not contain control characters")
        return s
    return check


_chat_id = _text(r"-?\d{1,20}", 21, "a numeric Telegram id")
_timeframe = _choice("m1", "m5", "m15", "m30", "h1", "h4", "d1")


# ─── Trading settings ────────────────────────────────────
# Safe to echo back in a message or an audit line: none is a credential.
_TRADING = {
    # cTrader only. The MT branch was still settable here even though
    # SUPPORTED_BROKERS has said ["ctrader"] for some time, so a remote
    # config or an admin could name an execution path the engine no longer
    # has.
    "BROKER":                  ("BROKER",                  _choice("ctrader")),
    "PAPER_TRADING":           ("PAPER_TRADING",           _flag),
    "PAPER_BALANCE":           ("PAPER_BALANCE",           _num(float, 1.0, 10_000_000.0)),
    "TRADE_SYMBOL":            ("SYMBOL",                  _symbol),
    "SCAN_SYMBOLS":            ("SCAN_SYMBOLS",            _symbol_list),
    "MULTI_SYMBOL":            ("MULTI_SYMBOL",            _flag),
    "RISK_PER_TRADE":          ("RISK_PER_TRADE",          _num(float, 0.0001, 0.10)),
    "STOP_LOSS_PIPS":          ("STOP_LOSS_PIPS",          _num(float, 1.0, 500.0)),
    "TAKE_PROFIT_PIPS":        ("TAKE_PROFIT_PIPS",        _num(float, 1.0, 1000.0)),
    "MIN_CONFIDENCE":          ("MIN_CONFIDENCE",          _num(int, 0, 100)),
    "CTRADER_ENV":             ("CTRADER_ENV",             _choice("demo", "live")),
    "LEVERAGE":                ("LEVERAGE",                _num(float, 1.0, 500.0)),
    "HTF_FILTER":              ("HTF_FILTER",              _flag),
    "HTF_STRICT":              ("HTF_STRICT",              _flag),
    "HTF_TIMEFRAME":           ("HTF_TIMEFRAME",           _timeframe),
    "TRAILING_STOP":           ("TRAILING_STOP",           _flag),
    "TRAILING_STOP_PIPS":      ("TRAILING_STOP_PIPS",      _num(float, 0.0, 500.0)),
    "ATR_BASED_SL":            ("ATR_BASED_SL",            _flag),
    "ATR_SL_MULT":             ("ATR_SL_MULT",             _num(float, 0.1, 20.0)),
    "ATR_TP_MULT":             ("ATR_TP_MULT",             _num(float, 0.1, 40.0)),
    "BREAKEVEN_AT_R":          ("BREAKEVEN_AT_R",          _num(float, 0.0, 20.0)),
    "LET_WINNERS_RUN":         ("LET_WINNERS_RUN",         _flag),
    "RIDE_AT_R":               ("RIDE_AT_R",               _num(float, 0.0, 20.0)),
    "RIDE_LOCK":               ("RIDE_LOCK",               _num(float, 0.0, 20.0)),
    "RUNNER_TRAIL_PIPS":       ("RUNNER_TRAIL_PIPS",       _num(float, 0.0, 500.0)),
    "MIN_EXIT_R":              ("MIN_EXIT_R",              _num(float, -10.0, 20.0)),
    "SCALP_MODE":              ("SCALP_MODE",              _flag),
    "STRUCTURAL_STOPS":        ("STRUCTURAL_STOPS",        _flag),
    "STRUCTURAL_MIN_RR":       ("STRUCTURAL_MIN_RR",       _num(float, 0.1, 20.0)),
    "MARGIN_CAP":              ("MARGIN_CAP",              _num(float, 0.0, 1.0)),
    "MAX_SPREAD_PCT":          ("MAX_SPREAD_PCT",          _num(float, 0.0, 100.0)),
    "FLASH_SPIKE_PCT":         ("FLASH_SPIKE_PCT",         _num(float, 0.0, 100.0)),
    "INSTITUTIONAL_GATE":      ("INSTITUTIONAL_GATE",      _flag),
    "SENTINEL_MODE":           ("SENTINEL_MODE",           _choice("off", "shadow", "enforce")),
    "SENTINEL_MIN_CONFIDENCE": ("SENTINEL_MIN_CONFIDENCE", _num(int, 0, 100)),
    "SENTINEL_TTL_S":          ("SENTINEL_TTL_S",          _num(int, 0, 86_400)),
    "AUTOPILOT_UNIVERSE":      ("AUTOPILOT_UNIVERSE",      _symbol_list),
}

# Credentials. Same validation, but the VALUE is never echoed, logged or
# audited — only the fact that the key changed.
_SECRETS = {
    "CTRADER_CLIENT_ID":     ("CTRADER_CLIENT_ID",     _secret(6)),
    "CTRADER_CLIENT_SECRET": ("CTRADER_CLIENT_SECRET", _secret(12)),
    "MT_BRIDGE_SECRET":      ("MT_BRIDGE_SECRET",      _secret(16)),
}

# Provisioning credentials the configurator legitimately sends on first
# deploy. Secret, so never logged by value.
_REMOTE_PROVISIONING = {
    "TELEGRAM_BOT_TOKEN": ("TELEGRAM_BOT_TOKEN", _secret(20)),
    "TELEGRAM_CHAT_ID":   ("TELEGRAM_CHAT_ID",   _chat_id),
    "DASHBOARD_TOKEN":    ("DASHBOARD_TOKEN",    _secret(16)),
    "MT_BRIDGE_SECRET":   ("MT_BRIDGE_SECRET",   _secret(16)),
    "GROQ_API_KEY":       ("GROQ_API_KEY",       _secret(16)),
    "GEMINI_API_KEY":     ("GEMINI_API_KEY",     _secret(16)),
    "TWELVE_DATA_KEY":    ("TWELVE_DATA_KEY",    _secret(8)),
    "METAAPI_TOKEN":      ("METAAPI_TOKEN",      _secret(16)),
    "METAAPI_ACCOUNT_ID": ("METAAPI_ACCOUNT_ID", _secret(6)),
    "AI_GATEWAY_KEY":     ("AI_GATEWAY_KEY",     _secret(16)),
}

# ─── The two allowlists ──────────────────────────────────
OPERATOR_SECRETS = dict(_SECRETS)
OPERATOR_SETTABLE = {**_TRADING, **_SECRETS}

# The remote source gets trading settings plus first-deploy provisioning —
# and NOT CTRADER_CLIENT_SECRET, which an operator may set by hand but a
# config blob may not.
REMOTE_SETTABLE = {**_TRADING, **_REMOTE_PROVISIONING}

# Every key whose value must stay out of logs, messages and audit records,
# from either source.
SECRET_KEYS = frozenset(_SECRETS) | frozenset(_REMOTE_PROVISIONING)


def is_secret_key(key) -> bool:
    return str(key).strip().upper() in SECRET_KEYS


def _validate(table, key, raw, source):
    k = str(key).strip().upper()
    if k not in table:
        # The KEY is named because an operator needs to know what was refused.
        # The VALUE is not, because a refused key may still carry a credential.
        raise SettingRejected(f"unknown setting for {source}: {k}")
    _attr, check = table[k]
    try:
        return k, check(raw)
    except SettingRejected as e:
        # Some validators quote the offending value back — `_num` says "got 50",
        # which is genuinely useful for a risk number an operator mistyped. It
        # would not be useful for a credential, so a secret key gets a message
        # that names only the key. The reason is not that the value is likely
        # to be secret; it is that this function cannot tell, and a log line is
        # forever.
        if k in SECRET_KEYS:
            raise SettingRejected(f"{k}: rejected (value withheld)") from None
        raise SettingRejected(f"{k}: {e}") from None


def validate_operator(key, raw):
    """(canonical_key, coerced_value) for an admin-initiated change, or raise."""
    return _validate(OPERATOR_SETTABLE, key, raw, "operator")


def validate_remote(key, raw):
    """(canonical_key, coerced_value) for remote configuration, or raise."""
    return _validate(REMOTE_SETTABLE, key, raw, "remote config")


def cfg_attr(key):
    """The cfg module attribute a key maps to, or None if it maps to none."""
    k = str(key).strip().upper()
    entry = OPERATOR_SETTABLE.get(k) or REMOTE_SETTABLE.get(k)
    return entry[0] if entry else None
