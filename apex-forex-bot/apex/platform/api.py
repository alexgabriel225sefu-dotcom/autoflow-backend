"""The Apex4Traders platform API. Transport-free on purpose.

`handle()` takes a method, a path, headers and a body, and returns a status
and a dict. It never touches a socket, so every endpoint below is tested
directly rather than through a server, and mounting it costs bot.py one line.

THE RULES EVERY ENDPOINT OBEYS, ENFORCED IN ONE PLACE

  authenticated   no route is reachable without a verified session
  owned           every read and write is scoped to the caller's user id by
                  the storage key itself (see store.py)
  licensed        anything that could lead to an order needs a live licence
  honest          a capability that is not wired yet answers 501 UNSUPPORTED.
                  It never answers 200 with an empty list, because an empty
                  list is a claim — "you have no positions" — and this
                  platform does not yet know whether that is true.

WHY REFUSALS CARRY A CODE

The UI has to say different sentences for "your licence expired", "confirm
your email" and "we could not reach the login service", and those sentences
lead to different buttons. A single 403 with prose would force the frontend to
match on English text.
"""

import json
import re

from apex.platform import conditions as _cond
from apex.platform import approvals as _appr
from apex.platform import automation as _auto
from apex.platform import billing as _billing
from apex.platform import broker_read as _read
from apex.platform import position_close as _close
from apex.platform import ctrader_link as _link
from apex.platform import emergency as _emerg
from apex.platform import emergency_stop as _panic
from apex.platform import engine_config as _ecfg
from apex.platform import entitlement as _ent
from apex.platform import health as _health
from apex.platform import identity as _id
from apex.platform import journal_store as _jstore
from apex.platform import notifications as _notify
from apex.platform import performance_read as _perfread
from apex.platform import preview as _preview
from apex.platform import linklog as _log
from apex.platform import ratelimit as _rl
from apex.platform import licence as _lic
from apex.platform import live_gate as _live_gate
from apex.platform import plans as _plans
from apex.platform import referral as _referral
from apex.platform import ruledoc as _rd
from apex.platform import store as _store
from apex.platform import waitlist as _wait
from apex.platform.safe_errors import message as _safe_message
from apex import user_store as _ustore

PREFIX = "/api/v1/"

# Capabilities that arrive with the broker phase. Listed explicitly so the
# frontend can grey a button out instead of discovering a 404, and so that
# nothing here quietly returns a plausible empty answer in the meantime.
# Everything here is built. The map stays because the next capability to be
# wired will use it, and because an endpoint that answers 501 by design is
# better declared in one place than scattered through the dispatcher.
_NOT_YET = {}


def _err(status, code, message, **extra):
    # A key whose value is None is worse than an absent key: the UI would
    # render "diagnosticId: null" and a person would read it out.
    body = {"ok": False, "error": dict({"code": code, "message": message},
                                       **{k: v for k, v in extra.items()
                                          if v is not None})}
    return status, body


def _safe_error(exc):
    return _safe_message(exc)


def _ok(payload=None, **kw):
    return 200, dict({"ok": True}, **dict(payload or {}, **kw))


