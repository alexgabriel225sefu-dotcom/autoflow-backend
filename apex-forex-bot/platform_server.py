"""Apex4Traders platform API — the entry point for the `apex4traders-api` service.

WHY THIS FILE EXISTS, AND WHY `main.py` COULD NOT BE USED

`main.py` starts `apex.bot.main()`, which starts Telegram polling, the per-user
trading loops and the operator dashboard. Deploying it under a second name would
have created a SECOND live Telegram trading bot competing with the one already
running — not a platform API. The platform's `/healthz`, `/readyz` and
`/api/v1/*` routes happen to be mounted on that bot's HTTP handler, which is what
made `python -u main.py` look like a plausible start command in the blueprint. It
was not one.

So this serves the platform surface and nothing else:

    GET  /healthz          process liveness, touches no dependency
    GET  /readyz           readiness, may touch dependencies
    *    /api/v1/*         the platform API
    OPTIONS any of those   CORS preflight
    everything else        404, as JSON

It starts no Telegram poller, no trading loop, no ownership lease and no
operator dashboard. `apex.bot` is never imported — asserted by
tests/test_platform_server.py, because "does not import the trading bot" is the
property that makes this safe to deploy and the easiest one to lose by accident.

TRANSPORT ONLY

Every decision — who the caller is, what they own, whether they are licensed,
whether anything may execute — is made in `apex/platform/api.py` and
`apex/platform/health.py`, both of which are transport-free and tested without a
socket. This module reads the request and writes the reply. It must stay that
way: a rule enforced here would be a rule the platform's own tests cannot see.

CORS, AND WHY IT IS REQUIRED RATHER THAN OPTIONAL

The web client runs on a different origin from this service and calls
`/api/v1/*` from the browser with an `Authorization: Bearer` header. That header
makes the request non-simple, so the browser sends an `OPTIONS` preflight first
and refuses the real request unless the reply allows the origin. Without the
headers below the deployed dashboard loads and then shows nothing but network
errors.

The allowed origin is configured, never reflected. Echoing back whatever
`Origin` the caller sent would let any site on the internet make authenticated
requests with a victim's bearer token. A4T_ALLOWED_ORIGIN holds the web
service's URL, one or more, comma-separated; an origin that is not on the list
gets no CORS header at all and the browser blocks it. Credentials are not
allowed, because this API authenticates with a bearer token and never a cookie.

Run: PORT=8080 python -u platform_server.py
"""
import json
import os
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Before anything can print. Installing the redactor after the first line of
# output leaves exactly the line that carried a credential.
from apex import redact                                          # noqa: E402

redact.install()

from apex import http_security                                   # noqa: E402
from apex.platform import api as platform_api                     # noqa: E402
from apex.platform import health as platform_health               # noqa: E402

# Render provides PORT. DASHBOARD_PORT is not read here on purpose: that
# variable belongs to the legacy bot's operator dashboard, and this service does
# not serve it.
PORT = int(os.getenv("PORT") or 8080)

_HEALTH_PATHS = ("/healthz", "/readyz")

# Methods the platform API dispatches. OPTIONS is handled here and never
# forwarded, since a preflight is a transport concern.
_METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")

MAX_BODY = 1_000_000


def allowed_origins():
    """The web origins permitted to call this API, exactly as configured.

    Read on every request rather than captured at import, so the list can be
    corrected in the dashboard and take effect on the next deploy without a
    code change — and so a test can set it.

    An empty list means no cross-origin caller is allowed. That is the right
    default for a service whose own health checks are same-origin: the failure
    is a dashboard that cannot reach its API, which is loud, rather than an API
    any site may call, which is silent.
    """
    raw = os.getenv("A4T_ALLOWED_ORIGIN") or ""
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def cors_headers(origin):
    """Headers to add for this Origin, or {} when it is not allowed.

    Never reflects an arbitrary origin. `Vary: Origin` is always sent when the
    decision depends on the origin, or a shared cache could hand one site's
    allow header to another.
    """
    if not origin:
        return {}
    if origin.rstrip("/") not in allowed_origins():
        return {"Vary": "Origin"}
    return {
        "Access-Control-Allow-Origin": origin.rstrip("/"),
        "Access-Control-Allow-Methods": ", ".join(_METHODS) + ", OPTIONS",
        # Exactly the two the client sends. Authorization is what makes the
        # request non-simple in the first place.
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
        # No Access-Control-Allow-Credentials. This API reads a bearer token,
        # never a cookie, and allowing credentials would let a browser attach
        # one it holds for this origin.
    }


