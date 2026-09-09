"""Every Mini App route, checked as a set — so a new one cannot be added unscoped.

The individual screen tests each assert their own route is scoped. That leaves
the failure this file exists for: the fifteenth endpoint, added next month by
someone who copied the shape of a route but not its first four lines.

So the routes are DISCOVERED from bot.py rather than listed here. A new
`/api/app/...` handler is picked up automatically and has to satisfy the same
four properties as the rest:

  1. identity from the verified Telegram signature, before any data access;
  2. an explicit refusal when that fails;
  3. no user, chat, account or trade owner taken from the request — an id in a
     query string is a request to see something, not proof of the right to;
  4. no bare local, because do_GET and do_POST are single long methods and a
     bare name makes itself local to the whole method. That has shipped twice
     here and dropped connections with no response both times.

Run: python tests/test_miniapp_isolation.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


BOT = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()

# Every branch that handles an /api/app path, with its body running to the next
# `if self.path` at the same indent. Discovered, never listed — one branch can
# serve several paths (history and replay share one), so all of them are
# recorded against the same body.
_START = re.compile(r'^(?P<indent>[ ]+)if self\.path\b.*$', re.M)

routes = {}
_ALL = [m for m in _START.finditer(BOT)]
# Only the OUTERMOST dispatch level is a route. An `if self.path.startswith(...)`
# nested inside an already-authenticated branch is a sub-dispatch — the history
# branch serves both history and replay that way — and demanding its own
# identity check would be demanding it twice.
_paths = [m for m in _ALL if "/api/app/" in m.group(0)]
_TOP = min((len(m.group("indent")) for m in _paths), default=0)
starts = [m for m in _paths if len(m.group("indent")) == _TOP]
for m in starts:
    nxt = next((x for x in _ALL
                if x.start() > m.start()
                and len(x.group("indent")) <= len(m.group("indent"))), None)
    body = BOT[m.start():(nxt.start() if nxt else len(BOT))]
    for pth in re.findall(r'"(/api/app/[a-z]+)"', m.group(0)):
        routes.setdefault(pth, []).append(body)

print(f"\n1. Discovered {len(routes)} Mini App endpoints")
for pth in sorted(routes):
    print(f"     {pth}")
check("at least the fourteen known endpoints are found", len(routes) >= 14,
      str(sorted(routes)))
for expected in ("/api/app/data", "/api/app/tick", "/api/app/history",
                 "/api/app/replay", "/api/app/markets", "/api/app/risk",
                 "/api/app/intelligence", "/api/app/automation", "/api/app/ask",
                 "/api/app/close", "/api/app/stream", "/api/app/account",
                 "/api/app/alerts", "/api/app/symbol", "/api/app/trade"):
    check(f"{expected} is discovered", expected in routes)


def code_of(body):
    return "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))


print("\n2. Identity comes from the signature, before any data access")
DATA_ACCESS = ("user_store.load", "_us.load", "get_dash", "_make_broker",
               "load_trades", "find_trade", "recent(", "declines(",
               "snapshot(", "force_close", "answer(")
for pth in sorted(routes):
    for body in routes[pth]:
        code = code_of(body)
        if "_telegram_identity" not in code:
            check(f"{pth}: authenticates", False,
                  "every Mini App route must resolve identity from initData")
            continue
        idx = code.index("_telegram_identity")
        first_access = min(
            [code.index(t) for t in DATA_ACCESS if t in code] or [len(code)])
        check(f"{pth}: identity precedes any data access", idx < first_access,
              f"identity at {idx}, first access at {first_access}")
        check(f"{pth}: refuses explicitly when identity fails",
              "_telegram_denied" in code)

print("\n3. No owner is taken from the request")
# A route may read a FILTER from the query (symbol, timeframe, trade id, page).
# What it may never read is who the caller is.
OWNER_KEYS = ("user_id", "chat_id", "account_id", "accountId", "userId",
              "chatId", "owner", "paper", "live")
for pth in sorted(routes):
    for body in routes[pth]:
        code = code_of(body)
        # Only look at values pulled OUT of the request.
        pulled = re.findall(r'(?:_qs|qs)\.get\(\s*"([a-zA-Z_]+)"', code)
        pulled += re.findall(r'_body\s*or\s*\{\}\)\.get\(\s*"([a-zA-Z_]+)"', code)
        pulled += re.findall(r'_body\.get\(\s*"([a-zA-Z_]+)"', code)
        bad = [k for k in pulled if k in OWNER_KEYS]
        check(f"{pth}: reads no owner from the request ({pulled or 'nothing'})",
              not bad, str(bad))
        check(f"{pth}: the chat id is derived from the verified user",
              'str(_' in code and '["id"])' in code or "chat_id" not in code
              or 'tg_user["id"]' in code)

print("\n4. No local can shadow the enclosing method")
# The rule is narrower than "prefix everything", and the narrow version is the
# one that matters. do_GET is nested inside _start_dashboard_server, so a bare
# assignment only causes UnboundLocalError for a name the METHOD reads from an
# outer scope — the module globals, or the enclosing function's locals. A route
# binding `candles` or `pos` is harmless; one binding `dash`, `parse_qs` or
# `token` breaks every branch above it, and both of those have shipped here.
import ast as _ast

_tree = _ast.parse(BOT)


def _direct_bindings(body):
    """Names bound at THIS level only — not inside nested functions.

    Walking the whole subtree collects every local of every nested function,
    which is hundreds of names that share a spelling with a route local and
    shadow nothing. Only the direct children of a scope are that scope.
    """
    out = set()
    for node in body:
        if isinstance(node, _ast.Assign):
            for t in node.targets:
                for nm in _ast.walk(t):
                    if isinstance(nm, _ast.Name):
                        out.add(nm.id)
        elif isinstance(node, (_ast.AnnAssign, _ast.AugAssign)):
            if isinstance(node.target, _ast.Name):
                out.add(node.target.id)
        elif isinstance(node, (_ast.Import, _ast.ImportFrom)):
            for a in node.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (_ast.If, _ast.Try, _ast.For, _ast.While, _ast.With)):
            # Same scope, just indented.
            for attr in ("body", "orelse", "finalbody", "handlers"):
                for sub in getattr(node, attr, []) or []:
                    inner = getattr(sub, "body", None)
                    out |= _direct_bindings(inner if inner is not None else [sub])
    return out


_module_names = _direct_bindings(_tree.body)
# The enclosing function's own locals, which do_GET closes over.
_encl = next((n for n in _ast.walk(_tree)
              if isinstance(n, _ast.FunctionDef)
              and n.name == "_start_dashboard_server"), None)
_encl_names = _direct_bindings(_encl.body) if _encl else set()
_OUTER = (_module_names | _encl_names) - {"self"}
print(f"     {len(_OUTER)} names live in an outer scope and must not be shadowed")

ASSIGN = re.compile(r'^\s+([a-z][\w]*) = (?!=)', re.M)
for pth in sorted(routes):
    for body in routes[pth]:
        bound = {m.group(1) for m in ASSIGN.finditer(code_of(body))}
        clash = sorted(bound & _OUTER)
        check(f"{pth}: shadows nothing from an outer scope ({clash or 'none'})",
              not clash,
              "a bare name that also exists outside makes itself local to the "
              "WHOLE method and raises UnboundLocalError in every branch above")

print("\n5. Only one route may move money, and it delegates")
writers = []
for pth in sorted(routes):
    for body in routes[pth]:
        code = code_of(body)
        if any(x in code for x in ("force_close", "place_order", "close_position",
                                   "amend_sltp")):
            writers.append(pth)
check(f"exactly one route reaches an execution path ({writers})",
      writers == ["/api/app/close"], str(writers))
close_code = code_of(routes["/api/app/close"][0])
check("...and it calls the shared close rather than a broker",
      "force_close(" in close_code
      and not any(x in close_code for x in ("place_order", "_make_broker",
                                            "get_broker")))
check("...with its own origin so the audit can tell it apart",
      'origin="miniapp"' in close_code)
check("...and names no position — the server closes the one it holds",
      "position_id" not in close_code and "positionId" not in close_code)

print("\n6. No route calls the risk engine's stateful check")
for pth in sorted(routes):
    for body in routes[pth]:
        check(f"{pth}: should_stop is never called", "should_stop" not in code_of(body),
              "it advances the peak balance and the daily reset as a side effect")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print(f"ALL ISOLATION CHECKS PASSED - {len(routes)} endpoints, discovered and scoped.")
