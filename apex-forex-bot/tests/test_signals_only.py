"""Signals Only on the platform: the client is told, and nothing is placed.

THE TWO FACTS THIS PINS, AND WHY EACH ONE SHIPPED BROKEN ONCE

ONE. A LEVEL WHOSE OUTPUT GOES NOWHERE IS NOT A LEVEL.

`engine_config.translate` did not write the engine's `automation` key, so
`apex.automation.mode()` resolved every platform client to `approval` — and in
approval mode the loop proposes through `alert_fn`, which was None, because
`automation.start` started the loop as `user_loop.start(user_id)`. Every
platform client evaluated their rule, found setups, told nobody and placed
nothing, indefinitely, while the dashboard said Running. Commit 6f984dfe9 fixed
it by refusing to offer a level the platform cannot service.

`signals` has exactly the same dependency: `user_loop._signal_only` reports
through `alert_fn` and the caller sets `entry_ok = False`. So the invariant
below is stated over ALL THREE levels rather than over the one being added — a
level that neither executes nor is delivered must not be serviceable. That is
the question nobody asked last time.

TWO. NOTHING IS EVER PLACED, AND THAT IS NOT A MATTER OF GOOD BEHAVIOUR.

The refusal is the product at this level. So it is checked three ways that do
not depend on each other: the engine's own table says the level does not
execute, the dispatch in `_loop` sets `entry_ok = False` on the same line it
reports the signal, and the delivery module is parsed to prove it holds no
reference to an order path at all. One of those can be refactored away without
the other two going quiet.

Run: python3 tests/test_signals_only.py
"""
import ast
import os
import shutil
import sys
import tempfile
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-signals-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ["CTRADER_REDIRECT_URI"] = "https://apex4traders.test/cb"
from cryptography.fernet import Fernet                      # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("A4T_EMERGENCY_HALT", None)

import apex.automation as _eng_auto                        # noqa: E402
from apex import user_loop                                 # noqa: E402
from apex.brokers import ctrader as _ct_broker             # noqa: E402
from apex.platform import automation as AU                 # noqa: E402
from apex.platform import ctrader_link as CL               # noqa: E402
from apex.platform import engine_config as _ecfg           # noqa: E402
from apex.platform import journal as _j                    # noqa: E402
from apex.platform import journal_store as _jstore         # noqa: E402
from apex.platform import notifications as _notify         # noqa: E402
from apex.platform import ruledoc as _rd                   # noqa: E402
from apex.platform import signals as _sig                  # noqa: E402
from apex.platform import store as _pstore                 # noqa: E402

_ct_broker.list_accounts = lambda token: [{"ctid": 901, "live": False}]

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def _func(src, name):
    """One function's AST node, by name, from a module's source."""
    return next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef) and n.name == name)


def _names_in(fn):
    """Every identifier and string literal a function uses, MINUS its docstring.

    The docstring has to come out. Both of the functions asked about below
    explain in prose exactly the thing they must not do — `_signal_only` says
    it stores no `pending_suggestion`, `approvals.engine_alert` says it does
    not answer SIGNAL — so a plain substring search over the source finds the
    promise and reads it as the breach.
    """
    body = fn.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    out = set()
    for stmt in body:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                out.add(n.value)
            elif isinstance(n, ast.Attribute):
                out.add(n.attr)
            elif isinstance(n, ast.Name):
                out.add(n.id)
    return out


def _notes():
    """This client's signal notifications, or an empty page.

    `notifications.query` refuses a type it does not know, which is right of
    it — but it means a change that drops `signal` from TYPES would make this
    file explode instead of naming what broke, and the named report is the
    whole value of these tests.
    """
    try:
        return _notify.query(USER, type=_notify.SIGNAL)
    except ValueError as e:
        print(f"  (the notification centre refused the signal type: {e})")
        return {"notifications": [], "total": 0, "unread": 0}


USER = "5151a1a1-2222-4333-8444-515155556666"

