"""Live execution is unreachable in this release — proved on the AST.

WHY NOT grep

`tests/test_platform_http.py` already asserts some of this by looking for
substrings. That catches `bridge.submit(...)` and misses
`getattr(mod, "submit")`, `fn = bridge.submit` passed somewhere else, an alias
introduced by `import ... as`, and a call assembled from a name in a dict. A
substring check is a reasonable smoke test and a poor invariant.

So this parses every module under `apex/platform/` and asks structural
questions: which modules import which, what a function's body actually
returns, which attribute names are referenced anywhere, and — the one that
matters most — what the transitive import closure of the automation entry
point contains.

THE CENTRAL FACT

`apex/platform/bridge.py` is the only module that can ask a broker to place an
order, and **nothing in production imports it**. Its only importer is its own
test. So `bridge.submit` is not merely gated, it is unreachable: there is no
sequence of calls from any request that arrives at it.

Wiring it up is the live-execution milestone. When somebody does, this file
fails — and that is the intent. The failure is the review gate.

`tests/test_live_path_invariants.py` covers the LEGACY Telegram bot's live
activation, which is a different product with a different path. This one is
about the platform.

Run: python3 tests/test_platform_live_invariants.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLATFORM = os.path.join(ROOT, "apex", "platform")

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


# ── parse everything once ───────────────────────────────────────────────────
# Walked, not listed. os.listdir() sees only the top level, so any module
# placed in a subpackage — say apex/platform/brokers/ — escaped every check in
# this file silently. That is the wrong way round: a new broker integration is
# exactly the kind of code these invariants exist for, and it is exactly the
# kind of code somebody puts in a subdirectory.
#
# Top-level modules keep their bare name as the key, so the checks below go on
# reading `func("entitlement", ...)`. Nested ones are keyed by their path,
# `brokers/mt5_cloud`, which is what appears in a failure message.
MODULES = {}
for _dir, _subdirs, _files in os.walk(PLATFORM):
    _subdirs[:] = [d for d in sorted(_subdirs)
                   if d != "__pycache__" and not d.startswith(".")]
    for fn in sorted(_files):
        if not fn.endswith(".py"):
            continue
        full = os.path.join(_dir, fn)
        rel = os.path.relpath(full, PLATFORM)[:-3].replace(os.sep, "/")
        with open(full, encoding="utf-8") as fh:
            src = fh.read()
        MODULES[rel] = {"src": src, "tree": ast.parse(src, filename=rel)}


def imports_of(name):
    """The `apex.platform.X` modules this module imports, by module name.

    Covers `from apex.platform import x`, `from apex.platform import x as y`,
    `import apex.platform.x` and `from . import x` alike, because an invariant
    that only understands one import form is an invariant with three holes.
    """
    out = set()
    for node in ast.walk(MODULES[name]["tree"]):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "apex.platform" or (node.level and mod in ("", None)):
                out.update(a.name for a in node.names)
            elif mod.startswith("apex.platform."):
                out.add(mod.split(".")[-1])
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("apex.platform."):
                    out.add(a.name.split(".")[-1])
    return {m for m in out if m in MODULES}


IMPORTS = {name: imports_of(name) for name in MODULES}


def closure(start):
    """Every platform module reachable from `start` by imports."""
    seen, stack = set(), [start]
    while stack:
        cur = stack.pop()
        for dep in IMPORTS.get(cur, ()):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def names_in(name):
    """Every attribute name, plain name and string constant in a module.

    String constants are included on purpose: `getattr(b, "place_order")`
    hides the call from an attribute check and not from this one.
    """
    out = set()
    for node in ast.walk(MODULES[name]["tree"]):
        if isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
    return out


def func(module, fname):
    for node in ast.walk(MODULES[module]["tree"]):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == fname:
            return node
    return None


def body_src(module, fname):
    node = func(module, fname)
    return "" if node is None else ast.get_source_segment(
        MODULES[module]["src"], node) or ""


# ── 1. the execution boundary is reachable only through the gates ───────────
# REWRITTEN, NOT DELETED — §12 of the specification asks for exactly this
# change, from "unreachable" to "reachable only through the gates".
#
# The old shape asserted that NOTHING imported `bridge`. That was right while
# the gates were built and unwired, and it stopped being the useful question
# the moment `live_execution` assembled them: an order path that nothing can
# reach proves only that it was never finished.
#
# The new shape says where the door is. `bridge` has exactly one importer,
# that importer is the module which runs every gate, and the module itself is
# imported by nothing — so the path is complete, auditable, and still not
# wired into anything that runs.
BOUNDARY = ("bridge", "execution", "live_execution")

print("\n[1] the order path is reachable only through live_execution")
importers = sorted(m for m, deps in IMPORTS.items() if "bridge" in deps)
check("`bridge` has exactly one importer, and it is the gated path",
      importers == ["live_execution"],
      f"imported by {importers} — anything else is a second way to an order")
check("`bridge` exists, so this is a wired path and not a missing file",
      "bridge" in MODULES)
check("and `execution` is reachable only through `bridge`",
      sorted(m for m, d in IMPORTS.items() if "execution" in d) == ["bridge"],
      str(sorted(m for m, d in IMPORTS.items() if "execution" in d)))
check("and NOTHING imports `live_execution` itself",
      sorted(m for m, d in IMPORTS.items() if "live_execution" in d) == [],
      f"imported by "
      f"{sorted(m for m, d in IMPORTS.items() if 'live_execution' in d)} — "
      f"turning it on is the §12 milestone and needs its own review")

# ── 1b. and that one path actually runs every gate ──────────────────────────
# The half of the rewrite that matters more than the import graph.
#
# "Reachable only through the gates" is worth nothing if the gated path does
# not contain the gates. Each of these modules was built with its own tests
# and wired to nothing; the failure this section exists to catch is one of
# them being dropped out of `place()` later, which no other test would notice
# because every gate's own tests would still pass.
print("\n[1b] the one path runs every gate the specification names")
_place = body_src("live_execution", "place")
check("live_execution.place exists", bool(_place))
for gate, what in (
    ("_emerg.check", "§8 the emergency stop"),
    ("live_execution_enabled", "§1 the release switch"),
    ("entitlement_of", "§2 the entitlement"),
    ("mode_reader", "§3 the mode, from the broker"),
    ("_rate.authorize", "§9 the per-client order rate"),
    ("_gates.authorize", "§5 the thirteen risk gates"),
    ("_ledger.claim", "§6 the duplicate-order claim"),
    ("_audit.record_live_order", "§7 the audit record"),
):
    check(f"it runs {what}", gate in _place, f"`{gate}` is not in place()")

# ORDER, not merely presence. A claim taken after the broker call is not a
# claim, and a risk gate run after the order is sent is a report.
_at = {g: _place.index(g) for g in
       ("_emerg.check", "_rate.authorize", "_gates.authorize",
        "_ledger.claim", "_audit.record_live_order")}
check("the emergency stop is checked before anything else",
      _at["_emerg.check"] < min(v for k, v in _at.items()
                                if k != "_emerg.check"))
check("the risk gates run before the claim is taken",
      _at["_gates.authorize"] < _at["_ledger.claim"])
check("the claim is taken before the audit record is written",
      _at["_ledger.claim"] < _at["_audit.record_live_order"])
check("and the broker is called after all of them",
      _place.index("broker or _default_broker") > max(_at.values()),
      "a gate that runs after the order is sent is a report, not a gate")

# §6's one rule, asserted on the source: an unknown outcome keeps the claim.
check("an unknown broker outcome abandons without releasing",
      "_ledger.abandon_unknown" in _place,
      "a submit that timed out may have filled; releasing there turns one "
      "uncertain order into two certain ones")
check("and the only release paths are the CONFIRMED ones",
      "_ledger.confirm_filled" in _place
      and "_ledger.confirm_rejected" in _place)

# The switch is checked INSIDE the path, so the module is safe to exist.
check("the release switch refuses before any broker work begins",
      _at["_emerg.check"] < _place.index("live_execution_enabled")
      < _place.index("_rate.authorize"),
      "every call refuses here today, which is what makes this module safe "
      "to have written before the §12 review")


# ── 2. the automation entry point cannot reach it ───────────────────────────
# Reachability, not a direct-call check. A module two hops away is just as
# dangerous as one imported directly, and only the closure sees it.
print("\n[2] automation's transitive import closure holds no execution path")
auto = closure("automation")
check("automation reaches something (the closure is not empty)", bool(auto))
for forbidden in BOUNDARY:
    check(f"automation cannot reach `{forbidden}`", forbidden not in auto,
          f"closure = {sorted(auto)}")
api_closure = closure("api")
for forbidden in BOUNDARY:
    check(f"the API cannot reach `{forbidden}` either",
          forbidden not in api_closure,
          f"closure = {sorted(api_closure)}")
check("preview cannot reach any of them",
      not (set(BOUNDARY) & closure("preview")),
      str(sorted(set(BOUNDARY) & closure("preview"))))

# ── 3. no module names an order-mutating operation ───────────────────────────
print("\n[3] no platform module names a broker-mutating operation")
MUTATING = ("place_order", "close_position", "amend_sltp", "force_trade",
            "authorize_order", "authorize_close", "modify_position")
for op in MUTATING:
    hits = sorted(m for m in MODULES
                  if m not in BOUNDARY and op in names_in(m))
    check(f"nothing outside the unwired boundary names `{op}`", hits == [],
          f"named in {hits}")

# ── 4. live_execution_enabled returns a literal, not a decision ─────────────
# The dangerous version of this function is one that reads an environment
# variable. Then a deployment enables an execution path that does not exist,
# and the only thing that was ever stopping it was a string in a config.
print("\n[4] live_execution_enabled is a constant, not configurable")
node = func("entitlement", "live_execution_enabled")
check("the function exists", node is not None)
returns = [n for n in ast.walk(node)
           if isinstance(n, ast.Return)] if node else []
check("it has exactly one return", len(returns) == 1, str(len(returns)))
if returns:
    val = returns[0].value
    check("and it returns a literal", isinstance(val, ast.Constant), type(val).__name__)
    check("and that literal is False", isinstance(val, ast.Constant)
          and val.value is False, getattr(val, "value", "?"))
if node:
    inner = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    check("it reads no name at all — no getenv, no flag, no import",
          not inner, str(sorted(inner)))
    calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
    check("and calls nothing", not calls, str(len(calls)))

# ── 5. the live-trading flag is read in exactly one place, to refuse ────────
print("\n[5] LIVE_TRADING_ENABLED is read once, and only to refuse")
readers = sorted(m for m in MODULES if "LIVE_TRADING_ENABLED" in names_in(m))
check("exactly one module reads it", readers == ["health"], str(readers))
if readers == ["health"]:
    body = MODULES["health"]["src"]
    i = body.index("LIVE_TRADING_ENABLED")
    window = body[max(0, i - 400):i + 600]
    check("and it is used to FAIL readiness, not to enable anything",
          "FAIL" in window, window[:120])
    check("and says no execution path exists for it",
          "not" in window and "implemented" in window)

# ── 6. all three locks are present, and each is its own construct ───────────
# Each has its own test elsewhere proving it refuses with the other two
# disabled. This asserts they still EXIST as separate things — the failure
# mode being a well-meaning refactor that merges them into one check.
print("\n[6] the three independent locks are still three")
env_lock = body_src("ctrader_link", "live_allowed")
check("lock 1: ctrader_link.live_allowed exists", bool(env_lock))
check("lock 1 requires production", "APP_ENV" in env_lock or "prod" in env_lock)
check("lock 1 ALSO requires an explicit flag",
      "APEX_ALLOW_LIVE_ACCOUNTS" in env_lock, "one lock is not two")

cap = body_src("entitlement", "capability")
check("lock 2: entitlement.capability exists", bool(cap))
check("lock 2 refuses a LIVE account", "LIVE" in cap and "LIVE_NOT_AVAILABLE" in cap)
check("lock 2 does not consult the entitlement when refusing live",
      cap.index("LIVE_NOT_AVAILABLE") > 0
      and "ent != PAID_LIVE" not in cap and "ent == PAID_LIVE" not in cap,
      "a paid plan must not unlock a path that does not exist")

pre = body_src("automation", "_preflight")
check("lock 3: automation._preflight exists", bool(pre))
check("lock 3 checks the resolved connection's own mode",
      'conn.get("mode")' in pre, pre[:80])
check("lock 3 calls the entitlement layer as well",
      "require_automation" in pre, "the two locks must both be invoked")

# ── 7. the refusal reaches the client as a code, not as English ─────────────
print("\n[7] the refusal is a code the UI can branch on")
check("LIVE_NOT_AVAILABLE is defined once, in entitlement",
      "LIVE_REFUSAL" in MODULES["entitlement"]["src"])
check("and automation reuses it rather than restating it",
      "_ent.LIVE_REFUSAL" in MODULES["automation"]["src"],
      "two copies of a refusal drift")

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print(f"All live-path invariants hold across {len(MODULES)} platform modules.")
