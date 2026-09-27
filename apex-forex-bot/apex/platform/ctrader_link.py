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
from apex.platform import linklog as _log
from apex.platform import store as _store

STATE_TTL_S = 600          # 10 minutes to log into cTrader and approve
PENDING_TTL_S = 900        # then 5 more to come back and confirm while signed in
_DOMAIN = b"apex4traders/ctrader-oauth-state/v1"

DEMO = "demo"
LIVE = "live"


class LinkError(RuntimeError):
    """Base for every refusal here. Carries a code the UI can branch on."""

    def __init__(self, code, detail, attempt=None):
        self.code, self.detail = code, detail
        # The id the client may be shown and may quote back. It is a keyed
        # reference to the attempt, not the nonce, so putting it on an error
        # page gives support something to search for and an onlooker nothing.
        self.attempt = attempt
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
    _log.event("begin", attempt=_log.attempt_id(nonce),
               user=_log.user_ref(user_id), redirect=_log.host_of(uri),
               expiresAt=ts + STATE_TTL_S)
    return {"authorizeUrl": authorize_url_fn(uri, make_state(nonce, ts)),
            "nonce": nonce, "expiresAt": ts + STATE_TTL_S}


def _code_digest(code: str) -> str:
    """A comparison handle for an authorization code, not the code itself.

    Reloading the callback page re-sends the identical code and must get the
    same answer rather than a refusal, so the code has to be recognisable
    later. Keeping the code to do that stopped being acceptable once it is
    spent at the callback, so what is kept is a digest keyed with the same
    secret the state signature uses — useless anywhere but here.
    """
    return hmac.new(_secret(), (code or "").encode("utf-8"),
                    hashlib.sha256).hexdigest()


def handle_callback(query, *, now=None, exchanger=None):
    """Spend the code, and make sure every refusal can be traced.

    The stamping happens here rather than at each raise: a refusal that
    escaped without an id would be the one the client is looking at, and a
    diagnostic id that is present only most of the time is not one support can
    rely on.
    """
    ctx = {}
    try:
        return _handle_callback(query, now=now, exchanger=exchanger, ctx=ctx)
    except LinkError as e:
        if getattr(e, "attempt", None) is None:
            e.attempt = ctx.get("attempt")
        raise