# ── 1. the level's name is still the engine's name ──────────────────────────
print("\n[1] the level this module delivers for is a level the engine has")
check("signals.LEVEL_SIGNALS is one of automation.MODES",
      _sig.LEVEL_SIGNALS in _eng_auto.MODES,
      f"{_sig.LEVEL_SIGNALS!r} not in {_eng_auto.MODES} — the copy has drifted "
      f"and this module now delivers for a level that does not exist")

# ── 2. a level that neither executes nor is delivered is not serviceable ────
#
# THE INVARIANT THAT WOULD HAVE CAUGHT 6f984dfe9.
#
# Stated over every level, so it is not a restatement of the change that
# introduced it. For each one: either the engine acts on its own (nothing to
# deliver), or this platform has a delivery path for it, or the platform must
# refuse to run it. Any level in all three "no" columns is a loop that runs,
# finds setups and tells nobody — which is the state the product shipped in.
print("\n[2] no serviceable level is silent")
for level in _eng_auto.MODES:
    executes = bool(_eng_auto.EXECUTES[level])
    delivered = level in AU.DELIVERED_LEVELS
    serviceable = level in _ecfg.SERVICEABLE_LEVELS
    check(f"{level!r} is answerable: executes={executes} "
          f"delivered={delivered} serviceable={serviceable}",
          executes or delivered or not serviceable,
          f"{level!r} is offered by the platform, does not place orders, and "
          f"has nowhere to report to — a client would press Start, see "
          f"Running, and never be told anything")

check("signals is delivered by this platform",
      _sig.LEVEL_SIGNALS in AU.DELIVERED_LEVELS,
      "without this the level is only safe because it is refused, and the "
      "moment somebody makes it serviceable it goes quiet")

# ── 3. the engine never executes at this level ──────────────────────────────
print("\n[3] the engine itself says this level places nothing")
check("automation.EXECUTES says signals does not execute",
      _eng_auto.EXECUTES.get(_sig.LEVEL_SIGNALS) is False)
check("and executes() agrees for a record at that level",
      _eng_auto.executes({"automation": "signals", "copilot": False}) is False,
      "this is the function the loop asks before it sizes an order")
check("the level survives resolution — signals is not read back as full",
      _eng_auto.mode({"automation": "signals", "copilot": False}) == "signals",
      "signals and full are both copilot=False; only the stored mode "
      "separates them, and reading signals as full would trade an account "
      "that asked to be left alone")

_LSRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()

# ── 4. THE DISPATCH, RUN. NOT READ — RUN. ───────────────────────────────────
#
# This is the proof the task turns on, so it is behavioural: the REAL source
# of the loop's level dispatch is extracted and EXECUTED, once per level, and
# what is asserted is the value of `entry_ok` afterwards. Reading the source
# for the string "entry_ok = False" would pass just as well against a dispatch
# that never runs, and a loop that never runs is the bug that shipped.
#
# `_loop` cannot be called on its own — it needs a broker, candles, an AI
# gateway and 2500 lines of preceding state — so the branch is lifted out and
# given exactly the four names it reads. The text is the production text; if
# somebody edits that branch, this runs the edit.
print("\n[4] the loop's own dispatch, executed at each level")


def _find_dispatch(src):
    """The `if entry_ok:` block in `_loop` that resolves the client's level.

    Found through the AST rather than by matching the text, because a text
    anchor has to name the very lines under test: an anchor containing
    `automation.mode(...)` disappears the moment somebody changes how the
    level is read, and the test then fails by crashing instead of by saying
    what broke. Located structurally, that same edit is still executed and
    still judged.
    """
    for node in ast.walk(_func(src, "_loop")):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == "entry_ok"):
            continue
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        if "'signals'" in body or '"signals"' in body:
            return ast.get_source_segment(src, node)
    return None


_DISPATCH_SRC = _find_dispatch(_LSRC)
check("the loop's level dispatch can be located",
      _DISPATCH_SRC is not None,
      "no `if entry_ok:` in _loop mentions the signals level — either the "
      "dispatch moved, in which case point this at the new one, or the level "
      "is no longer dispatched at all, in which case nothing below is true")
_DISPATCH = textwrap.dedent(_DISPATCH_SRC or "entry_ok = None")


