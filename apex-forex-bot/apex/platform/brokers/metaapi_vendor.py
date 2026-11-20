"""The MetaApi provisioning calls, and only the three we need.

WHY THIS EXISTS, AND WHAT IT CHANGES

MetaTrader has no OAuth. It has no public API at all: the protocol is account
number, password and server name, which is why the spike
(`docs/MT5_CLOUD_CONNECTOR_SPIKE.md`) stopped short of credential collection —
"we would be asking clients to type a broker password into our web app" is not
something to design casually.

MetaApi documents a way out of that, and it is the reason this module exists:
an account can be created WITHOUT login and password, and the client is then
sent a one-time configuration link where they enter their credentials on
MetaApi's own page. MetaApi's documentation states the consequence plainly —
"we will not be able to disclose the account password if your user has
configured the account this way".

So the credential never reaches Apex4Traders. That is not OAuth and must not
be described as it:

  * the password still EXISTS, at MetaApi;
  * there is no scope — an investor password reads, a master password trades,
    and nothing narrower is expressible;
  * the client cannot revoke us specifically from their broker, the way a
    cTrader client can revoke this application;
  * the broker has not sanctioned the integration and does not know of it.

What it does buy is real: we hold nothing, so we cannot leak it, and the
client types their password into the vendor that needs it rather than into a
web app that does not.

WHAT IS STRUCTURALLY IMPOSSIBLE HERE

`create_account` takes no password parameter. Not "takes one and refuses it" —
there is nowhere to put one. A future caller that wanted to send a client
credential through this module would have to change its signature, which is a
diff somebody reviews rather than a field somebody fills in.

THE TOKEN IS OURS

`A4T_MT5_VENDOR_TOKEN` is Apex4Traders' MetaApi token, not any client's. It
authorises us to the vendor; it is never derived from, and never mixed with,
anything a client supplies.
"""

import json
import os
import urllib.error
import urllib.request
import uuid

from apex.platform.brokers import base

# Pointed at a fake in tests. The spike named this variable for exactly that
# reason before a line of this module existed.
_BASE_URL_VAR = "A4T_MT5_VENDOR_BASE_URL"
_TOKEN_VAR = "A4T_MT5_VENDOR_TOKEN"
_DEFAULT_BASE = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"

PLATFORMS = ("mt4", "mt5")

# Read-only is the whole safety argument of the spike: an investor password
# cannot place an order at the broker, so a compromise of this path cannot
# trade. Execution needs a MASTER password and is a separate decision with its
# own gate — this module does not know how to ask for one.
TIMEOUT_S = 20


def base_url():
    return (os.getenv(_BASE_URL_VAR) or _DEFAULT_BASE).rstrip("/")


def token():
    return (os.getenv(_TOKEN_VAR) or "").strip()


def configured():
    """Whether this deployment can talk to the vendor at all."""
    return bool(token())


