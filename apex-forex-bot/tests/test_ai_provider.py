"""No model is a supported state, not a failure.

The operator's constraint is that nothing may cost money. That rules out a
paid API, and — measured rather than assumed — it also rules out Ollama on the
current host: the Render service caps at 512 MB with 82 MB already used by the
bot, while the smallest useful quantised model needs roughly 700 MB. A model
there would not run slowly; it would OOM the trading loop.

So the design this file protects is: the model is OPTIONAL, and the platform's
intelligence comes from what costs nothing to run — the measured probability
model, the deterministic scanner, the risk engine.

Three properties matter and each has bitten this kind of code before:

  1. no provider configured is DISABLED, and trading continues;
  2. NullProvider RAISES rather than returning "" — a caller that treated an
     empty string as an answer would run it through the schema, collect a
     rejection, and journal an AI failure that never happened;
  3. an unreachable Ollama reads OFFLINE and a missing model reads
     MODEL_UNAVAILABLE, because reporting either as READY puts the failure at
     the wrong layer.

Run: python tests/test_ai_provider.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex import ai_provider as P  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


_ENV = ("AI_ENABLED", "AI_PROVIDER", "OLLAMA_MODEL", "OLLAMA_BASE_URL",
        "GROQ_API_KEY", "OLLAMA_TIMEOUT_MS")
_SAVED = {k: os.environ.get(k) for k in _ENV}


def env(**kw):
    for k in _ENV:
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in kw.items() if v is not None})
    P.reset()


print("\n1. Nothing configured is a supported state")
env()
p = P.select()
check("selection yields NullProvider", isinstance(p, P.NullProvider), type(p).__name__)
check("...reported as DISABLED", p.health()[0] == P.DISABLED, str(p.health()))
check("...and it says the deterministic engine runs alone",
      "deterministic engine" in p.health()[1])
try:
    p.generate("anything")
    check("NullProvider.generate raises", False, "it returned instead")
except P.ProviderError:
    check("NullProvider.generate raises", True)
except Exception as e:
    check("NullProvider.generate raises ProviderError", False, type(e).__name__)

print("\n2. The operator can turn it off outright")
env(AI_ENABLED="false", OLLAMA_MODEL="llama3.2", GROQ_API_KEY="k")
check("AI_ENABLED=false outranks every other setting",
      isinstance(P.select(), P.NullProvider), type(P.select()).__name__)
for val in ("none", "null"):
    env(AI_PROVIDER=val, GROQ_API_KEY="k")
    check(f"AI_PROVIDER={val} selects nothing",
          isinstance(P.select(), P.NullProvider))

print("\n3. Ollama needs no key, and no model is invented")
env(OLLAMA_MODEL="llama3.2:1b")
p = P.select()
check("a named model selects Ollama", isinstance(p, P.OllamaProvider))
check("...with the configured model", p.model == "llama3.2:1b", p.model)
check("...and a default base url", p.base_url == "http://localhost:11434", p.base_url)
env()
bare = P.OllamaProvider()
check("no model name is defaulted", bare.model == "", repr(bare.model),)
check("...an unnamed model is DISABLED, not READY",
      bare.health()[0] == P.DISABLED, str(bare.health()))
try:
    bare.generate("x")
    check("...and generate refuses", False)
except P.ProviderError:
    check("...and generate refuses", True)

SRC = open(os.path.join(ROOT, "apex", "ai_provider.py"), encoding="utf-8").read()
check("no model name is hardcoded as a default",
      'os.getenv("OLLAMA_MODEL") or ""' in SRC,
      "a default would pull a model onto a host nobody sized")
check("no API key is required for the local path",
      "OLLAMA_API_KEY" not in SRC and "Authorization" not in SRC.split(
          "class GroqProvider")[0])

print("\n4. A broken Ollama reads broken")
env(OLLAMA_MODEL="llama3.2:1b", OLLAMA_BASE_URL="http://127.0.0.1:1")
st, detail = P.select().health()
check("unreachable reads OFFLINE", st == P.OFFLINE, f"{st}: {detail}")
check("...and names the endpoint", "127.0.0.1:1" in detail, detail)
check("MODEL_UNAVAILABLE is a distinct state from OFFLINE",
      P.MODEL_UNAVAILABLE != P.OFFLINE and P.MODEL_UNAVAILABLE in P.STATUSES,
      "a reachable server with no model fails at a different layer")
check("the health check does not run an inference",
      "/api/generate" not in SRC.split("def health", 2)[2].split("class ")[0],
      "paying for an inference per health request is what §42 forbids")

print("\n5. Selection never raises, whatever the configuration says")
for bad in ("nonsense", "", "OLLAMA", "groq"):
    env(AI_PROVIDER=bad)
    try:
        got = P.select()
        check(f"AI_PROVIDER={bad!r} yields a provider",
              isinstance(got, P.AIProvider), type(got).__name__)
    except Exception as e:
        check(f"AI_PROVIDER={bad!r} does not raise", False, repr(e))

print("\n6. Health is cached, but not forever")
env(OLLAMA_MODEL="m", OLLAMA_BASE_URL="http://127.0.0.1:1")
a, b = P.health(), P.health()
check("repeated calls are consistent", a == b)
check(f"the TTL is short ({P._HEALTH_TTL_S:.0f}s)", 0 < P._HEALTH_TTL_S <= 60,
      "a cached READY must not outlive a server that died")
check("the version accompanies the status",
      isinstance(a[2], dict) and "provider" in a[2] and "model" in a[2],
      str(a[2]))

print("\n7. AI status is not trading status")
check("the vocabulary is its own",
      set(P.STATUSES) == {P.DISABLED, P.READY, P.DEGRADED, P.OFFLINE,
                          P.MODEL_UNAVAILABLE, P.STARTING})
check("...and carries no trading state",
      not ({"LIVE", "DEMO", "SHADOW", "HALTED"} & set(P.STATUSES)),
      "merging them tells a client their account is halted because a model "
      "is loading")

print("\n8. A provider decides nothing and reaches no broker")
_tree = ast.parse(SRC)
_calls = {n.func.attr for n in ast.walk(_tree)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
check(f"it calls nothing that executes ({sorted(_calls)[:6]}…)",
      not (_calls & {"place_order", "force_close", "close_position",
                     "amend_sltp", "authorize_order", "authorize_close"}))
# Built as one explicit set. The first version of this check chained `&` and
# `|` in a single expression, and `&` binds tighter — so it asserted something
# other than what it read as, and passed for the wrong reason.
_imported = set()
for _n in ast.walk(_tree):
    if isinstance(_n, ast.ImportFrom):
        _imported.add((_n.module or "").split(".")[-1])
        if (_n.module or "") == "apex":
            _imported |= {a.name for a in _n.names}
    elif isinstance(_n, ast.Import):
        _imported |= {a.name.split(".")[0] for a in _n.names}
_forbidden = {"gates", "brokers", "ledger", "user_loop", "ctrader"}
check(f"it imports no risk engine or broker ({sorted(_imported)})",
      not (_imported & _forbidden), str(sorted(_imported & _forbidden)))
check("the Groq path delegates rather than reimplementing the call",
      "_ai._call_groq(prompt)" in SRC,
      "a second implementation of the same request is what drifts")

for k, v in _SAVED.items():
    os.environ.pop(k, None)
    if v is not None:
        os.environ[k] = v
P.reset()

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL PROVIDER CHECKS PASSED - no model is a state, not a failure.")