class _FixedLevel:
    """Stands in for `user_store` so the dispatch reads the level under test.

    Only `load` is reached from the branch. The real `_signal_only` keeps using
    the real user_store for its own throttle, which is what makes the run
    realistic rather than a mime of one.
    """

    def __init__(self, record):
        self.record = record

    def load(self, _uid):
        return dict(self.record)


def _run_dispatch(level, symbol):
    """Execute the real branch for `level`. Returns (entry_ok, suggested)."""
    suggested = []
    ns = {
        "entry_ok": True,
        "automation": _eng_auto,
        "user_store": _FixedLevel(_eng_auto.patch(level)),
        "_signal_only": user_loop._signal_only,
        "_suggest_trade": lambda *a, **k: suggested.append(a),
        "user_id": USER, "symbol": symbol, "price": 1.2345,
        "alert_fn": AU.engine_alert,
        "signal": {"action": "BUY", "confidence": 71,
                   "reasoning": "executed dispatch", "keyFactors": ["live"]},
    }
    exec(_DISPATCH, ns)                                     # noqa: S102
    return ns["entry_ok"], suggested


# FIRST, PROVE THE HARNESS CAN SEE A POSITIVE. At `full` the dispatch must
# leave the entry standing — if this came back False, every "nothing was
# placed" below would be worthless, because an inert harness refuses
# everything.
_n_full = _notes()["total"]
_ok_full, _sugg_full = _run_dispatch("full", "USDCHF")
check("at FULL the dispatch leaves the entry standing",
      _ok_full is True,
      "the harness cannot tell a refusal from an inert test — every check "
      "below this line would pass against a dead loop")
check("and delivers no signal at that level",
      _notes()["total"] == _n_full, "full automation trades; it does not report")

# NOW THE REFUSAL, from the same executed source.
_n_sig = _notes()["total"]
_ok_sig, _sugg_sig = _run_dispatch("signals", "EURJPY")
check("at SIGNALS the dispatch REFUSES the entry",
      _ok_sig is False,
      "entry_ok left True is an order placed for a client who asked to be "
      "told and nothing more — this is the one thing that must never happen")
check("and it delivered the setup instead",
      _notes()["total"] == _n_sig + 1,
      "refusing and saying nothing is the other failure; at this level the "
      "report IS the product")
check("and it stored no approval proposal",
      not _sugg_sig,
      "a pending suggestion is redeemable by an Approve tap, so routing a "
      "signal through the approval path would turn it into an order later")

# And the approval level still behaves as it did, from the same source.
_ok_appr, _sugg_appr = _run_dispatch("approval", "EURCHF")
check("at APPROVAL the dispatch refuses and proposes",
      _ok_appr is False and bool(_sugg_appr),
      f"entry_ok={_ok_appr} suggested={bool(_sugg_appr)}")

# WHAT entry_ok = False ACTUALLY BUYS, stated over the loop's structure:
# there is ONE order call in `_loop`, and it is inside `if entry_ok:`, which
# the dispatch above runs BEFORE. So a refused entry cannot reach it.
_loop_fn = _func(_LSRC, "_loop")
_parents = {}
for _n in ast.walk(_loop_fn):
    for _c in ast.iter_child_nodes(_n):
        _parents[_c] = _n
_orders = [n for n in ast.walk(_loop_fn)
           if isinstance(n, ast.Call)
           and (getattr(n.func, "attr", None) or getattr(n.func, "id", None))
           in ("place_order", "force_trade", "open_trade")]
check(f"there is exactly one order call in the loop ({len(_orders)})",
      len(_orders) == 1,
      "a second one would need its own proof that a signal cannot reach it")


def _under_entry_ok(node):
    """The `if entry_ok:` whose BODY contains `node`, or None.

    Body, not `orelse`: the entry path re-tests `entry_ok` further down and
    places the order in an `else`, so a check that accepted either branch
    would call an order guarded by `if not entry_ok` protected.
    """
    cur = node
    while cur in _parents:
        parent = _parents[cur]
        if (isinstance(parent, ast.If) and cur in parent.body
                and isinstance(parent.test, ast.Name)
                and parent.test.id == "entry_ok"):
            return parent
        cur = parent
    return None