def _handle_callback(query, *, now=None, exchanger=None, ctx=None):
    """What cTrader redirects to. Spends the code; binds it to nobody.

    Returns {"nonce": ...} on success. The authorization code is NEVER put in
    the response or in a redirect URL — it stays server-side, so it cannot
    reach a browser history, a referrer header or an access log.

    WHY THE EXCHANGE HAPPENS HERE

    cTrader's authorization code expires ONE MINUTE after it is issued. This
    function used to park the code and leave the exchange to `complete`, which
    runs on a second, human-timed click. That is not a race anyone wins: a
    visitor who reads the page, or who gets rate-limited on the finish button
    and waits for the window to move, comes back to a dead code — and cTrader
    answers ACCESS_DENIED, which names credentials and means nothing of the
    kind. It cost a whole session of chasing a credential that was correct all
    along.

    So the code is spent here, milliseconds after cTrader issues it, and what
    `complete` inherits is the ACCESS TOKEN, which lives about thirty days.
    Nothing about WHOSE account this becomes moves here: the tokens are parked
    in the pending record, and `complete` is still the only thing that may
    attach them to a user, still only for the user who began the attempt.
    """
    now = time.time() if now is None else now
    query = query or {}
    _log.event("callback.received", hasCode=bool(query.get("code")),
               hasError=bool(query.get("error")),
               hasState=bool(query.get("state")))
    if query.get("error"):
        _log.event("callback.provider_refused")
        raise LinkError("PROVIDER_REFUSED",
                        f"cTrader refused the authorization "
                        f"({query.get('error')})")
    code = (query.get("code") or "").strip()
    try:
        nonce, _ts = parse_state(query.get("state"), now=now)
    except LinkError as e:
        _log.event("callback.state", ok=False, code=e.code)
        raise
    attempt = _log.attempt_id(nonce)
    if ctx is not None:
        ctx["attempt"] = attempt
    _log.event("callback.state", ok=True, attempt=attempt)

    claimed = _consume_once(nonce)
    _log.event("callback.claim", attempt=attempt,
               claimed=("none" if claimed is None else bool(claimed)))

    rec = _store._read(_k_pending(nonce))
    _log.event("callback.pending", attempt=attempt, found=bool(rec),
               status=(rec or {}).get("status"))
    if not rec:
        raise LinkError("STATE_UNKNOWN",
                        "this connection attempt is not one this platform "
                        "started, or it has already been cleaned up")

    # Two ways to learn this nonce has been through here before: the shared
    # claim said so (False), or there is no shared backend and the record's own
    # flag says so (None, plus a status that has moved on). Same conclusion, so
    # the same handling — the first version of this fix covered only the first
    # and left the second raising, which a test caught immediately.
    replayed = (claimed is False
                or (claimed is None
                    and rec.get("status") != "awaiting_callback"))

    if replayed:
        # A replay is NOT automatically an attack. Somebody who lands on this
        # page and reloads it re-sends the identical code and state, and the
        # first real connection attempt died exactly there: the visitor saw raw
        # JSON, had no idea what to do, refreshed, and got STATE_REPLAYED with
        # no way forward.
        #
        # The replay that matters is a DIFFERENT code presented against this
        # state, which would swap which broker account gets linked. So the same
        # code parked in the same state is idempotent, and anything else is
        # refused exactly as before.
        already = rec.get("codeDigest") or ""
        same_code = bool(code and already
                         and already == _code_digest(code))
        if rec.get("status") == "awaiting_confirmation" and same_code:
            _log.event("callback.replay", attempt=attempt, outcome="idempotent")
            return {"nonce": nonce}
        # A reload after the exchange itself failed must show what failed, not
        # a refusal about replays. Replacing a real diagnosis with a wrong one
        # is the exact shape of the bug that sent this flow hunting
        # credentials for a day.
        if same_code and rec.get("failureCode"):
            _log.event("callback.replay", attempt=attempt,
                       outcome="repeat_failure", code=rec["failureCode"])
            raise LinkError(rec["failureCode"],
                            rec.get("failureMessage")
                            or "this connection attempt failed")
        _log.event("callback.replay", attempt=attempt, outcome="refused",
                   sameCode=same_code)
        raise LinkError("STATE_REPLAYED",
                        "this connection link has already been used")
    if not code:
        rec["status"] = "failed"
        _store._write(_k_pending(nonce), rec)
        _log.event("callback.no_code", attempt=attempt)
        raise LinkError("NO_CODE", "cTrader sent no authorization code")

    def _failure(err_code, message):
        rec["code"] = None
        rec["codeDigest"] = _code_digest(code)
        rec["status"] = "failed"
        rec["failureCode"] = err_code
        rec["failureMessage"] = message
        _store._write(_k_pending(nonce), rec)
        _log.event("exchange.result", attempt=attempt, ok=False,
                   code=err_code)
        # Returns the error rather than raising it, so the caller's `raise`
        # keeps the traceback at the point of failure.
        return LinkError(err_code, message)

    if exchanger is None:
        from apex.brokers import ctrader as _ct
        exchanger = _ct.exchange_code
    _log.event("exchange.attempt", attempt=attempt,
               redirect=_log.host_of(rec.get("redirectUri")))
    try:
        tok = exchanger(code, rec.get("redirectUri"))
    except Exception as e:  # noqa: BLE001
        raise _failure("EXCHANGE_FAILED",
                    f"cTrader would not exchange the code ({e})") from None
    access = (tok or {}).get("accessToken") or (tok or {}).get("access_token")
    if not access:
        raise _failure("NO_TOKEN",
                    "cTrader returned no access token, so nothing was "
                    "connected")
    refresh = tok.get("refreshToken") or tok.get("refresh_token")
    expires_in = tok.get("expiresIn") or tok.get("expires_in")

    # The code is spent and is not kept. `expiresAt` is measured from HERE,
    # when the token was actually issued, rather than from whenever the
    # visitor gets round to confirming.
    rec["code"] = None
    rec["codeDigest"] = _code_digest(code)
    rec["accessToken"] = user_store.encrypt_value(access)
    rec["refreshToken"] = user_store.encrypt_value(refresh or "")
    rec["expiresAt"] = (float(now) + float(expires_in)) if expires_in else None
    rec["status"] = "awaiting_confirmation"
    rec["callbackAt"] = int(now)
    _store._write(_k_pending(nonce), rec)
    _log.event("exchange.result", attempt=attempt, ok=True,
               hasRefresh=bool(refresh), expiresIn=expires_in)
    _log.event("callback.pending_write", attempt=attempt,
               status="awaiting_confirmation")
    return {"nonce": nonce}