def _body(raw):
    if not raw:
        return {}
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    try:
        parsed = json.loads(raw)
    except Exception:
        raise ValueError("the request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise ValueError("the request body must be a JSON object")
    return parsed


def _start_trial_if_new(principal):
    """Begin the free demo trial the first time a confirmed account is seen.

    WHY IT IS HERE. There is no sign-up hook to hang this on — Supabase owns
    registration and the platform first learns of an account when it presents
    a token. `_authenticate` is the one place every authenticated request
    resolves a principal, so it is the only place that sees every client
    exactly once-or-more and never zero times.

    Without this the trial would exist in `plans.py` and be granted to nobody,
    and since demo automation now requires an ACTIVE licence, no client could
    start anything at all.

    Three properties make calling it on every request correct rather than
    merely cheap:

      * `plans.start_trial` is idempotent and NEVER extends an expiry, so a
        client who signs in on day thirteen still has one day left.
      * it refuses to write over any plan already on file, so a paying client
        is never downgraded to a trial by signing in.
      * UNVERIFIED addresses are skipped. Otherwise the fourteen days would
        start ticking while somebody who has not yet clicked a confirmation
        link cannot use the product, and they would arrive to a shorter trial
        than they were promised.

    A failure here never fails the request. The automation gate refuses later
    with a message that names the missing trial, which is a better outcome
    than a signed-in client seeing a 500 from a store hiccup.
    """
    if not getattr(principal, "email_verified", False):
        return
    try:
        _plans.start_trial(principal.user_id)
    except Exception as e:                                   # noqa: BLE001
        print(f"[API] could not start the demo trial for "
              f"{principal.user_id} ({type(e).__name__}) — the automation "
              f"gate will report it")


def _authenticate(headers, *, fresh=False):
    token = _id.bearer_token((headers or {}).get("Authorization")
                             or (headers or {}).get("authorization"))
    if not token:
        raise _id.AuthFailed("this endpoint needs a signed-in session")
    principal = _id.verify_token(token, fresh=fresh)
    _start_trial_if_new(principal)
    return principal


# ── routes ──────────────────────────────────────────────────────────────────
_NOTIFY_RE = re.compile(r"^notifications/([A-Za-z0-9_-]{1,64})/read$")
_JOURNAL_RE = re.compile(r"^journal/([A-Za-z0-9_-]{1,64})$")
_ACCOUNT_RE = re.compile(
    r"^accounts/([A-Za-z0-9_-]{1,64})(?:/(positions|orders|deals|candles))?$")
_POSITION_CLOSE_RE = re.compile(
    r"^accounts/([A-Za-z0-9_-]{1,64})/positions/([A-Za-z0-9_-]{1,64})/close$")
_RULE_RE = re.compile(r"^rules/([A-Za-z0-9_-]{1,64})$")
_RULE_ACTION_RE = re.compile(
    r"^rules/([A-Za-z0-9_-]{1,64})/(validate|activate|pause|resume|archive"
    r"|version|preview)$")
_RULE_VERSION_RE = re.compile(
    r"^rules/([A-Za-z0-9_-]{1,64})/versions/(\d{1,9})$")


def _num(value, field):
    """A number from a query string, or a refusal. Never a silent default.

    A caller who writes ?limit=abc has a bug, and answering with the default
    50 hides it behind a page that looks right.
    """
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number, got {value!r}")


def _query(path):
    """The query string as a flat dict. Only the callback needs it."""
    from urllib.parse import parse_qs, urlparse
    return {k: v[0] for k, v in
            parse_qs(urlparse(path).query or "").items()}


def handle(method, path, headers=None, body=None, *, client_key=None):
    """Every request, with the broker-link ones written down.

    WHY THE LOGGING IS HERE AND NOT INSIDE

    `_handle` refuses from about twenty places — the rate limiter before
    dispatch, a dozen exception handlers after it — and a log line added to
    each is a log line that the next branch forgets. Wrapping the single exit
    means a refusal cannot escape unrecorded, which is the property that
    matters: the interesting failures are exactly the ones nobody thought to
    instrument.

    Only the cTrader routes are logged. This is a diagnostic for one flow, not
    an access log for the platform, and logging every route would bury the
    handful of lines that answer "what happened to this connection attempt".
    """
    # LAST RESORT, SO NO EXCEPTION CAN EVER PRODUCE A DEAD SOCKET.
    #
    # `_handle`'s clause list is long and still finite: it ended at
    # ValueError, and `emergency.Halted` — a RuntimeError — walked straight
    # past it. Neither transport guards the call either, so the failure mode
    # was not a 500 but NO RESPONSE: the connection closed with no status
    # line and every client read it as "Failed to fetch".
    #
    # A 500 is a bad answer. No answer is a worse one, because it is
    # indistinguishable from the network being down and tells the client to
    # go and check their wifi. This turns the whole class into one honest
    # refusal, and prints the real cause where an operator can find it.
    #
    # Deliberately does NOT swallow the None that means "this path is not
    # ours": that return value is how this module mounts inside another
    # server, and turning it into a 500 would answer for routes it does not
    # own.
    try:
        result = _handle(method, path, headers=headers, body=body,
                         client_key=client_key)
    except Exception as e:                                   # noqa: BLE001
        from apex import redact as _redact
        print(f"[API] unhandled {type(e).__name__} on "
              f"{(method or 'GET').upper()} {path}: {_redact.scrub(str(e))[:300]}")
        # Says nothing about whether the request took effect, because this
        # branch cannot know: the exception may have been raised after a
        # partial write. Claiming "nothing was changed" would be the exact
        # habit this codebase keeps paying for — a screen asserting a state
        # it has not verified. So it names what to check instead.
        return _err(500, "INTERNAL_ERROR",
                    "something went wrong on our side handling this "
                    "request, and we cannot tell whether it took effect. "
                    "Check the screen again before retrying. The fault is "
                    "ours and has been logged.")
    try:
        route = (path or "")[len(PREFIX):].split("?", 1)[0].strip("/") \
            if (path or "").startswith(PREFIX) else ""
        if route.startswith("ctrader/") and result:
            status, body_out = result
            err = (body_out or {}).get("error") or {}
            _log.event("api.response", method=(method or "GET").upper(),
                       route=route, status=status,
                       code=err.get("code"),
                       attempt=err.get("diagnosticId"),
                       retryAfterSec=err.get("retryAfterSec"))
    except Exception:  # noqa: BLE001
        pass
    return result


def _handle(method, path, headers=None, body=None, *, client_key=None):
    """(status, payload), or None when the path is not ours.

    `client_key` is the caller's network identity, supplied by the transport
    because only the transport knows it. It is used for rate limiting, and
    only as a fallback: an authenticated request is limited per user so one
    client behind a shared address cannot lock out another.

    Returning None rather than a 404 lets this mount inside an existing server
    whose other routes must keep working.
    """
    if not path or not path.startswith(PREFIX):
        return None
    route = path[len(PREFIX):].split("?", 1)[0].strip("/")

    # Before anything else, including authentication. A limiter that runs
    # after the session is verified still pays for verifying the session, and
    # the endpoints worth protecting — candles against the broker's shared
    # historical budget, preview against the evaluator — are exactly the ones
    # a loop would reach.
    allowed, bucket, retry_after = _rl.check(
        method, route, client_key=client_key,
        auth_header=(headers or {}).get("Authorization")
        or (headers or {}).get("authorization"))
    if not allowed:
        return _rl.refusal(bucket, retry_after)
    method = (method or "GET").upper()
    try:
        return _dispatch(method, route, headers or {}, body,
                         _query(path))
    except _id.AuthFailed as e:
        return _err(401, "AUTH_REQUIRED", _safe_error(e))
    except _id.AuthUnavailable as e:
        # 503, never 401. The client's session may be perfectly good; it is
        # the platform that cannot check right now, and telling them their
        # login is invalid would be a lie that also hides the real fault.
        return _err(503, "AUTH_UNAVAILABLE", _safe_error(e))
    except _ustore.StoreUnavailable as e:
        # 503, never a 200 that says the account has nothing. The record may
        # be perfectly intact; it is the store that did not answer, and
        # rendering that as "no cTrader account is connected" tells the
        # account's owner a falsehood about their own account while hiding
        # the real fault. Same reasoning as AUTH_UNAVAILABLE above.
        return _err(503, "STORE_UNAVAILABLE", _safe_error(e))
    except _link.LinkConfigError as e:
        # The platform is misconfigured, which is not the client's fault and
        # must not read as one. 503, like every other "we cannot", never 400.
        return _err(503, e.code, _safe_error(e.detail),
                    diagnosticId=getattr(e, "attempt", None))
    except _link.LinkError as e:
        # diagnosticId is a keyed reference to the attempt, safe to show and
        # safe to quote: it identifies the attempt in the logs and reveals
        # neither the nonce it derives from nor who made it.
        #
        # ACCOUNT_LIMIT is the ONE place the broker signup link belongs, and
        # the reason is the client's state rather than convenience: this
        # refusal is raised because they just tried to add another real-money
        # account. Nobody else is asking. Putting the link on the dashboard,
        # in onboarding, or in the general referral state would show it to
        # every client including the ones who want one account — which reads
        # as a nudge to open accounts they do not need, and earns nothing.
        #
        # It arrives with its disclosure attached, because `broker_signup()`
        # is the only accessor and it returns the two together.
        signup = (_referral.broker_signup()
                  if e.code == "ACCOUNT_LIMIT" else None)
        return _err(400, e.code, _safe_error(e.detail),
                    diagnosticId=getattr(e, "attempt", None),
                    brokerSignup=signup)
    except _lic.LicenceRequired as e:
        return _err(402, "LICENCE_REQUIRED", _safe_error(e), licenceState=e.state)
    except _ent.NotEntitled as e:
        # A WITHDRAWN licence keeps the 402 the client already understands,
        # so support can withdraw access without the UI needing a new branch.
        # Everything else is a 409: the request was understood and the state
        # of the account refuses it, which is not a payment problem and must
        # not be rendered as one. Sending somebody to a checkout because their
        # broker session expired would be the worst possible answer.
        if e.code == "LICENCE_REVOKED":
            return _err(402, "LICENCE_REQUIRED", _safe_error(e), licenceState=e.state)
        return _err(409, e.code, _safe_error(e))
    except _auto.AutomationRefused as e:
        return _err(409, e.code, _safe_error(e.detail))
    except _emerg.Halted as e:
        # THE ONE REFUSAL THE CLIENT COULD NOT READ, AND IT IS THE MOST
        # IMPORTANT ONE IN THE PRODUCT.
        #
        # `Halted` is a RuntimeError and the clause list below ended at
        # ValueError, so a start refused by the emergency switch escaped
        # `_handle` entirely. Nothing above caught it either: `handle` called
        # `_handle` unguarded and both transports call `handle` unguarded, so
        # the socket closed with no status line and the browser showed
        # "Failed to fetch". An operator pulls the emergency stop and every
        # client sees a network error.
        #
        # 503, not 409. A halt is not a conflict with the request — the
        # request was fine and the service is deliberately stopped. That
        # distinction is what tells a client this is not theirs to fix.
        return _err(503, e.code, _safe_error(e), scope=e.scope)
    except _preview.PreviewRefused as e:
        # INSUFFICIENT_DATA is a 422: the request was understood and the data
        # to answer it was not there. A 400 would say the client malformed it.
        return _err(422 if e.code == "INSUFFICIENT_DATA" else 400,
                    e.code, _safe_error(e.detail))
    except _close.CloseRefused as e:
        return _err(e.status, e.code, _safe_error(e.detail))
    except _close.CloseUnknown as e:
        return _err(503, "CLOSE_UNKNOWN", _safe_error(e))
    except _notify.NotificationNotFound:
        return _err(404, "NOT_FOUND", "no such notification")
    except _jstore.JournalNotFound:
        return _err(404, "NOT_FOUND", "no such journal entry")
    except _store.NotFound:
        return _err(404, "NOT_FOUND", "no such rule")
    except _store.OwnershipViolation:
        # Only reachable through a key-construction bug. Loud, and never
        # rendered as a normal "not found".
        return _err(500, "OWNERSHIP_VIOLATION",
                    "a stored document failed its ownership check")
    except _rd.RuleDocInvalid as e:
        return _err(422, "RULE_INVALID", "this rule cannot be activated",
                    problems=e.problems)
    except ValueError as e:
        return _err(400, "BAD_REQUEST", _safe_error(e))


def _dispatch(method, route, headers, body, query=None):
    head = route.split("/", 1)[0]
    if head in _NOT_YET:
        _authenticate(headers)          # still refuse anonymous callers first
        return _err(501, "UNSUPPORTED",
                    f"{_NOT_YET[head]} is not connected yet",
                    capability=head)

    # ── cTrader linking ─────────────────────────────────────────────────
    # THE UNAUTHENTICATED ROUTES, ALL OF THEM, IN ONE PLACE
    #
    # Four, and no more. Kept together rather than discovered one at a time,
    # because "which routes need no session" is the first question an auditor
    # asks and the one a scattered answer gets wrong. This comment once
    # claimed there was only one while sitting directly above the second.
    #
    #   billing/webhook   the provider's server has no session. Safe by
    #                     signature: the body is acted on only when it
    #                     verifies against the webhook secret.
    #   waitlist          a visitor asking to be told when access opens has
    #                     no session by definition. The only WRITE of the
    #                     four: tight rate-limit bucket of its own, one
    #                     field stored, nothing returned.
    #   billing/offer     a visitor reading the price has no session, and the
    #                     price is the public fact on the page. Read-only,
    #                     and public_offer() carries no provider secret.
    #   ctrader/callback  cTrader redirects the client's BROWSER here, and a
    #                     browser arriving from a redirect carries no bearer
    #                     token. Safe because it finishes nothing: it parks
    #                     the code and hands back a nonce, and the link is
    #                     completed by the authenticated POST below, from a
    #                     session that must be the same user that began it.
    #
    # Everything else on this API calls _authenticate first.
    if route == "billing/webhook" and method == "POST":
        return _billing.handle_event(
            body if isinstance(body, (bytes, bytearray)) else (body or "").encode(),
            (headers or {}).get("Stripe-Signature")
            or (headers or {}).get("stripe-signature") or "")

    # The offer, readable without a session. A pricing page is seen by
    # visitors who have none, and the price is public by definition — it is
    # the thing on the page. public_offer() carries no provider secret.
    #
    # It exists so the UI never states a price of its own. billing.py keeps
    # the approved offer and offer_drift() reports when a deployment moves
    # off it; a price typed into a component would be a second source of
    # truth that no gate can see, which is the same mistake as a component
    # deciding for itself whether live execution is on.
    if route == "billing/offer" and method == "GET":
        return _ok(_billing.public_offer())

    # Early access. The fourth route that needs no session, and the only one
    # a stranger can WRITE through — so it is rate limited in its own tight
    # bucket, stores one field, and answers the same shape whatever happens,
    # carrying no address back.
    if route == "waitlist" and method == "POST":
        payload = _body(body) or {}
        try:
            outcome = _wait.join(payload.get("email"),
                                 source=payload.get("source"),
                                 platform=payload.get("platform"),
                                 broker=payload.get("broker"))
        except _wait.WaitlistError as e:
            status = 503 if e.code == "NOT_CONFIGURED" else 400
            return _err(status, e.code, _safe_error(e.detail))
        return _ok(_wait.public_result(outcome))

    if route == "billing/checkout" and method == "POST":
        _authenticate(headers, fresh=True)
        offer = _billing.public_offer()
        if (not _billing.checkout_enabled()
                or not _billing.authenticated_checkout_enabled()):
            return _err(503, "CHECKOUT_NOT_ENABLED",
                        "checkout is not enabled for this release",
                        offer=offer)
        return _err(501, "CHECKOUT_NOT_IMPLEMENTED",
                    "authenticated checkout is not implemented yet",
                    offer=offer)

    if route == "ctrader/callback" and method == "GET":
        return _ok(_link.handle_callback(query or {}), pendingOnly=True)

    if route.startswith("ctrader/"):
        action = route.split("/", 1)[1]
        if method != "POST" and action not in ("status",):
            return _err(405, "METHOD_NOT_ALLOWED", f"{method} not allowed")
        # Connecting a broker account and disconnecting one are both
        # irreversible from the client's point of view, so neither trusts a
        # cached session.
        p = _authenticate(headers, fresh=action in ("complete", "disconnect"))
        if action == "status":
            # Flat, exactly like GET accounts — which returns this same
            # payload and which the status strip reads correctly.
            #
            # This route used to wrap it as {"ctrader": {...}}, and five
            # client screens read `connected` off the top level, where it was
            # undefined and therefore falsy. Every one of them printed "no
            # cTrader account is connected" about an account that was
            # connected, while the strip — reading the flat route — showed
            # the account. Seen on 2026-10-02; the server answered 200 to all
            # nine calls, so nothing looked wrong anywhere but the screen.
            #
            # The convention this settles on: a READ answers the resource
            # flat; an ACTION (complete, select) answers {"ctrader": ...},
            # naming what its result changed.
            return _ok(_link.public_status(p.user_id))
        if action == "connect":
            _id.require_verified_email(p)
            return _ok(_link.begin(p.user_id))
        if action == "complete":
            _id.require_verified_email(p)
            data = _body(body) or {}
            nonce = data.get("nonce")
            proof = data.get("proof")
            if not isinstance(proof, str) or not proof:
                return _err(400, "BROWSER_BINDING_REQUIRED",
                            "finish this connection in the browser that "
                            "returned from cTrader")
            return _ok({"ctrader": _link.complete(
                p.user_id, nonce, proof=proof)})
        if action == "select":
            return _ok({"ctrader": _link.select_account(
                p.user_id, (_body(body) or {}).get("ctid"))})
        if action == "disconnect":
            return _ok(_link.disconnect(p.user_id))
        return _err(404, "NOT_FOUND", "no such cTrader action")

    # Accounts are the connected ones, read from the link. Never fabricated:
    # a client with nothing connected gets connected=false and an empty list
    # that is a FACT, not a placeholder.
    if route == "accounts" and method == "GET":
        p = _authenticate(headers)
        return _ok(_link.public_status(p.user_id))

    # A manual close is deliberately a separate route from the read-only
    # account views. It authenticates first, verifies the linked account is a
    # DEMO account, and then delegates to the shared close gate.
    close_match = _POSITION_CLOSE_RE.match(route)
    if close_match:
        if method != "POST":
            return _err(405, "METHOD_NOT_ALLOWED", f"{method} not allowed")
        p = _authenticate(headers, fresh=True)
        ctid, position_id = close_match.groups()
        result = _close.close_demo(p.user_id, ctid=ctid,
                                   position_id=position_id)
        return _ok({"close": result, "sentence": result.get("sentence")})

    # ── read-only broker views ──────────────────────────────────────────
    # Every one of these answers {connected, status, ...} and omits its data
    # key unless status is "ok". An empty list of positions is a claim, and it
    # is only made when the broker was actually asked and actually answered.
    m = _ACCOUNT_RE.match(route)
    if m:
        if method != "GET":
            return _err(405, "METHOD_NOT_ALLOWED", f"{method} not allowed")
        p = _authenticate(headers)
        ctid, sub_route = m.group(1), m.group(2)
        if sub_route == "positions":
            return _ok(_read.positions(p.user_id, ctid=ctid))
        if sub_route == "orders":
            return _ok(_read.orders(p.user_id, ctid=ctid))
        if sub_route == "deals":
            days = (query or {}).get("days", 7)
            return _ok(_read.deals(p.user_id, ctid=ctid, days=days))
        if sub_route == "candles":
            # Market data for a preview. Read-only: broker_read imports no
            # gate, no ledger and no order function, and a test asserts it.
            q = query or {}
            return _ok(_read.candles(
                p.user_id, ctid=ctid, symbol=q.get("symbol"),
                timeframe=q.get("timeframe"), limit=q.get("limit")))
        return _ok(_read.account(p.user_id, ctid=ctid))

    if route in ("positions", "orders") and method == "GET":
        p = _authenticate(headers)
        fn = _read.positions if route == "positions" else _read.orders
        return _ok(fn(p.user_id))

    # ── the client's own emergency button ───────────────────────────────
    # Stop automation and, when asked, close every open position on the
    # selected DEMO account. Not the operator's halt (that is
    # `emergency.py`). The confirmation is enforced HERE, not only in the
    # browser: a request that does not carry `confirm: true` does nothing, so a
    # stray or malformed call (a script, a retry, a form post) cannot close
    # positions. It is NOT replay protection: a holder of a valid, freshly
    # verified session could send it twice, and the guard against closing the
    # same position twice is the ledger claim, not this flag.
    if route == "emergency/stop":
        if method != "POST":
            return _err(405, "METHOD_NOT_ALLOWED", f"{method} not allowed")
        p = _authenticate(headers, fresh=True)
        b = _body(body) or {}
        if b.get("confirm") is not True:
            return _err(400, "CONFIRMATION_REQUIRED",
                        "send confirm: true to stop automation and close positions")
        close = b.get("closePositions", True)
        if not isinstance(close, bool):
            return _err(400, "BAD_REQUEST", "closePositions must be true or false")
        # Counted per PERSON now that the session is verified and the request
        # is well-formed (a malformed one must not spend the budget): the
        # pre-auth limit is per session, and a person can open more sessions.
        # OVER THE LIMIT THE STOP STILL RUNS. Refusing the whole request would
        # leave automation trading for up to a minute because of how often the
        # button was pressed; what is withheld is only the closing sweep, which
        # is the part that holds a worker for minutes.
        _person_ok, _person_wait = _rl.check_user("emergency_user", p.user_id)
        if not _person_ok:
            # Asked as "close, but there is no account to close on": the answer
            # then carries unreadable positions, no closes and allFlat False, so
            # the screen says "Not confirmed flat" instead of showing neither.
            # A stop-only press had no sweep to withhold and is left as it was.
            if close:
                out = _panic.run(
                    p.user_id, ctid="", close_positions=True,
                    not_attempted=True,
                    no_account_reason=(
                        "Emergency was pressed too many times in the last "
                        f"minute - wait {int(_person_wait or 1)}s and press it "
                        "again"))
            else:
                out = _panic.run(p.user_id, ctid="", close_positions=False)
            out["throttled"] = True
            return _ok(out)
        # THE STOP RUNS WHATEVER THE ACCOUNT. This used to answer 409
        # NO_ACCOUNT_SELECTED before the stop step, so a client with no
        # selected account - after a disconnect, or when the selection could
        # not be read - pressed the panic button and nothing stopped, while a
        # loop that still held its broker session went on trading. Not having
        # an account to CLOSE on is a reason to skip the closing, said in the
        # answer; it is never a reason to skip the stop.
        ctid = str(b.get("ctid") or "")
        no_account = None
        if not ctid:
            try:
                ctid = _selected_ctid_strict(p.user_id)
            except Exception:                           # noqa: BLE001
                ctid = ""
                no_account = ("your selected account could not be read just "
                              "now")
        if close and not ctid and no_account is None:
            no_account = "no cTrader account is selected"
        return _ok(_panic.run(p.user_id, ctid=ctid, close_positions=close,
                              no_account_reason=no_account))

    # ── automation control (demo only) ──────────────────────────────────
    # Separate from connecting an account, deliberately: linking cTrader to
    # look at a balance is not consent to be traded for.
    if route.startswith("automation"):
        action = route.split("/", 1)[1] if "/" in route else ""
        if not action and method == "GET":
            p = _authenticate(headers)
            return _ok(_auto.status(p.user_id))
        if action == "why" and method == "GET":
            p = _authenticate(headers)
            return _ok(_auto.why(p.user_id))
        if method != "POST":
            return _err(405, "METHOD_NOT_ALLOWED", f"{method} not allowed")
        # Every one of these changes whether money moves, so none of them
        # trusts a cached session.
        p = _authenticate(headers, fresh=True)
        if action == "start":
            _id.require_verified_email(p)
            rid = (_body(body) or {}).get("ruleDocId")
            if not rid:
                raise ValueError("ruleDocId is required to start automation")
            return _ok(_auto.start(p.user_id, rid))
        if action == "pause":
            return _ok(_auto.pause(p.user_id))
        if action == "resume":
            _id.require_verified_email(p)
            return _ok(_auto.resume(p.user_id))
        if action == "stop":
            return _ok(_auto.stop(p.user_id))
        return _err(404, "NOT_FOUND", "no such automation action")

    # ── a setup waiting for the client's approval ───────────────────────
    # The platform's half of the engine's Approval Required level. In that
    # level the loop proposes and places nothing, and until these three
    # routes existed the only way to answer a proposal was a Telegram tap —
    # so a platform client's loop found setups and went silent. See
    # apex/platform/approvals.py, and commit 6f984dfe9 for the state it left
    # every client in.
    #
    # Rate limiting: every route here goes through `_rl.check` before
    # `_dispatch` is reached. `approvals/approve` is in the `control` bucket
    # (see `ratelimit.classify`), because approving IS placing an order and it
    # used to be metered as a dashboard read. Reject and the pending-list poll
    # stay in `default`: a client must always be able to say no. What stops a
    # double tap opening two positions is the claim and the clear in
    # `approvals.approve` plus the idempotency claim inside the order
    # controller; the limiter is the second layer, not the first.
    if route == "approvals":
        if method != "GET":
            return _err(405, "METHOD_NOT_ALLOWED", f"{method} not allowed")
        p = _authenticate(headers)
        return _ok(_appr.pending(p.user_id))

    if route in ("approvals/approve", "approvals/reject"):
        if method != "POST":
            return _err(405, "METHOD_NOT_ALLOWED", f"{method} not allowed")
        # Both decide whether a position opens, so neither trusts a cached
        # session — the same reasoning as the automation controls above.
        p = _authenticate(headers, fresh=True)
        try:
            if route == "approvals/approve":
                # Approving IS placing an order, so it is held to what every
                # other order-producing action is held to. Dismissing is not:
                # a client must always be able to say no, and refusing that
                # would leave them with a proposal they cannot answer.
                _id.require_verified_email(p)
                return _ok(_appr.approve(p.user_id))
            return _ok(_appr.reject(p.user_id))
        except _appr.ApprovalRefused as e:
            # 409, and translated here rather than in `_handle`'s clause list:
            # these are the only two routes that can raise it, and the code
            # travels to the UI so a client is told WHICH refusal — expired,
            # already answered, not running — instead of one sentence that
            # fits none of them.
            return _err(409, e.code, _safe_error(e.detail))

    # ── notifications ───────────────────────────────────────────────────
    if route == "notifications":
        p = _authenticate(headers)
        q = query or {}
        if method == "GET":
            return _ok(_notify.query(
                p.user_id, type=q.get("type"),
                unread_only=str(q.get("unread", "")).lower()
                in ("1", "true", "yes"),
                limit=_num(q.get("limit"), "limit") or 50,
                offset=_num(q.get("offset"), "offset") or 0))
        return _err(405, "METHOD_NOT_ALLOWED", f"{method} not allowed")

    if route == "notifications/read-all" and method == "POST":
        p = _authenticate(headers)
        return _ok(_notify.mark_all_read(
            p.user_id, type=(_body(body) or {}).get("type")))

    m = _NOTIFY_RE.match(route)
    if m and method == "POST":
        p = _authenticate(headers)
        return _ok(_notify.mark_read(p.user_id, m.group(1)))

    # ── performance (closed trades the engine recorded) ─────────────────
    if route == "performance" and method == "GET":
        p = _authenticate(headers)
        q = query or {}
        return _ok(_perfread.read(p.user_id, period=q.get("period") or "all",
                                  mode=q.get("mode") or "demo",
                                  ctid=q.get("accountId") or None))

    # ── journal ─────────────────────────────────────────────────────────
    if route == "journal" and method == "GET":
        p = _authenticate(headers)
        q = query or {}
        return _ok(_jstore.query(
            p.user_id,
            account_id=q.get("accountId"), symbol=q.get("symbol"),
            since=_num(q.get("since"), "since"),
            until=_num(q.get("until"), "until"),
            rule_doc_id=q.get("ruleDocId"), status=q.get("status"),
            limit=_num(q.get("limit"), "limit") or 50,
            offset=_num(q.get("offset"), "offset") or 0))

    m = _JOURNAL_RE.match(route)
    if m and method == "GET":
        p = _authenticate(headers)
        return _ok({"entry": _jstore.get(p.user_id, m.group(1))})

    # Operator diagnostics. Authenticated, because "which dependency is down"
    # is not a thing to publish, and carrying no more secret material than
    # /readyz does — being signed in is not a reason to start returning keys.
    if route == "system/status" and method == "GET":
        p = _authenticate(headers)
        return _ok(_health.system_status(p))

    # Live access. The client can read the gate, accept the published
    # versions, and request a connection. Publishing, granting and deciding
    # are operator actions; live_gate.http refuses anyone else and writes
    # nothing. The body cannot choose a mode, a version, or a price.
    if route == "live" or route.startswith("live/"):
        fresh = not (method == "GET" and route == "live/status")
        p = _authenticate(headers, fresh=fresh)
        if method != "GET":
            _id.require_verified_email(p)
        return _live_gate.http(
            method, route, p, _body(body) if method != "GET" else None)

    if route == "me" and method == "GET":
        p = _authenticate(headers)
        # `execution` is the SERVER's verdict on what this client may do, so
        # the browser renders a badge rather than inferring one by combining
        # a licence state with an account mode. Those two have to be read
        # together to mean anything, and a UI that combines them itself is a
        # second implementation of this decision.
        return _ok({"user": p.as_dict(),
                    "licence": _lic.status_for(p.user_id),
                    "execution": _ent.capability(p.user_id)})

    # The strategy picker renders its list from this, so the UI can never
    # offer a strategy the engine does not register — the same contract
    # `conditions` has below, for the same reason. The catalogue intersects
    # this release's descriptions with the live registry, so a strategy that
    # exists only in one of the two is not on the list.
    #
    # Authenticated like its neighbours. It carries no secret material, but
    # "what can be traded here" is product surface and there is no reason an
    # unauthenticated caller needs it.
    if route == "strategies" and method == "GET":
        _authenticate(headers)
        # Imported here rather than at the top of the file, which is against
        # this module's convention and deliberate: the catalogue reads the
        # engine's registry, and that import pulls apex.ai and
        # apex.strategies. Every other route in this file would pay for them
        # at process start to serve one list.
        from apex.platform import strategy_catalog as _scat
        return _ok(_scat.catalogue())

    # The Rule Builder renders its form from this, so the UI can never offer a
    # condition the evaluator does not implement.
    if route == "conditions" and method == "GET":
        _authenticate(headers)
        return _ok({"conditions": _cond.describe()})

    if route == "rules":
        p = _authenticate(headers)
        if method == "GET":
            return _ok({"rules": [_summary(d) for d in
                                  _store.list_docs(p.user_id)]})
        if method == "POST":
            return _create(p, _body(body))
        return _err(405, "METHOD_NOT_ALLOWED", f"{method} is not allowed here")

    m = _RULE_RE.match(route)
    if m:
        p = _authenticate(headers)
        rid = m.group(1)
        if method == "GET":
            rule = _store.get(p.user_id, rid)
            # WHICH OF THESE TERMS THE ENGINE WILL ACT ON, per rule.
            #
            # The screen lists every field as the rule's own. Some of them
            # reach the loop and some do not, and which is which depends on
            # the rule — a stop in pips is applied exactly, the same stop as
            # an ATR multiple is not. A blanket sentence on the page cannot
            # say that, so the server answers it for this document.
            _applied, _missed = _ecfg.translate(rule)
            return _ok({"rule": rule, "notApplied": _missed})
        if method == "PUT":
            doc = dict(_body(body))
            doc["ruleDocId"] = rid
            # AN ACCOUNTLESS RULE COULD NEVER GET AN ACCOUNT, AND THE
            # REFUSAL TOLD THE CLIENT TO DO THE ONE THING THAT WOULD NOT
            # HELP.
            #
            # `_create` derives accountId from the client's selection, but
            # only at creation. The dashboard's own "Create a rule" button
            # and the builder's "what happens next" list both invite
            # building a rule BEFORE connecting a broker, and nothing on
            # that path says otherwise. Such a rule stores accountId "" and
            # stays that way: `save_draft` never derives it and the edit
            # form never sends it.
            #
            # So validation refused it with "connect and select an account,
            # then save the rule again" — and saving again changed nothing.
            # A brand-new client's only escape was to guess that the rule
            # was unfixable and start a second one. That is a dead end
            # reached after eleven steps, with instructions that cannot
            # work.
            #
            # Derived server-side, not read from the body: the selection
            # lives in the link record, and the browser has no business
            # naming which account a rule binds to. Only ever FILLS a gap —
            # a rule that already names an account keeps it, because
            # re-pointing a rule at a different account on an unrelated
            # save is not an edit the client asked for.
            try:
                if not str((_store.get(p.user_id, rid) or {})
                           .get("accountId") or ""):
                    _sel = _selected_ctid(p.user_id)
                    if _sel:
                        doc["accountId"] = _sel
            except Exception:                            # noqa: BLE001
                # save_draft re-reads and will raise properly for a missing
                # or unreadable rule. This is a convenience, not a gate.
                pass
            return _ok({"rule": _store.save_draft(p.user_id, doc)})
        return _err(405, "METHOD_NOT_ALLOWED", f"{method} is not allowed here")

    m = _RULE_VERSION_RE.match(route)
    if m and method == "GET":
        p = _authenticate(headers)
        return _ok({"rule": _store.get_version(p.user_id, m.group(1),
                                               int(m.group(2)))})

    m = _RULE_ACTION_RE.match(route)
    if m:
        if method != "POST":
            return _err(405, "METHOD_NOT_ALLOWED", f"{method} is not allowed")
        return _rule_action(m.group(2), m.group(1), headers, body)

    return _err(404, "NOT_FOUND", "no such endpoint")


def _summary(doc):
    """What a list shows. The whole document is a lot of JSON, and a list of
    rules does not need every condition's parameters."""
    return {"ruleDocId": doc.get("ruleDocId"), "name": doc.get("name"),
            "state": doc.get("state"), "version": doc.get("version"),
            "symbols": doc.get("symbols"), "timeframe": doc.get("timeframe"),
            "updatedAt": doc.get("updatedAt"),
            "accountId": doc.get("accountId")}


def _selected_ctid(user_id):
    """The account this client has chosen, or "".

    Read rather than asked of the browser. The link record is where the
    selection lives, and a rule bound to an account the client has not
    selected is a rule that will not run on the account they are looking at.
    """
    try:
        return _selected_ctid_strict(user_id)
    except Exception:                                   # noqa: BLE001
        return ""


def _selected_ctid_strict(user_id):
    """Like `_selected_ctid`, but a read that FAILS raises instead of reading
    as "nothing selected". The emergency stop needs the difference: it must
    still stop, and it must not tell the client no account is selected when
    the truth is that the selection could not be read."""
    sel = (_link.public_status(user_id) or {}).get("selected") or {}
    return str(sel.get("ctid") or "")


def _create(principal, payload):
    """A new draft. The blank is built here, not accepted from the browser, so
    a document can never arrive missing fields the evaluator later assumes.

    accountId falls back to the client's SELECTED account. The rule builder
    never sent one, so every rule it created carried "" and was refused at
    activation with "accountId: required" — a dead end reached only after the
    client had filled in eleven steps. The browser is not the right place to
    learn this anyway: the server already knows which account is selected.
    """
    doc = _rd.blank(user_id=principal.user_id,
                    account_id=(str(payload.get("accountId") or "")
                                or _selected_ctid(principal.user_id)),
                    symbols=payload.get("symbols") or [],
                    timeframe=payload.get("timeframe") or "1h")
    for field in ("name", "sides", "entry", "exit", "order", "sizing",
                  "stopLoss", "takeProfit", "trailingStop", "breakEven",
                  "limits", "schedule", "evaluateOn", "automationLevel"):
        if field in payload:
            doc[field] = payload[field]
    return _ok({"rule": _store.create(principal.user_id, doc)}, created=True)


def _rule_action(action, rid, headers, body):
    # Activation is the moment a configuration becomes capable of producing
    # orders, so it is the one that re-checks the session against Supabase
    # instead of trusting a cached answer, insists on a confirmed address, and
    # requires a live licence.
    sensitive = action == "activate"
    p = _authenticate(headers, fresh=sensitive)

    if action == "validate":
        doc = _store.get(p.user_id, rid)
        problems = _rd.validate(doc, known_condition_ids=_cond.available())
        return _ok({"valid": not problems, "problems": problems})

    if action == "activate":
        # Ownership and existence are settled BEFORE the licence, so an
        # unlicensed client asking about a rule that is not theirs gets the
        # same 404 as for one that never existed, rather than a 402 that
        # confirms the platform got as far as looking.
        _store.get(p.user_id, rid)
        _id.require_verified_email(p)
        # Activation records terms; it does not trade. It is free, and refuses
        # only a withdrawn licence.
        _ent.require_activation(p.user_id)
        return _ok({"rule": _store.activate(
            p.user_id, rid, known_condition_ids=_cond.available())})

    if action in ("pause", "resume", "archive"):
        want = {"pause": _rd.PAUSED, "resume": _rd.ACTIVE,
                "archive": _rd.ARCHIVED}[action]
        return _ok({"rule": _store.set_state(p.user_id, rid, want)})

    if action == "version":
        return _ok({"rule": _store.next_version(p.user_id, rid)})

    if action == "preview":
        # Read-only, and it stays that way because of what it does NOT touch:
        # no broker is built, force_trade is never called, no gate is entered
        # and no ExecutionRequest is created. The bars come from the caller,
        # so a preview can never be a verdict reached on invented data.
        doc = _store.get(p.user_id, rid)
        return _ok(_preview.preview(doc,
                                    (_body(body) or {}).get("snapshot")))

    return _err(404, "NOT_FOUND", "no such action")