def _call(method, path, *, body=None, query=None):
    """One vendor call, or a ProviderError.

    The vendor's own exception is never raised onward. MetaApi echoes the
    request in its errors, and the request carries a server name and an
    account id; `base.ProviderError` exists because a connector that leaks the
    vendor's message has already been the bug once.
    """
    if not configured():
        raise base.ProviderError(
            "VENDOR_NOT_CONFIGURED",
            "the MetaTrader connector is not configured on this deployment")

    url = f"{base_url()}{path}"
    if query:
        pairs = "&".join(f"{k}={v}" for k, v in query.items() if v is not None)
        if pairs:
            url = f"{url}?{pairs}"

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "auth-token": token(),
        # Required by the vendor, and it is their idempotency key: a retry
        # after a timeout must not create a second trading account.
        "transaction-id": uuid.uuid4().hex,
        **({"Content-Type": "application/json"} if data is not None else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            raw = r.read().decode() or "{}"
    except urllib.error.HTTPError as e:
        # The status is ours to report; the body is the vendor's and stays
        # out of the message.
        raise base.ProviderError(
            "VENDOR_REFUSED",
            f"the MetaTrader provider refused the request (HTTP {e.code})",
        ) from None
    except Exception as e:                                  # noqa: BLE001
        raise base.ProviderError(
            "VENDOR_UNREACHABLE",
            f"the MetaTrader provider could not be reached "
            f"({type(e).__name__})") from None
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise base.ProviderError(
            "VENDOR_UNREADABLE",
            "the MetaTrader provider sent something that is not JSON") from None


def create_account(*, name, server, platform, magic=0, region=None):
    """Register a trading account that has NO credentials yet.

    Note the signature: there is no `password`, and no `login`. Both are
    omitted from the request on purpose, because omitting them is what makes
    the account one the END USER configures — see the module docstring.

    `server` is not a secret. It is the broker's server name, the same string
    printed in the client's MetaTrader terminal, and the vendor requires it to
    know which broker to reach.
    """
    if platform not in PLATFORMS:
        raise base.ProviderError(
            "UNSUPPORTED_PLATFORM",
            f"platform must be one of {', '.join(PLATFORMS)}")
    if not (name or "").strip():
        raise base.ProviderError("NAME_REQUIRED",
                                 "the account needs a name to be listed under")
    if not (server or "").strip():
        raise base.ProviderError(
            "SERVER_REQUIRED",
            "the broker's server name is required — it is shown in your "
            "MetaTrader terminal next to the account")

    body = {
        "name": str(name).strip(),
        "server": str(server).strip(),
        "platform": platform,
        # The vendor requires it. 0 is correct for an account whose trades we
        # do not place: a magic number tags OUR orders, and there are none.
        "magic": int(magic),
    }
    if region:
        body["region"] = str(region)
    out = _call("POST", "/users/current/accounts", body=body)
    account_id = (out or {}).get("id")
    if not account_id:
        raise base.ProviderError(
            "VENDOR_UNREADABLE",
            "the MetaTrader provider did not return an account id")
    return {"accountId": str(account_id), "platform": platform}


def configuration_link(account_id, *, ttl_days=7):
    """The one-time page where the CLIENT enters their own credentials.

    This is the whole point of the flow. The link goes to the client; what
    they type lands at MetaApi; we never see it and, per the vendor's
    documentation, cannot later ask for it.
    """
    if not (account_id or "").strip():
        raise base.ProviderError("ACCOUNT_REQUIRED", "an account id is required")
    if not isinstance(ttl_days, int) or isinstance(ttl_days, bool) or ttl_days < 1:
        raise base.ProviderError("BAD_TTL", "the link's lifetime must be a "
                                            "whole number of days, at least 1")
    out = _call("PUT",
                f"/users/current/accounts/{account_id}/configuration-link",
                query={"ttlInDays": ttl_days})
    link = (out or {}).get("configurationLink")
    if not link:
        raise base.ProviderError(
            "VENDOR_UNREADABLE",
            "the MetaTrader provider did not return a configuration link")
    return str(link)


def account_state(account_id):
    """What the vendor says about the account. Never a guess.

    `configured` answers the question the UI actually has — has the client
    finished entering their credentials? — and it is derived from the vendor's
    own fields rather than from whether we once sent them a link.
    """
    if not (account_id or "").strip():
        raise base.ProviderError("ACCOUNT_REQUIRED", "an account id is required")
    out = _call("GET", f"/users/current/accounts/{account_id}") or {}
    return {
        "accountId": str(out.get("_id") or out.get("id") or account_id),
        "name": out.get("name"),
        "platform": out.get("platform"),
        "state": out.get("state"),
        "connectionStatus": out.get("connectionStatus"),
        # The vendor reports the login once the client has set one. Its
        # presence is how we know the link was used; its absence is not an
        # error, it is "not yet".
        "configured": bool(out.get("login")),
    }
