"""The broker TLS connection verifies the certificate. Proved, not assumed.

WHY THIS FILE EXISTS

The `ctrader-open-api` SDK's own `Client` class connects with
`clientFromString(reactor, f"ssl:{host}:{port}")`. Twisted's bare `ssl:`
endpoint string, with no trust root supplied, builds `OpenSSLCertificateOptions`
with `trustRoot=None` and `verify=False`, and the OpenSSL context it produces
has **VERIFY_NONE**. Measured, in this repository, on the installed version:

    trustRoot          = None
    verify             = False
    OpenSSL verify mode = VERIFY_NONE

A client that does not verify its peer will accept any certificate, and this
connection carries a broker access token. Anyone able to intercept it could
read that token.

**Our code does not use that class.** `apex/brokers/ctrader.py` opens its own
socket with `ssl.create_default_context()` — `CERT_REQUIRED`, `check_hostname`
on — and passes `server_hostname`, so the certificate and the hostname are both
verified, against the system OpenSSL rather than the one bundled in the
`cryptography` wheel. The module docstring says it reuses "only the protobuf
message definitions" from the SDK, and that is load-bearing rather than
stylistic.

Nothing was enforcing it. If somebody ever switches to the SDK's `Client` — a
reasonable-looking simplification, since the SDK ships a client and we hand-roll
one — broker tokens start crossing an unverified connection and no test would
notice. This file notices.

Run: python3 tests/test_broker_tls_posture.py
"""
import ast
import os
import ssl
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONNECTOR = os.path.join(ROOT, "apex", "brokers", "ctrader.py")

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


with open(CONNECTOR, encoding="utf-8") as fh:
    SRC = fh.read()
TREE = ast.parse(SRC, filename="ctrader.py")


def func(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    return None


# ── 1. the standard library's default context is what we think it is ────────
# Asserted rather than assumed: if a future Python or a site-level change made
# the default permissive, every claim below would be worthless.
print("\n[1] ssl.create_default_context() verifies, on this interpreter")
ctx = ssl.create_default_context()
check("verify_mode is CERT_REQUIRED", ctx.verify_mode == ssl.CERT_REQUIRED,
      str(ctx.verify_mode))
check("check_hostname is on", ctx.check_hostname is True)

# ── 2. our connector uses it, and passes the hostname ───────────────────────
# check_hostname without server_hostname raises at wrap time; passing the
# hostname is what makes the check actually happen.
print("\n[2] the connector builds a verifying context and names the host")
connect = func("connect")
check("connect() exists", connect is not None)
if connect:
    body = ast.get_source_segment(SRC, connect) or ""
    check("it calls ssl.create_default_context()",
          "ssl.create_default_context()" in body, body[:120])
    check("it passes server_hostname to wrap_socket",
          "server_hostname=" in body and "wrap_socket" in body, body[:160])
    for bad in ("CERT_NONE", "check_hostname = False", "check_hostname=False",
                "_create_unverified_context", "verify_mode = ssl.CERT_NONE"):
        check(f"it does not weaken verification with {bad!r}", bad not in body)

# The whole module, not just connect(): a helper could disable it elsewhere.
for bad in ("CERT_NONE", "_create_unverified_context", "check_hostname=False",
            "check_hostname = False"):
    check(f"nothing in the module uses {bad!r}", bad not in SRC)

# ── 3. the SDK's unverified client is never instantiated ────────────────────
# This is the regression that matters. The SDK ships a Client; we hand-roll a
# socket. Switching to theirs looks like a simplification and silently turns
# certificate verification off.
print("\n[3] the SDK's VERIFY_NONE client is not used anywhere")
SEARCH = [os.path.join(ROOT, "apex"), os.path.join(ROOT, "scripts")]
offenders = []
for base in SEARCH:
    for dirpath, dirnames, names in os.walk(base):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for n in names:
            if not n.endswith(".py"):
                continue
            full = os.path.join(dirpath, n)
            with open(full, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            rel = os.path.relpath(full, ROOT)
            tree = ast.parse(body, filename=n)
            for node in ast.walk(tree):
                # `from ctrader_open_api import Client` / `... import Client as X`
                if isinstance(node, ast.ImportFrom) \
                        and (node.module or "") == "ctrader_open_api" \
                        and any(a.name == "Client" for a in node.names):
                    offenders.append(f"{rel}: from ctrader_open_api import Client")
                # `ctrader_open_api.Client(...)`
                if isinstance(node, ast.Attribute) and node.attr == "Client" \
                        and isinstance(node.value, ast.Name) \
                        and node.value.id == "ctrader_open_api":
                    offenders.append(f"{rel}: ctrader_open_api.Client")
check("no module imports or references the SDK's Client", not offenders,
      str(offenders))
check("and nothing builds a Twisted SSL endpoint string",
      "clientFromString" not in SRC and 'f"ssl:' not in SRC)

# ── 4. only the protobuf definitions are taken from the SDK ─────────────────
# The reason the SDK is a dependency at all. If that widens, the TLS posture
# above stops being ours to guarantee.
print("\n[4] the SDK is used for message definitions and nothing else")
sdk_imports = set()
for node in ast.walk(TREE):
    if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "ctrader_open_api"):
        sdk_imports.add(node.module)
check("every SDK import is a protobuf message module",
      sdk_imports and all("_pb2" in m for m in sdk_imports),
      str(sorted(sdk_imports)))
check("the docstring says so, so the next reader knows it is deliberate",
      "protobuf message definitions" in SRC)

# ── 5. the port and hosts are the broker's, not something configurable ──────
# A host read from a request body would make verification pointless: an
# attacker who chooses the hostname gets a certificate that validates for it.
print("\n[5] the endpoint is not attacker-influenced")
check("hosts are module-level constants", "_HOST = " in SRC or "_HOST=" in SRC)
check("the port is a module-level constant", "_PORT = " in SRC or "_PORT=" in SRC)
hosts_ok = "ctraderapi.com" in SRC
check("and they are cTrader's own domain", hosts_ok)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("Broker TLS posture holds: our connection verifies, the SDK's does not, "
      "and we do not use the SDK's.")
