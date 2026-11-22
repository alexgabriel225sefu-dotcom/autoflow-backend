"""Tell the early-access list that access is opening. Operator tooling.

WHY THIS IS A SEPARATE, CAREFUL TOOL

The list is a few hundred strangers who gave an address to a form that promised
"one email, when early access opens". This is that one email. Every mistake
available here goes in the same direction, so each rule below is one of them
refused:

  * A SECOND email to somebody who already got it. Worse than a missing one,
    so an uncertain outcome (a timeout, a 5xx, a crash between "claimed" and
    "answered") is HELD, never retried by itself. The operator opts in to a
    retry with a flag, after looking.
  * An email to somebody who asked to be removed. Each address is re-read
    immediately before its turn; a removal made mid-run is honoured.
  * A send nobody confirmed. A dry run is the default; sending needs both the
    switch and a phrase naming the campaign and the exact number about to go.
  * A send to the wrong list. The phrase carries the count, so a list that
    changed since the dry run no longer matches and must be planned again.
  * An address in a log. Results carry counts and masked samples only.
  * Copy that promises an outcome. The same refusal the landing page lives
    under; overridable on purpose, never by accident.
  * A run that keeps hammering a provider that is plainly down.

NO COPY IS SHIPPED. The words are the owner's, supplied at run time
(docs/WAITLIST_EMAIL_DELIVERY.md: final copy is pending owner approval). This
module only refuses bad ones and adds the one thing every message must carry:
how to be taken off the list.

NOT A MARKETING SYSTEM. One plain-text message per address, per campaign. No
HTML, no tags, no tracking pixel, no click-tracking links: that is the
product's contract with the people on the list. (Open/click tracking is also a
per-domain setting at the provider; keep it OFF there.)
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid

from apex import user_store
from apex.platform import store as _store
from apex.platform import waitlist as W

CAMPAIGN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_SUBJECT = 120
MAX_BODY = 5000
MAX_LIMIT = 500           # a day's batch, well inside the provider's free tier
DEFAULT_LIMIT = 100
DEFAULT_DELAY_SEC = 0.6   # the provider allows two requests a second
ANNOUNCE_TIMEOUT_SEC = 10
LOCK_TTL_SEC = 3600

SENT, FAILED, UNKNOWN, SENDING = "sent", "failed", "unknown", "sending"

# Words that promise an outcome. The product makes no such claim anywhere, and
# a mailing is where one most easily slips in. One pattern per line: this is a
# list of what to REFUSE, and the repository's own copy audit reads a line, not
# intent.
_FLAGGED = (
    r"guarantee",
    r"risk[- ]?free",
    r"profit",
    r"\bearn(s|ed|ing)?\b",
    r"income",
    r"\breturns?\b",
    r"\d+\s?%",
    r"get rich",
    r"double your",
    r"win rate",
    r"passive",
)
_COPY_FLAGS = re.compile("|".join(_FLAGGED), re.IGNORECASE)


class AnnounceError(ValueError):
    """Refused. `code` is what a caller branches on, never the message."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


# --------------------------------------------------------------------------- input

def validate_campaign(campaign, subject, body, *, allow_copy_flags=False):
    """The campaign, subject and body as they will be sent, or a refusal."""
    c = (campaign or "").strip()
    if not CAMPAIGN_RE.match(c):
        raise AnnounceError("CAMPAIGN_INVALID",
                            "campaign: 1-40 characters of a-z, 0-9 and '-'")
    s = (subject or "").strip()
    if not s or len(s) > MAX_SUBJECT or re.search(r"[\x00-\x1f\x7f]", s):
        raise AnnounceError("SUBJECT_INVALID",
                            f"subject: 1-{MAX_SUBJECT} characters on one line")
    b = (body or "").strip()
    if not b or len(b) > MAX_BODY:
        raise AnnounceError("BODY_INVALID", f"body: 1-{MAX_BODY} characters")
    flagged = sorted({m.group(0).lower() for m in _COPY_FLAGS.finditer(f"{s}\n{b}")})
    if flagged and not allow_copy_flags:
        raise AnnounceError(
            "COPY_FLAGGED",
            "the copy contains words that promise an outcome: "
            + ", ".join(flagged) + ". Remove them, or pass allow_copy_flags "
            "once you have checked the copy.")
    return {"campaign": c, "subject": s, "body": b}


def mask(address):
    """a***@e***.com. Enough to recognise your own address, nobody else's."""
    local, _, domain = (address or "").partition("@")
    labels = domain.split(".")
    tld = labels[-1] if len(labels) > 1 else ""
    host = (labels[0][:1] + "***") if labels and labels[0] else "***"
    return f"{local[:1]}***@{host}" + (f".{tld}" if tld else "")


