# Apex4Traders v2 — proposed architecture

**State:** a proposal. Nothing that follows is implemented.
**Base:** commit `1bea525`, identical to the archive Codex analysed.
**Rule:** the system that trades today is not touched until there are agreed
contracts and a migration path.

---

## 1. What the product is, stated as an invariant

> When the conditions the client defined are met, execute the configured
> action, respecting the limits that are switched on.

Everything below follows from that. Three consequences that are not
negotiable, because without them the sentence above becomes false:

1. **Determinism.** The same configuration + the same market data = the same
   decision. No automatic selection, no fallback, no AI in the path.
2. **Traceability.** Every order must say *which version of the configuration*
   produced it and *which conditions* matched.
3. **Explicit refusal.** What cannot be executed to specification is not
   executed approximately. It is refused and recorded.

Point 3 is the one most often violated in the current code — see §4.

---

## 2. The layers

| Layer | Role | Source |
|---|---|---|
| **Versioned config** | the rule document, immutable once activated | **built** |
| **Deterministic evaluator** | (config, snapshot) → decision. A pure function. | **built** |
| **Condition library** | indicators and patterns, with mathematical definitions | **built** |
| **Risk checks** | limits, exposure, ownership, idempotency | **reused** (`gates.py`) |
| **Execution + reconciliation** | orders, confirmations, broker positions | **reused** (`brokers/ctrader.py`) |
| **Position management** | SL/TP/trailing/partials, across restarts | **adapted** (from `user_loop.py`) |
| **Journal + explanations** | what happened and why | **adapted** (`user_store` + `ev`) |
| **Interface** | connection, charts, builder, automation, journal | **built** |
| **Access and licensing** | entitlement, revalidation, revocation | **reused** (`access.py`, `gates`) |

---

## 3. What we reuse — and why it is worth it

We are not starting from zero. These components have been audited and have
tests that catch real regressions:

- **`apex/gates.py`** — centralised authorisation. `authorize_order` /
  `authorize_close` check entitlement, exposure, ownership and idempotency in
  one place. A recent audit confirmed there is no shortcut in the broker
  layer. **It remains the only gate.**
- **`apex/brokers/ctrader.py`** — OAuth, protobuf, reconnection, pagination,
  rate limiter (5/s historical, 50/s the rest, per connection), slippage
  ceiling. This is where the months of work are that a rewrite would lose.
- **`apex/ledger.py`** — the order idempotency ledger.
- **`apex/user_store.py`** — versioned records with compare-and-set, now for
  the journal too. **Exactly the primitive a versioned configuration needs.**
- **`apex/access.py`** + the licence server — entitlement and revocation.
- **The testing discipline** — 142 files, including a meta-test that rejects
  assertions made against comment text. Kept as the standard.

## 4. What we adapt

- **`apex/builder.py`** → becomes configuration authoring in the interface.
  Today it produces *patches* over a global configuration; it must produce a
  self-contained **rule document**.
- **`apex/forex.py::calc_units`** → the sizing mathematics is correct. What
  changes: risk comes **exclusively** from the configuration, with no
  multiplier.
- **`apex/user_loop.py`** → the tick loop, the market data and position
  management are kept. **The decision part is replaced** by the evaluator.

## 5. What we build

### 5.1 The rule document (`RuleDoc`)

Immutable once activated. Versioned with the same CAS primitive as the user
record. Every order carries `ruleDocId` + `version`.

It covers exactly what the client asked to control: account and instruments,
timeframe and evaluation moment (intrabar / at close), entry and exit
conditions with thresholds and periods, AND/OR combination, permitted
directions, order type and expiry, fixed volume or a risk formula,
SL/TP/trailing/break-even/partials, schedule and timezone, position and
exposure limits, behaviour when a threshold is hit, and state (draft / active
/ stopped).

**The three threshold behaviours are distinct fields**, not a single switch:
*block new entries*, *cancel pending orders*, *close positions*. They are
different operations and are configured separately.

### 5.2 The deterministic evaluator

```
evaluate(rule_doc, snapshot) -> Decision
```

A **pure** function: no I/O, no clock, no network. The clock and the data
arrive through `snapshot`, which is what makes the evaluator testable with
golden files.

