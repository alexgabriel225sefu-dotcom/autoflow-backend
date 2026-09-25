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
MODULES = {}
for fn in sorted(os.listdir(PLATFORM)):
    if not fn.endswith(".py"):
        continue
    name = fn[:-3]
    with open(os.path.join(PLATFORM, fn), encoding="utf-8") as fh:
        src = fh.read()
    MODULES[name] = {"src": src, "tree": ast.parse(src, filename=fn)}


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


# ── 1. the execution boundary is not wired to anything ──────────────────────
print("\n[1] nothing in the platform imports the module that can place orders")
importers = sorted(m for m, deps in IMPORTS.items() if "bridge" in deps)
check("no platform module imports `bridge`", importers == [],
      f"imported by {importers} — wiring it up is the live-execution "
      f"milestone and needs its own review")
check("`bridge` exists, so this is an unwired path and not a missing file",
      "bridge" in MODULES)
check("and `execution` is reachable only through it",
      sorted(m for m, d in IMPORTS.items() if "execution" in d) == ["bridge"],
      str(sorted(m for m, d in IMPORTS.items() if "execution" in d)))

# ── 2. the automation entry point cannot reach it ───────────────────────────
# Reachability, not a direct-call check. A module two hops away is just as
# dangerous as one imported directly, and only the closure sees it.
print("\n[2] automation's transitive import closure holds no execution path")
auto = closure("automation")
check("automation reaches something (the closure is not empty)", bool(auto))
for forbidden in ("bridge", "execution"):
    check(f"automation cannot reach `{forbidden}`", forbidden not in auto,
          f"closure = {sorted(auto)}")
api_closure = closure("api")
for forbidden in ("bridge", "execution"):
    check(f"the API cannot reach `{forbidden}` either",
          forbidden not in api_closure)
check("preview cannot reach either", not ({"bridge", "execution"} & closure("preview")))

# ── 3. no module names an order-mutating operation ───────────────────────────
print("\n[3] no platform module names a broker-mutating operation")
MUTATING = ("place_order", "close_position", "amend_sltp", "force_trade",
            "authorize_order", "authorize_close", "modify_position")
for op in MUTATING:
    hits = sorted(m for m in MODULES
                  if m not in ("bridge", "execution") and op in names_in(m))
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
