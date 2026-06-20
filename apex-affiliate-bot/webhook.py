"""HTTP webhook — site-ul apelează asta când se face o vânzare sau un click."""
import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import store
import bot as affiliate_bot

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
PORT = int(os.getenv("AFFILIATE_PORT", "3002"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _auth(self, qs):
        if not WEBHOOK_SECRET:
            return True
        return qs.get("secret", [""])[0] == WEBHOOK_SECRET

    def _json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path

        # Health check
        if path == "/health":
            self._json(200, {"ok": True})
            return

        # Click tracking: /click?ref=XXXXXXXX
        if path == "/click":
            ref = qs.get("ref", [""])[0].strip().upper()
            if not ref:
                return self._json(400, {"error": "ref required"})
            ok = store.record_click(ref)
            self._json(200, {"ok": ok})
            return

        self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(min(length, 10_000))
        try:
            data = json.loads(body) if body else {}
        except Exception:
            return self._json(400, {"error": "invalid json"})

        if not self._auth(qs):
            return self._json(401, {"error": "unauthorized"})

        # Sale notification: POST /sale
        # Body: { "ref": "XXXXXXXX", "amount": 297, "product": "Apex Forex Bot" }
        if path == "/sale":
            ref = (data.get("ref") or "").strip().upper()
            amount = float(data.get("amount") or 0)
            product = data.get("product") or "Apex Bot"
            if not ref or amount <= 0:
                return self._json(400, {"error": "ref and amount required"})
            chat_id, commission = store.record_sale(ref, amount,
                                                    commission_pct=0.30,
                                                    product=product)
            if not chat_id:
                return self._json(404, {"error": "ref not found"})
            affiliate_bot.notify_sale(chat_id, amount, commission, product)
            print(f"[WEBHOOK] Sale ${amount:.2f} → ref {ref} → commission ${commission:.2f}")
            self._json(200, {"ok": True, "commission": commission})
            return

        self._json(404, {"error": "not found"})


def start_server():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[WEBHOOK] Listening on port {PORT}")
    server.serve_forever()
