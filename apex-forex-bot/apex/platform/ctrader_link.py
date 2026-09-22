"""Linking a cTrader account to an Apex4Traders account. No Telegram anywhere.

THE ATTACK THIS FLOW IS SHAPED AROUND

The obvious design — sign the user id into `state`, and on callback bind the
tokens to whoever that state names — has a hole that is easy to miss. An
attacker starts a connect flow for THEIR OWN Apex account, takes the authorize
link, and gets a victim to open it. The victim logs into cTrader and approves.
The callback arrives carrying the ATTACKER's user id, and the VICTIM's live
trading account is now bound to the attacker's dashboard.

`state` cannot close that on its own, because the attacker's state is
perfectly valid — it is their state. So the callback here does NOT finish the
link. It parks the authorization code server-side and hands the browser a
nonce. The link is completed by an authenticated POST, and the session making
that call must be the same user that began the flow. An attacker who cannot
sign in as the victim cannot complete it, and a victim who is signed in as
themselves completes their own.

ON PKCE

cTrader's Open API implements the confidential-client authorization code
grant: the token endpoint takes client_id and client_secret, and the authorize
endpoint documents no code_challenge parameter (see brokers/ctrader.py —
authorize_url sends client_id, redirect_uri, scope, state, product; nothing
else is accepted). Sending a code_challenge that the server ignores would put
the word PKCE in our documentation without putting any protection in the
flow, which is worse than not claiming it: somebody would later trust it.

PKCE exists to protect clients that cannot hold a secret. This callback is
server-side and does hold one. The equivalent protection is implemented
instead: state is random, HMAC-signed, single-use, time-limited, and bound to
a user id that the completing session must match.

THE SIGNING KEY IS NOT THE TELEGRAM TOKEN

ctrader_oauth.py signs state with `TELEGRAM_BOT_TOKEN or CTRADER_CLIENT_SECRET`.
That is a Telegram dependency in the middle of a security primitive, and this
flow must work on a deployment with no bot at all. The key here is derived by
HMAC from TOKEN_ENCRYPTION_KEY (or CTRADER_CLIENT_SECRET, which any working
OAuth deployment must already have), with a domain separation string so the
derived key is never the same bytes as the key it came from.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from apex import user_store
from apex.platform import store as _store

STATE_TTL_S = 600          # 10 minutes to log into cTrader and approve
PENDING_TTL_S = 900        # then 5 more to come back and confirm while signed in
_DOMAIN = b"apex4traders/ctrader-oauth-state/v1"

DEMO = "demo"
LIVE = "live"


class LinkError(RuntimeError):
    """Base for every refusal here. Carries a code the UI can branch on."""

    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


class LinkConfigError(LinkError):
    """The platform is not configured to run this flow. A 503, never a denial
    aimed at the client."""


def _secret() -> bytes:
    """The state signing key. Derived, never used raw, never Telegram's.

    Deriving rather than using TOKEN_ENCRYPTION_KEY directly means a leak of
    one does not hand over the other, and the domain string means this key
    cannot collide with any other use of the same material.
    """
    raw = (os.getenv("TOKEN_ENCRYPTION_KEY")
           or os.getenv("CTRADER_CLIENT_SECRET") or "").strip()
    if not raw:
        raise LinkConfigError(
            "OAUTH_NOT_CONFIGURED",
            "no key to sign the OAuth state with — set TOKEN_ENCRYPTION_KEY "
            "(or CTRADER_CLIENT_SECRET). Without one a callback cannot be "
            "tied to the account that started it")
    return hmac.new(raw.encode(), _DOMAIN, hashlib.sha256).digest()


def live_allowed() -> bool:
    """Whether a LIVE trading account may be selected at all.

    Two locks, not one: the deployment must say it is production AND the
    operator must have turned live accounts on explicitly. A development box
    that happens to hold real credentials still cannot select a live account,
    which is the case this is actually defending.
    """
    prod = (os.getenv("APP_ENV") or "").strip().lower() in ("prod",
                                                            "production")
    flag = (os.getenv("APEX_ALLOW_LIVE_ACCOUNTS") or "").strip().lower()
    return prod and flag in ("1", "true", "yes", "on")


# ── state ───────────────────────────────────────────────────────────────────
def _sign(nonce, ts):
    payload = f"{nonce}.{ts}".encode()
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()[:32]


def make_state(nonce, ts):
    token = f"{nonce}.{ts}.{_sign(nonce, ts)}"
    return base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")


def parse_state(state, *, now=None):
    """(nonce, ts), or raise. Never returns a user id.

    The user id lives only in the server-side record. A state that carried it
    would let anyone who sees a callback URL learn which account is being
    connected, and would tempt a future caller into trusting it.
    """
    now = time.time() if now is None else now
    if not state or not isinstance(state, str):
        raise LinkError("STATE_MISSING", "the callback carried no state")
    try:
        pad = "=" * (-len(state) % 4)
        token = base64.urlsafe_b64decode(state + pad).decode()
        nonce, ts, sig = token.rsplit(".", 2)
    except Exception:
        raise LinkError("STATE_MALFORMED", "the state is not readable")
    if not hmac.compare_digest(sig, _sign(nonce, ts)):
        raise LinkError("STATE_BAD_SIGNATURE",
                        "the state was not issued by this platform")
    try:
        age = now - int(ts)
    except Exception:
        raise LinkError("STATE_MALFORMED", "the state has no usable timestamp")
    if age > STATE_TTL_S or age < -60:
        raise LinkError("STATE_EXPIRED",
                        "this connection attempt has expired — start again")
    return nonce, int(ts)


# ── storage ─────────────────────────────────────────────────────────────────
def _k_pending(nonce):
    return f"{_store._ns()}:{_store._P}:ctlink:pending:{nonce}"


def _k_conn(user_id):
    return f"{_store._ns()}:{_store._P}:ctrader:{user_id}"


def _k_consume(nonce):
    return f"{_store._ns()}:{_store._P}:ctlink:used:{nonce}"


def _consume_once(nonce) -> bool:
    """True if this caller is the first to consume `nonce`.

    user_store.claim is SET NX, which is the only primitive that works across
    the processes a Render deploy runs side by side. It returns None when
    there is no shared backend — "I could not ask", not "nobody has it" — and
    the caller below falls back to the record's own flag, which coordinates
    within one process only. That is development behaviour and is stated where
    it matters rather than hidden.
    """
    got = user_store.claim(_k_consume(nonce), ttl_s=PENDING_TTL_S)
    return got if got is not None else None


# ── the flow ────────────────────────────────────────────────────────────────
def begin(user_id, *, now=None, redirect_uri=None, authorize_url_fn=None):
    """Start a connection. Returns the URL to send the client to.

    Stores nothing about cTrader yet and touches no existing token: a client
    who abandons the flow is exactly where they started.
    """
    now = time.time() if now is None else now
    user_id = str(user_id)
    if not user_id:
        raise LinkError("NO_USER", "a connection needs a signed-in user")
    uri = redirect_uri or (os.getenv("CTRADER_REDIRECT_URI") or "").strip()
    if not uri:
        raise LinkConfigError(
            "NO_REDIRECT_URI",
            "CTRADER_REDIRECT_URI is not set, so cTrader has nowhere to send "
            "the client back to")
    nonce = secrets.token_urlsafe(32)
    ts = int(now)
    _store._write(_k_pending(nonce), {
        "nonce": nonce, "userId": user_id, "createdAt": ts,
        "status": "awaiting_callback", "code": None, "redirectUri": uri})
    if authorize_url_fn is None:
        from apex.brokers import ctrader as _ct
        authorize_url_fn = _ct.authorize_url
    return {"authorizeUrl": authorize_url_fn(uri, make_state(nonce, ts)),
            "nonce": nonce, "expiresAt": ts + STATE_TTL_S}


def handle_callback(query, *, now=None):
    """What cTrader redirects to. Parks the code; finishes nothing.

    Returns {"nonce": ...} on success. The authorization code is NEVER put in
    the response or in a redirect URL — it stays server-side, so it cannot
    reach a browser history, a referrer header or an access log.
    """
    now = time.time() if now is None else now
    query = query or {}
    if query.get("error"):
        raise LinkError("PROVIDER_REFUSED",
                        f"cTrader refused the authorization "
                        f"({query.get('error')})")
    code = (query.get("code") or "").strip()
    nonce, _ts = parse_state(query.get("state"), now=now)

    claimed = _consume_once(nonce)
    if claimed is False:
        raise LinkError("STATE_REPLAYED",
                        "this connection link has already been used")

    rec = _store._read(_k_pending(nonce))
    if not rec:
        raise LinkError("STATE_UNKNOWN",
                        "this connection attempt is not one this platform "
                        "started, or it has already been cleaned up")
    if claimed is None and rec.get("status") != "awaiting_callback":
        # No shared backend to claim with; the record's own flag is the only
        # guard left. Single-process only — see _consume_once.
        raise LinkError("STATE_REPLAYED",
                        "this connection link has already been used")
    if not code:
        rec["status"] = "failed"
        _store._write(_k_pending(nonce), rec)
        raise LinkError("NO_CODE", "cTrader sent no authorization code")

    rec["code"] = user_store.encrypt_value(code)
    rec["status"] = "awaiting_confirmation"
    rec["callbackAt"] = int(now)
    _store._write(_k_pending(nonce), rec)
    return {"nonce": nonce}


def complete(user_id, nonce, *, now=None, exchanger=None, lister=None):
    """Finish the link, as the signed-in user who started it.

    This is where the account-injection attack in the module docstring dies:
    the session calling this must match the user id recorded by begin().
    """
    now = time.time() if now is None else now
    user_id = str(user_id)
    rec = _store._read(_k_pending(str(nonce or "")))
    if not rec:
        raise LinkError("STATE_UNKNOWN", "no such connection attempt")
    if rec.get("status") != "awaiting_confirmation":
        raise LinkError("NOT_READY",
                        "this connection has not come back from cTrader yet")
    if str(rec.get("userId")) != user_id:
        # Deliberately the same message a stranger's nonce would get: telling
        # the caller that the attempt exists but belongs to someone else would
        # confirm a guess.
        raise LinkError("STATE_UNKNOWN", "no such connection attempt")
    if now - float(rec.get("createdAt") or 0) > PENDING_TTL_S:
        raise LinkError("STATE_EXPIRED",
                        "this connection attempt has expired — start again")

    code = user_store.decrypt_value(rec.get("code") or "")
    if not code:
        raise LinkError("NO_CODE", "the authorization code is missing")

    if exchanger is None or lister is None:
        from apex.brokers import ctrader as _ct
        exchanger = exchanger or _ct.exchange_code
        lister = lister or _ct.list_accounts
    try:
        tok = exchanger(code, rec.get("redirectUri"))
    except Exception as e:  # noqa: BLE001
        raise LinkError("EXCHANGE_FAILED",
                        f"cTrader would not exchange the code ({e})")
    access = tok.get("accessToken") or tok.get("access_token")
    refresh = tok.get("refreshToken") or tok.get("refresh_token")
    if not access:
        raise LinkError("NO_TOKEN",
                        "cTrader returned no access token, so nothing was "
                        "connected")
    try:
        accounts = lister(access) or []
    except Exception as e:  # noqa: BLE001
        raise LinkError("ACCOUNTS_FAILED",
                        f"connected, but the account list could not be read "
                        f"({e})")

    expires_in = tok.get("expiresIn") or tok.get("expires_in")
    conn = {
        "userId": user_id,
        "accessToken": user_store.encrypt_value(access),
        "refreshToken": user_store.encrypt_value(refresh or ""),
        "expiresAt": (float(now) + float(expires_in)) if expires_in else None,
        "connectedAt": float(now),
        "accounts": [{"ctid": a.get("ctid"),
                      "mode": LIVE if a.get("live") else DEMO,
                      "label": a.get("label") or a.get("brokerName") or ""}
                     for a in accounts],
        "selectedCtid": None, "selectedMode": None,
    }
    _store._write(_k_conn(user_id), conn)
    # The pending record is finished with. The code inside it is single-use on
    # cTrader's side anyway, but leaving it lying around encrypted serves
    # nothing and could be replayed against a future bug.
    _store._write(_k_pending(nonce), {"nonce": nonce, "userId": user_id,
                                      "status": "completed", "code": None})
    return public_status(user_id)


def _read_conn(user_id):
    """The connection record, or NOT_CONNECTED.

    "Connected" means a usable access token is held — not that a record
    exists. disconnect() leaves a tombstone behind (so the moment of
    disconnection is auditable), and without this check that tombstone read
    back as a live connection: the dashboard would show the account as
    connected while every call that needed the token failed with something
    obscure about refreshing.
    """
    rec = _store._read(_k_conn(str(user_id)))
    if not rec:
        raise LinkError("NOT_CONNECTED", "no cTrader account is connected")
    if str(rec.get("userId")) != str(user_id):
        raise LinkError("NOT_CONNECTED", "no cTrader account is connected")
    if rec.get("disconnectedAt") or not rec.get("accessToken"):
        raise LinkError("NOT_CONNECTED", "no cTrader account is connected")
    return rec


def public_status(user_id):
    """What may be shown in a browser. Carries no token, ever."""
    try:
        rec = _read_conn(user_id)
    except LinkError:
        return {"connected": False, "accounts": [], "selected": None,
                "liveAllowed": live_allowed()}
    return {
        "connected": True,
        "connectedAt": rec.get("connectedAt"),
        "expiresAt": rec.get("expiresAt"),
        "accounts": rec.get("accounts") or [],
        "selected": ({"ctid": rec.get("selectedCtid"),
                      "mode": rec.get("selectedMode")}
                     if rec.get("selectedCtid") else None),
        "liveAllowed": live_allowed(),
    }


def select_account(user_id, ctid):
    """Choose which connected account this client trades.

    Selecting an account does NOT start anything. It records a choice.
    """
    rec = _read_conn(user_id)
    match = next((a for a in rec.get("accounts") or []
                  if str(a.get("ctid")) == str(ctid)), None)
    if not match:
        raise LinkError("NO_SUCH_ACCOUNT",
                        "that account is not one of the connected ones")
    if match.get("mode") == LIVE and not live_allowed():
        raise LinkError(
            "LIVE_BLOCKED",
            "live accounts are blocked in this environment — connect and "
            "test on a demo account")
    rec["selectedCtid"] = match["ctid"]
    rec["selectedMode"] = match["mode"]
    _store._write(_k_conn(str(user_id)), rec)
    return public_status(user_id)


def access_token_for(user_id, *, now=None, refresher=None, skew_s=120):
    """The decrypted access token, refreshed if it is about to expire.

    Server-side only. Nothing in this module returns it to a caller that
    serialises to a browser — public_status exists precisely so that the
    obvious thing to hand the frontend is the one with no token in it.
    """
    now = time.time() if now is None else now
    rec = _read_conn(user_id)
    exp = rec.get("expiresAt")
    fresh_enough = exp is None or float(exp) - now > skew_s
    if fresh_enough:
        tokv = user_store.decrypt_value(rec.get("accessToken") or "")
        if tokv:
            return tokv
    refresh = user_store.decrypt_value(rec.get("refreshToken") or "")
    if not refresh:
        raise LinkError("REFRESH_UNAVAILABLE",
                        "the access token has expired and there is no refresh "
                        "token — reconnect the account")
    if refresher is None:
        from apex.brokers import ctrader as _ct
        refresher = _ct.refresh_access_token
    try:
        tok = refresher(refresh)
    except Exception as e:  # noqa: BLE001
        raise LinkError("REFRESH_FAILED",
                        f"the access token could not be refreshed ({e})")
    access = tok.get("accessToken") or tok.get("access_token")
    if not access:
        raise LinkError("REFRESH_FAILED",
                        "the refresh returned no access token")
    rec["accessToken"] = user_store.encrypt_value(access)
    new_refresh = tok.get("refreshToken") or tok.get("refresh_token")
    if new_refresh:
        rec["refreshToken"] = user_store.encrypt_value(new_refresh)
    ein = tok.get("expiresIn") or tok.get("expires_in")
    rec["expiresAt"] = (float(now) + float(ein)) if ein else None
    _store._write(_k_conn(str(user_id)), rec)
    return access


def disconnect(user_id):
    """Forget the tokens. Does not revoke them at cTrader — say so plainly
    rather than implying a revocation that never happened."""
    _store._write(_k_conn(str(user_id)),
                  {"userId": str(user_id), "disconnectedAt": time.time()})
    return {"connected": False, "note": "tokens removed from this platform; "
                                        "revoke app access in cTrader too if "
                                        "you want it withdrawn there"}