_gate = _under_entry_ok(_orders[0]) if _orders else None
check("and it sits inside `if entry_ok:`", _gate is not None,
      "the refusal above stops nothing if the order is not gated on it")
_dispatch_line = _LSRC[:_LSRC.index('elif _auto == "signals":')].count("\n") + 1
check(f"which is reached after the dispatch (line {_dispatch_line} then "
      f"{_gate.lineno if _gate else '?'})",
      _gate is not None and _gate.lineno > _dispatch_line,
      "a gate evaluated before the level is resolved is not a gate")

check("_signal_only stores no pending_suggestion",
      "pending_suggestion" not in _names_in(_func(_LSRC, "_signal_only")),
      "a pending suggestion is redeemable by an Approve tap, so writing one "
      "here would turn a signal into an order later")

# ── 5. the delivery module cannot place an order ────────────────────────────
print("\n[5] the delivery module holds no path to an order")
_SSRC = open(os.path.join(ROOT, "apex", "platform", "signals.py"),
             encoding="utf-8").read()
_STREE = ast.parse(_SSRC)
_imports = set()
for _n in ast.walk(_STREE):
    if isinstance(_n, ast.Import):
        _imports |= {a.name for a in _n.names}
    elif isinstance(_n, ast.ImportFrom):
        _imports |= {f"{_n.module}.{a.name}" for a in _n.names if _n.module}
_forbidden = {m for m in _imports
              if any(bad in m for bad in ("user_loop", "broker", "gates",
                                          "ledger", "execution", "bridge",
                                          "live_execution", "telegram"))}
check(f"no execution-path import ({sorted(_imports)})", not _forbidden,
      f"{sorted(_forbidden)} — this module reports, it does not trade")

