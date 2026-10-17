"""`platform_server.py` serves the platform and NOT the trading bot.

WHY THIS FILE EXISTS

The deployment blueprint originally said `startCommand: python -u main.py`, and
that was wrong in the worst available way. `main.py` starts `apex.bot.main()`,
which starts Telegram polling, the per-user trading loops and the operator
dashboard. Deploying it under a second name would have created a SECOND live
Telegram trading bot alongside the one already running.

It looked plausible because the platform's `/healthz`, `/readyz` and `/api/v1/*`
routes are mounted on that bot's HTTP handler, so the health check path in the
blueprint was real. The service behind it would not have been.

`platform_server.py` exists to serve only the platform surface. The property
that makes it safe to deploy is "it never reaches the trading bot", and that is
the property easiest to lose by accident — one convenience import away. So it is
checked here on the AST, by transitive closure, rather than trusted.

The second half of this file is CORS, which is not a nicety: the web client runs
on a different origin and calls `/api/v1/*` from the browser with an
`Authorization` header, so without a correct preflight reply the deployed
dashboard shows nothing but network errors.

Run: python3 tests/test_platform_server.py
"""
import ast
import json
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.update(
    APP_ENV="test",
    ALLOW_LOCAL_BACKEND_DEV="true",
    PRODUCT="forex",
    TOKEN_ENCRYPTION_KEY="cDcb_wSOjqAiI8jn9la_Vx3J1GpCVJyFlJXX6VYHHWI=",  # SYNTHETIC
    DATA_DIR=tempfile.mkdtemp(prefix="apex-platform-server-"),
)

ALLOWED = "https://apex4traders-web.onrender.com"
os.environ["A4T_ALLOWED_ORIGIN"] = ALLOWED

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


SERVER_PY = os.path.join(ROOT, "platform_server.py")

# ── 1. it does not reach the trading bot, by any import path ────────────────
print("\n[1] the trading bot is not reachable from the API entry point")


