"""Self-contained Stripe webhook handler for instant license activation.

Registered as its own endpoint in the Stripe Dashboard, pointed at this bot's
own /api/stripe/webhook — separate from the main site's /stripe-webhook, so
this keeps working even while the main site backend is down.

Flow: /purchase sends a Payment Link with ?client_reference_id=<chat_id>.
On checkout.session.completed, we read that chat_id back, mint a license key
in the same format the manual /start FORX-... flow expects, store it, and
message the buyer directly — all within this one process, no external call.
"""
import hmac
import time
import json
import hashlib
import secrets

from apex import config as cfg
from apex import user_store

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ23456789"  # matches ^[A-Z2-9]{4}$ groups
_SIG_TOLERANCE_SEC = 300  # reject replayed/stale webhook deliveries


def generate_license_key() -> str:
    group = lambda: "".join(secrets.choice(_ALPHABET) for _ in range(4))
    return f"{cfg.LICENSE_KEY_PREFIX}-{group()}-{group()}-{group()}"


def _verify_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Manual Stripe webhook signature check (stdlib only, no stripe SDK)."""
    if not secret or not sig_header:
        return False
    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    ts = parts.get("t")
    v1 = parts.get("v1")
    if not ts or not v1:
        return False
    try:
        if abs(time.time() - int(ts)) > _SIG_TOLERANCE_SEC:
            return False
    except ValueError:
        return False
    signed_payload = f"{ts}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


def _event_key(event_id):
    return f"stripe:evt:{event_id}"


def _drop_event_claim(event_id):
    """Give the idempotency claim back after a delivery we could not complete.

    Without this the two defences deadlock against each other: the claim says
    "this event is handled" while the licence was never written, so every
    Stripe retry is answered with "duplicate" and the buyer — who has paid —
    is never provisioned. The claim must only outlive the delivery when the
    delivery actually succeeded.
    """
    if not event_id:
        return
    try:
        # Best effort by design: if this fails the claim expires on its own,
        # and Stripe's retry window is long enough that a later delivery still
        # lands. Warn loudly either way, because until it clears, retries of
        # THIS event are being refused.
        user_store.set_blob(_event_key(event_id), "", ttl_s=1)
        print(f"[Stripe] released idempotency claim for {event_id} so a retry "
              f"can provision the buyer")
    except Exception as e:
        print(f"[Stripe] could not release claim for {event_id} ({e}) — "
              f"retries of this event will be refused until it expires")


def handle_webhook(raw_body: bytes, sig_header: str):
    """Returns (http_status, response_bytes)."""
    if not cfg.STRIPE_WEBHOOK_SECRET:
        print("[Stripe] STRIPE_WEBHOOK_SECRET not set — refusing webhook")
        return 500, b"not configured"
    if not _verify_signature(raw_body, sig_header or "", cfg.STRIPE_WEBHOOK_SECRET):
        print("[Stripe] webhook signature verification failed")
        return 400, b"bad signature"

    try:
        event = json.loads(raw_body)
    except Exception as e:
        print(f"[Stripe] webhook payload parse failed: {e}")
        return 400, b"bad payload"

    if event.get("type") != "checkout.session.completed":
        return 200, b"ignored"

    session = event.get("data", {}).get("object", {})
    if session.get("payment_status") != "paid":
        return 200, b"not paid"

    chat_id = session.get("client_reference_id")
    if not chat_id:
        print(f"[Stripe] checkout.session.completed with no client_reference_id "
              f"(session={session.get('id')}) — can't attribute to a Telegram user")
        return 200, b"no chat id"

    # Stripe retries a delivery it did not get a 2xx for, and it may deliver the
    # same event more than once by design. Without this, every retry minted a
    # SECOND license key and overwrote the first — so the key in the buyer's
    # first activation message stopped working, and they got the whole welcome
    # sequence again. Two defences, because they fail in different directions:
    #
    #   1. The event id, claimed atomically (SET NX EX). This is the only thing
    #      that stops two containers processing the same retry concurrently.
    #      Held well past Stripe's ~3-day retry schedule.
    #   2. The stored license itself. A claim needs Redis; this does not, so a
    #      redelivery still cannot mint a second key when there is no shared
    #      backend at all.
    event_id = str(event.get("id") or "").strip()
    if event_id:
        seen = user_store.claim(_event_key(event_id), ttl_s=7 * 24 * 3600)
        if seen is False:
            # Held by a delivery that got further than this one. Only answer
            # "handled" if it actually finished — a claim taken by an attempt
            # that then failed to write must not lock the buyer out. Defence 2
            # is the evidence: the licence either exists or it does not.
            if (user_store.load(chat_id) or {}).get("license_key"):
                print(f"[Stripe] duplicate delivery of {event_id} — already handled")
                return 200, b"duplicate"
            print(f"[Stripe] {event_id} was claimed but {chat_id} has no licence "
                  f"— a previous delivery failed part-way; provisioning now")
        # seen is None => no shared backend; defence 2 below still applies.

    try:
        existing = (user_store.load(chat_id) or {}).get("license_key")
    except Exception as e:
        print(f"[Stripe] could not read existing license for {chat_id}: {e}")
        existing = None

    if existing:
        # Already provisioned by an earlier delivery of this purchase. Re-grant
        # access (cheap, idempotent) but keep the key the buyer already has and
        # do not re-send the activation sequence.
        try:
            from apex import access
            access.grant(str(chat_id))
        except Exception as e:
            print(f"[Stripe] re-grant failed for {chat_id}: {e}")
        print(f"[Stripe] {chat_id} already licensed — kept existing key "
              f"(session={session.get('id')})")
        return 200, b"already active"

    key = generate_license_key()
    # STRICT: the buyer has already been charged. A write that quietly does not
    # land leaves them paid and unlicensed, and returning 200 here tells Stripe
    # the event is handled so it never retries — the one combination there is
    # no recovery path for. Fail loudly instead and let Stripe redeliver.
    try:
        stored_ok = user_store.update(chat_id, {"license_key": key}, strict=True)
    except Exception as e:
        print(f"[Stripe] LICENSE WRITE FAILED for {chat_id} ({e}) — returning "
              f"500 so Stripe retries; buyer is paid and NOT yet provisioned")
        _drop_event_claim(event_id)
        return 500, b"store failed"
    if not stored_ok:
        print(f"[Stripe] LICENSE WRITE not confirmed for {chat_id} — returning "
              f"500 so Stripe retries")
        _drop_event_claim(event_id)
        return 500, b"store failed"

    # Read it back. `strict` covers a write that reported failure; this covers
    # one that reported success and still is not there.
    if (user_store.load(chat_id) or {}).get("license_key") != key:
        print(f"[Stripe] LICENSE READBACK MISMATCH for {chat_id} — returning "
              f"500 so Stripe retries")
        _drop_event_claim(event_id)
        return 500, b"store failed"

    granted = False
    try:
        from apex import access
        granted = access.grant(str(chat_id)) is not False
    except Exception as e:
        print(f"[Stripe] access grant FAILED for {chat_id}: {e}")
    if not granted:
        # The licence is stored, so a retry takes the "already licensed" path
        # above and re-grants without minting a second key. Ask for that retry.
        print(f"[Stripe] {chat_id} licensed but not granted — returning 500 "
              f"so Stripe retries the grant")
        return 500, b"grant failed"

    # Messaging is best-effort on purpose: it is the only step whose failure
    # does not leave the buyer unprovisioned, and forcing a Stripe retry over a
    # Telegram hiccup would re-send the welcome to everyone it did reach.
    try:
        from apex import telegram as tg
        tg.send_activation_sequence(chat_id, paid=True)
    except Exception as e:
        print(f"[Stripe] activation notify failed for {chat_id} "
              f"(licence IS active): {e}")

    print(f"[Stripe] activated {chat_id} with license {key} "
          f"(session={session.get('id')})")
    return 200, b"ok"