_calls = {n.func.attr for n in ast.walk(_STREE)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
_calls |= {n.func.id for n in ast.walk(_STREE)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
_opening = _calls & {"force_trade", "place_order", "open_trade",
                     "authorize_order", "close_position", "claim"}
check(f"and no opening call anywhere in it ({sorted(_opening) or 'none'})",
      not _opening)

# The one platform module it reaches that is NOT a store. `automation` can
# start and stop trading loops, so the import is not taken on trust: this
# names the only attribute this file may touch on it. A reader who sees
# `apex.platform.automation` in the list above is owed this line.
_am_uses = {n.attr for n in ast.walk(_STREE)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "_am"}
check(f"and it asks `automation` for nothing but context ({sorted(_am_uses)})",
      _am_uses <= {"running_context"},
      f"{sorted(_am_uses - {'running_context'})} — that module starts and "
      f"stops loops; this one reports on them")

# ── 6. the allowlists cannot deliver one action twice ───────────────────────
#
# `automation.engine_alert` offers every alert to both sinks and lets each
# answer for its own action, so the two allowlists ARE the routing. If they
# ever overlap, one setup becomes two rows on two screens.
print("\n[6] the two alert sinks do not claim the same action")
from apex.platform import approvals as _appr                # noqa: E402
check("SUGGEST is not in the signals allowlist",
      _appr.SUGGEST not in _sig.DELIVERED_ACTIONS,
      f"{_appr.SUGGEST!r} is the approval level's proposal and needs an "
      f"answer; delivered from here it would be an alert with no reply")
_APPRSRC = open(os.path.join(ROOT, "apex", "platform", "approvals.py"),
                encoding="utf-8").read()
check("SIGNAL is not answered by approvals",
      "SIGNAL" not in _names_in(_func(_APPRSRC, "engine_alert")),
      "two owners for one action is two notifications for one setup")

# ── 7. a signal is delivered, durably, and is readable afterwards ───────────
print("\n[7] a setup the engine finds reaches the client")
_payload = {"action": "SIGNAL", "symbol": "eurusd", "side": "BUY",
            "price": 1.08421, "confidence": 72,
            "reasoning": "RSI 28 with price above the 200 EMA.",
            "keyFactors": ["RSI oversold", "trend intact"]}
# Counted as a DELTA, not a total: section [4] runs the real dispatch and
# therefore delivers real signals before this point. A total would make these
# checks depend on how many sections above happened to deliver one, which is
# the kind of coupling that gets a test weakened rather than fixed.
_j_before, _n_before7 = _jstore.query(USER, status=_j.SIGNAL)["total"], _notes()["total"]
_out = _sig.engine_alert(USER, _payload)
check("the alert was accepted", _out is not None, str(_out))

_jq = _jstore.query(USER, status=_j.SIGNAL, symbol="EURUSD")
check("it is in the journal, which is the durable record",
      _jstore.query(USER, status=_j.SIGNAL)["total"] == _j_before + 1
      and _jq["total"] == 1,
      f"{_jq['total']} EURUSD entries — a client who was not looking has "
      f"nothing to come back to")
_entry = _jq["entries"][0] if _jq["entries"] else {}
check("filed against the instrument, so the symbol filter finds it",
      _entry.get("symbol") == "EURUSD", str(_entry.get("symbol")))
check("the record itself says it was not executable",
      (_entry.get("decision") or {}).get("executable") is False,
      "the one field that distinguishes this row from an order")
check("and carries the price the setup qualified at",
      (_entry.get("snapshot") or {}).get("price") == 1.08421,
      "at this level the client places the trade, so the level is the whole "
      "point of telling them")

_nq = _notes()
check("and the client was interrupted about it exactly once",
      _nq["total"] == _n_before7 + 1 and _nq["unread"] == _nq["total"],
      f"total={_nq['total']} (was {_n_before7}) unread={_nq['unread']}")
_body = (_nq["notifications"][0].get("body") or "") if _nq["notifications"] else ""
check("the notification says nothing was placed",
      "Nothing was placed" in _body,
      f"{_body!r} — a client reading an alert about a BUY has to be able to "
      f"tell it is not a position without opening anything")
check("and says who places it",
      "yourself" in _body.lower(), _body)

# ── 8. the firehose is dropped, including the one that needs an answer ──────
print("\n[8] every other loop event is dropped")
_before = _jstore.query(USER)["total"], _notify.query(USER)["total"]
for _act in ("BROKER_HEALTH", "SKIP_WARN", "OWNERSHIP_LOST", "NEWS_WARN",
             "STOP", "CLOSE", "WEEKEND_CLOSE", "SHADOW_OPEN", "SUGGEST",
             "BUY", "SELL", "", None):
    _sig.engine_alert(USER, {"action": _act, "symbol": "EURUSD",
                             "side": "BUY", "price": 1.0})
_after = _jstore.query(USER)["total"], _notify.query(USER)["total"]
check(f"nothing was written for any of them ({_before} -> {_after})",
      _before == _after,
      "an allowlist that lets the heartbeat through buries the two rows that "
      "mattered under the ones that did not")

# ── 9. a malformed signal is not silently dropped ──────────────────────────
print("\n[9] an unreadable setup leaves a trace instead of a gap")
_err_before = _jstore.query(USER, status=_j.BROKER_ERROR)["total"]
for _bad in ({"action": "SIGNAL", "symbol": "", "side": "BUY"},
             {"action": "SIGNAL", "symbol": "EURUSD", "side": "SIDEWAYS"},
             {"action": "SIGNAL", "side": "BUY"}):
    check(f"refused: {_bad}", _sig.engine_alert(USER, _bad) is None)
check("each refusal is journalled",
      _jstore.query(USER, status=_j.BROKER_ERROR)["total"] == _err_before + 3,
      "a setup the client was not told about is the failure this whole "
      "module exists to end; it must be searchable, not absent")

print("\n[9b] but a missing price never cancels a signal")
_n_before = _notes()["total"]
_sig.engine_alert(USER, {"action": "SIGNAL", "symbol": "GBPUSD", "side": "SELL",
                         "price": float("nan"), "confidence": 900})
check("the setup is still delivered",
      _notes()["total"] == _n_before + 1,
      "the promise is that the client hears about EVERY setup; an unreadable "
      "price is reported as unavailable, not used as a reason to withhold one")
_sigs = _notes()["notifications"]
_latest = _sigs[0] if _sigs else {}
check("and says the price was unavailable rather than inventing one",
      "unavailable" in (_latest.get("body") or ""), str(_latest.get("body")))

# ── 10. the sink never raises on the trading thread ─────────────────────────
print("\n[10] a broken store costs a notification, not the rest of the tick")
_real = _notify.notify
try:
    def _boom(*a, **k):
        raise RuntimeError("notification store is down")
    _notify.notify = _boom
    _raised = None
    try:
        _sig.engine_alert(USER, dict(_payload))
    except Exception as e:                                  # noqa: BLE001
        _raised = e
finally:
    _notify.notify = _real
check("engine_alert swallowed it", _raised is None, repr(_raised))
# Why this matters beyond tidiness, and why the loop's own net is checked too.
#
# The tick body is one `try` inside `while True`. An exception from an alert
# therefore cannot place an order — it abandons the REST of the tick, and the
# rest of the tick is where trailing stops, break-even moves and exits are
# managed. Both halves have to hold: the sink must not raise, and the loop
# must keep catching if it ever does.
_loop_fn = _func(_LSRC, "_loop")
_while = next((n for n in _loop_fn.body
               if isinstance(n, ast.While) and isinstance(n.test, ast.Constant)
               and n.test.value is True), None)
check("the tick body is wrapped in a try", _while is not None
      and any(isinstance(n, ast.Try) for n in _while.body),
      "the loop stopped catching, so a raising alert would now skip the exit "
      "and stop management that follow it in the same tick")
_tries = [n for n in (_while.body if _while else []) if isinstance(n, ast.Try)]
check("which catches Exception",
      any(isinstance(h.type, ast.Name) and h.type.id == "Exception"
          for t in _tries for h in t.handlers),
      str([ast.dump(h.type) if h.type else None
           for t in _tries for h in t.handlers])[:200])

# ── 11. the platform hands the engine somewhere to send it ──────────────────
#
# THE BUG ITSELF. `automation.start` called `user_loop.start(user_id)` and the
# engine's `alert_fn` defaulted to None, so `_signal_only` reported into
# nothing. Asserted on the DEFAULT starter, because an injected one is the
# test seam and would answer a question nobody asked.
print("\n[11] a platform-started loop is given an alert function")
_seen = {}
_real_start = user_loop.start
try:
    user_loop.start = lambda uid, alert_fn=None: _seen.setdefault(
        "args", (uid, alert_fn)) or True
    AU._engine_starter(USER)
finally:
    user_loop.start = _real_start
check("the default starter reached the engine", "args" in _seen, str(_seen))
_uid, _afn = _seen.get("args", (None, None))
check("with this user", _uid == USER, str(_uid))
check("and an alert function that is NOT None", _afn is not None,
      "this is the exact omission that left every platform client silent — "
      "the loop runs, finds setups, and reports into nothing")
check("which is the platform's own sink", _afn is AU.engine_alert, repr(_afn))

print("\n[12] that sink delivers a signal and claims no order path")
_n0 = _notes()["total"]
AU.engine_alert(USER, dict(_payload, symbol="AUDUSD"))
check("a SIGNAL through automation.engine_alert is delivered",
      _notes()["total"] == _n0 + 1,
      "the sink is wired but the signal does not arrive — which is the "
      "shipped bug with one more layer of indirection")
_ASRC = open(os.path.join(ROOT, "apex", "platform", "automation.py"),
             encoding="utf-8").read()
_sink = _ASRC[_ASRC.index("def engine_alert("):]
_sink = _sink[:_sink.index("\ndef ")]
check("and the sink itself only forwards to the two reporting modules",
      not ({"force_trade", "place_order", "start", "update"}
           & {n.func.attr for n in ast.walk(ast.parse(_sink.strip()))
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}),
      "an alert sink is a report of a decision already made; it must not be "
      "able to act on one")

# ── 13. a watchdog restart does not take the delivery away ──────────────────
#
# `bot.py` starts `start_all` and the watchdog with `telegram._user_alert`,
# which addresses a Telegram chat id. A platform identity is a Supabase uuid,
# so every event for a platform account the watchdog revived went to a chat
# that does not exist. Survivable for a heartbeat; at this level the alert IS
# the product, and a redeploy would have ended delivery for good.
print("\n[13] a loop restarted by the watchdog still delivers")
# A REAL platform connection, linked the way a client links one, because the
# question this asks is whether the classification recognises an actual
# platform account — a stubbed predicate would only confirm the branch.
_begun = CL.begin(USER)
_state = _begun["authorizeUrl"].split("state=")[1].split("&")[0]
CL.handle_callback({"code": "c", "state": _state},
                   exchanger=lambda c, u: {"accessToken": "TOK",
                                           "refreshToken": "REF",
                                           "expiresIn": 2592000})
CL.complete(USER, _begun["nonce"],
            lister=lambda a: [{"ctid": 901, "live": False}])
CL.select_account(USER, 901)


def _tg_alert(uid, payload):
    """Stands in for telegram._user_alert, which bot.py gives the watchdog."""
    _seen["telegram"] = True


check("this test's user is recognised as a platform account",
      CL.is_platform_account(USER) is True,
      "the rest of this section would pass for the wrong reason")
check("a platform account's alerts are redirected to the platform sink",
      user_loop._alert_fn_for(USER, _tg_alert) is AU.engine_alert,
      "the watchdog passes the Telegram alerter; a platform client's signals "
      "would go to a chat id that is not a chat and vanish — permanently, "
      "because nothing re-wires a loop that is already running")
check("a non-platform account keeps the caller's own alert function",
      user_loop._alert_fn_for("77771234", _tg_alert) is _tg_alert,
      "redirecting a Telegram client's alerts would be a regression in the "
      "other direction")
check("and an alert function is still optional for a Telegram start",
      user_loop._alert_fn_for("77771234", None) is None,
      "the legacy engine starts loops with no alerter at all; that must stay "
      "possible")

# ── 14. the screen can say what Running means ──────────────────────────────
#
# "Running" is the same word for all three levels, and they differ by whether
# a setup becomes an order. A client at Signals Only reading RUNNING with
# nothing beside it reads "it is trading for me" — which is how the silence in
# 6f984dfe9 went unnoticed for as long as it did.
print("\n[14] the status a browser reads says which level is running")
AU._write(USER, {"state": AU.RUNNING, "ruleDocId": "rule-sig-1",
                 "mode": AU.DEMO, "startedAt": 1.0, "accountId": 901,
                 "correlationId": "corr-sig-1",
                 "appliedTerms": {"automation": "signals"},
                 "notApplied": []})
_st = AU.status(USER)
check("the level is reported", _st.get("level") == "signals", str(_st))
check("with a label the browser does not have to invent",
      _st.get("levelLabel") == "Signals Only", repr(_st.get("levelLabel")))
check("and no emoji, which is the Telegram label's own",
      _st.get("levelLabel", "").isascii(), repr(_st.get("levelLabel")))
check("and the SERVER's verdict on whether it places orders",
      _st.get("levelExecutes") is False,
      "a browser deciding which levels trade would be a second copy of a "
      "decision about money")
check("and the sentence that explains it",
      "place" in (_st.get("levelBlurb") or "").lower(),
      repr(_st.get("levelBlurb")))

# A stopped account has no level to report, and must not be given one.
AU._write(USER, {"state": AU.STOPPED, "ruleDocId": None, "appliedTerms": None})
check("a stopped account reports no level",
      AU.status(USER).get("level") is None
      and AU.status(USER).get("levelExecutes") is None,
      str(AU.status(USER)))

print("\n[15] a signal is filed against the rule that produced it")
AU._write(USER, {"state": AU.RUNNING, "ruleDocId": "rule-sig-1",
                 "mode": AU.DEMO, "startedAt": 1.0, "accountId": 901,
                 "correlationId": "corr-sig-1",
                 "appliedTerms": {"automation": "signals"}})
AU.engine_alert(USER, dict(_payload, symbol="NZDUSD"))
_filed = _jstore.query(USER, status=_j.SIGNAL, rule_doc_id="rule-sig-1")
check("the rule filter finds it",
      _filed["total"] >= 1,
      "the engine knows a user id and nothing else, so the join has to be "
      "made on this side — without it 'show me this rule's signals' is empty")
_row = _filed["entries"][0] if _filed["entries"] else {}
check("filed against the account too", str(_row.get("accountId")) == "901",
      str(_row.get("accountId")))
check("and joined to the start that produced it",
      _row.get("correlationId") == "corr-sig-1",
      str(_row.get("correlationId")))

# ── 16. a rule that asks for this level gets it, all the way to the engine ──
#
# The complete path, measured rather than reasoned about: a client edits their
# rule (the PUT the builder already uses), `translate` turns it into engine
# settings, and `apex.automation` resolves those settings. The level is only
# real if the LAST step says "signals" — that is the question 6f984dfe9 added
# and the one nothing had been asking.
print("\n[16] a rule asking for signals reaches the engine as signals")
_doc = _rd.blank(user_id=USER, account_id="901", symbols=["EURUSD"],
                 timeframe="1h")
_rid = _doc["ruleDocId"]
_pstore.create(USER, _doc)
_saved = _pstore.save_draft(USER, {"ruleDocId": _rid,
                                   "automationLevel": "signals"})
check("the rule document can carry the level",
      _saved.get("automationLevel") == "signals",
      "nothing can select a level the document cannot hold")

# THE HOP WITH A REBUILD IN IT. `automation.start` does not read the draft: it
# reads `_store.get` after `activate`, and activation freezes a new version of
# the document. A rebuild that dropped an unrecognised key would leave this
# level unreachable in production while every assertion about what `translate`
# writes still passed — which is the exact shape of the bug this branch is
# about. (Raised by the `approval` agent, who measured it for their own level.)
_pstore.save_draft(USER, {"ruleDocId": _rid, "entry": {
    "combine": "AND",
    "conditions": [{"id": "rsi", "period": 14, "op": "below", "value": 30}]}})
_pstore.activate(USER, _rid, known_condition_ids={"rsi"})
_live = _pstore.get(USER, _rid)
check("and activation freezes it rather than dropping it",
      _live.get("automationLevel") == "signals",
      f"the activated rule carries {_live.get('automationLevel')!r} — the "
      f"loop is started from THIS document, not from the draft")
_saved = _live
_applied, _ = _ecfg.translate(_saved)
_record = dict(_applied, active=True)       # what automation.start writes
check("translate writes it as an engine setting",
      _record.get("automation") == "signals", str(_record.get("automation")))
check("and the engine RESOLVES it as signals",
      _eng_auto.mode(_record) == "signals",
      f"the engine read {_eng_auto.mode(_record)!r} — a level that resolves to "
      f"something else is a level the client did not choose")
check("so the loop will not execute for this client",
      _eng_auto.executes(_record) is False,
      "this is the function the loop asks before it sizes an order")
check("and the level is one the platform can service",
      "signals" in _ecfg.SERVICEABLE_LEVELS,
      "until this holds, a rule asking for signals silently runs at full — "
      "ask the owner of SERVICEABLE_LEVELS to add it")

# The fallback, which must be a level that CAN be serviced rather than the
# engine's own default of approval-with-nobody-to-ask.
for _asked in (None, "nonsense", "SIGNALS_ONLY"):
    _a2, _ = _ecfg.translate(dict(_saved, automationLevel=_asked))
    _r2 = dict(_a2)
    check(f"a rule asking for {_asked!r} falls back to a serviceable level",
          _eng_auto.mode(_r2) in _ecfg.SERVICEABLE_LEVELS
          and _eng_auto.mode(_r2) != "signals",
          f"resolved to {_eng_auto.mode(_r2)!r} — an unrecognised level must "
          f"not quietly become the one that places nothing either")

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print(f"  - {f}")
    sys.exit(1)
print("Signals Only is delivered on the platform, and places nothing.")
sys.exit(0)
