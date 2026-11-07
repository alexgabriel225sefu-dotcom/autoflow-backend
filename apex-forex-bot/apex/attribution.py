"""Carry an ad click from the ad into the sale.

A Telegram deep link — t.me/BOT?start=PAYLOAD — accepts at most 64 characters
drawn from [A-Za-z0-9_-]. A Meta click identifier does not fit: it is longer
than that and uses characters the payload rejects. So an ad that links straight
into Telegram arrives carrying nothing. Every sale is then unattributed, Meta's
optimiser never learns who buys, and the cost per purchase never comes down —
which is the whole point of running the ads.

This module is the bridge across that gap:

    ad  ──▶  GET /go?fbclid=…        the click lands in a browser, where the
                                     identifier still exists
             mint a 24-char token    short enough for the deep link
             store the identifiers   under that token, in the shared store
        ──▶  t.me/BOT?start=<token>  the token is what travels
    /start   claim(token, chat_id)   the click is now tied to a Telegram chat
    Stripe   report_purchase(chat)   the webhook already knows the chat from
                                     client_reference_id

Nothing here talks to Meta unless META_CAPI_ENABLED is explicitly "true".
Reporting a purchase to an advertising platform is advertising data processing,
and the privacy policy has to permit it before that flag goes on — as written
today it says the opposite. Everything above the reporting call is inert on its
own: it stores an identifier the visitor's own browser supplied and sends it
nowhere.
"""

import hashlib
import json
import os
import re
import secrets
import time

from apex import user_store

# ── Token ───────────────────────────────────────────────────────────────
# "ax" + 22 url-safe characters = 24, inside Telegram's 64-character limit and
# built from the character set the payload allows. The prefix is what lets
# /start tell an attribution token apart from a licence key, which is the other
# thing that arrives in that position.
_TOKEN_RE = re.compile(r"^ax[A-Za-z0-9_-]{22}$")

# A click is worth remembering for longer than Meta's attribution window, so a
# buyer who thinks it over for a week is still credited to the ad that found
# them. The chat-level record outlives the click record: it is what the Stripe
# webhook reads, and a purchase can trail the click by a long way.
_CLICK_TTL_S = 30 * 24 * 3600
_CHAT_TTL_S = 90 * 24 * 3600

_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION") or "v21.0"


def _enabled() -> bool:
    """Whether purchases may be reported to Meta.

    Three things must all be true, and the flag is not implied by the other
    two: having credentials configured is not the same as having decided to
    send data with them.
    """
    if (os.getenv("META_CAPI_ENABLED") or "").strip().lower() not in ("1", "true", "yes"):
        return False
    return bool(_dataset_id() and _access_token())


def _dataset_id():
    return (os.getenv("META_DATASET_ID") or os.getenv("META_PIXEL_ID") or "").strip()


def _access_token():
    return (os.getenv("META_CAPI_TOKEN") or "").strip()


def mint_token() -> str:
    """A fresh attribution token. token_urlsafe(16) yields exactly 22 chars."""
    return "ax" + secrets.token_urlsafe(16)


def looks_like_token(value) -> bool:
    return bool(value and _TOKEN_RE.match(str(value).strip()))


# ── Capture ─────────────────────────────────────────────────────────────

def _clean(value, limit=400):
    """Query-string values arrive from the open internet.

    Clamped and stripped of control characters before anything stores them,
    renders them, or puts them in a URL sent to Meta.
    """
    if not value:
        return ""
    s = str(value)[:limit]
    return "".join(ch for ch in s if ch.isprintable()).strip()


def _fbc(fbclid: str, clicked_ms: int) -> str:
    """Meta's click cookie format: fb.<subdomain index>.<time ms>.<fbclid>.

    Index 1 is the correct value for a click that landed on the registered
    domain rather than a sub-subdomain.
    """
    return f"fb.1.{clicked_ms}.{fbclid}" if fbclid else ""


def record_click(*, fbclid="", fbp="", utm=None, ip="", user_agent="", url="") -> str:
    """Store one ad click and return the token that stands for it.

    Returns the token even when the store is unavailable: the redirect to
    Telegram has to happen either way. A visitor must never be left staring at
    an error page because attribution could not be written — the sale matters
    more than the measurement.
    """
    token = mint_token()
    now_ms = int(time.time() * 1000)
    record = {
        "fbclid": _clean(fbclid, 255),
        "fbc": _fbc(_clean(fbclid, 255), now_ms),
        "fbp": _clean(fbp, 128),
        "utm": {k: _clean(v, 120) for k, v in (utm or {}).items() if v},
        "ip": _clean(ip, 64),
        "ua": _clean(user_agent, 400),
        "url": _clean(url, 500),
        "ts": int(now_ms / 1000),
    }
    try:
        user_store.set_blob(f"attr:click:{token}", json.dumps(record), ttl_s=_CLICK_TTL_S)
    except Exception as e:
        print(f"[Attribution] could not store click {token}: {e}")
    return token