class Handler(BaseHTTPRequestHandler):
    # Identifies the service in logs without naming a version, which would be a
    # free hint about which advisories apply.
    server_version = "apex4traders-api"
    sys_version = ""

    def log_message(self, *args):
        """Silenced. The default logs the request line, and a query string can
        carry a token; everything worth keeping is logged by the API itself."""

    # ── replies ──────────────────────────────────────────────────────────────
    def _send(self, status, payload, extra=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # None of this is cacheable: it is per-caller and, for readiness, the
        # whole point is that it is current.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _origin(self):
        try:
            return (self.headers.get("Origin") or "").strip()
        except Exception:
            return ""

    # ── routes ───────────────────────────────────────────────────────────────
    def _health(self):
        """True when this was a health request and it has been answered."""
        path = (self.path or "").split("?", 1)[0]
        if path not in _HEALTH_PATHS:
            return False
        status, payload = (platform_health.live() if path == "/healthz"
                           else platform_health.ready())
        # No CORS on the probes. What probes them holds no origin, and the
        # readiness payload names which dependency is unhealthy — not something
        # to make readable from an arbitrary web page.
        self._send(status, payload)
        return True

    def _api(self):
        """True when this was an /api/v1/ request and it has been answered."""
        if not (self.path or "").startswith(platform_api.PREFIX):
            return False
        raw = None
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if 0 < length <= MAX_BODY:
                raw = self.rfile.read(length)
            elif length > MAX_BODY:
                self._send(413, {"ok": False, "error": {
                    "code": "BODY_TOO_LARGE",
                    "message": "Request body is too large."}},
                    cors_headers(self._origin()))
                return True
        except Exception:
            raw = None

        # Only these two headers are forwarded, matching the mount in
        # apex/bot.py. No cookies: this API authenticates with a bearer token,
        # and a session cookie must never be able to stand in for one.
        out = platform_api.handle(
            self.command, self.path,
            {"Authorization": self.headers.get("Authorization") or "",
             "Stripe-Signature": self.headers.get("Stripe-Signature") or ""},
            raw,
            client_key=http_security.client_key(self))
        if out is None:
            self._send(404, {"ok": False, "error": {
                "code": "NOT_FOUND", "message": "No such endpoint."}},
                cors_headers(self._origin()))
            return True
        status, payload = out
        self._send(status, payload, cors_headers(self._origin()))
        return True

    def _dispatch(self):
        if self._health():
            return
        if self._api():
            return
        self._send(404, {"ok": False, "error": {
            "code": "NOT_FOUND", "message": "No such endpoint."}},
            cors_headers(self._origin()))

    def do_OPTIONS(self):
        """CORS preflight. 204 with the headers, or 403 without them.

        A preflight is answered for the paths this service serves and refused
        for everything else, so a probe cannot use OPTIONS to discover routes.
        """
        path = (self.path or "").split("?", 1)[0]
        known = path in _HEALTH_PATHS or path.startswith(platform_api.PREFIX)
        headers = cors_headers(self._origin())
        if not known or "Access-Control-Allow-Origin" not in headers:
            self._send(403, {"ok": False, "error": {
                "code": "ORIGIN_NOT_ALLOWED",
                "message": "This origin is not permitted."}}, headers)
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PATCH(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()


def build_server(port=None):
    """ThreadingHTTPServer, for the reason bot.py uses one.

    The plain HTTPServer handles one request at a time, so a slow broker read
    would block the health probe behind it and the platform would restart a
    container that was merely busy.
    """
    return ThreadingHTTPServer(("0.0.0.0", PORT if port is None else port),
                               Handler)


def _start_broker_probe():
    """Log, once at boot, whether THIS host can reach the broker at all.

    /readyz cannot answer this. Its cTrader check verifies that CTRADER_*
    variables are set, which is a different claim: a service can be perfectly
    configured and sit on a network that does not permit outbound TCP 5035, and
    the first sign would be a client whose account will not connect. cTrader
    Open API is protobuf over TLS on 5035, not HTTPS, and plenty of networks
    allow 443 and nothing else.

    IN A THREAD, because the probe can take seconds and the platform must bind
    $PORT promptly — a start-up that stalls fails the health check and the
    container is replaced. NEVER blocks and never raises: a diagnostic that can
    take the process down is worse than no diagnostic.

    Credential-free, one connection, closed before any application message.
    Set A4T_SKIP_BROKER_PROBE=1 to turn it off.
    """
    if (os.getenv("A4T_SKIP_BROKER_PROBE") or "").strip().lower() in (
            "1", "true", "yes", "on"):
        print("[API] broker reachability probe skipped "
              "(A4T_SKIP_BROKER_PROBE)")
        return

    def run():
        try:
            sys.path.insert(0, os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "scripts"))
            import check_ctrader_tls as chk
            r = chk.probe(env="demo", timeout=8.0)
        except Exception as e:                               # noqa: BLE001
            print(f"[API] broker reachability probe could not run "
                  f"({type(e).__name__}) — this is the probe failing, not the "
                  f"broker")
            return
        if r["ok"]:
            print(f"[API] broker reachable: {r['detail']}")
        else:
            print(f"[API] BROKER NOT REACHABLE at the {r['stage']} stage: "
                  f"{r['detail']}")
            print("[API] clients will not be able to connect a cTrader "
                  "account from this host. This is infrastructure, not "
                  "configuration — /readyz cannot see it.")

    threading.Thread(target=run, name="broker-probe", daemon=True).start()


def main():
    origins = allowed_origins()
    print(f"[API] Apex4Traders platform API starting on :{PORT}")
    print(f"[API] routes: /healthz, /readyz, {platform_api.PREFIX}*")
    if origins:
        print(f"[API] cross-origin callers allowed: {len(origins)}")
    else:
        print("[API] ⚠️  A4T_ALLOWED_ORIGIN is not set — the browser will block "
              "every call from the web client. Set it to the web service's URL.")
    # Said plainly at boot, because "is live trading off" is the question an
    # operator should never have to read code to answer.
    from apex.platform import entitlement as _ent
    print(f"[API] live execution enabled: {_ent.live_execution_enabled()}")

    _start_broker_probe()

    server = build_server()

    def _graceful(signum, _frame):
        print(f"[API] signal {signum} — shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()

    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(_sig, _graceful)
        except Exception as e:
            print(f"[API] could not install handler for {_sig}: {e}")

    try:
        server.serve_forever()
    finally:
        server.server_close()
        print("[API] stopped")


if __name__ == "__main__":
    main()
