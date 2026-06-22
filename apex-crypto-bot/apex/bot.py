"""APEX TRADE BOT (crypto, Python) — entry point.

Multi-tenant: one process serves every paying client. Runs 24/7 on Render's
free tier via an HTTP health server + self-ping. Paper trading by default with
real Binance market data.
"""
import os
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from apex import config as cfg
from apex import telegram as tg


def _validate():
    if not cfg.TELEGRAM_BOT_TOKEN:
        print("❌  TELEGRAM_BOT_TOKEN not set!")
        sys.exit(1)
    if not cfg.ANTHROPIC_API_KEY and not cfg.GROQ_API_KEY:
        print("⚠️  No AI key (ANTHROPIC_API_KEY / GROQ_API_KEY) — using rule-based signals only.")
    print(f"✅  Telegram token: ...{cfg.TELEGRAM_BOT_TOKEN[-6:]}")
    print(f"✅  AI: {'Anthropic' if cfg.ANTHROPIC_API_KEY else ''}"
          f"{' + ' if cfg.ANTHROPIC_API_KEY and cfg.GROQ_API_KEY else ''}"
          f"{'Groq (free)' if cfg.GROQ_API_KEY else ''}" or "rule-based only")


# ─── Health server + self-ping (keeps Render free tier awake) ──
def _start_health_server():
    port = int(os.getenv("PORT") or 0)
    if not port:
        return
    render_url = (os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")

    server = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"✅  Health server on :{port}")

    if render_url:
        def _ping():
            while True:
                time.sleep(600)
                try:
                    requests.get(f"{render_url}/", timeout=10)
                except Exception:
                    pass
        threading.Thread(target=_ping, daemon=True).start()
        print(f"✅  Self-ping every 10 min → {render_url}/")


def main():
    print(f"[APEX TRADE BOT] Starting (crypto, Python {sys.version.split()[0]})...")
    _validate()
    _start_health_server()
    tg.refresh_from_config()
    tg.start_polling()
    print("🚀  Multi-tenant crypto bot live — clients activate via Telegram.")
    # Keep the main thread alive (polling + loops run as daemon threads).
    while True:
        time.sleep(3600)
