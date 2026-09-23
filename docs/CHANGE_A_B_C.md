# A → B → C — inventory before coding

**State:** order confirmed by Codex. **Nothing implemented.** This document
lists exactly what gets touched, which tests appear, and which existing tests
are at risk.

**Base:** `1bea525` (current production). **Not touched:** `apex/gates.py`,
environment settings (`PAPER_TRADING`, `CTRADER_ENV`, `BROKER`), `public/`.

---

## Constraints found during verification — read before implementing

### 1. The strategy registry is EMPTY at import (blocks A if ignored)

```
from apex import strategy_api            -> available() == 0
+ strategy_modules, _extra, _specialized -> available() == 17
```

The registry is populated by a **side effect** of importing the strategy
modules. Today `control_actions.py` imports only `automation, user_store,
user_loop, config`.

**Consequence:** a list built at module level in `control_actions.py` can be
**empty**, and then A rejects **every** valid strategy. Exactly the risk that
was flagged, but worse than it looked.

**Requirement:** the list is computed **lazily, inside the validation**, not at
import.

**Existing precedent in the code:** `telegram.py:3699` already does
`{sid: sid for sid in strategy_api.available()}` **inside**
`_handle_strategy()`, at call time. Same pattern.

### 2. Five of the six callers of `signal_for_mode` crash on `None` (this changes C's shape)

| Caller | Function | Consumes | `None` |
|---|---|---|---|
| `ai.py:217` | `get_signal()` | `rule_sig.get(...)` | ❌ AttributeError |
| `strategy_modules.py:48` | `signal()` | `self.stamp(verdict)` | ❌ |
| `strategy_modules.py:58` | `advise_risk()` | `own.get(...)` | ❌ AttributeError |
| `strategy_modules.py:81` | `exit()` | `verdict.get(...)` | ❌ AttributeError |
| `telegram.py:3626,3635` | `_sim_strategy()` | `sx.get(...)` | ❌ AttributeError |
| `scanner.py:143` | `scan_symbol()` | `... or {}` inside `try` | ✅ safe |

**Consequence:** "return `None`" is not the right shape — it would turn an
invalid strategy from a silent substitution into an exception in five
unprotected places.

**Two options, both of which satisfy your criteria:**

- **C-exception** — `signal_for_mode` raises `UnknownStrategyMode`.
  `scanner.py` already catches it (→ `setups.invalid`, correct). The other
  **five** need explicit handling. The most visible refusal, at the highest
  cost.
- **C-HOLD** — returns a verdict `{"action": "HOLD", "reasoning": "<mode>
  unknown — no entry"}`. Safe in all six without changing them, keeps the
  invalid name in the reason, places zero orders.

**My recommendation: C-HOLD.** It is an explicit refusal, not a fallback — it
trades nothing and names the invalid value. C-exception requires touching five
more files for the same observable result. **The decision is yours** — say
which.

---

## A — validation at write time

**Modified:** `apex/control_actions.py` — `_ENUM_KEYS` (line 99) and
`coerce_setting()` (104-133).

`strategy`, `symbol` and `timeframe` are today the only three keys in
`_SETTABLE` (16 total) with no validation at all — the other 13 have type
conversion.

Source of the list: `strategy_api.available()` ∪ `ai.STRATEGY_MODES` ∪
`{"auto"}`, **computed at call time**. No hand-written lists.

**New test:** `tests/test_setting_value_validation.py`
- every strategy in the registry is accepted
- an unknown id is **rejected at write time**, and the message lists the
  permitted values
- the same for `symbol` and `timeframe`
- **registry, not a list:** registers a fictitious strategy in `_REGISTRY` and
  checks that it becomes settable — fails if the list is duplicated
- **lazy import:** validation works even if the strategy modules were not
  imported before `control_actions`

**Existing tests at risk:** `test_control_actions.py`,
`test_remote_config_allowlist.py`, `test_config_reaches_loop.py`.
If any of them sets an invented strategy, it will start failing — **correctly**,
but it must be updated deliberately, not worked around.

## B — refusal at decision time

**Modified:** `apex/user_loop.py` — `_rule_signal()`, the block at 3181-3203.

Today the defence at 3194 is **in the `except` branch**: it covers "the module
crashed", not "the module does not exist". A `strategy_api.get()` returning
`None` skips the whole `if _strategy is not None` block and falls through to
`ai.signal_for_mode` at 3203.

It is extended to: module absent **and** unknown in `ai.STRATEGY_MODES` →
`HOLD`, with a reason that keeps the requested name.

**New test:** `tests/test_unknown_strategy_holds.py`
- module absent → `HOLD`, **zero** `place_order` calls
- the reason contains the **invalid value**, not the substituted one
- module present but raising → current behaviour, **unchanged**
- **mutation:** reintroducing the fall-through to `signal_for_mode` must fail
  the test

**Existing tests at risk:** `test_strategy_registry.py:329` asserts the literal
string `"ai.signal_for_mode(active_mode, ind, strat_data, open_pos)"` in the
source. It stays valid as long as that line is not deleted, but if the code is
restructured it must be updated — with an assertion on **behaviour**, not on a
string. Plus `test_strategy_equivalence.py`, `test_client_experience.py`.

## C — refusal at the source

**Modified:** `apex/ai.py:1053-1055` (`signal_for_mode`).
**Plus, only in the C-exception variant:** `ai.py:217`,
`strategy_modules.py:48/58/81`, `telegram.py:3626/3635`.

**New test:** `tests/test_signal_for_mode_refuses.py`
- unknown mode → refusal, never a mean-reversion verdict
- every known mode → unchanged
- **each of the six callers** handles the refusal without crashing
- mutation: reintroducing `default=STRATEGY_MODES["mean_reversion"]` fails

**Existing tests at risk:** `test_ai_contract.py:144`, `test_ai.py:98`,
`test_strategy_equivalence.py` (5 calls). All of them use **valid** modes, so
they should pass unchanged — to be confirmed at run time.

---

## Traversal — the test that matters most

**New:** `tests/test_no_silent_strategy_substitution.py`

Structural, over the AST, in the pattern of `test_live_path_invariants.py` —
**not over text strings**. It asserts that no path from a configuration value
to a trading decision can silently change the strategy.

It is the only test that stays valid if somebody later rewrites any of the
three places.

---

## Summary: what gets touched

| File | A | B | C |
|---|---|---|---|
| `apex/control_actions.py` | ✏️ | | |
| `apex/user_loop.py` | | ✏️ | |
| `apex/ai.py` | | | ✏️ |
| `apex/strategy_modules.py` | | | ✏️ C-exception only |
| `apex/telegram.py` | | | ✏️ C-exception only |

**New tests:** 4. **Existing tests to re-check:** 10.
**Untouched, confirmed:** `gates.py`, `public/`, the environment settings.

## What I need from Codex

1. **C-HOLD or C-exception?** The data is in §2 above.
2. Any objection to computing A's list lazily?
3. Confirmation that the existing tests marked "at risk" will be updated
   deliberately, not worked around.

**No line of code until confirmation.**
