"""The orchestrator: gather facts, ask the model, refuse most of what it says.

WHAT THIS IS FOR

§11 of the brief. One place that takes an analysis request, collects
deterministic facts through authorised tools, builds a prompt with the data
walled off from the instructions, calls whatever provider is configured,
validates the reply against a schema, and hands back a proposal that
deterministic code then re-checks.

The shape that matters is the last part. This module's output is never acted
on directly. `decision.evaluate` and `gates.authorize_order` both run
afterwards and either can refuse. The agent is an opinion with provenance
attached, not an instruction.

WHY IT IS SAFE WHEN THERE IS NO MODEL

With `NullProvider` — the default when nothing is configured — `analyse`
returns a result whose `action` is None and whose reason says no provider was
available. Callers treat that exactly like a rejection: the deterministic path
stands. That is the normal operating mode for this deployment, not a
degradation, because the host cannot run a local model and the operator wants
no paid API.

BOUNDED, ALWAYS

§19 and §43: the tool loop has a hard step cap, tool results are bounded, the
prompt is bounded, and a repeat request for the same subject inside a cooldown
is refused rather than queued. A runaway agent on a 0.5-CPU host would starve
the trading loop, which is the one thing on that host that must never stall.
"""

import hashlib
import os
import time

from apex import ai_provider, ai_schema, prompts, tools

AGENT_VERSION = "1.0.0"

# Every one is overridable (§66, §71). The defaults are chosen for a small
# host: few steps, short timeout, one request at a time.
DEFAULTS = {
    "max_tool_steps": 4,
    "timeout_s": 25.0,
    "cooldown_s": 90.0,
    "max_tool_result_chars": 3000,
}

# Outcomes. Distinct values because a screen and a journal both need to tell
# "the model refused" from "there was no model" from "the model was ignored".
OK = "OK"
NO_PROVIDER = "NO_PROVIDER"
PROVIDER_FAILED = "PROVIDER_FAILED"
INVALID_OUTPUT = "INVALID_OUTPUT"
COOLDOWN = "COOLDOWN"
STEP_LIMIT = "STEP_LIMIT"

# Per-subject memory, so repeated ticks on one candidate do not each buy an
# inference. Process-local: this is cost control, not a financial control, and
# a restart paying for one extra call is harmless.
_recent = {}


def _subject_key(kind, user_id, symbol, extra=""):
    raw = f"{kind}:{user_id}:{str(symbol).upper()}:{extra}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def reset_memory():
    _recent.clear()


class AgentResult:
    """One agent run, with everything needed to record and audit it."""

    __slots__ = ("outcome", "action", "payload", "tool_calls", "meta",
                 "detail", "latency_ms", "at")

    def __init__(self, outcome, *, action=None, payload=None, tool_calls=None,
                 meta=None, detail="", latency_ms=0):
        self.outcome = outcome
        self.action = action
        self.payload = payload or {}
        self.tool_calls = list(tool_calls or [])
        self.meta = dict(meta or {})
        self.detail = detail
        self.latency_ms = latency_ms
        self.at = time.time()

    @property
    def usable(self):
        """Only a validated reply from a working provider is usable."""
        return self.outcome == OK and self.action is not None

    def to_dict(self):
        return {
            "outcome": self.outcome, "action": self.action,
            "detail": self.detail, "latencyMs": self.latency_ms,
            "agentVersion": AGENT_VERSION,
            "toolCalls": [c.to_dict() for c in self.tool_calls],
            **self.meta,
            **{k: v for k, v in self.payload.items()
               if k in ("reason_codes", "supporting_evidence",
                        "invalidation_conditions", "uncertainties",
                        "reasoning", "symbol", "direction")},
        }

    def __repr__(self):
        return f"<AgentResult {self.outcome} action={self.action}>"


def _policy(overrides=None):
    p = dict(DEFAULTS)
    for k, env in (("max_tool_steps", "AI_MAX_TOOL_STEPS"),
                   ("timeout_s", "AI_TIMEOUT_S"),
                   ("cooldown_s", "AI_COOLDOWN_S")):
        v = os.getenv(env)
        if v:
            try:
                p[k] = type(p[k])(v)
            except (TypeError, ValueError):
                pass
    p.update(overrides or {})
    return p


def _gather(ctx, plan, *, max_steps, max_chars):
    """Run a fixed tool plan. Returns (data, calls).

    The plan is chosen by THIS code, not by the model. A model-driven tool loop
    is where §19's runaway comes from, and nothing in the analyses below needs
    one: the facts a market judgement rests on are known in advance.
    """
    data, calls = {}, []
    for name, args in plan[:max_steps]:
        out, rec = tools.call(ctx, name, args)
        calls.append(rec)
        if out is None:
            # A failed tool is a missing fact. It is recorded as absent rather
            # than filled in, so the model can say it could not determine
            # something instead of assuming a default.
            data[name] = {"_status": "UNAVAILABLE", "_error": rec.error}
            continue
        blob = out
        if len(str(out)) > max_chars:
            blob = {k: v for k, v in list(out.items())[:20]}
        data[name] = blob
    return data, calls


