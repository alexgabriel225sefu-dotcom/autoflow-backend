"""Two invariants that must survive every future change.

ONE — every NEW live order clears the same gate. `gates.authorize_order`
holds entitlement, the risk guard as the loop published it, ownership, and
the idempotency claim. Four entry points reach it today: the strategy loop,
manual Telegram, the AI assistant (and through it the voice channel), and the
operator control plane. A fifth added later must not be able to reach the
broker without it, and the way that happens is not malice — it is somebody
adding a feature and calling `broker.place_order` because that is the obvious
function.

TWO — LIVE is an activation, never a setting. `_handle_paper` is the only
authoritative path: recorded risk acceptance, the account environment as the
BROKER reports it rather than the writable `ctrader_env` flag, a single-use
typed confirmation, an initial risk cap, and an audit entry.

Both are enforced structurally rather than by reading text, because a comment
saying "goes through the gate" is not the gate.

The second invariant caught a live bypass. `ob:mode:real` — an onboarding
button that survives in old chats, as its own comment said — wrote
`{"paper": False}` straight onto the record. None of the gates: no risk
acceptance, no broker verification, no confirmation, no cap, no audit. A
message from weeks earlier could still flip an account to real money.

Run: python tests/test_live_path_invariants.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APEX = os.path.join(ROOT, "apex")

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


def modules():
    for base, _dirs, files in os.walk(APEX):
        if "__pycache__" in base:
            continue
        for f in sorted(files):
            if f.endswith(".py"):
                p = os.path.join(base, f)
                yield p, ast.parse(open(p, encoding="utf-8").read())


def enclosing(tree, lineno):
    """The innermost function containing `lineno`."""
    best = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.lineno <= lineno <= (n.end_lineno or n.lineno):
                if best is None or n.lineno > best.lineno:
                    best = n
    return best


def calls_named(node, attr):
    return [n for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == attr]


print("\n🚦 LIVE PATH INVARIANTS\n")

print("1. Only the trading loop may touch the broker's mutating methods")
MUTATORS = ("place_order", "close_position", "amend_sltp")
for path, tree in modules():
    rel = os.path.relpath(path, ROOT)
    for attr in MUTATORS:
        for call in calls_named(tree, attr):
            obj = call.func.value
            is_broker = isinstance(obj, ast.Name) and "broker" in obj.id.lower()
            if not is_broker:
                continue
            check(f"{rel}:{call.lineno} {attr} is inside the loop",
                  rel.endswith("user_loop.py"),
                  "read-only surfaces (ops_api, miniapp_api, webapp) must stay read-only")

print("\n2. Every NEW order is authorised in the same function that places it")
LOOP = os.path.join(APEX, "user_loop.py")
LOOP_SRC = open(LOOP, encoding="utf-8").read()
loop_tree = ast.parse(LOOP_SRC)
placements = [c for c in calls_named(loop_tree, "place_order")
              if isinstance(c.func.value, ast.Name)
              and "broker" in c.func.value.id.lower()]
check("the order paths are still the two we know about", len(placements) == 2,
      f"found {len(placements)} — a new one must be audited, not assumed safe")
for call in placements:
    fn = enclosing(loop_tree, call.lineno)
    where = fn.name if fn else "<module>"
    gated = bool(calls_named(fn, "authorize_order")) if fn else False
    check(f"place_order at line {call.lineno} ({where}) clears authorize_order",
          gated, "an order that skips the gate skips entitlement, risk, "
                 "ownership and idempotency at once")

print("\n3. EVERY close is authorised, not just the operator's two")
# Naming force_close and force_close_all covered two of the six closes that
# reach the broker. The other four lived inside _loop — including the ordinary
# strategy exit, which the comment beside it calls the path that runs far more
# often than any gated one — and an enclosing-function check cannot see them:
# _loop calls authorize_close somewhere, so every close inside it would pass
# vacuously.
#
# So the check is per CALL SITE. Each close must have a gate, or the helper
# that contains one, within the lines just above it.
_LOOP_LINES = LOOP_SRC.splitlines()
_closes = [n for n in ast.walk(loop_tree)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr == "close_position"]
check(f"the close sites are still found ({len(_closes)})", len(_closes) >= 4,
      "if this drops to zero the check below passes by finding nothing")
for call in _closes:
    fn = enclosing(loop_tree, call.lineno)
    where = fn.name if fn else "<module>"
    if where == "_authorized_close":
        check(f"close_position at line {call.lineno} IS the gated helper", True)
        continue
    window = "\n".join(_LOOP_LINES[max(0, call.lineno - 46):call.lineno])
    gated = ("authorize_close" in window) or ("_authorized_close" in window)
    check(f"close_position at line {call.lineno} ({where}) clears a gate",
          gated,
          "a close that skips the gate skips ownership and idempotency: a "
          "non-owning instance can close what the owner is managing, and a "
          "timed-out close can be retried onto a position reopened since")

for fname in ("force_close", "force_close_all"):
    fn = next((n for n in ast.walk(loop_tree)
               if isinstance(n, ast.FunctionDef) and n.name == fname), None)
    if fn is None:
        continue
    check(f"{fname} clears authorize_close",
          bool(calls_named(fn, "authorize_close")),
          "an operator close still needs ownership and an idempotency claim")

check("the loop's own closes go through one helper",
      "_authorized_close" in LOOP_SRC,
      "so a new close added to the loop inherits the gate by construction")

print("\n4. LIVE is an activation — exactly one writer, and it is the gated one")
writers = []
for path, tree in modules():
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("update", "save")):
            continue
        for arg in n.args:
            if isinstance(arg, ast.Dict) and any(
                    isinstance(k, ast.Constant) and k.value == "paper"
                    for k in arg.keys):
                fn = enclosing(tree, n.lineno)
                writers.append((os.path.relpath(path, ROOT), n.lineno,
                                fn.name if fn else "<module>"))
check("exactly one place writes the live/demo flag", len(writers) == 1, writers)
check("and it is _handle_paper",
      bool(writers) and writers[0][2] == "_handle_paper", writers)

print("\n5. That writer applies every activation gate")
TG = os.path.join(APEX, "telegram.py")
tg_tree = ast.parse(open(TG, encoding="utf-8").read())
hp = next((n for n in ast.walk(tg_tree)
           if isinstance(n, ast.FunctionDef) and n.name == "_handle_paper"), None)
check("_handle_paper exists", hp is not None)
body = ast.get_source_segment(open(TG, encoding="utf-8").read(), hp) if hp else ""
check("it requires recorded risk acceptance", "risk_accepted" in body)
check("it asks the BROKER which account this is", "environment(" in body,
      "ctrader_env is writable; the connected account is not")
check("it requires a single-use confirmation", "consume_live_confirm" in body)
check("it caps the initial risk", "_LIVE_INITIAL_RISK_CAP" in body)
check("it writes an audit entry", "live_trading_activated" in body)

print("\n6. The onboarding buttons route through it instead of writing directly")
src = open(TG, encoding="utf-8").read()
for data, arg in (("ob:mode:real", '"off"'), ("ob:mode:paper", '"on"')):
    seg = src.split(f'if data == "{data}":')[1][:220]
    check(f"{data} calls _handle_paper({arg})",
          "_handle_paper(chat_id, " + arg in seg, seg[:120])
    check(f"{data} does not write paper itself", '"paper"' not in seg, seg[:120])

print("\n7. The control plane cannot set it either")
CA = open(os.path.join(APEX, "control_actions.py"), encoding="utf-8").read()
ca_tree = ast.parse(CA)
settable = next((sorted(e.value for e in n.value.elts if isinstance(e, ast.Constant))
                 for n in ast.walk(ca_tree) if isinstance(n, ast.Assign)
                 for t in n.targets
                 if isinstance(t, ast.Name) and t.id == "_SETTABLE"), [])
check("the settable allowlist is non-empty", bool(settable))
check("paper is not in it", "paper" not in settable,
      "read as a SET, not as text — the comment beside it mentions the word")
check("and the handler refuses it by name",
      'if key == "paper"' in CA,
      "defence in depth if the allowlist is ever edited carelessly")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — one gate for orders, one path to LIVE.")
