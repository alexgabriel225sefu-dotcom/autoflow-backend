"""Linking a cTrader account to an Apex4Traders account. No Telegram anywhere.

THE ATTACK THIS FLOW IS SHAPED AROUND

The obvious design — sign the user id into `state`, and on callback bind the
tokens to whoever that state names — has a hole that is easy to miss. An
attacker starts a connect flow for THEIR OWN Apex account, takes the authorize
link, and gets a victim to open it. The victim logs into cTrader and approves.
The callback arrives carrying the ATTACKER's user id, and the VICTIM's live
trading account is now bound to the attacker's dashboard.

`state` cannot close that on its own, because the attacker's state is
perfectly valid — it is their state. So the callback here exchanges the code
immediately, parks the encrypted token server-side and hands the callback page
a nonce plus a one-time finish ticket. The link is completed by an
authenticated POST, and the session making that call must be the same user
that began the flow. A different browser does not receive the finish ticket.

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
from apex.platform import plans as _plans
from apex.platform import store as _store

STATE_TTL_S = 600          # 10 minutes to log into cTrader and approve
PENDING_TTL_S = 900        # then 5 more to come back and confirm while signed in
_DOMAIN = b"apex4traders/ctrader-oauth-state/v1"

DEMO = "demo"
LIVE = "live"
# The third value, and it lives here because this is where the mode comes
# from. `entitlement` re-exports it rather than defining its own, so there is
# one spelling of "the broker would not confirm it" in the product.
UNKNOWN = "unknown"
MODES = (DEMO, LIVE, UNKNOWN)


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
    the processes a Render deploy runs side by side. A failed shared claim
    refuses; it must never fall back to process-local coordination. Only a
    development process with no shared backend uses the record's own flag.
    """
    got = user_store.claim(_k_consume(nonce), ttl_s=PENDING_TTL_S)
    if got is None and user_store._USE_REDIS:
        raise _storage_failure("claim", nonce)
    return got


def _storage_failure(operation, nonce=None):
    attempt = _log.attempt_id(nonce) if nonce else None
    _log.event("storage.failed", operation=operation, attempt=attempt,
               code="STORE_UNAVAILABLE")
    return LinkConfigError(
        "STORE_UNAVAILABLE",
        "The connection store could not confirm this step. Try again when "
        "the service recovers. If authorization at cTrader completed but "
        "could not be saved, start a new connection.", attempt=attempt)


def _pending(nonce):
    try:
        return _store._read_strict(_k_pending(nonce))
    except (user_store.StoreUnavailable, ValueError, OSError):
        raise _storage_failure("read", nonce) from None


