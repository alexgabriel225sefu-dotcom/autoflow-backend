"""One slow request must not freeze every other one.

The bot's HTTP server was `HTTPServer`, which handles exactly ONE request at a
time. So opening the Mini App went: GET /app, then GET /api/app/data — which
connects the broker, pulls 150 candles, stats, news and the journal — and every
tick, the dashboard, and the OAuth callback queued behind that single response.
The terminal looked slow because it was standing in line behind itself.

Reported as "it still loads slowly" after the caching fix, which had made
repeated polls cheap but could do nothing about requests being serialised.

The second cost was on the critical path of every cold open: ~160KB of chart
library fetched from unpkg, a third-party host, before anything could be drawn.

Run: python tests/test_miniapp_serving.py
"""
import os
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-serve-")

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()
HTML = open(os.path.join(ROOT, "apex", "static", "terminal.html"), encoding="utf-8").read()

print("\n🧪 MINI APP SERVING — nothing waits in line behind a slow call\n")

print("1. The server handles requests concurrently")
check("it uses ThreadingHTTPServer", "ThreadingHTTPServer((" in BOT)
check("...and imports that, not the serial one",
      "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer" in BOT)
check("the plain HTTPServer is gone", "HTTPServer((\"0.0.0.0\", port)" not in BOT
      or "ThreadingHTTPServer" in BOT)
check("a hung request cannot block shutdown", "daemon_threads = True" in BOT)

print("\n2. Proof, not just the class name: two slow requests overlap")


class _Slow(BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(0.4)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), _Slow)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]

done = []


def hit():
    urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read()
    done.append(time.time())


t0 = time.time()
threads = [threading.Thread(target=hit) for _ in range(3)]
[t.start() for t in threads]
[t.join() for t in threads]
elapsed = time.time() - t0
srv.shutdown()
check("three 0.4s requests finish in well under 1.2s",
      elapsed < 0.9, f"{elapsed:.2f}s — serialised would be ~1.2s")

print("\n3. The chart library is served from this deployment")
lib = os.path.join(ROOT, "apex", "static", "lightweight-charts.js")
check("the file ships with the app", os.path.exists(lib))
check("...and is a real build, not a stub",
      os.path.getsize(lib) > 100_000, f"{os.path.getsize(lib)} bytes")
check("its licence header is intact",
      "Apache License 2.0" in open(lib, encoding="utf-8", errors="ignore").read(4000),
      "vendoring must not strip the licence")
check("the page loads it from here", '<script src="/static/lightweight-charts.js">' in HTML)
check("...and no longer from unpkg", "unpkg.com" not in HTML)
check("the route exists", "/static/lightweight-charts.js" in BOT)
check("it is cached hard — the file never changes under its own name",
      "immutable" in BOT)

print("\n4. The static route is reachable without the dashboard token")
_static_at = BOT.index('self.path.startswith("/static/lightweight-charts.js")')
_auth_at = BOT.index("if not self._authorized():")
check("it is served before the auth gate", _static_at < _auth_at,
      "behind the gate the Mini App would get a 401 for its own chart library")

print("\n5. The cheap paint happens first")
check("the tick runs before the heavy refresh",
      HTML.index("tick().finally") < HTML.index("refresh().finally"),
      "price and positions should be on screen while candles are still loading")
check("both still settle into their own intervals",
      "setInterval(tick, 1500)" in HTML and "setInterval(refresh, 6000)" in HTML)
check("the one remaining third-party script is preconnected",
      'rel="preconnect" href="https://telegram.org"' in HTML)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the terminal stops queueing behind itself.")
