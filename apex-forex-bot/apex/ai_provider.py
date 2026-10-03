"""Where a model answer comes from — and how the platform runs without one.

WHY THIS EXISTS, GIVEN THE CONSTRAINT

The operator's constraint is that nothing may cost money. That rules out a
paid API, and — measured, not assumed — it also rules out Ollama on the
current host: the Render service has a 512 MB limit with 82 MB already used by
the bot, and the smallest useful quantised model needs about 700 MB. A model
there would not be slow, it would OOM the trading loop.

So the honest design is not "pick a cheaper model". It is: make the model
OPTIONAL, and make the platform's intelligence come from things that cost
nothing to run — the measured probability model, the deterministic scanner,
the risk engine.

That is what this module is for. It gives the rest of APEX one interface, and
three implementations behind it:

    NullProvider     no model at all. Not an error state — a supported one.
    OllamaProvider   a local model, when the operator has a machine for it.
    GroqProvider     the existing free-tier path, unchanged.

Selection is configuration. `AI_ENABLED=false` is a first-class answer, and
the deterministic engine keeps working — which was already true before this
module, and is now true explicitly rather than by accident.

WHAT A PROVIDER IS NOT ALLOWED TO BE

A provider returns text. It does not decide anything, it does not know what a
trade is, and nothing downstream may act on its output before
`ai_schema.validate` has accepted it. §90 of the brief is the rule that
matters most here and it is worth stating plainly: local does not mean
trusted. A model on your own machine can still hallucinate a symbol.
"""

import json
import os
import time
import urllib.error
import urllib.request

# ── Status vocabulary (§41, §75) ─────────────────────────────────────────
# Deliberately separate from trading readiness. "AI is offline" and "trading is
# blocked" are different facts and a screen that merges them will eventually
# tell a client their account is halted because a model is loading.
DISABLED = "DISABLED"
READY = "READY"
DEGRADED = "DEGRADED"
OFFLINE = "OFFLINE"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
STARTING = "STARTING"

STATUSES = (DISABLED, READY, DEGRADED, OFFLINE, MODEL_UNAVAILABLE, STARTING)

# How long a health verdict is trusted. §42: do not pay for an inference on
# every health request, and do not let a stale "READY" outlive a dead server.
_HEALTH_TTL_S = 60.0


class ProviderError(Exception):
    """The provider could not answer. Never a reason to assume approval."""


class AIProvider:
    """One interface. Text in, text out, plus an honest health reading."""

    name = "base"

    # Identity that goes into the journal with every decision (§33, §71), so a
    # historical record says which model produced it.
    def version(self):
        return {"provider": self.name, "model": None, "digest": None}

    def generate(self, prompt, *, timeout_s=None, max_tokens=None):
        raise NotImplementedError

    def health(self):
        """(status, detail). Cached by the caller, not here."""
        raise NotImplementedError

    @property
    def available(self):
        return self.health()[0] == READY


class NullProvider(AIProvider):
    """No model configured. A supported state, not a failure.

    `generate` raises rather than returning an empty string: a caller that
    treats "" as an answer would run it through the schema, get a rejection,
    and record an AI failure that never happened. Refusing loudly keeps the
    journal honest about the difference between "the model said something
    unusable" and "there is no model".
    """

    name = "none"

    def generate(self, prompt, *, timeout_s=None, max_tokens=None):
        raise ProviderError("no AI provider is configured")

    def health(self):
        return DISABLED, "no provider configured; the deterministic engine runs alone"


class OllamaProvider(AIProvider):
    """A local model over Ollama's HTTP API. No key, no account, no billing.

    Uses urllib rather than adding a dependency — the whole HTTP layer of this
    repository is stdlib, and a provider that is optional should not make the
    build heavier for everyone who does not use it.
    """

    name = "ollama"

    def __init__(self, base_url=None, model=None, timeout_s=None):
        self.base_url = (base_url
                         or os.getenv("OLLAMA_BASE_URL")
                         or "http://localhost:11434").rstrip("/")
        # No default model name. A hardcoded one would silently pull a model
        # the operator never chose, on a machine whose memory nobody checked.
        self.model = model or os.getenv("OLLAMA_MODEL") or ""
        self.timeout_s = float(timeout_s
                               or os.getenv("OLLAMA_TIMEOUT_MS", "30000")) / 1000.0
        self._digest = None

    def version(self):
        return {"provider": self.name, "model": self.model or None,
                "digest": self._digest}

    def _get(self, path, timeout_s):
        req = urllib.request.Request(f"{self.base_url}{path}",
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8") or "{}")

    def generate(self, prompt, *, timeout_s=None, max_tokens=None):
        if not self.model:
            raise ProviderError("OLLAMA_MODEL is not set")
        body = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            # Structured output. The schema check runs afterwards regardless —
            # this only raises the odds of getting past it.
            "format": "json",
            "options": {"temperature": 0,
                        **({"num_predict": int(max_tokens)} if max_tokens else {})},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate", data=body,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(
                    req, timeout=timeout_s or self.timeout_s) as r:
                out = json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            raise ProviderError(f"ollama HTTP {e.code}")
        except Exception as e:
            raise ProviderError(f"ollama unreachable: {str(e)[:100]}")
        text = out.get("response")
        if not text:
            raise ProviderError("ollama returned no response field")
        return text

    def health(self):
        """Reachable, and is the configured model actually pulled?

        Both halves matter. A reachable server with the model missing answers
        every request with an error, and reporting that as READY would put the
        failure at the wrong layer.
        """
        if not self.model:
            return DISABLED, "OLLAMA_MODEL is not set"
        try:
            tags = self._get("/api/tags", min(5.0, self.timeout_s))
        except Exception as e:
            return OFFLINE, f"cannot reach {self.base_url}: {str(e)[:80]}"
        names = []
        for m in (tags.get("models") or []):
            if isinstance(m, dict) and m.get("name"):
                names.append(m["name"])
                if m["name"].split(":")[0] == self.model.split(":")[0]:
                    self._digest = m.get("digest")
        want = self.model.split(":")[0]
        if not any(n.split(":")[0] == want for n in names):
            return MODEL_UNAVAILABLE, (f"{self.model} is not pulled "
                                       f"(have: {', '.join(names[:4]) or 'none'})")
        return READY, f"{self.model} on {self.base_url}"