def complete(user_id, nonce, *, now=None, lister=None):
    """Finish the link, stamping every refusal with the attempt it concerns."""
    ctx = {}
    try:
        return _complete(user_id, nonce, now=now, lister=lister, ctx=ctx)
    except LinkError as e:
        if getattr(e, "attempt", None) is None:
            e.attempt = ctx.get("attempt")
        raise


def _complete(user_id, nonce, *, now=None, lister=None, ctx=None):
    """Finish the link, as the signed-in user who started it.

    This is where the account-injection attack in the module docstring dies:
    the session calling this must match the user id recorded by begin().

    The authorization code is already spent — `handle_callback` did that,
    because the code only lives a minute. What this works with is the access
    token, good for about thirty days, so a visitor who takes their time here
    is not punished for it. There is deliberately no `exchanger` parameter any
    more: nothing after the callback may exchange a code.
    """
    now = time.time() if now is None else now
    user_id = str(user_id)
    attempt = _log.attempt_id(nonce)
    if ctx is not None:
        ctx["attempt"] = attempt
    rec = _store._read(_k_pending(str(nonce or "")))
    _log.event("complete.called", attempt=attempt,
               user=_log.user_ref(user_id), found=bool(rec),
               status=(rec or {}).get("status"))
    if not rec:
        raise LinkError("STATE_UNKNOWN", "no such connection attempt")
    if str(rec.get("userId")) != user_id:
        # Logged as a mismatch only. Naming the other party here would put one
        # client's identity in a line reachable by another's support request.
        _log.event("complete.user_match", attempt=attempt, match=False)
        # Deliberately the same message a stranger's nonce would get: telling
        # the caller that the attempt exists but belongs to someone else would
        # confirm a guess. Checked BEFORE the status, which would otherwise
        # confirm the same guess by answering NOT_READY.
        raise LinkError("STATE_UNKNOWN", "no such connection attempt")
    _log.event("complete.user_match", attempt=attempt, match=True)
    if rec.get("status") == "failed" and rec.get("failureCode"):
        # Say what actually went wrong at the callback instead of the
        # uninformative "not back from cTrader yet" below.
        raise LinkError(rec["failureCode"],
                        rec.get("failureMessage")
                        or "this connection attempt failed")
    if rec.get("status") != "awaiting_confirmation":
        raise LinkError("NOT_READY",
                        "this connection has not come back from cTrader yet")
    if now - float(rec.get("createdAt") or 0) > PENDING_TTL_S:
        raise LinkError("STATE_EXPIRED",
                        "this connection attempt has expired — start again")

    # Already encrypted by the callback, and moved across without a decrypt
    # and re-encrypt round trip.
    access_enc = rec.get("accessToken") or ""
    access = user_store.decrypt_value(access_enc)
    if not access:
        raise LinkError("NO_TOKEN",
                        "the access token from the callback is missing")

    if lister is None:
        from apex.brokers import ctrader as _ct
        lister = _ct.list_accounts
    try:
        accounts = lister(access) or []
    except Exception as e:  # noqa: BLE001
        _log.event("accounts.result", attempt=attempt, ok=False)
        raise LinkError("ACCOUNTS_FAILED",
                        f"connected, but the account list could not be read "
                        f"({e})")

    conn = {
        "userId": user_id,
        "accessToken": access_enc,
        "refreshToken": rec.get("refreshToken") or user_store.encrypt_value(""),
        "expiresAt": rec.get("expiresAt"),
        "connectedAt": float(now),
        "accounts": [{"ctid": a.get("ctid"),
                      "mode": LIVE if a.get("live") else DEMO,
                      "label": a.get("label") or a.get("brokerName") or ""}
                     for a in accounts],
        "selectedCtid": None, "selectedMode": None,
    }
    # The account NUMBERS are logged, not just the counts. A ctid is not a
    # secret — the status bar renders it as "#4258018" — and without it the
    # server cannot answer "which account am I on", which is the first
    # question support ever gets. The owner had to ask it, and the log could
    # not say. Ownership is what is confidential here, and that is carried by
    # the user reference, which is keyed and reveals nobody.
    _log.event("accounts.result", attempt=attempt, ok=True,
               count=len(conn["accounts"]),
               demo=sum(1 for a in conn["accounts"] if a["mode"] == DEMO),
               live=sum(1 for a in conn["accounts"] if a["mode"] == LIVE),
               ctids=",".join(str(a["ctid"]) for a in conn["accounts"]))
    _store._write(_k_conn(user_id), conn)
    _log.event("complete.connected", attempt=attempt,
               user=_log.user_ref(user_id), count=len(conn["accounts"]),
               selected=False)
    # The pending record is finished with. The code inside it is single-use on
    # cTrader's side anyway, but leaving it lying around encrypted serves
    # nothing and could be replayed against a future bug.
    _store._write(_k_pending(nonce), {"nonce": nonce, "userId": user_id,
                                      "status": "completed", "code": None,
                                      "accessToken": None,
                                      "refreshToken": None})
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


