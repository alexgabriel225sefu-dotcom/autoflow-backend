"""The MetaTrader link flow: what it sends, and what it can never send.

The point of this connector is that a client's broker password does not reach
Apex4Traders. That is a claim about what leaves this process, so most of what
follows inspects the actual request rather than the return value.

Run: python3 tests/test_metaapi_vendor.py
"""
import inspect
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["A4T_MT5_VENDOR_BASE_URL"] = "https://vendor.test"
os.environ["A4T_MT5_VENDOR_TOKEN"] = "our-own-vendor-token"

from apex.platform.brokers import base                     # noqa: E402
from apex.platform.brokers import metaapi_vendor as V      # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


class Sent:
    """Captures one outgoing request instead of making it."""

    def __init__(self, reply, status=200):
        self.reply, self.status = reply, status
        self.url = self.method = None
        self.headers = {}
        self.body = None

    def __call__(self, req, timeout=None):
        self.url, self.method = req.full_url, req.get_method()
        self.headers = {k.lower(): v for k, v in req.headers.items()}
        self.body = req.data.decode() if req.data else None

        class R:
            def __init__(self, payload): self._p = payload
            def read(self_inner): return json.dumps(self.reply).encode()
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False
        return R(self.reply)


def with_sender(sender, fn):
    real = V.urllib.request.urlopen
    V.urllib.request.urlopen = sender
    try:
        return fn()
    finally:
        V.urllib.request.urlopen = real


print("\n[1] a client's password cannot be sent, because there is nowhere to put it")
_sig = inspect.signature(V.create_account)
_params = set(_sig.parameters)
check("create_account takes no password parameter",
      not any("password" in p.lower() for p in _params), str(sorted(_params)))
check("and no login parameter either",
      not any(p.lower() == "login" for p in _params), str(sorted(_params)))
check("it does take the broker server, which is not a secret",
      "server" in _params, str(sorted(_params)))
# The whole module, not just this function: a password field anywhere would
# make the claim in the docstring false.
_src = inspect.getsource(V)
_code = "\n".join(l for l in _src.splitlines()
                  if not l.strip().startswith("#"))
_code = _code.split('"""')
_code = "".join(_code[i] for i in range(0, len(_code), 2))   # drop docstrings
check("no password field is assembled anywhere in the module",
      '"password"' not in _code and "'password'" not in _code,
      "prose may mention it; code may not")


print("\n[2] what create_account actually puts on the wire")
s = Sent({"id": "acc-123"})
out = with_sender(s, lambda: V.create_account(
    name="Alex MT5", server="ICMarketsSC-Demo", platform="mt5"))
check("it returns the vendor's account id",
      out == {"accountId": "acc-123", "platform": "mt5"}, json.dumps(out))
check("it POSTs to the accounts endpoint",
      s.method == "POST" and s.url.endswith("/users/current/accounts"),
      f"{s.method} {s.url}")
_body = json.loads(s.body or "{}")
check("the body carries name, server, platform and magic",
      set(_body) == {"name", "server", "platform", "magic"}, json.dumps(_body))
check("and carries NO credential of any kind",
      "password" not in _body and "login" not in _body, json.dumps(_body))
check("our own vendor token authenticates the call",
      s.headers.get("auth-token") == "our-own-vendor-token")
check("a transaction id is sent, so a retry cannot open a second account",
      bool(s.headers.get("transaction-id")))

s2 = Sent({"id": "acc-9"})
with_sender(s2, lambda: V.create_account(name="x", server="y", platform="mt5"))
check("and that transaction id is different every call",
      s.headers.get("transaction-id") != s2.headers.get("transaction-id"))