def analyse(user_id, *, kind, prompt_name, plan, subject, dash=None,
            environment=None, extra_data=None, policy=None):
    """Run one analysis. Never raises.

    `kind` and `subject` form the cooldown key. `plan` is the fixed list of
    (tool, args) this analysis needs. `extra_data` is deterministic context the
    caller already holds — a candidate, a thesis — merged into the DATA block.
    """
    t0 = time.time()
    pol = _policy(policy)
    key = _subject_key(kind, user_id, subject)

    prev = _recent.get(key)
    if prev and (t0 - prev) < pol["cooldown_s"]:
        return AgentResult(COOLDOWN, latency_ms=0,
                           detail=f"{kind} for {subject} ran "
                                  f"{t0 - prev:.0f}s ago")

    provider = ai_provider.select()
    status, health_detail, version = ai_provider.health()
    if status != ai_provider.READY:
        # Not an error. The deterministic engine is the platform's normal
        # operating mode on this host.
        return AgentResult(NO_PROVIDER, detail=f"{status}: {health_detail}",
                           meta={"aiStatus": status, **version})

    tmpl = prompts.get(prompt_name)
    if tmpl is None:
        return AgentResult(INVALID_OUTPUT, detail=f"no prompt {prompt_name!r}")

    ctx = tools.ToolContext(user_id, environment=environment, dash=dash,
                            symbol=subject)
    data, calls = _gather(ctx, plan, max_steps=pol["max_tool_steps"],
                          max_chars=pol["max_tool_result_chars"])
    if extra_data:
        data["context"] = extra_data

    text, meta = tmpl.render(data)
    meta.update(version)
    meta["toolsVersion"] = tools.TOOLS_VERSION

    _recent[key] = t0
    if len(_recent) > 256:
        for k in list(_recent)[:128]:
            _recent.pop(k, None)

    try:
        raw = provider.generate(text, timeout_s=pol["timeout_s"])
    except Exception as e:
        return AgentResult(PROVIDER_FAILED, tool_calls=calls, meta=meta,
                           detail=str(e)[:160],
                           latency_ms=int((time.time() - t0) * 1000))

    clean, why = ai_schema.safe_validate(
        raw, allowed_actions=frozenset(tmpl.actions), symbol=subject,
        require_evidence=True)
    ms = int((time.time() - t0) * 1000)
    if clean is None:
        # §40: an invalid reply is rejected, recorded, and changes nothing.
        return AgentResult(INVALID_OUTPUT, tool_calls=calls, meta=meta,
                           detail=str(why), latency_ms=ms)

    return AgentResult(OK, action=clean["action"], payload=clean,
                       tool_calls=calls, meta=meta, latency_ms=ms)


# ── The three analyses the platform actually needs ───────────────────────

def analyse_market(user_id, symbol, *, dash=None, environment=None, policy=None):
    """§12 Market Analyst — what is this instrument doing."""
    return analyse(user_id, kind="market", prompt_name="market_analysis",
                   subject=symbol, dash=dash, environment=environment,
                   policy=policy,
                   plan=[("get_market_state", {"symbol": symbol}),
                         ("get_market_regime", {"symbol": symbol}),
                         ("get_market_status", {}),
                         ("get_portfolio_risk", {})])


def analyse_candidate(user_id, candidate, *, dash=None, environment=None,
                      policy=None):
    """§12 Trade Analyst — does the evidence support taking this setup.

    The candidate is passed as data rather than re-derived: the scanner
    already measured it, and a second measurement here could disagree with the
    one the decision engine is about to use.
    """
    sym = getattr(candidate, "symbol", None)
    return analyse(user_id, kind="candidate", prompt_name="trade_analysis",
                   subject=sym, dash=dash, environment=environment,
                   policy=policy,
                   extra_data={"candidate": (candidate.to_dict()
                                             if hasattr(candidate, "to_dict")
                                             else candidate)},
                   plan=[("get_market_state", {"symbol": sym}),
                         ("get_market_regime", {"symbol": sym}),
                         ("get_portfolio_risk", {}),
                         ("get_position_state", {"symbol": sym})])


def analyse_position(user_id, symbol, thesis, *, dash=None, environment=None,
                     policy=None):
    """§12 Position Manager — does the original reason still hold."""
    return analyse(user_id, kind="position", prompt_name="position_management",
                   subject=symbol, dash=dash, environment=environment,
                   policy=policy,
                   extra_data={"thesis": (thesis.to_dict()
                                          if hasattr(thesis, "to_dict")
                                          else thesis)},
                   plan=[("get_position_state", {"symbol": symbol}),
                         ("get_market_state", {"symbol": symbol}),
                         ("get_market_regime", {"symbol": symbol}),
                         ("get_portfolio_risk", {})])


def record(user_id, result, *, symbol=None, decision_id=None):
    """Journal one agent run. Never raises; losing it costs an audit row."""
    try:
        from apex import trade_events as _te
        _te.record(user_id,
                   _te.AI_REJECTED if result.outcome in
                   (INVALID_OUTPUT, PROVIDER_FAILED) else _te.ANALYSIS_COMPLETED,
                   symbol=symbol, payload={**result.to_dict(),
                                           "decisionId": decision_id})
    except Exception as e:
        print(f"[Agent:{user_id}] journal write failed: {e}")


def status():
    """§75 — AI readiness, separate from trading readiness."""
    st, detail, version = ai_provider.health()
    return {"status": st, "detail": detail, "agentVersion": AGENT_VERSION,
            "toolsVersion": tools.TOOLS_VERSION,
            "prompts": prompts.versions(), **version}