def apex_imports(path):
    """Every `apex.*` module this file imports, at any nesting depth."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("apex"):
                    out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:            # relative: not an apex.* absolute import
                continue
            if mod == "apex":
                for a in node.names:
                    out.add(f"apex.{a.name}")
            elif mod.startswith("apex"):
                out.add(mod)
                for a in node.names:
                    out.add(f"{mod}.{a.name}")
    return out


def module_path(mod):
    p = os.path.join(ROOT, mod.replace(".", os.sep) + ".py")
    return p if os.path.isfile(p) else None


def closure(entry):
    """Transitive apex.* closure. A name that is not a module is dropped."""
    seen, queue = set(), [entry]
    while queue:
        m = queue.pop()
        if m in seen:
            continue
        seen.add(m)
        p = module_path(m)
        if not p:
            continue
        for nxt in apex_imports(p):
            if nxt not in seen:
                queue.append(nxt)
    return seen

DIRECT = apex_imports(SERVER_PY)
check("it imports apex.platform.api", "apex.platform.api" in DIRECT, str(sorted(DIRECT)))
check("it imports apex.platform.health", "apex.platform.health" in DIRECT)
check("it imports apex.redact, so output is scrubbed", "apex.redact" in DIRECT)

for forbidden, why in (
    ("apex.bot", "starts Telegram polling, the trading loops and the dashboard"),
    ("apex.telegram", "is the Telegram transport"),
):
    check(f"it does NOT import {forbidden} directly — it {why}",
          forbidden not in DIRECT, str(sorted(DIRECT)))

CLOSURE = closure("apex.platform.api") | closure("apex.platform.health") | DIRECT
check(f"and apex.bot is absent from the whole transitive closure "
      f"({len(CLOSURE)} modules)",
      "apex.bot" not in CLOSURE,
      "something in the platform now pulls the trading bot in")

# Not just the imports: no CALL that starts a loop or places an order. Checked
# on the AST, not as a substring — the docstring names `apex.bot.main()` while
# explaining why it is not used, and a substring check reads that as a call.
# (The first version of this check did exactly that and failed on its own prose.)
with open(SERVER_PY, encoding="utf-8") as fh:
    SRC = fh.read()
TREE = ast.parse(SRC, filename="platform_server.py")


def called_names():
    """Every dotted name that appears in call position."""
    out = set()
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        parts = []
        while isinstance(f, ast.Attribute):
            parts.append(f.attr)
            f = f.value
        if isinstance(f, ast.Name):
            parts.append(f.id)
        if parts:
            out.add(".".join(reversed(parts)))
    return out


CALLED = called_names()
for bad in ("start_polling", "user_loop.start", "session_watch.start",
            "bot.main", "force_trade", "place_order", "close_position"):
    check(f"it never calls {bad}",
          bad not in CALLED and not any(c.endswith("." + bad) for c in CALLED),
          str(sorted(c for c in CALLED if bad.split(".")[-1] in c)))
# And the resolver is not vacuous: it does find the calls that ARE there.
check("the call resolver works — it sees redact.install()",
      "redact.install" in CALLED, str(sorted(CALLED))[:200])
check("and it sees server.serve_forever()",
      any(c.endswith("serve_forever") for c in CALLED))

# ── 2. the platform's own live-execution lock still reads False ─────────────
print("\n[2] this entry point cannot turn live execution on")
from apex.platform import entitlement as _ent                     # noqa: E402
check("entitlement.live_execution_enabled() is False",
      _ent.live_execution_enabled() is False)
check("and the server prints it at boot, so nobody has to read code",
      "live_execution_enabled()" in SRC)

# ── 3. the origin allowlist is configured, never reflected ─────────────────
# Reflecting Origin would let any site on the internet make authenticated
# requests with a victim's bearer token. This is the check that matters most in
# the file.
print("\n[3] CORS allows a configured origin and reflects nothing")
import platform_server as ps                                      # noqa: E402

check("the configured origin is allowed", ALLOWED in ps.allowed_origins())
check("an arbitrary origin is not",
      "https://evil.example" not in ps.allowed_origins())
check("the allowed origin gets an allow header",
      ps.cors_headers(ALLOWED).get("Access-Control-Allow-Origin") == ALLOWED)
for evil in ("https://evil.example", "http://" + ALLOWED.split("//")[1],
             ALLOWED + ".evil.example", "null"):
    check(f"no allow header for {evil}",
          "Access-Control-Allow-Origin" not in ps.cors_headers(evil),
          str(ps.cors_headers(evil)))
check("a trailing slash still matches, since a browser may send either",
      ps.cors_headers(ALLOWED + "/").get("Access-Control-Allow-Origin") == ALLOWED)
check("Vary: Origin is set even when refusing, or a cache could cross them over",
      ps.cors_headers("https://evil.example").get("Vary") == "Origin")
check("credentials are NOT allowed — this API reads a bearer token, not a cookie",
      "Access-Control-Allow-Credentials" not in ps.cors_headers(ALLOWED))
check("only Authorization and Content-Type are permitted as request headers",
      ps.cors_headers(ALLOWED).get("Access-Control-Allow-Headers")
      == "Authorization, Content-Type")

# With nothing configured, nothing is allowed — the failure is a dashboard that
# cannot reach its API, which is loud, not an API anyone may call.
_saved = os.environ.pop("A4T_ALLOWED_ORIGIN")
check("with A4T_ALLOWED_ORIGIN unset, no origin is allowed",
      ps.allowed_origins() == [] and
      "Access-Control-Allow-Origin" not in ps.cors_headers(ALLOWED))
os.environ["A4T_ALLOWED_ORIGIN"] = _saved
check("and it is read per request, so the dashboard value takes effect",
      ALLOWED in ps.allowed_origins())

# Several origins, for a custom domain alongside the onrender.com one.
os.environ["A4T_ALLOWED_ORIGIN"] = f"{ALLOWED}, https://app.example.test"
check("a comma-separated list is honoured",
      ps.cors_headers("https://app.example.test").get(
          "Access-Control-Allow-Origin") == "https://app.example.test"
      and ps.cors_headers(ALLOWED).get("Access-Control-Allow-Origin") == ALLOWED)
os.environ["A4T_ALLOWED_ORIGIN"] = ALLOWED

# ── 4. over a real socket ──────────────────────────────────────────────────
print("\n[4] and it behaves over a real socket")
srv = ps.build_server(port=0)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"


def req(path, method="GET", origin=None, headers=None):
    r = urllib.request.Request(f"{BASE}{path}", method=method)
    if origin:
        r.add_header("Origin", origin)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


status, hdrs, body = req("/healthz")
check("/healthz answers 200", status == 200, str(status))
check("and its body is JSON with ok:true",
      json.loads(body).get("ok") is True, body[:80])
check("/healthz sends no CORS header — a probe holds no origin",
      "Access-Control-Allow-Origin" not in hdrs)

status, hdrs, body = req("/readyz")
check("/readyz answers, and 503 here because nothing is configured",
      status in (200, 503), str(status))
_ready = json.loads(body)
check("it names which checks failed, so the owner knows what to configure",
      isinstance(_ready.get("checks"), list) and _ready["checks"], body[:80])
check("and it leaks no environment VALUE, only names",
      os.environ["TOKEN_ENCRYPTION_KEY"] not in body.decode(),
      "the key appeared in the readiness payload")

status, hdrs, _ = req("/api/v1/me", origin=ALLOWED)
check("an unauthenticated /api/v1/me is refused with 401", status == 401, str(status))
check("but it still carries the CORS header, so the browser can READ the 401 "
      "and say 'sign in' instead of showing a network error",
      hdrs.get("Access-Control-Allow-Origin") == ALLOWED, str(hdrs))

status, hdrs, _ = req("/api/v1/me", method="OPTIONS", origin=ALLOWED,
                      headers={"Access-Control-Request-Method": "GET",
                               "Access-Control-Request-Headers": "authorization"})
check("a preflight from the allowed origin gets 204", status == 204, str(status))
check("with the allow header", hdrs.get("Access-Control-Allow-Origin") == ALLOWED)

status, hdrs, _ = req("/api/v1/me", method="OPTIONS",
                      origin="https://evil.example",
                      headers={"Access-Control-Request-Method": "GET"})
check("a preflight from another origin is refused", status == 403, str(status))
check("and carries no allow header",
      "Access-Control-Allow-Origin" not in hdrs, str(hdrs))

# ── 4b. the OAuth callback answers a PERSON, not only a machine ────────────
# The route a third party redirects a browser to. It used to return the same
# JSON an API client gets, so the first real connection ended with somebody
# looking at {"ok": true, "nonce": ...} on a phone, refreshing — the only thing
# the page invited — and killing the attempt with STATE_REPLAYED.
print("\n[4b] the callback renders a page for a browser and JSON for a client")

CB = "/api/v1/ctrader/callback?code=x&state=bogus"
status, hdrs, body = req(CB, headers={"Accept": "text/html"})
html = body.decode("utf-8", "replace")
check("a browser gets HTML", "text/html" in (hdrs.get("Content-Type") or ""),
      str(hdrs.get("Content-Type")))
check("with the real status, not a cheerful 200", status == 400, str(status))
check("it says in words what went wrong", "Not connected" in html, html[:90])
check("it names the code for someone reporting it", "STATE_MALFORMED" in html)
check("it says nothing was linked, so nobody wonders",
      "Nothing has been linked" in html)
check("and it offers the way back rather than a dead end",
      "/connect" in html and "Back to Apex4Traders" in html)
check("the page loads nothing external — no script, no image, no font",
      "<script" not in html.lower() and "<img" not in html.lower()
      and "http://" not in html.replace("http://127.0.0.1", ""))

status, hdrs, body = req(CB)
check("a client with no Accept still gets JSON",
      "application/json" in (hdrs.get("Content-Type") or ""),
      str(hdrs.get("Content-Type")))
check("with the same code, so the two representations agree",
      json.loads(body)["error"]["code"] == "STATE_MALFORMED")

# The success page is what the person actually sees, so it is built directly
# rather than inferred from the failure one.
ok_html = ps.callback_page(200, {"ok": True, "nonce": "ABC123",
                                 "pendingOnly": True})
check("the success page says authorisation worked", "Authorised" in ok_html)
check("and says plainly that it is NOT the last step",
      "not the last step" in ok_html.lower(), ok_html[:120])
check("and carries the nonce back to the app, so a dead tab is survivable",
      "?n=ABC123" in ok_html, ok_html[-200:])
# A nonce is generated server-side, but the page renders whatever arrives, so
# it is treated as hostile input. Percent-encoded for the URL, HTML-escaped for
# the attribute — once each, which is what the first version got wrong.
_hostile = ps.callback_page(200, {"ok": True, "nonce": '"><script>alert(1)</script>'})
# Asserted on the ATTRIBUTE VALUE, not on the whole document: a first version
# looked for '"><' anywhere in the page and matched `<html lang="en"><head>`,
# its own template. A check that fires on legitimate markup teaches you to
# ignore it.
_href = re.search(r'<a class="btn" href="([^"]*)"', _hostile)
check("the link renders as a single well-formed href", bool(_href),
      _hostile[_hostile.find("<a "):][:120])
if _href:
    check("nothing in the nonce escapes the attribute",
          "<" not in _href.group(1) and ">" not in _href.group(1)
          and '"' not in _href.group(1), _href.group(1))
check("it is percent-encoded for the URL it sits in",
      "%3Cscript%3E" in _hostile or "%3cscript%3e" in _hostile.lower(),
      _hostile[_hostile.find("<a "):][:120])
check("and not double-encoded, which would render as gibberish",
      "&amp;lt;" not in _hostile)

status, _, body = req("/nope")
check("an unknown path is 404 JSON, not an HTML error page", status == 404)
check("with a machine-readable code",
      json.loads(body)["error"]["code"] == "NOT_FOUND", body[:80])

status, _, _ = req("/secret-admin", method="OPTIONS", origin=ALLOWED)
check("OPTIONS on an unknown path does not confirm it exists", status == 403,
      str(status))

srv.shutdown()
srv.server_close()

# ── 5. the blueprint points at THIS file ──────────────────────────────────
# The whole reason this file exists. If the blueprint drifts back to main.py,
# the next deploy starts a second trading bot.
print("\n[5] the deployment blueprint starts this, not the trading bot")
BP = os.path.join(os.path.dirname(ROOT), "docs", "deploy",
                  "render-apex4traders.yaml")
check("the blueprint exists", os.path.isfile(BP), BP)
if os.path.isfile(BP):
    with open(BP, encoding="utf-8") as fh:
        bp = fh.read()
    check("its start command runs platform_server.py",
          "platform_server.py" in bp, "it must not be main.py")
    # Not a substring check on "main.py": it appears in the prose explaining
    # why it is not used. Only the startCommand line matters.
    start_lines = [l for l in bp.splitlines() if "startCommand:" in l]
    check("there is a startCommand for each service", len(start_lines) == 2,
          str(start_lines))
    check("no startCommand runs main.py",
          not any("main.py" in l for l in start_lines), str(start_lines))
    check("and A4T_ALLOWED_ORIGIN is declared, or the browser blocks every call",
          "A4T_ALLOWED_ORIGIN" in bp)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("platform_server.py serves the platform only, never the trading bot, and "
      "its CORS allowlist is configured rather than reflected.")