`Decision` carries the action, **every evaluated condition with its result**,
and the reason. That is the source of the explanations in the interface — not
a separately generated text that may not match.

**No fallback.** An unknown strategy or condition is a validation error, not a
reason to substitute.

### 5.3 The condition library — a defined initial set

We do not promise every imaginable strategy. The proposed initial set, each
with a mathematical definition and documented parameters:

- **Indicators:** EMA, SMA, RSI, MACD, ATR, Bollinger, Stochastic
- **Structure:** HH/HL/LH/LL, break of structure
- **Level:** price vs level, vs indicator, vs band
- **Time:** session, time-of-day window, weekday
- **Patterns, with an explicit definition:** FVG, liquidity sweep,
  supply/demand

The last three go in **only** with a written mathematical definition and
parameters exposed to the client. Without that, a client cannot know what they
configured, and we cannot claim the platform executes to specification.

---

## 6. The contracts — to be settled BEFORE splitting the work

Five contracts. Until they are agreed, splitting the work across agents cannot
begin.

| # | Contract | Who depends on it |
|---|---|---|
| 1 | `RuleDoc` — JSON schema, versioning, validation | the interface and the engine, both |
| 2 | `MarketSnapshot` — what the evaluator receives | the engine; the interface for preview |
| 3 | `Decision` — what it returns, including evaluated conditions | the engine produces, the interface displays |
| 4 | `ExecutionRequest` — including mandatory constraints | the engine produces, execution consumes |
| 5 | The journal entry — tied to the configuration version | everything |

**Contract 4 contains the rule Codex proposed and which I support:** an
execution constraint marked mandatory that cannot be honoured **blocks the
entry**. It is not silently degraded.

---

## 7. Technical findings that contradict the direction — verified in the code

Each was verified against `1bea525`, not taken from the report.

| Place | What it does today | Why it contradicts the direction |
|---|---|---|
| `ai.py:1054` | `STRATEGY_MODES.get(mode, STRATEGY_MODES["mean_reversion"])` | an **unknown** mode silently becomes mean reversion — exactly the forbidden substitution |
| `user_loop.py:3135-3148` | `active_mode == "auto"` → strategy chosen by regime | automatic strategy selection |
| `user_loop.py:4280→4317` | `druckenmiller_multiplier(...)` → `calc_units(mult=...)` | risk varies **0.4×–1.2×** without the client choosing |
| `user_loop.py:4303` | `if regime == "volatile": risk_mult *= 0.5` | the effective floor drops to **0.2×** |
| `brokers/ctrader.py:1110-1116` | no quote → the order stays `MARKET`, with no ceiling | the configured protection is silently abandoned |
| `builder.py` | a wizard over existing strategies | it is not a condition builder |

**A refinement of Codex's report, point 4:** `advise_risk()` in
`strategy_modules.py` **is** advisory and **is** clamped by `_sanitize_advice`
to `[0.4, 1.2]` — but **the loop does not consume it at all**. The live path is
the **direct** call from `user_loop.py:4280`, which bypasses the advisory API.
The clamp comes from inside the function, not from `_sanitize_advice`. So: a
dormant advisory API, a live direct call. Both need handling, but they are
different things.

---

## 8. What we do NOT settle here

The fact that a client chooses their own settings **does not by itself
determine** the provider's liability, nor does it establish the product's legal
classification. The findings above are technical.

Requiring separate legal review: the product's classification, how liability is
worded, what may be claimed about loss thresholds, and the obligations towards
the client. **A loss threshold is not a guarantee against gaps or slippage** —
that is a technical finding, but how it is worded to the client is a legal one.

---

## 9. The first concrete step

Not implementation. **Contract 1 and the skeleton of contract 3.**

1. The `RuleDoc` schema as JSON Schema, with validation that explicitly
   refuses any unknown condition or strategy.
2. Three complete example configurations, written in the schema, as golden
   files.
3. The `Decision` structure, with every evaluated condition visible.
4. Tests asserting that **validation refuses** — invalid configuration, unknown
   condition, missing parameter, impossible threshold — with no substitution.

Only once those are agreed is the work split.