class GroqProvider(AIProvider):
    """The existing free-tier path, wrapped so it sits behind the same door.

    `ai.py` still owns the call itself — this does not reimplement it, because
    a second implementation of the same request is exactly the kind of thing
    that drifts. It exists so `select()` can return something uniform and so
    the journal records which provider answered.
    """

    name = "groq"

    def __init__(self, model=None):
        self.model = model or os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile"

    def version(self):
        return {"provider": self.name, "model": self.model, "digest": None}

    def generate(self, prompt, *, timeout_s=None, max_tokens=None):
        from apex import ai as _ai
        try:
            out = _ai._call_groq(prompt)
        except Exception as e:
            raise ProviderError(f"groq: {str(e)[:100]}")
        if out is None:
            raise ProviderError("groq returned nothing")
        return out if isinstance(out, str) else json.dumps(out)

    def health(self):
        if not _groq_key():
            return DISABLED, "no GROQ_API_KEY"
        # Deliberately not an inference. §42 says not to pay for one on every
        # health check, and for a hosted provider the only cheap signal is
        # whether a key is present — so this reports "configured", and the
        # first real call is what proves it works.
        return READY, f"{self.model} (hosted, free tier)"


def _groq_key():
    """The key, from wherever this platform actually keeps it.

    Selection used to read os.environ while health read config, so the two
    could disagree — a key loaded from a .env would be invisible to selection
    and visible to health, and the provider would report DISABLED while the
    direct call worked. One source for both.
    """
    try:
        from apex import config as cfg
        if getattr(cfg, "GROQ_API_KEY", ""):
            return True
    except Exception:
        pass
    return bool(os.getenv("GROQ_API_KEY"))


# ── Selection ────────────────────────────────────────────────────────────
_cached = {"provider": None, "at": 0.0, "health": None, "health_at": 0.0}


def select(force=False):
    """The configured provider. Never raises; falls back to NullProvider.

    Order is explicit rather than clever: AI_PROVIDER wins if set, otherwise
    Ollama when a model is named, otherwise Groq when a key exists, otherwise
    nothing. "Nothing" is a valid outcome and the platform keeps trading.
    """
    now = time.time()
    if not force and _cached["provider"] is not None and now - _cached["at"] < 300:
        return _cached["provider"]

    enabled = (os.getenv("AI_ENABLED", "true").strip().lower()
               not in ("0", "false", "no", "off"))
    choice = (os.getenv("AI_PROVIDER") or "").strip().lower()

    if not enabled:
        p = NullProvider()
    elif choice == "ollama":
        p = OllamaProvider()
    elif choice == "groq":
        p = GroqProvider()
    elif choice in ("none", "null"):
        p = NullProvider()
    elif os.getenv("OLLAMA_MODEL"):
        p = OllamaProvider()
    elif _groq_key():
        p = GroqProvider()
    else:
        p = NullProvider()

    _cached.update({"provider": p, "at": now, "health": None, "health_at": 0.0})
    return p


def health(force=False):
    """(status, detail, version) — cached for _HEALTH_TTL_S.

    A cached READY must not outlive a server that died, which is why the TTL
    is a minute rather than the five the provider itself is cached for.
    """
    p = select()
    now = time.time()
    if not force and _cached["health"] and now - _cached["health_at"] < _HEALTH_TTL_S:
        status, detail = _cached["health"]
    else:
        try:
            status, detail = p.health()
        except Exception as e:
            status, detail = OFFLINE, f"health check raised: {str(e)[:80]}"
        _cached.update({"health": (status, detail), "health_at": now})
    return status, detail, p.version()


def reset():
    """Drop the caches. For tests, and for a deliberate reconfiguration."""
    _cached.update({"provider": None, "at": 0.0, "health": None, "health_at": 0.0})