print("\n[3] refusals before anything leaves the process")
for kwargs, code, why in (
    (dict(name="n", server="s", platform="mt3"), "UNSUPPORTED_PLATFORM", "a platform we do not support"),
    (dict(name="", server="s", platform="mt5"), "NAME_REQUIRED", "no name"),
    (dict(name="n", server="  ", platform="mt4"), "SERVER_REQUIRED", "no server"),
):
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("a request was made")
    try:
        with_sender(_boom, lambda: V.create_account(**kwargs))
        check(f"refuses {why}", False, "it did not refuse")
    except base.ProviderError as e:
        check(f"refuses {why}", e.code == code, e.code)
        check(f"  and sends nothing for {why}", called["n"] == 0)


print("\n[4] the configuration link")
s3 = Sent({"configurationLink": "https://vendor.test/configure/abc"})
link = with_sender(s3, lambda: V.configuration_link("acc-123", ttl_days=3))
check("it returns the link the client opens",
      link == "https://vendor.test/configure/abc", str(link))
check("asked for on the account's own path",
      "/users/current/accounts/acc-123/configuration-link" in s3.url, s3.url)
check("with the lifetime we chose", "ttlInDays=3" in s3.url, s3.url)
check("and the request body carries nothing",
      s3.body is None, str(s3.body))

for ttl, why in ((0, "zero days"), (-1, "a negative lifetime"), (True, "a boolean")):
    try:
        with_sender(Sent({}), lambda: V.configuration_link("acc-1", ttl_days=ttl))
        check(f"refuses {why}", False, "accepted")
    except base.ProviderError as e:
        check(f"refuses {why}", e.code == "BAD_TTL", e.code)


print("\n[5] the vendor's words never become ours")
class Boom:
    def __call__(self, req, timeout=None):
        import urllib.error
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {},
            __import__("io").BytesIO(
                b'{"message":"login MASTER-PASSWORD-abc123 rejected for '
                b'server ICMarketsSC-Demo"}'))


try:
    with_sender(Boom(), lambda: V.account_state("acc-123"))
    check("a vendor error is raised as our own", False, "no error raised")
except base.ProviderError as e:
    check("a vendor error is raised as our own", e.code == "VENDOR_REFUSED", e.code)
    # The vendor echoes the request in its errors. That is exactly how a
    # credential ends up in a log — it has happened in this repo before.
    check("and its message is not repeated",
          "MASTER-PASSWORD" not in e.detail and "ICMarkets" not in e.detail,
          e.detail)
    check("while still saying enough to diagnose", "400" in e.detail, e.detail)


print("\n[6] the state comes from the vendor, never from our own memory")
s4 = Sent({"_id": "acc-123", "name": "Alex MT5", "platform": "mt5",
           "state": "DEPLOYED", "connectionStatus": "CONNECTED",
           "login": "5001234"})
st = with_sender(s4, lambda: V.account_state("acc-123"))
check("a login at the vendor means the client finished configuring",
      st["configured"] is True, json.dumps(st))
check("and the connection status is reported, not inferred",
      st["connectionStatus"] == "CONNECTED", json.dumps(st))

s5 = Sent({"_id": "acc-123", "state": "CREATED", "connectionStatus": "DISCONNECTED"})
st2 = with_sender(s5, lambda: V.account_state("acc-123"))
check("no login yet is 'not configured', not an error",
      st2["configured"] is False, json.dumps(st2))
check("and the login itself is never carried back",
      "login" not in st2, json.dumps(st2))


print("\n[7] an unconfigured deployment refuses rather than pretends")
_tok = os.environ.pop("A4T_MT5_VENDOR_TOKEN")
try:
    V.create_account(name="n", server="s", platform="mt5")
    check("no vendor token is a refusal", False, "it tried anyway")
except base.ProviderError as e:
    check("no vendor token is a refusal", e.code == "VENDOR_NOT_CONFIGURED", e.code)
check("and configured() says so", V.configured() is False)
os.environ["A4T_MT5_VENDOR_TOKEN"] = _tok
check("with the token back, it is configured again", V.configured() is True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All MetaTrader vendor checks passed.")
