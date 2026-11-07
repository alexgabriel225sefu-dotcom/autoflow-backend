#!/usr/bin/env python3
"""Replay correctly SIGNED fake Stripe events against a LOCAL platform server.

Purpose: exercise the Apex4Traders billing webhook (`apex/platform/billing.py`)
the way Stripe would, without Stripe, money or a network. It prints PASS/FAIL
for each expected outcome and exits non-zero if any fails.

SAFETY
  * The signing secret comes from the environment, never from argv, and is
    never printed. Use a throwaway test value (it must start with "whsec_"),
    and start the local server with the SAME value, e.g.

        export STRIPE_WEBHOOK_TEST_SECRET=whsec_local_replay_only
        A4T_STRIPE_WEBHOOK_SECRET=$STRIPE_WEBHOOK_TEST_SECRET \\
            PORT=8080 python -u platform_server.py
        python scripts/stripe_webhook_replay.py

  * Only loopback targets are allowed (127.0.0.1, localhost, ::1).
  * It writes licence records for synthetic users named `a4t-replay-*` into the
    TARGET server's store. Point it at a dev/test store, never production data.
  * It never calls Stripe and cannot flip any checkout gate.

What it cannot show: it only sees HTTP replies. Whether a licence was really
written or removed must be read from the server (see the runbook).
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

SECRET_ENV = "STRIPE_WEBHOOK_TEST_SECRET"
DEFAULT_URL = "http://127.0.0.1:8080/api/v1/billing/webhook"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")
# Mirrors the approved offer in apex/platform/billing.py (APPROVED_PRICE_MINOR).
# Kept as a parameter, not imported, so this script runs without the package;
# the test suite asserts the two agree.
PRICE_MINOR = 49700
CURRENCY = "usd"
USER_META_KEY = "a4tUserId"


def sign_payload(payload: bytes, secret: str, *, ts=None) -> str:
    """Stripe's scheme: `t=<unix>,v1=hex(hmac_sha256(secret, "<t>." + body))`."""
    ts = int(time.time() if ts is None else ts)
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload,
                   hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def check_target(url: str) -> None:
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS and f"[{host}]" not in LOCAL_HOSTS:
        raise SystemExit(f"refusing non-local target {host!r}: this script "
                         f"only talks to a server on this machine")


def _event(etype, obj, *, event_id=None):
    return {"id": event_id or f"evt_replay_{uuid.uuid4().hex[:16]}",
            "object": "event", "type": etype, "livemode": False,
            "data": {"object": obj}}


def _session(user, pi, *, status="paid", amount=PRICE_MINOR):
    obj = {"id": f"cs_test_{uuid.uuid4().hex[:16]}", "object": "checkout.session",
           "payment_status": status, "payment_intent": pi,
           "amount_total": amount, "currency": CURRENCY,
           "metadata": {USER_META_KEY: user} if user else
                       {"email": "victim@example.com"}}
    if user:
        obj["client_reference_id"] = user
    return obj


