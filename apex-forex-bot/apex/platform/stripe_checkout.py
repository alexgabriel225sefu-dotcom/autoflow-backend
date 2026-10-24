"""Stripe Checkout for the founder licence. Nothing here sells by default.

Two ways to pay, both off until the owner sets environment variables.
Values are read at call time and are never logged. This module has no
default price, key, or payment-link URL.

Payment Link
    ``A4T_STRIPE_PAYMENT_LINK`` is a ``https://buy.stripe.com/<id>`` URL.
    The signed-in user's id and email are added as ``client_reference_id``
    and ``prefilled_email``. The browser is sent there. No HTTP call.

Checkout Session
    ``STRIPE_SECRET_KEY``, ``A4T_STRIPE_PRICE_ID`` and
    ``A4T_PUBLIC_WEB_ORIGIN`` together. The server creates a one-time
    Session for that price, with ``client_reference_id`` set to the user
    id and success and cancel URLs on ``/license``. The HTTP call is
    injectable so tests never touch the network.

The webhook that records the licence lives in ``billing.handle_event``.
A Payment Link purchase arrives as ``checkout.session.completed`` with
the ``client_reference_id`` from the URL.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

PAYMENT_LINK_ENV = "A4T_STRIPE_PAYMENT_LINK"
SECRET_KEY_ENV = "STRIPE_SECRET_KEY"
PRICE_ENV = "A4T_STRIPE_PRICE_ID"
ORIGIN_ENV = "A4T_PUBLIC_WEB_ORIGIN"

_CHECKOUT_URL = "https://api.stripe.com/v1/checkout/sessions"
_BUY_HOST = "buy.stripe.com"
_SESSION_HOST = "checkout.stripe.com"

# Tests assign a callable(body: bytes, secret_key: str) -> bytes | str | dict.
# Production leaves this None, which uses the Stripe API.
_transport = None


class CheckoutError(Exception):
    """A refusal safe to show a browser. The message has no key and no URL."""

    def __init__(self, code, message, status=502):
        self.code = code
        self.status = int(status)
        super().__init__(message)


def _env(name):
    value = (os.getenv(name) or "").strip()
    return value or None


def _parts(url):
    try:
        return urllib.parse.urlsplit(str(url))
    except Exception:                                        # noqa: BLE001
        return None


def payment_link_base():
    """The configured Payment Link, or None when it is missing or not Stripe."""
    raw = _env(PAYMENT_LINK_ENV)
    parts = _parts(raw) if raw else None
    if parts is None:
        return None
    if parts.scheme != "https" or parts.hostname != _BUY_HOST:
        return None
    if parts.username or parts.password or parts.fragment:
        return None
    if not parts.path or parts.path == "/" or ".." in parts.path:
        return None
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, parts.query, ""))


def public_origin():
    """Scheme and host of the web app, used only to build /license URLs."""
    raw = _env(ORIGIN_ENV)
    parts = _parts(raw) if raw else None
    if parts is None or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    host = parts.hostname
    if parts.scheme == "https" and host not in (_BUY_HOST, _SESSION_HOST):
        return f"https://{parts.netloc}"
    if parts.scheme == "http" and host in ("localhost", "127.0.0.1"):
        return f"http://{parts.netloc}"
    return None


def _price_id():
    price = _env(PRICE_ENV)
    if not price or any(ch.isspace() for ch in price):
        return None
    if not all(ch.isalnum() or ch == "_" for ch in price):
        return None
    return price


def _secret_key():
    key = _env(SECRET_KEY_ENV)
    if not key or any(ch.isspace() for ch in key):
        return None
    return key


def session_configured():
    return bool(_secret_key() and _price_id() and public_origin())


def purchase_ready():
    """True when a buyer can be sent to Stripe. False when nothing is set."""
    return payment_link_base() is not None or session_configured()


def payment_link_for(user_id, email):
    """The Payment Link with this user's id and email. None when unconfigured.

    Identity comes from the caller, which is the authenticated principal.
    Query parameters already on the link do not get to replace them.
    """
    base = payment_link_base()
    uid = str(user_id or "").strip()
    if not base or not uid:
        return None
    parts = urllib.parse.urlsplit(base)
    kept = [(key, value) for key, value in urllib.parse.parse_qsl(
        parts.query, keep_blank_values=False)
            if key not in ("client_reference_id", "prefilled_email")]
    kept.append(("client_reference_id", uid))
    mail = str(email or "").strip()
    if mail:
        kept.append(("prefilled_email", mail))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path,
         urllib.parse.urlencode(kept), ""))


def _license_urls(origin):
    root = origin.rstrip("/")
    return (root + "/license?checkout=success",
            root + "/license?checkout=cancel")


def _hosted(url, host):
    parts = _parts(url)
    return bool(parts and parts.scheme == "https" and parts.hostname == host
                and not parts.username)


def _default_transport(body, secret_key):
    request = urllib.request.Request(
        _CHECKOUT_URL, data=body, method="POST",
        headers={
            "Authorization": "Bearer " + secret_key,
            "Content-Type": "application/x-www-form-urlencoded",
        })
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        # The body can echo the request. The browser gets a fixed sentence.
        raise CheckoutError(
            "CHECKOUT_FAILED",
            "the payment provider refused the checkout",
            status=502) from exc
    except CheckoutError:
        raise
    except Exception as exc:                                 # noqa: BLE001
        raise CheckoutError(
            "CHECKOUT_FAILED",
            "the payment provider could not be reached",
            status=502) from exc


def _session_url(raw):
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception as exc:                             # noqa: BLE001
            raise CheckoutError(
                "CHECKOUT_FAILED",
                "the payment provider returned an unreadable response",
                status=502) from exc
    else:
        data = raw
    url = data.get("url") if isinstance(data, dict) else None
    if not _hosted(url, _SESSION_HOST):
        raise CheckoutError(
            "CHECKOUT_FAILED",
            "the payment provider did not return a checkout page",
            status=502)
    return url


def create_checkout_session(user_id, *, email=None, transport=None):
    """Create one Checkout Session. Raises CheckoutError. Does not grant."""
    if not session_configured():
        raise CheckoutError(
            "CHECKOUT_NOT_IMPLEMENTED", "Not on sale yet", status=501)
    from apex.platform import billing as billing
    uid = str(user_id or "").strip()
    if not uid:
        raise CheckoutError("NO_USER", "a signed-in user is required", status=401)
    success, cancel = _license_urls(public_origin())
    form = {
        "mode": "payment",
        "client_reference_id": uid,
        "success_url": success,
        "cancel_url": cancel,
        "line_items[0][price]": _price_id(),
        "line_items[0][quantity]": "1",
        f"metadata[{billing.USER_META_KEY}]": uid,
    }
    mail = str(email or "").strip()
    if mail:
        form["customer_email"] = mail
    body = urllib.parse.urlencode(form).encode()
    send = transport or _transport or _default_transport
    try:
        raw = send(body, _secret_key())
    except CheckoutError:
        raise
    except Exception as exc:                                 # noqa: BLE001
        raise CheckoutError(
            "CHECKOUT_FAILED",
            "the payment provider could not be reached",
            status=502) from exc
    return _session_url(raw)


def start_checkout(principal, body=None, *, transport=None):
    """Where this signed-in user pays.

    The default is the Payment Link when one is configured, and a Checkout
    Session otherwise. ``method`` in the body may be ``payment_link`` or
    ``session``. A user id or email in the body is ignored.
    """
    method = ""
    if isinstance(body, dict):
        method = str(body.get("method") or "").strip().lower()
    if method not in ("", "auto", "payment_link", "session"):
        raise CheckoutError(
            "BAD_METHOD", "method must be payment_link or session", status=400)
    uid = str(getattr(principal, "user_id", "") or "")
    email = getattr(principal, "email", None)
    if method == "session" or (method in ("", "auto") and not payment_link_base()):
        url = create_checkout_session(uid, email=email, transport=transport)
        return {"url": url, "kind": "checkout_session"}
    url = payment_link_for(uid, email)
    if not url:
        raise CheckoutError(
            "CHECKOUT_NOT_IMPLEMENTED", "Not on sale yet", status=501)
    return {"url": url, "kind": "payment_link"}