def build_payload(address, subject, body, remove_contact):
    """One plain-text message. The footer is not optional."""
    contact = (remove_contact or "").strip()
    if not contact:
        raise AnnounceError("NO_REMOVE_CONTACT",
                            "say where somebody writes to be taken off the list")
    sender = (os.getenv("A4T_WAITLIST_FROM_EMAIL") or "").strip()
    if not sender:
        raise AnnounceError("NOT_CONFIGURED", "A4T_WAITLIST_FROM_EMAIL is not set")
    footer = (
        "\n\n--\nYou are receiving this once because you joined the "
        "Apex4Traders early-access list. To be removed from the list, write "
        f"to {contact}."
    )
    payload = {"from": sender, "to": [address], "subject": subject,
               "text": body + footer}
    reply_to = (os.getenv("A4T_WAITLIST_REPLY_TO") or "").strip()
    if reply_to:
        payload["reply_to"] = reply_to
    if W._EMAIL.match(contact.lower()):
        payload["headers"] = {"List-Unsubscribe": f"<mailto:{contact}>"}
    return payload


# --------------------------------------------------------------------------- provider

def _post_resend(payload):
    key = (os.getenv("RESEND_API_KEY") or "").strip()
    req = urllib.request.Request(
        W.RESEND_ENDPOINT, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": "apex4traders-announce/1.0"})
    with urllib.request.urlopen(req, timeout=ANNOUNCE_TIMEOUT_SEC) as resp:  # nosec B310 - fixed HTTPS endpoint
        body = resp.read(1024 * 64).decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError:
        parsed = {}
    return parsed.get("id") if isinstance(parsed, dict) else None


def _deliver(payload, post):
    """(status, providerId, reason). Never raises, never carries the address.

    A 4xx means the provider refused the request, so nothing went out: FAILED.
    Anything else that is not a clean answer (a timeout, a 5xx, a dropped
    connection) may have been delivered: UNKNOWN, and held.
    """
    try:
        provider_id = (post or _post_resend)(payload)
    except urllib.error.HTTPError as exc:
        status = FAILED if 400 <= exc.code < 500 else UNKNOWN
        return status, None, f"HTTP_{exc.code}"
    except Exception as exc:            # noqa: BLE001 - any failure is "unknown"
        return UNKNOWN, None, type(exc).__name__
    return SENT, (str(provider_id)[:80] if provider_id else None), None


# --------------------------------------------------------------------------- the list

def _blocked(state, retry_failed, retry_unknown):
    """Why this entry must not be planned or sent, or None if it may be."""
    status = (state or {}).get("status")
    if status == SENT:
        return SENT
    if status == FAILED and not retry_failed:
        return FAILED
    if status in (UNKNOWN, SENDING) and not retry_unknown:
        return status
    return None


def _entries():
    for key in sorted(_store._set_members(W._k_index())):
        rec = _store._read(key)
        if rec:
            yield key, rec


def _plan(campaign, retry_failed, retry_unknown):
    todo, held, unreadable = [], {FAILED: 0, UNKNOWN: 0, SENDING: 0}, 0
    for key, rec in _entries():
        stored = rec.get("email") or ""
        address = user_store.decrypt_value(stored)
        if stored and not address:
            unreadable += 1
            continue
        why = _blocked((rec.get("announced") or {}).get(campaign),
                       retry_failed, retry_unknown)
        if why == SENT:
            continue
        if why:
            held[why] += 1
            continue
        todo.append((rec.get("joinedAt") or 0, key, address))
    todo.sort()
    return todo, held, unreadable


def status(campaign):
    """Counts for one campaign. Never an address."""
    out = {SENT: 0, FAILED: 0, UNKNOWN: 0, SENDING: 0, "pending": 0}
    for _key, rec in _entries():
        s = ((rec.get("announced") or {}).get(campaign) or {}).get("status")
        out[s if s in out else "pending"] += 1
    out["total"] = sum(out.values())
    return out


def _mark(key, campaign, state):
    current = _store._read(key)
    if not current:
        return False
    announced = dict(current.get("announced") or {})
    announced[campaign] = state
    _store._write(key, dict(current, announced=announced))
    return True


# --------------------------------------------------------------------------- the run lease

def _lock_key(campaign):
    return f"{_store._ns()}:{_store._P}:waitlist:announce-lock:{campaign}"


_TOKENS = {}


def _claim_run(campaign):
    """True: this run holds the campaign. False: another does. None: cannot ask."""
    token = uuid.uuid4().hex
    got = user_store.claim_value(_lock_key(campaign), token, ttl_s=LOCK_TTL_SEC)
    if got:
        _TOKENS[campaign] = token
    return got


def _release_run(campaign):
    token = _TOKENS.pop(campaign, None)
    if token:
        user_store.release_claim(_lock_key(campaign), token)


# --------------------------------------------------------------------------- the run

def run(campaign, subject, body, *, remove_contact=None, limit=DEFAULT_LIMIT,
        send=False, confirm=None, retry_failed=False, retry_unknown=False,
        allow_copy_flags=False, lock=True, post=None, sleep=time.sleep,
        delay=DEFAULT_DELAY_SEC, max_consecutive_failures=3, now=None):
    """Plan, or send, one campaign to the people who have not had it.

    `send=False` (the default) changes nothing and returns the plan together
    with the exact phrase a real send must be given.
    """
    v = validate_campaign(campaign, subject, body, allow_copy_flags=allow_copy_flags)
    c = v["campaign"]
    if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise AnnounceError("LIMIT_INVALID", f"limit: 1-{MAX_LIMIT}")

    # Caught on the dry run too: a message with no way off the list is not one
    # to find out about at send time.
    if not (remove_contact or "").strip():
        raise AnnounceError("NO_REMOVE_CONTACT",
                            "say where somebody writes to be taken off the list")

    cfg = W.email_config_status()
    if send and not cfg["configured"]:
        raise AnnounceError(
            "NOT_CONFIGURED",
            "provider not configured; missing: " + ", ".join(cfg["missing"]))

    todo, held, unreadable = _plan(c, retry_failed, retry_unknown)
    batch = todo[:limit]
    phrase = f"SEND {c} TO {len(batch)}"
    plan = {
        "campaign": c, "planned": len(batch), "remaining": len(todo) - len(batch),
        "held": held, "unreadable": unreadable,
        "sample": [mask(a) for _j, _k, a in batch[:3]],
        "providerConfigured": cfg["configured"],
    }
    if not send:
        return dict(plan, dryRun=True, confirmation=phrase)
    if confirm != phrase:
        raise AnnounceError(
            "CONFIRM_MISMATCH",
            f"to send, pass exactly: {phrase}. (If the list changed since the "
            f"dry run the number differs: plan again.)")

    if lock:
        got = _claim_run(c)
        if got is False:
            raise AnnounceError("RUN_LOCKED", "another run holds this campaign")
        if got is None:
            raise AnnounceError(
                "LOCK_UNKNOWN",
                "cannot tell whether another run is in progress (no shared "
                "backend). Run on the service itself, or pass lock=False if "
                "you are certain nothing else is running.")
    try:
        return _send_batch(v, batch, plan, remove_contact, retry_failed,
                           retry_unknown, post, sleep, delay,
                           max_consecutive_failures, now)
    finally:
        if lock:
            _release_run(c)


def _send_batch(v, batch, plan, remove_contact, retry_failed, retry_unknown,
                post, sleep, delay, max_consec, now):
    c = v["campaign"]
    counts = {SENT: 0, FAILED: 0, UNKNOWN: 0}
    skipped, consecutive, stopped = 0, 0, None
    for i, (_joined, key, address) in enumerate(batch):
        # Re-read at the last moment: a removal made since the plan is honoured,
        # and so is any state another run wrote in the meantime.
        fresh = _store._read(key)
        if not fresh or _blocked(((fresh.get("announced") or {}).get(c)),
                                 retry_failed, retry_unknown):
            skipped += 1
            continue
        payload = build_payload(address, v["subject"], v["body"], remove_contact)
        stamp = int(now if now is not None else time.time())
        # CLAIM BEFORE THE CALL, answer after. A crash in between leaves
        # 'sending', which is held: one uncertain email, never two.
        if not _mark(key, c, {"status": SENDING, "at": stamp}):
            skipped += 1
            continue
        status_, provider_id, reason = _deliver(payload, post)
        state = {"status": status_, "at": stamp}
        if provider_id:
            state["providerId"] = provider_id
        if reason:
            state["reason"] = reason
        _mark(key, c, state)
        counts[status_] += 1
        consecutive = 0 if status_ == SENT else consecutive + 1
        if consecutive >= max_consec:
            stopped = "CONSECUTIVE_FAILURES"
            break
        if delay and i < len(batch) - 1:
            sleep(delay)
    return dict(plan, dryRun=False, sent=counts[SENT], failed=counts[FAILED],
                unknown=counts[UNKNOWN], skipped=skipped, stopped=stopped)


def send_test(address, subject, body, remove_contact, *, post=None,
              allow_copy_flags=False):
    """One real email to one address, to read it before the list does.

    Touches nothing on the list: no record is written and nobody is marked.
    """
    v = validate_campaign("test", subject, body, allow_copy_flags=allow_copy_flags)
    try:
        to = W.normalise(address)
    except W.WaitlistError as e:
        raise AnnounceError(e.code, e.detail) from None
    cfg = W.email_config_status()
    if not cfg["configured"]:
        raise AnnounceError(
            "NOT_CONFIGURED",
            "provider not configured; missing: " + ", ".join(cfg["missing"]))
    payload = build_payload(to, "[TEST] " + v["subject"], v["body"], remove_contact)
    status_, provider_id, reason = _deliver(payload, post)
    out = {"status": status_}
    if provider_id:
        out["providerId"] = provider_id
    if reason:
        out["reason"] = reason
    return out
