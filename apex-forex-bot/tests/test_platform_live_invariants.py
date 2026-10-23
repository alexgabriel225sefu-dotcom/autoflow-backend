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


def body_src_of_tree(tree, src, fname):
    """The same, for a file outside `apex/platform/` — `apex/gates.py`.

    The wiring that permits real-money trading lives there, so an invariant
    file that could only read the platform package was reading everything
    except the part that matters most.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == fname:
            return ast.get_source_segment(src, node) or ""
    return ""


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
check("and no PLATFORM module imports `live_execution` behind the gate",
      sorted(m for m, d in IMPORTS.items() if "live_execution" in d) == [],
      f"imported by "
      f"{sorted(m for m, d in IMPORTS.items() if 'live_execution' in d)} — "
      f"its only caller is apex/gates.py, checked in [1c]")

# ── 1c. the engine gate is wired to the platform, and is the ONLY wiring ────
# This is the §12 milestone, and the invariant had to change shape with it.
#
# It used to say "nothing imports live_execution", which was the right
# question while the path was unwired and became the wrong one the moment the
# point was to wire it. What replaces it is narrower and harder: the path is
# reachable from EXACTLY ONE place, and that place is the single function
# every order origin in this codebase already converges on.
#
# `apex/gates.py` is outside `apex/platform/`, so none of the scanning above
# can see it. That was a real hole: the wiring that enables real-money
# trading lives in the one file these invariants were not reading.
GATES_SRC = open(os.path.join(ROOT, "apex", "gates.py"), encoding="utf-8").read()
GATES_TREE = ast.parse(GATES_SRC, filename="apex/gates.py")

print("\n[1c] the engine's order gate is the only thing that calls the path")


def _engine_importers():
    """Every module OUTSIDE apex/platform that names live_execution."""
    found = []
    for d, subs, files in os.walk(os.path.join(ROOT, "apex")):
        subs[:] = [s for s in subs if s not in ("__pycache__", "platform")
                   and not s.startswith(".")]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            p = os.path.join(d, fn)
            with open(p, encoding="utf-8") as fh:
                if "live_execution" in fh.read():
                    # Keep the AST contract portable: Windows returns
                    # backslashes from relpath while the repository contract
                    # uses POSIX-style module paths.
                    found.append(os.path.relpath(p, ROOT).replace(os.sep, "/"))
    return sorted(found)


_importers = _engine_importers()
check("exactly one engine module reaches the live path",
      _importers == ["apex/gates.py"],
      f"{_importers} — every extra one is a way round the gate")

_auth = body_src_of_tree(GATES_TREE, GATES_SRC, "authorize_order")
check("gates.authorize_order exists", bool(_auth))
check("and it calls the platform's live guard",
      "guard_engine_order" in _auth,
      "the one function that applies §1, §2, §3 and §9 to an engine order")
check("and only for a live PLATFORM account",
      "if live and is_platform:" in _auth,
      "a demo order must not pay for a broker round trip it does not need")
# Placement, not merely presence: before the claim, after the local checks.
# Same two reasons the portfolio check sits where it does.
check("before the idempotency claim",
      _auth.index("guard_engine_order") < _auth.index("ledger.claim"),
      "a platform refusal must not burn an idempotency key")
check("and it fails CLOSED",
      "LIVE_GUARD_FAILED" in _auth,
      "a platform outage is not permission to risk real money unexamined")
# ORDERING, and this one was a real outage rather than a hypothetical.
#
# `audit.py` refuses AT IMPORT on a process with no shared backend — which is
# §7 working — and `live_execution` imports it. So importing the live path
# merely to discover "this is not a platform account" raised, and the
# except-branch denied the order. Every Telegram-bot live order went through
# that branch. The legacy engine's own safety tests caught it; this pins the
# fix so that tidying the two steps back into one cannot land silently.
# Matched on the IMPORT STATEMENT, not the bare module name. The comment
# above the code explains this very hazard and so contains the name earlier
# in the function — the third time in this project that a guard has tripped
# on prose describing the thing it guards against.
_IMP = "from apex.platform import live_execution"
check("it classifies the account BEFORE importing the live path",
      "_platform_mode(user_id)" in _auth and _IMP in _auth
      and _auth.index("_platform_mode(user_id)") < _auth.index(_IMP),
      "importing the live path to find out it does not apply takes the "
      "legacy engine down with it wherever there is no shared backend")
# AND THE CLASSIFIER ITSELF MUST STAY CHEAP, which the original check could
# not see. The ordering above is worth nothing if the function that answers
# "is this a platform account, and is it live?" reaches the heavy path to do
# it — the import would simply move one frame down and take the engine with
# it exactly as before. `ctrader_link` imports clean; `live_execution` and
# `audit` do not.
_pm = body_src_of_tree(GATES_TREE, GATES_SRC, "_platform_mode")
check("the classifier exists", bool(_pm))
check("and it does not reach the live path to answer",
      "live_execution" not in _pm and "import audit" not in _pm,
      "the cheap question must stay cheap, or the ordering above is a fiction")
check("it reads the mode the BROKER confirmed, not a local flag",
      "selected_mode" in _pm,
      "`paper` is only ever written by the Telegram path, so reading it "
      "answered 'no real money' for every platform account that existed")

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

# The pilot guard (live_pilot) narrows who may trade real money to the
# operator's own account at a capped size. It is a gate like the others, so it
# is asserted on BOTH doors and in a fixed place on each: a guard that exists
# but is not called, or is called after the thing it protects, is decoration.
print("\n[1b2] the pilot guard is on both doors, in order")
_auth_door = body_src("live_execution", "authorize_order")
for _door_name, _door in (("place", _place), ("authorize_order", _auth_door)):
    check(f"{_door_name} asks the pilot guard who may trade",
          "_pilot.check_identity" in _door,
          f"`_pilot.check_identity` is not in {_door_name}()")
    check(f"{_door_name} asks the pilot guard which instrument and how much",
          "_pilot.check_order" in _door,
          f"`_pilot.check_order` is not in {_door_name}()")
    _i = _door.index("_pilot.check_identity") if "_pilot.check_identity" in _door else -1
    check(f"{_door_name}: the pilot identity check follows the entitlement and "
          f"precedes the broker read of the mode",
          _door.index("entitlement_of") < _i < _door.index("mode_reader()"),
          "a refused client must not cost a broker round trip, and a client "
          "told 'not entitled' should hear that before 'not in the pilot'")
_s_place = _place.index("_pilot.check_order") if "_pilot.check_order" in _place else -1
check("place: the size check runs on the built request, before the risk gates",
      _place.index("_bridge.build") < _s_place < _place.index("_gates.authorize"))
_s_auth = _auth_door.index("_pilot.check_order") if "_pilot.check_order" in _auth_door else -1
check("authorize_order: the size check follows the mode and precedes the rate",
      _auth_door.index("mode_reader()") < _s_auth < _auth_door.index("_rate.authorize"))
check("and the engine door is handed the account from the link record",
      'get("selectedCtid")' in body_src("live_execution", "guard_engine_order"),
      "the pilot account list is compared to the caller's own link record, "
      "never to a value from a request")

# The loop holds the account it was built on; the order gate must be told which,
# or a selection changed under a running loop silently drops it out of every
# live gate. Both order sites in user_loop must pass what their broker is bound
# to, and a live start must be held to the pilot before anything is running.
print("\n[1b3] the loop tells the order gate which account it holds")
_UL = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "user_loop.py")).read()
_sites = [seg for seg in _UL.split("gates.authorize_order(")[1:]]
check("user_loop has the two order sites", len(_sites) == 2, str(len(_sites)))
for _n, _seg in enumerate(_sites, 1):
    _call = _seg[:_seg.index(")\n")]
    check(f"order site {_n} passes the account its broker is bound to",
          "bound_account=" in _call and "CTRADER_ACCOUNT_ID" in _call,
          "without it the gate reads only the CURRENT selection")
    check(f"order site {_n} passes the environment its broker is bound to",
          "bound_env=" in _call and "CTRADER_ENV" in _call)
_pre = body_src("automation", "_preflight")
check("a live start is held to the pilot, after the broker confirmed the mode",
      "_pilot.check_identity" in _pre
      and _pre.index("verify_selected_mode") < _pre.index("_pilot.check_identity"),
      "a client outside the pilot must not be able to start a live loop")

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
# NARROWED, NOT RELAXED — and the one exemption is written down rather than
# discovered.
#
# This used to be a flat "nothing outside the boundary names any of these".
# That was the whole truth while the platform could not place an order at all.
# It stopped being the truth when Approval Required was made serviceable: the
# engine's approval level proposes a setup and waits, and somebody has to be
# able to say yes. `approvals.approve` is that somebody, and it places the
# trade by calling `user_loop.force_trade` — the single controller that
# already performs ownership.may_trade, gates.authorize_order, gates.audit,
# the ledger claim and only then broker.place_order.
#
# The alternative was worse in a way worth stating: re-implementing those five
# steps inside the platform, which is exactly what `bridge.py`'s docstring
# refuses to do, because two order paths that must both stay correct forever
# eventually disagree and the one that places orders wins.
#
# So the exemption is per-operation and per-module. `approvals` may name the
# one controller and NOTHING else on this list — no broker call, no gate, no
# closing or amending operation — and every other module still may not name
# any of them. The assertions below that one pin what `approvals` is allowed
# to be: one call site, no reachable execution path, and the suggestion
# claimed and cleared BEFORE the order is attempted.
print("\n[3] the only order-mutating name outside the boundary is the one "
      "controller")
MUTATING = {
    "place_order": (),
    "close_position": (),
    "amend_sltp": (),
    # The client's own approval of a setup the engine proposed. Nothing else.
    "force_trade": ("approvals",),
    "authorize_order": (),
    "authorize_close": (),
    "modify_position": (),
}
for op, allowed in MUTATING.items():
    hits = sorted(m for m in MODULES
                  if m not in BOUNDARY and m not in allowed
                  and op in names_in(m))
    check(f"nothing outside the unwired boundary names `{op}`", hits == [],
          f"named in {hits}")
check("and exactly one module is exempt, for exactly one operation",
      sorted(m for ms in MUTATING.values() for m in ms) == ["approvals"]
      and MUTATING["force_trade"] == ("approvals",),
      f"{ {k: v for k, v in MUTATING.items() if v} } — every addition here "
      f"is a second way to an order and needs the review this comment "
      f"describes")


def attr_calls(module, attr):
    """How many times a module names `attr` as an attribute.

    Attributes, not substrings: the prose above a call mentions the controller
    by name on purpose, and an invariant that counted the name would punish
    the explanation and pass the second call site.
    """
    return sum(1 for n in ast.walk(MODULES[module]["tree"])
               if isinstance(n, ast.Attribute) and n.attr == attr)


print("\n[3b] the exempt module has one call site and no path of its own")
check("`approvals` exists", "approvals" in MODULES)
check("and it names the controller exactly once",
      attr_calls("approvals", "force_trade") == 1,
      f"{attr_calls('approvals', 'force_trade')} references — one order path "
      f"means one call site")
check("and it names no broker or gate operation of its own",
      not [op for op in MUTATING if op != "force_trade"
           and op in names_in("approvals")],
      str([op for op in MUTATING if op != "force_trade"
           and op in names_in("approvals")]))
_appr_closure = closure("approvals")
for forbidden in BOUNDARY:
    check(f"and it cannot reach `{forbidden}`", forbidden not in _appr_closure,
          f"closure = {sorted(_appr_closure)}")
check("and it is reachable from the API, so this is wired and not a "
      "half-built module",
      "approvals" in api_closure, f"closure = {sorted(api_closure)}")

# ORDER, on the source, for the same reason `place()` is checked that way: a
# claim taken after the order is not a claim. Two requests can both read a
# pending suggestion before either acts, so the suggestion is claimed and then
# CLEARED before the controller is called — a second approve then finds
# nothing to approve even where there is no shared backend to claim against.
_appr = body_src("approvals", "approve")
check("approvals.approve exists", bool(_appr))
for token, what in (("claim_value", "the cross-process claim"),
                    ("_clear(user_id)", "dropping the suggestion"),
                    ("executor(user_id", "handing it to the controller")):
    check(f"approve runs {what}", token in _appr, f"`{token}` is not in it")
check("the suggestion is claimed before it is cleared",
      _appr.index("claim_value") < _appr.index("_clear(user_id)"))
check("and cleared before the order is attempted",
      _appr.index("_clear(user_id)") < _appr.index("executor(user_id"),
      "clearing after the order means a double tap can open two positions")
check("and an expired suggestion is refused rather than placed",
      "EXPIRED" in _appr and _appr.index("EXPIRED") < _appr.index("executor("),
      "a setup found five minutes ago is a price that has moved")

# ── 4. live_execution_enabled returns a literal, not a decision ─────────────
# The dangerous version of this function is one that reads an environment
# variable. Then a deployment enables an execution path that does not exist,
# and the only thing that was ever stopping it was a string in a config.
print("\n[4] the release switch is closed unless opened on purpose")
# REWRITTEN with the milestone, and the reasoning is worth keeping.
#
# This used to assert the function read NO name — no getenv, no flag — and
# returned the literal False. That was exactly right while there was no
# execution path behind it: a config string that enabled a code path which
# did not exist would have been the only thing standing between a deployment
# and undefined behaviour.
#
# The path exists now and every gate in front of it is wired and asserted, so
# the switch takes its ordinary shape: a per-deployment release decision. The
# question changes with it, from "can this be configured at all" to "can it
# be opened by ACCIDENT" — which is the failure that would actually happen.
import importlib  # noqa: E402

# Every other section here reads the AST and imports nothing. This one has to
# RUN the function: the failure it exists to catch is a sloppy truthiness
# test — `in ("1", "true", "yes")` — and no amount of reading the source
# proves what those return. `python -I` drops the cwd from sys.path, so the
# repo root goes on explicitly rather than depending on how it was invoked.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# `user_store` refuses to load without an encryption key, which is correct of
# it and has nothing to do with what this section tests. The dev escape is
# the one the other platform tests use.
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
_ent_mod = importlib.import_module("apex.platform.entitlement")
node = func("entitlement", "live_execution_enabled")
check("the function exists", node is not None)

_saved = os.environ.get(_ent_mod.LIVE_SWITCH_ENV)
try:
    # Closed by default, and closed for every value that is not THE value.
    # These are not hypotheticals: "1", "true" and "" are what a copied
    # config, a boolean-ish habit and a cleared variable actually look like.
    for val in (None, "", "0", "1", "true", "TRUE", "yes", "on", "enabled",
                "false", "off", "  ", "enabled-i-accept-real-money-ris"):
        if val is None:
            os.environ.pop(_ent_mod.LIVE_SWITCH_ENV, None)
        else:
            os.environ[_ent_mod.LIVE_SWITCH_ENV] = val
        check(f"closed when the variable is {val!r}",
              _ent_mod.live_execution_enabled() is False,
              "this value opened real-money trading")

    # And it does open — a switch that cannot be opened is not a switch, it
    # is a hardcoded False with extra steps, and nobody would find that out
    # until the day they needed it.
    os.environ[_ent_mod.LIVE_SWITCH_ENV] = _ent_mod.LIVE_SWITCH_ON
    check("open for the one exact value",
          _ent_mod.live_execution_enabled() is True,
          "the switch cannot be opened at all")
finally:
    if _saved is None:
        os.environ.pop(_ent_mod.LIVE_SWITCH_ENV, None)
    else:
        os.environ[_ent_mod.LIVE_SWITCH_ENV] = _saved

# The value is long and specific on purpose. A one-character switch is one
# typo away from being set by somebody who meant something else.
check("the value cannot be arrived at by accident",
      len(_ent_mod.LIVE_SWITCH_ON) > 20
      and _ent_mod.LIVE_SWITCH_ON not in ("1", "true", "yes", "on"),
      repr(_ent_mod.LIVE_SWITCH_ON))

# ONE READER. The danger a config switch introduces is a second place that
# decides what it means — a module that checks the variable itself and gets a
# different answer from the function everything else asks.
#
# Counted as GETENV CALLS, not as occurrences of the name. The substring
# version failed the moment health.py's refusal told an operator which
# variable the real switch is — which is exactly the right thing for that
# message to say. An invariant that forbids naming a thing punishes the
# documentation and lets a second `os.getenv` in some other form through; it
# is the READ that creates a second opinion, so the read is what to count.
def _getenv_reads(name):
    """Modules that pass `name` to os.getenv, by literal or by constant."""
    out = []
    for mod in MODULES:
        aliases = {"LIVE_SWITCH_ENV"}          # the constant, where exported
        for node in ast.walk(MODULES[mod]["tree"]):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn = node.func
            is_getenv = ((isinstance(fn, ast.Attribute) and fn.attr == "getenv")
                         or (isinstance(fn, ast.Name) and fn.id == "getenv"))
            if not is_getenv:
                continue
            a = node.args[0]
            if (isinstance(a, ast.Constant) and a.value == name) \
                    or (isinstance(a, ast.Name) and a.id in aliases) \
                    or (isinstance(a, ast.Attribute) and a.attr in aliases):
                out.append(mod)
                break
    return sorted(set(out))


_readers = _getenv_reads(_ent_mod.LIVE_SWITCH_ENV)
check("exactly one module reads the variable",
      _readers == ["entitlement"], str(_readers))
check("and health describes the switch by ASKING, not by re-reading it",
      "live_execution_enabled" in body_src("health", "_live_trading")
      and "health" not in _readers,
      "two readers is two answers to 'is live open'")
_fn_src = body_src("entitlement", "live_execution_enabled")
check("and it is read through os.getenv, not a cached module global",
      "os.getenv" in _fn_src,
      "a value read at import time cannot be turned off without a redeploy")

# ── 5. the live-trading flag is read in exactly one place, to refuse ────────
print("\n[5] LIVE_TRADING_ENABLED is a legacy name that enables nothing")
readers = sorted(m for m in MODULES if "LIVE_TRADING_ENABLED" in names_in(m))
check("exactly one module reads it", readers == ["health"], str(readers))
# READ FROM THE FUNCTION, NOT A CHARACTER WINDOW.
#
# This used to take ±400/600 characters around the first occurrence of the
# name in health.py. That worked until the function grew a docstring
# mentioning it, after which the window held prose and no code — and the
# second assertion then passed on the words "not" and "implemented" happening
# to appear in that prose, while asserting something that had become FALSE.
#
# A window around a string is not a scope. The function is.
_lt = body_src("health", "_live_trading")
check("the readiness check exists", bool(_lt))
check("and setting the flag FAILS readiness",
      "FAIL" in _lt,
      "somebody who sets it believes live trading is on; it is not")
check("it is never used to permit anything",
      "if _flag_on(\"LIVE_TRADING_ENABLED\")" in _lt
      and "FAIL" in _lt.split("if _flag_on(\"LIVE_TRADING_ENABLED\")")[1][:400],
      "the only branch it controls must be the refusing one")
# And the check reports the REAL switch, so an operator reading /readyz is
# told whether real money can move — which is the question they are asking.
check("and the check reports the real switch's state",
      "live_execution_enabled" in _lt,
      "readyz must not describe live trading from a variable that does not "
      "control it")

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
# These two assertions USED to say "lock 2 refuses a LIVE account" and "lock 2
# does not consult the entitlement when refusing live". Both still passed
# after live was wired, which is the worst way for an assertion to behave:
# the first passed because the string was still present on the switch-closed
# branch, and the second because the forbidden text was a comparison spelled
# a particular way and the new code calls a function instead.
#
# An assertion that keeps passing through the change it was written to catch
# is not protecting anything. So they are replaced by what is actually true
# and actually load-bearing now.
check("lock 2 asks the release switch FIRST",
      "live_execution_enabled" in cap
      and cap.index("live_execution_enabled") < cap.index("may_trade_live"),
      "a client must be told the release is closed before they are told "
      "their plan is wrong — one of those is a lie about what they bought")
check("lock 2 decides the plan by CALLING plans.may_trade_live",
      "may_trade_live" in cap,
      "the commercial rule belongs in plans.py, where answering it can "
      "unlock nothing")
check("lock 2 writes no tier comparison of its own",
      "ent != PAID_LIVE" not in cap and "ent == PAID_LIVE" not in cap,
      "a comparison here is one edit away from letting the wrong plan "
      "through, and this function guards real money")
check("lock 2 still has a refusal for a closed release",
      "LIVE_NOT_AVAILABLE" in cap)
check("and a DIFFERENT one for an unentitled plan",
      "LIVE_NOT_ENTITLED" in cap,
      "one code for two situations tells the client the wrong next step")

pre = body_src("automation", "_preflight")
check("lock 3: automation._preflight exists", bool(pre))
check("lock 3 asks the BROKER for the mode, not the record",
      "verify_selected_mode" in pre,
      "§3 — a stored mode is not a verified mode")
check("lock 3 calls the entitlement layer as well",
      "require_automation" in pre, "the two locks must both be invoked")
check("lock 3 re-asks the entitlement once the broker has answered LIVE",
      "capability" in pre and "canAutomate" in pre,
      "the first answer was derived from a stored record; a real-money "
      "loop is not started on the strength of one")

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
