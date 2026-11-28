"""The engine modules are CALLED, not merely present.

An earlier commit added eight modules and wired none of them. They were inert:
built, tested in isolation, and reachable by nothing. That is a different
condition from "cannot execute" — which is the required architecture, not a
defect. §13 is explicit that the path runs

    decision proposal -> deterministic validation -> risk engine -> execution

so a decision module that cannot place an order is correct. A decision module
nothing calls is unfinished.

This file holds the second property. Each of the eight is asserted to be
reached from the live path, on the parsed source rather than by substring —
several of these modules name gates.authorize_order in prose in order to say
they do not call it.

Run: python tests/test_engine_active.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def src(mod):
    return open(os.path.join(ROOT, "apex", f"{mod}.py"), encoding="utf-8").read()


LOOP, AI, GATES = src("user_loop"), src("ai"), src("gates")


def imports_of(text):
    """Every apex module a file imports, including inside functions."""
    out = set()
    for n in ast.walk(ast.parse(text)):
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("apex"):
            out |= {a.name for a in n.names}
            out |= {(a.asname or a.name) for a in n.names}
        elif isinstance(n, ast.Import):
            out |= {a.name.split(".")[-1] for a in n.names}
    return out


LOOP_IMPORTS = imports_of(LOOP)

print("\n1. All eight modules are reached from the live path")
for mod, where in (("setups", LOOP), ("regime", LOOP), ("ranking", LOOP),
                   ("decision", LOOP), ("thesis", LOOP),
                   ("position_manager", LOOP), ("scanner", LOOP),
                   ("portfolio", GATES), ("ai_schema", AI)):
    check(f"{mod} is imported by the path that uses it",
          mod in imports_of(where), "still inert")

print("\n2. The scanner drives the scan, and the old one is gone")
check("the loop calls scanner.scan", "_scan.scan(" in LOOP)
check("...and decision.evaluate_all", "_dec.evaluate_all(" in LOOP)
check("...and ranking.rank", "_rank.rank(" in LOOP)
check("the inline confidence-only ranking is gone",
      's2["confidence"] > best[1]' not in LOOP,
      "ranking by confidence alone compared two strategies' self-assessments")
check("the pass is journalled", "_scan.record(" in LOOP)
check("the focused symbol comes from the top proposal",
      "best = (_top.symbol, _top.rank_score)" in LOOP)
check("a scan failure leaves the focus alone",
      "APEX scan failed" in LOOP,
      "the scan is how the bot finds work; a failure must not halt the loop")

print("\n3. Every instrument looked at produces a record")
SCAN = src("scanner")
check("a skipped symbol is still recorded",
      "not eligible this pass" in SCAN,
      "a blank screen cannot distinguish 'skipped' from 'never looked'")
check("an unreadable one is recorded as unreadable",
      SCAN.count("setups.invalid(") >= 4)
check("a symbol with no trigger is WATCH, not silence",
      "no trigger (" in SCAN)
check("one failing symbol does not stop the pass",
      "one symbol must not stop a pass" in SCAN)

print("\n4. The quote is only paid for once a direction exists")
_i_action = SCAN.index('if action not in ("BUY", "SELL"):')
_i_spread = SCAN.index("_spread_pips(broker, forex, symbol) if forex")
check("the bid/ask read happens after the trigger check",
      _i_action < _i_spread,
      "§28: cheap filters before expensive work")
check("an unread quote is None, never zero",
      "return sp if sp and sp > 0 else None" in SCAN,
      "a zero spread reads as a perfect fill")

print("\n5. The thesis is written at entry, from the setup that justified it")
check("the loop writes one", "_write_thesis(" in LOOP)
_tree = ast.parse(LOOP)
_wt = next((n for n in ast.walk(_tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_write_thesis"), None)
check("the writer exists", _wt is not None)
_wt_src = ast.get_source_segment(LOOP, _wt) or ""
check("it uses the scanner's own candidate when there is one",
      "_last_proposal.get(" in _wt_src)
check("a proposal for the other direction is refused",
      'cand.direction != action' in _wt_src,
      "reusing it would attach conditions nobody measured for this position")
# The CALL site, located on the parsed tree — `LOOP.index` finds the `def`
# first, which sits hundreds of lines above the entry block.
_call_lines = [n.lineno for n in ast.walk(_tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "_write_thesis"]
_entry_line = LOOP[:LOOP.index('"entryStrategyVersion": signal.get')].count("\n") + 1
check(f"it is called once, inside the entry block ({_call_lines})",
      len(_call_lines) == 1 and _call_lines[0] > _entry_line,
      "from the next tick the broker reports the CURRENT stop, which moves — "
      "this is the only moment the real fill and the sent stop are both known")
check("losing it costs a thesis, never the trade",
      "thesis write failed" in _wt_src)
check("the thesis is journalled", "_te.THESIS_CREATED" in _wt_src)

print("\n6. The AI schema rejects before the old normaliser runs")
check("_validate_verdict calls the schema", "_sch.safe_validate(" in AI)
check("...and takes the symbol that was asked about",
      "symbol=symbol" in AI.split("_sch.safe_validate(")[1][:200])
_i_sch = AI.index("_sch.safe_validate(")
_i_norm = AI.index('action = raw.get("action")')
check("the schema runs first", _i_sch < _i_norm,
      "the shape check cannot tell whether the reply answers the question")
check("a rejection returns None, never a HOLD",
      "return None" in AI[_i_sch:_i_sch + 900],
      "an unusable reply is not a neutral verdict")
check("a validator failure is also a rejection",
      "treating as unusable" in AI,
      "a bug in the check must not become a way past it")
check("the rejection is journalled against the account",
      "_te.AI_REJECTED" in AI and "user_id=user_id" in LOOP)

print("\n7. Being active did not make anything able to execute")
for mod in ("decision", "ranking", "setups", "regime", "thesis",
            "position_manager", "scanner", "portfolio", "ai_schema"):
    text = src(mod)
    tree = ast.parse(text)
    calls = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    check(f"{mod} calls nothing that executes",
          not (calls & {"place_order", "force_close", "close_position",
                        "amend_sltp", "authorize_order", "authorize_close"}),
          str(sorted(calls & {"place_order", "force_close", "close_position",
                              "amend_sltp", "authorize_order",
                              "authorize_close"})))
# Checked on parsed calls: the scanner's docstring names gates.authorize_order
# in order to say the scanner does not call it.
_scan_calls = {n.func.attr for n in ast.walk(ast.parse(SCAN))
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
check("gates still holds the idempotency claim", "ledger.claim(" in GATES)
check("...and the scanner does not authorise anything",
      not (_scan_calls & {"authorize_order", "authorize_close"}),
      str(sorted(_scan_calls)))
check("the scanner reads the broker but never writes to it",
      "get_candles" in SCAN and "get_bid_ask" in SCAN
      and "place_order" not in SCAN)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL ACTIVATION CHECKS PASSED - the eight are called, and still cannot execute.")