def _save_link(key, doc, *, nonce=None):
    """Never report a saved connection or consume pending tokens on write loss.

    Storage errors may contain the full key, including a pending nonce. Only
    the operation and a keyed attempt reference may leave this boundary.
    """
    try:
        back = _store._write_strict(key, doc)
        if back != doc:
            raise user_store.StoreUnavailable("connection readback mismatch")
    except (user_store.StoreUnavailable, ValueError, OSError):
        raise _storage_failure("write", nonce or doc.get("nonce")) from None


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
    _save_link(_k_pending(nonce), {
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


def _callback_result(rec):
    """Return the callback hand-off without exposing the parked token."""
    proof = user_store.decrypt_value(rec.get("finishToken") or "")
    out = {"nonce": rec.get("nonce")}
    if proof:
        out["finishToken"] = proof
    return out


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

    rec = _pending(nonce)
    _log.event("callback.pending", attempt=attempt, found=bool(rec),
               status=(rec or {}).get("status"))
    if not rec:
        raise LinkError("STATE_UNKNOWN",
                        "this connection attempt is not one this platform "
                        "started, or it has already been cleaned up")

    # Read before claiming: an unavailable store must not burn a valid state.
    claimed = _consume_once(nonce)
    _log.event("callback.claim", attempt=attempt,
               claimed=("none" if claimed is None else bool(claimed)))

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
            return _callback_result(rec)
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
        _save_link(_k_pending(nonce), rec)
        _log.event("callback.no_code", attempt=attempt)
        raise LinkError("NO_CODE", "cTrader sent no authorization code")

    def _failure(err_code, message):
        rec["code"] = None
        rec["codeDigest"] = _code_digest(code)
        rec["status"] = "failed"
        rec["failureCode"] = err_code
        rec["failureMessage"] = message
        _save_link(_k_pending(nonce), rec)
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
    # This is delivered only in the callback browser's page. The nonce is
    # intentionally public, but this one-time hand-off is what prevents a
    # person who started a flow from completing it after another browser
    # approved the broker account.
    rec["finishToken"] = user_store.encrypt_value(
        secrets.token_urlsafe(32))
    _save_link(_k_pending(nonce), rec)
    _log.event("exchange.result", attempt=attempt, ok=True,
               hasRefresh=bool(refresh), expiresIn=expires_in)
    _log.event("callback.pending_write", attempt=attempt,
               status="awaiting_confirmation")
    return _callback_result(rec)


def complete(user_id, nonce, *, proof=None, now=None, lister=None):
    """Finish the link, stamping every refusal with the attempt it concerns."""
    ctx = {}
    try:
        return _complete(user_id, nonce, proof=proof, now=now,
                         lister=lister, ctx=ctx)
    except LinkError as e:
        if getattr(e, "attempt", None) is None:
            e.attempt = ctx.get("attempt")
        raise


def _complete(user_id, nonce, *, proof=None, now=None, lister=None, ctx=None):
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
    if not nonce:
        _log.event("complete.no_pending", user=_log.user_ref(user_id))
        raise LinkError("NO_PENDING",
                        "there is no connection attempt to finish")
    attempt = _log.attempt_id(nonce)
    if ctx is not None:
        ctx["attempt"] = attempt
    rec = _pending(str(nonce))
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
    if rec.get("status") == "completed":
        # Already done, by this same user. Answer with the real state rather
        # than an error about it.
        #
        # cTrader opens in a NEW TAB, so this flow routinely ends with two
        # tabs open: the connection finishes in one, and the other keeps its
        # own sessionStorage, its own stale status, and a button offering to
        # finish something already finished. Pressing it used to answer
        # NOT_READY — "this connection has not come back from cTrader yet" —
        # about an attempt that had come back, been exchanged and been
        # written. Untrue, and read by the owner as the feature being broken.
        #
        # Safe because it is reached only after the userId check above, which
        # is the same gate that stops account injection. A stranger with a
        # guessed nonce gets STATE_UNKNOWN and never arrives here.
        _log.event("complete.already_done", attempt=attempt,
                   user=_log.user_ref(user_id))
        return public_status(user_id)
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

    expected = user_store.decrypt_value(rec.get("finishToken") or "")
    # The public API requires proof before it calls this function. Keeping the
    # argument optional here preserves trusted in-process maintenance callers;
    # an external request can never reach this branch without the API check.
    if proof is not None and expected and (
            not hmac.compare_digest(str(proof), expected)):
        raise LinkError("BROWSER_BINDING_INVALID",
                        "finish this connection in the browser that returned "
                        "from cTrader")

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
    _save_link(_k_conn(user_id), conn, nonce=nonce)
    # The pending record is finished with. The code inside it is single-use on
    # cTrader's side anyway, but leaving it lying around encrypted serves
    # nothing and could be replayed against a future bug.
    _save_link(_k_pending(nonce), {"nonce": nonce, "userId": user_id,
                                      "status": "completed", "code": None,
                                      "accessToken": None,
                                      "refreshToken": None})
    _log.event("complete.connected", attempt=attempt,
               user=_log.user_ref(user_id), count=len(conn["accounts"]),
               selected=False)
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
    rec = _store._read_strict(_k_conn(str(user_id)))
    if not rec:
        raise LinkError("NOT_CONNECTED", "no cTrader account is connected")
    if str(rec.get("userId")) != str(user_id):
        raise LinkError("NOT_CONNECTED", "no cTrader account is connected")
    if rec.get("disconnectedAt") or not rec.get("accessToken"):
        raise LinkError("NOT_CONNECTED", "no cTrader account is connected")
    return rec


def is_platform_account(user_id) -> bool:
    """Does this user trade through the PLATFORM, or only the legacy bot?

    Exists to be answerable without importing anything heavy. `gates.py` asks
    it before it imports `live_execution`, and that ordering is load-bearing:
    `audit.py` refuses AT IMPORT on a process with no shared backend — which
    is correct of it, §7 allows no live order without a trail — so importing
    the live path to discover "this is not a platform account" took the whole
    legacy engine down with it on any deployment without Redis.

    Raises nothing for an ordinary absent connection, because "no" is an
    answer. A store that cannot be read is not an answer and does raise, so
    the caller can fail closed rather than read a fault as a no.
    """
    try:
        _read_conn(str(user_id))
        return True
    except LinkError:
        return False


def selected_mode(user_id):
    """Which environment this client's SELECTED account trades in, or None.

    None means "not a platform account" — there is no connection to read a
    mode from. Every other answer is one of MODES.

    WHY THE ORDER GATE NEEDS THIS, AND WHY IT IS HERE

    `gates._live` answers "is real money at stake?" from the user record's
    `paper` flag, which only the legacy Telegram path ever writes. A platform
    client's record has no such flag, so that question answered "no" for
    every platform account — including one trading a LIVE cTrader account.
    Every gate behind it (the release switch, the paid plan, the mode the
    broker confirms, the order rate limit, the audit trail) was therefore
    unreachable for exactly the accounts it was written to protect.

    Like `is_platform_account`, this must be answerable WITHOUT importing the
    live path: `audit.py` refuses at import without a shared backend, so the
    gate has to learn what kind of account this is before it may import
    anything that could refuse. That ordering is load-bearing, not tidiness.

    A missing `selectedMode` reads as UNKNOWN rather than DEMO. An account
    nobody has confirmed the environment of is not evidence of safety, and
    the caller treats anything that is not DEMO as real money.
    """
    try:
        rec = _read_conn(str(user_id))
    except LinkError:
        return None
    mode = str(rec.get("selectedMode") or "").strip().lower()
    return mode if mode in MODES else UNKNOWN


def public_status(user_id):
    """What may be shown in a browser. Carries no token, ever.

    `connected: False` here is a claim about the reader's account, and the
    UI prints it as the sentence "no cTrader account is connected". So only
    a LinkError produces it — a store that could not be asked raises
    StoreUnavailable through, and the API answers 503, for the same reason
    an unreachable auth backend is never a 401: "we cannot check" and "you
    have nothing" are different answers and only one of them is true.
    """
    try:
        rec = _read_conn(user_id)
    except LinkError:
        return {"connected": False, "accounts": [], "selected": None,
                "liveAllowed": live_allowed(),
                "accountPlan": _account_plan(user_id, [])}
    return {
        "connected": True,
        "connectedAt": rec.get("connectedAt"),
        "expiresAt": rec.get("expiresAt"),
        "accounts": rec.get("accounts") or [],
        "selected": ({"ctid": rec.get("selectedCtid"),
                      "mode": rec.get("selectedMode")}
                     if rec.get("selectedCtid") else None),
        "liveAllowed": live_allowed(),
        "accountPlan": _account_plan(user_id, rec.get("tradedCtids") or []),
    }


def _account_plan(user_id, traded):
    """How many real-money accounts this client may trade, and where more
    come from.

    Carried on the ACCOUNTS read and nowhere else. This is the screen a client
    is on when they are managing accounts, so it is the screen where "how do I
    add another" is a question somebody is actually asking — the dashboard and
    onboarding are not.

    `signup` arrives with its disclosure attached and never without it:
    `referral.broker_signup()` is the only accessor and it returns the two
    together. Demo accounts are not limited, so none of this constrains them.
    """
    from apex.platform import plans as _plans
    from apex.platform import referral as _referral
    allowance = _plans.account_allowance(str(user_id))
    used = len([c for c in traded if c])
    return {
        "realMoneyAllowance": allowance,
        "realMoneyUsed": used,
        "demoUnlimited": True,
        "confirmed": _referral.is_confirmed(str(user_id)),
        # Offered while there is something to act on. A client whose broker
        # account is already confirmed has the larger allowance and no reason
        # to be sent to the link again.
        "signup": (None if _referral.is_confirmed(str(user_id))
                   else _referral.broker_signup()),
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

    # How many distinct REAL-MONEY accounts this client trades here.
    #
    # WHY LIVE ONLY. The allowance exists to govern clients who run several
    # accounts through the platform, and the revenue behind it — introducing
    # broker rebates — is paid on traded volume, which a demo account does not
    # produce. Counting demo accounts would therefore charge nothing extra and
    # would hit the most ordinary client there is: one cTrader login carrying a
    # demo and a live account, which is what every broker hands out. A trial
    # user switching to their demo and being told they are over a limit is a
    # support ticket that earns nobody anything.
    #
    # So demo accounts are unlimited — they are the free trial — and the
    # allowance applies where the money and the rebate both are.
    traded = [str(c) for c in (rec.get("tradedCtids") or [])]
    wanted = str(match["ctid"])
    counted = match.get("mode") == LIVE

    if counted:
        # Seeded from the current selection for a connection made before this
        # existed, so a client who already chose an account is not told they
        # are over a limit that did not exist when they chose it.
        #
        # The seed happens BEFORE the membership test, not after. Seeding
        # afterwards put the account being re-selected into the list and then
        # measured the list as full, so the one client this seed exists to
        # protect was the one it locked out.
        if not traded and rec.get("selectedCtid") is not None \
                and rec.get("selectedMode") == LIVE:
            traded = [str(rec["selectedCtid"])]

    if counted and wanted not in traded:
        allowance = _plans.account_allowance(str(user_id))
        if len(traded) >= allowance:
            raise LinkError(
                "ACCOUNT_LIMIT",
                f"this plan covers {allowance} real-money trading account"
                f"{'' if allowance == 1 else 's'} and {len(traded)} "
                f"{'is' if len(traded) == 1 else 'are'} already in use. "
                f"Demo accounts are not limited. Additional real-money "
                f"accounts are available once your broker account is "
                f"confirmed under the referral programme — the accounts you "
                f"already use are unaffected.")
        traded.append(wanted)

    rec["tradedCtids"] = traded
    rec["selectedCtid"] = match["ctid"]
    rec["selectedMode"] = match["mode"]
    _save_link(_k_conn(str(user_id)), rec)
    return public_status(user_id)


def verify_selected_mode(user_id, *, lister=None, now=None, refresher=None):
    """Ask the BROKER what the selected account is, right now.

    §3 of docs/LIVE_EXECUTION_SPECIFICATION.md. `select_account` records the
    mode cTrader reported when the account was linked, and for demo that is
    enough: being wrong means refusing a practice account, which costs
    nothing. For a live account it is not enough — a link record can be months
    old, and the question "is this real money?" must be answered by the party
    that knows, at the moment it matters.

    Returns:
        {"mode": demo|live|unknown, "verified": bool, "recorded": ...,
         "changed": bool, "ctid": ..., "reason": str|None, "at": float}

    `unknown` NEVER folds into demo or live. Three values, and the third means
    "the broker did not confirm it" — which a caller must treat as a refusal,
    not as a default. Every failure path below produces `unknown` rather than
    falling back to the stored value, because falling back to the stored value
    is exactly what this function exists to stop doing.

    It does not write the mode. `select_account` remains the only writer, and
    a test asserts that. What this reports is a FACT ABOUT NOW, and a fact
    that disagrees with the record is for the caller to act on — §3.4 says
    stop and notify, never adapt.
    """
    stamp = float(now if now is not None else time.time())
    # Never raises. A function whose job is to return one of three values
    # cannot be one a caller has to wrap in try/except to find out which —
    # that shape is how "no account" ends up handled in the same branch as
    # "the broker said live".
    try:
        rec = _read_conn(str(user_id))
    except Exception:                                       # noqa: BLE001
        rec = None
    recorded = (rec or {}).get("selectedMode")
    ctid = (rec or {}).get("selectedCtid")

    def _out(mode, reason=None, verified=False):
        return {"mode": mode, "verified": verified, "recorded": recorded,
                "ctid": ctid, "at": stamp, "reason": reason,
                # A change is only meaningful when the broker actually
                # answered. An unverified read differing from the record is
                # not a mode change, it is a failed read, and reporting it as
                # a change would stop a loop over a network blip.
                "changed": bool(verified and recorded
                                and mode != recorded)}

    if not rec:
        return _out(UNKNOWN, "no cTrader account is connected")
    if ctid is None:
        return _out(UNKNOWN, "no account is selected")

    try:
        access = access_token_for(user_id, now=stamp, refresher=refresher)
    except LinkError as e:
        return _out(UNKNOWN, f"the broker session could not be used ({e.code})")
    except Exception as e:                                  # noqa: BLE001
        return _out(UNKNOWN, f"the broker session could not be used "
                             f"({type(e).__name__})")

    if lister is None:
        from apex.brokers import ctrader as _ct
        lister = _ct.list_accounts
    try:
        accounts = lister(access) or []
    except Exception as e:                                  # noqa: BLE001
        return _out(UNKNOWN, f"the broker did not answer ({type(e).__name__})")

    match = next((a for a in accounts if str(a.get("ctid")) == str(ctid)), None)
    if match is None:
        # The account is gone from the broker's own list. Not a mode change —
        # there is no mode to have. Anything still running against it is
        # running against something that is not there.
        return _out(UNKNOWN,
                    "the selected account is no longer on the broker's list")
    if "live" not in match:
        # The flag is the whole answer. An account record without it tells us
        # nothing, and nothing is `unknown`.
        return _out(UNKNOWN, "the broker did not say whether it is live")
    return _out(LIVE if match.get("live") else DEMO, verified=True)


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
    _save_link(_k_conn(str(user_id)), rec)
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
    _save_link(_k_conn(str(user_id)),
                  {"userId": str(user_id), "disconnectedAt": time.time()})
    return {"connected": False, "note": "tokens removed from this platform; "
                                        "revoke app access in cTrader too if "
                                        "you want it withdrawn there"}