def post(url, body: bytes, sig: str):
    """(status, parsed-json) — HTTP errors are answers here, not exceptions."""
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Stripe-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def scenarios(run_id=None):
    """The cases, as (name, event|None, how-to-sign, expectation) tuples.

    Expectation is a function of (status, body) -> bool plus a text for the
    report. Events are built fresh each call so reruns never collide.
    """
    rid = run_id or uuid.uuid4().hex[:8]
    ua, ub, uc, ud = (f"a4t-replay-{rid}-{n}" for n in "abcd")
    pia, pid_ = f"pi_replay_{rid}_a", f"pi_replay_{rid}_d"

    paid = _event("checkout.session.completed", _session(ua, pia))
    unpaid = _event("checkout.session.completed",
                    _session(ub, f"pi_replay_{rid}_b", status="unpaid"))
    cheap = _event("checkout.session.completed",
                   _session(uc, f"pi_replay_{rid}_c", amount=100))
    nouser = _event("checkout.session.completed",
                    _session(None, f"pi_replay_{rid}_n"))
    paid_d = _event("checkout.session.completed", _session(ud, pid_))
    # A refund / dispute arrives on a Charge / Dispute: no metadata of ours,
    # only the PaymentIntent id. That is the whole point of these two cases.
    refund = _event("charge.refunded", {
        "id": f"ch_replay_{rid}", "object": "charge", "payment_intent": pia,
        "amount": PRICE_MINOR, "amount_refunded": PRICE_MINOR})
    partial = _event("charge.refunded", {
        "id": f"ch_replay_{rid}_p", "object": "charge", "payment_intent": pid_,
        "amount": PRICE_MINOR, "amount_refunded": 1000})
    dispute = _event("charge.dispute.created", {
        "id": f"dp_replay_{rid}", "object": "dispute", "payment_intent": pid_,
        "amount": PRICE_MINOR})
    other = _event("customer.created", {"id": "cus_replay", "object": "customer"})

    def is_(code, **kv):
        def f(s, b):
            return s == code and all(b.get(k) == v for k, v in kv.items())
        return f

    return [
        ("tampered signature is refused", paid, "bad",
         "400 BAD_SIGNATURE",
         lambda s, b: s == 400 and (b.get("error") or {}).get("code") == "BAD_SIGNATURE"),
        ("stale timestamp (replay of a captured body) is refused", paid, "stale",
         "400 BAD_SIGNATURE",
         lambda s, b: s == 400 and (b.get("error") or {}).get("code") == "BAD_SIGNATURE"),
        ("paid checkout.session.completed grants", paid, "ok",
         "200 handled=true outcome=granted",
         is_(200, handled=True, outcome="granted")),
        ("duplicate delivery of the same event id is a no-op", paid, "ok",
         "200 duplicate=true", is_(200, duplicate=True)),
        ("unpaid session grants nothing", unpaid, "ok",
         "200 handled=false (payment not completed)",
         is_(200, handled=False, reason="payment not completed")),
        ("wrong amount (discounted/other product) grants nothing", cheap, "ok",
         "200 handled=false (does not match the approved offer)",
         lambda s, b: s == 200 and b.get("handled") is False
         and "approved offer" in str(b.get("reason"))),
        ("no platform user (email-only metadata) grants nothing", nouser, "ok",
         "200 handled=false (no platform user)",
         lambda s, b: s == 200 and b.get("handled") is False
         and "no platform user" in str(b.get("reason"))),
        ("full refund revokes (matched through the PaymentIntent)", refund, "ok",
         "200 handled=true outcome=revoked",
         is_(200, handled=True, outcome="revoked")),
        ("second buyer is granted (for the dispute cases)", paid_d, "ok",
         "200 handled=true outcome=granted",
         is_(200, handled=True, outcome="granted")),
        ("partial refund leaves the licence in place", partial, "ok",
         "200 handled=false (partial refund)",
         lambda s, b: s == 200 and b.get("handled") is False
         and "partial" in str(b.get("reason"))),
        ("dispute revokes", dispute, "ok",
         "200 handled=true outcome=revoked",
         is_(200, handled=True, outcome="revoked")),
        ("an event type we do not act on is acknowledged", other, "ok",
         "200 handled=false", is_(200, handled=False)),
    ]


def run(url, secret, *, poster=post, run_id=None, out=print):
    """Execute every scenario. Returns the list of (name, passed)."""
    results = []
    for name, ev, how, expect, ok in scenarios(run_id):
        body = json.dumps(ev, separators=(",", ":")).encode()
        if how == "bad":
            sig = sign_payload(body, secret + "-tampered")
        elif how == "stale":
            sig = sign_payload(body, secret, ts=time.time() - 3600)
        else:
            sig = sign_payload(body, secret)
        try:
            status, payload = poster(url, body, sig)
        except Exception as e:                                # noqa: BLE001
            status, payload = 0, {"error": type(e).__name__}
        passed = bool(ok(status, payload))
        results.append((name, passed))
        out(f"{'PASS' if passed else 'FAIL'}  {name}\n"
            f"      expected {expect}; got {status} "
            f"{json.dumps(payload, sort_keys=True)[:160]}")
    return results


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    url = argv[0] if argv else DEFAULT_URL
    secret = (os.getenv(SECRET_ENV) or "").strip()
    if not secret.startswith("whsec_"):
        raise SystemExit(f"set {SECRET_ENV} to a throwaway test secret that "
                         f"starts with whsec_ (the same value the local "
                         f"server was started with)")
    check_target(url)
    results = run(url, secret)
    bad = [n for n, p in results if not p]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