def claim(token, chat_id) -> bool:
    """Tie a stored click to the Telegram chat that opened it.

    First claim wins. Re-running /start with an older token must not overwrite
    the click that actually brought the buyer in, and a second visitor cannot
    take a token that is already spoken for.
    """
    if not looks_like_token(token) or not chat_id:
        return False
    chat_key = f"attr:chat:{chat_id}"
    try:
        if user_store.get_blob(chat_key):
            return False
        raw = user_store.get_blob(f"attr:click:{token}")
        if not raw:
            return False
        record = json.loads(raw)
        record["chat_id"] = str(chat_id)
        record["claimed_ts"] = int(time.time())
        user_store.set_blob(chat_key, json.dumps(record), ttl_s=_CHAT_TTL_S)
        # One click, one chat. Retiring the click record stops a token that
        # leaks — forwarded in a screenshot, or sitting in someone's history —
        # from crediting a second person's purchase to the same ad. Emptied
        # rather than left to expire, because get_blob treats "" as absent.
        user_store.set_blob(f"attr:click:{token}", "", ttl_s=60)
        print(f"[Attribution] {chat_id} arrived from "
              f"{record.get('utm', {}).get('utm_source') or 'an ad'}"
              f"{' with a click id' if record.get('fbclid') else ' without a click id'}")
        return True
    except Exception as e:
        print(f"[Attribution] claim failed for {chat_id}: {e}")
        return False


def for_chat(chat_id):
    """The click that brought this chat in, or None."""
    try:
        raw = user_store.get_blob(f"attr:chat:{chat_id}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


# ── Reporting ───────────────────────────────────────────────────────────

def _sha256(value):
    return hashlib.sha256(str(value).strip().lower().encode("utf-8")).hexdigest()


def report_purchase(chat_id, value, currency="USD", email="", event_id=""):
    """Tell Meta that this chat bought, against the click that found them.

    Returns a short reason string for the log rather than raising: a purchase
    is already complete and provisioned by the time this runs, and nothing here
    may put that at risk. The caller ignores the result.

    What is sent, when enabled: the Meta click identifier, the IP and user agent
    recorded at the click, and — if the buyer's email is known — its SHA-256
    hash, never the address itself. Meta requires the hash to match the buyer to
    an account; it is the standard field, and it is still personal data leaving
    for an advertising purpose, which is why the flag exists.
    """
    if not _enabled():
        return "disabled"
    record = for_chat(chat_id)
    if not record:
        return "no click on record"
    if not (record.get("fbc") or email):
        # With neither a click id nor an email there is nothing to match on;
        # the event would be counted but attributed to nobody.
        return "nothing to match on"

    user_data = {}
    if record.get("fbc"):
        user_data["fbc"] = record["fbc"]
    if record.get("fbp"):
        user_data["fbp"] = record["fbp"]
    if record.get("ip"):
        user_data["client_ip_address"] = record["ip"]
    if record.get("ua"):
        user_data["client_user_agent"] = record["ua"]
    if email:
        user_data["em"] = [_sha256(email)]

    payload = {
        "data": [{
            "event_name": "Purchase",
            "event_time": int(time.time()),
            # Stripe's event id, so a redelivery Meta also receives collapses
            # into one conversion instead of two.
            "event_id": str(event_id or f"{chat_id}-{int(time.time())}"),
            "action_source": "website",
            "event_source_url": record.get("url") or "",
            "user_data": user_data,
            "custom_data": {"currency": currency, "value": float(value)},
        }],
    }
    test_code = (os.getenv("META_CAPI_TEST_CODE") or "").strip()
    if test_code:
        payload["test_event_code"] = test_code

    url = (f"https://graph.facebook.com/{_GRAPH_VERSION}/"
           f"{_dataset_id()}/events?access_token={_access_token()}")
    try:
        import requests
        r = requests.post(url, json=payload, timeout=8)
        if r.status_code >= 300:
            # The token is in the query string, so the URL never goes in a log.
            print(f"[Attribution] Meta rejected the purchase event "
                  f"(HTTP {r.status_code}): {r.text[:200]}")
            return f"http {r.status_code}"
        print(f"[Attribution] reported purchase for {chat_id} to Meta")
        return "sent"
    except Exception as e:
        print(f"[Attribution] could not report purchase for {chat_id}: {e}")
        return "error"
