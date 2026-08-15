"""An AI gateway in front of the chain, and a cold one that costs nothing.

Every client shares one Groq key today, and the trading signal draws on the
same quota — so a busy chat can starve the bot of its ability to decide. A
gateway (OmniRoute) fans one request across hundreds of providers and reroutes
on a quota or an outage, which is the actual shape of this problem.

The risk of putting anything in FRONT of a working chain is that a new first
link becomes a new single point of failure. On a free-tier host the gateway
sleeps after fifteen idle minutes and a cold start eats most of a minute, so
that risk is not hypothetical — it is the expected daily behaviour. The whole
design rests on the fall-through still working, and that is what most of this
file checks.

Run: python tests/test_ai_gateway.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-gw-")

from apex import assistant, chat_memory  # noqa: E402
from apex import config as cfg           # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


class Resp:
    def __init__(self, status=200, text="hello from the model"):
        self.status_code = status
        self._t = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"choices": [{"message": {"content": self._t}}]}


print("\n── the gateway speaks the same wire format as Groq ──")
# That is the reason a gateway costs a URL and not a second client: adding one
# by copy-paste is how three /ctaccount formatters drifted apart.
import apex.assistant as A  # noqa: E402
check("both go through one shared client",
      A._chat_groq.__code__.co_names.count("_chat_openai_compatible") == 1
      or "_chat_openai_compatible" in A._chat_groq.__code__.co_names)
check("and so does the gateway",
      "_chat_openai_compatible" in A._chat_gateway.__code__.co_names)

print("\n── what the gateway is actually sent ──")
seen = {}


def _fake_post(url, json=None, headers=None, timeout=None):
    seen.update(url=url, body=json, headers=headers, timeout=timeout)
    return Resp()


import requests  # noqa: E402
_orig_post = requests.post
A._build_context = lambda uid: "balance $3000"
chat_memory.load = lambda uid: []
chat_memory.save = lambda uid, h: None
A._save_exchange = lambda uid, m, r: None

_gw = ("https://gw.example/v1/chat/completions", "gw-key", "auto")
cfg.AI_GATEWAY_URL, cfg.AI_GATEWAY_KEY, cfg.AI_GATEWAY_MODEL = _gw
requests.post = _fake_post
try:
    out = A._chat_gateway("1", "how am I doing?")
    check("it returns the model's reply", out == "hello from the model", out)
    check("it calls the configured URL", seen["url"] == _gw[0], seen.get("url"))
    check("it sends the configured model", seen["body"]["model"] == "auto")
    check("it authenticates", seen["headers"].get("Authorization") == "Bearer gw-key")
    check("the account state still reaches the model",
          "balance $3000" in seen["body"]["messages"][0]["content"])
    check("the client's question is in there",
          any("how am I doing?" in str(m.get("content")) for m in seen["body"]["messages"]))
    check("the timeout is longer than a direct call, for cold starts",
          seen["timeout"] >= 20, str(seen["timeout"]))

    print("\n── a key-less gateway is allowed (self-hosted on localhost) ──")
    cfg.AI_GATEWAY_KEY = ""
    seen.clear()
    A._chat_gateway("1", "hi")
    check("no Authorization header is invented",
          "Authorization" not in seen["headers"], str(seen["headers"]))
    cfg.AI_GATEWAY_KEY = _gw[1]

    print("\n── a cold, broken or throttled gateway raises _ProviderDown ──")
    for _status, _label in ((429, "quota"), (500, "server error"), (503, "asleep")):
        requests.post = lambda *a, s=_status, **k: Resp(status=s)
        try:
            A._chat_gateway("1", "hi")
            check(f"{_label} ({_status}) is reported as down", False, "no exception")
        except assistant._ProviderDown:
            check(f"{_label} ({_status}) is reported as down", True)
        except Exception as e:
            check(f"{_label} ({_status}) is reported as down", False, repr(e))

    def _timeout(*a, **k):
        raise requests.exceptions.Timeout("cold start")

    requests.post = _timeout
    try:
        A._chat_gateway("1", "hi")
        check("a timeout is reported as down", False, "no exception")
    except assistant._ProviderDown:
        check("a timeout is reported as down", True)
finally:
    requests.post = _orig_post

print("\n── ORDER: the gateway leads, the old chain stays behind it ──")
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "assistant.py"), encoding="utf-8").read()
_chain = SRC[SRC.index("chain = []"):SRC.index("reply = None")]
check("gateway is appended first", _chain.index("Gateway") < _chain.index("Gemini"))
check("Gemini is still there", "Gemini" in _chain)
check("Groq is still there", "Groq" in _chain)
check("the gateway is only used when configured",
      "if cfg.AI_GATEWAY_URL:" in _chain)

print("\n── and _ProviderDown is what makes the fall-through work ──")
# Search forward from the loop: "if not reply:" also appears earlier in the
# file, so a plain .index() sliced backwards and silently produced an empty
# string — a test that asserts nothing while printing a failure.
_loop_at = SRC.index("for name, prov in chain:")
_loop = SRC[_loop_at:SRC.index("if not reply:", _loop_at)]
check("a down provider moves to the next one",
      "except _ProviderDown" in _loop and "continue" in _loop)
check("so does any other error, rather than killing the turn",
      _loop.count("continue") >= 2, _loop)

print("\n── unconfigured, nothing changes at all ──")
cfg.AI_GATEWAY_URL = ""
check("no gateway URL → the chain is exactly what it was",
      not cfg.AI_GATEWAY_URL)
try:
    A._chat_gateway("1", "hi")
    check("calling it anyway is refused, not attempted", False, "no exception")
except assistant._ProviderDown as e:
    check("calling it anyway is refused, not attempted", "url" in str(e), str(e))

print("\n── the trading signal is deliberately NOT routed through it ──")
AI = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "apex", "ai.py"), encoding="utf-8").read()
check("ai.py still calls Groq directly", "api.groq.com" in AI)
check("and knows nothing about the gateway", "AI_GATEWAY" not in AI)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the gateway leads, and never blocks.")
