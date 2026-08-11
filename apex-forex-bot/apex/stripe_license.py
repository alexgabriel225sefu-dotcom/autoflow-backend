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

    key = generate_license_key()
    try:
        user_store.update(chat_id, {"license_key": key})
    except Exception as e:
        print(f"[Stripe] failed to store license for {chat_id}: {e}")
        return 500, b"store failed"

    try:
        from apex import access, telegram as tg
        access.grant(str(chat_id))
        # Full instant sequence: welcome + FP Markets signup link + the real
        # cTrader authorize link, all in one shot — no /ctrader typing needed.
        tg.send_activation_sequence(chat_id, paid=True)
    except Exception as e:
        print(f"[Stripe] activation notify failed for {chat_id}: {e}")

    print(f"[Stripe] activated {chat_id} with license {key} "
          f"(session={session.get('id')})")
    return 200, b"ok"