def get_ctrader_connection(user_id, *, ctid=None, now=None, refresher=None):
    """THE one way anything server-side reads a client's cTrader credentials.

    There is exactly one canonical store for these: this namespace, keyed by
    supabase_user_id. Nothing copies the tokens into the user record, because
    two namespaces holding the same secret means two places to rotate, two to
    revoke and two to leak — and the user record's ctrader_* fields belong to
    the Telegram-era flow, which must not blend with a Supabase identity.

    Returns None when nothing usable is connected, so a caller can tell
    "not connected" from "connected but broken" without catching anything.
    Raises LinkError only when the connection exists and cannot be made
    usable — an expired token whose refresh fails, which the API turns into
    reauth_required rather than an empty list of positions.

    NEVER hand the result to anything that serialises to a browser. It holds a
    live access token. public_status() is the one shaped for that.
    """
    try:
        rec = _read_conn(user_id)
    except LinkError:
        return None
    if ctid is None:
        want_ctid, want_mode = rec.get("selectedCtid"), rec.get("selectedMode")
        if not want_ctid:
            return None
    else:
        # An explicit account must be one of THIS client's. Looking it up in
        # their own record is the ownership check: another client's account
        # id simply is not in the list.
        match = next((a for a in rec.get("accounts") or []
                      if str(a.get("ctid")) == str(ctid)), None)
        if not match:
            raise LinkError("NO_SUCH_ACCOUNT",
                            "that account is not one of the connected ones")
        want_ctid, want_mode = match["ctid"], match["mode"]
    if want_mode == LIVE and not live_allowed():
        # Read-only or not, opening a live account means a live broker
        # session. The environment gate is the same one select_account uses;
        # having two different answers to "may this touch live?" is how one of
        # them ends up being the wrong one.
        raise LinkError("LIVE_BLOCKED",
                        "live accounts are blocked in this environment")
    token = access_token_for(user_id, now=now, refresher=refresher)
    return {"userId": str(user_id), "accessToken": token,
            "ctid": want_ctid, "mode": want_mode,
            "expiresAt": rec.get("expiresAt")}


def disconnect(user_id):
    """Forget the tokens. Does not revoke them at cTrader — say so plainly
    rather than implying a revocation that never happened."""
    _store._write(_k_conn(str(user_id)),
                  {"userId": str(user_id), "disconnectedAt": time.time()})
    return {"connected": False, "note": "tokens removed from this platform; "
                                        "revoke app access in cTrader too if "
                                        "you want it withdrawn there"}
