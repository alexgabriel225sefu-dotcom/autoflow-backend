"""Every request gets an ANSWER. No request closes the socket.

THE BUG, AND IT HID THE MOST IMPORTANT REFUSAL IN THE PRODUCT

`api._handle` refuses from about twenty places and ends its clause list at
`except ValueError`. `emergency.Halted` is a RuntimeError, so a start refused
by the emergency switch walked straight past every clause. Nothing above
caught it either — `handle` called `_handle` unguarded, and both transports
(`platform_server._api` and `bot.py`) call `handle` unguarded — so the
connection closed with no status line.

The web turns a failed fetch into `NETWORK: Failed to fetch`
(`web/src/lib/api.ts`), so the client's screen said the network was down.

Think about what that means operationally. The emergency stop is the control
that exists for the worst day this product will ever have. On that day, every
client who pressed Start would have been told to check their wifi, and the
operator would have had no idea the message never arrived.

THE SHAPE OF THE FIX, AND WHY BOTH HALVES ARE HERE

Mapping `Halted` alone would fix this one exception and leave the class
open — the next unmapped exception type does the same thing again. So there
are two assertions below: the halt answers with its own code, AND no
exception of any type can produce a non-answer.

A 500 is a bad answer. No answer is a worse one, because it is
indistinguishable from the network being down.

Run: python3 tests/test_platform_api_never_silent.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-silent-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex.platform import api as API                        # noqa: E402
from apex.platform import emergency as EMERG                # noqa: E402

PREFIX = API.PREFIX


# ── 1. a halted start ANSWERS ───────────────────────────────────────────────
print("\n[1] a request refused by the emergency switch gets a response")
_real_dispatch = API._dispatch


def _halted(*a, **kw):
    raise EMERG.Halted("HALTED_ALL",
                       "automation is stopped for every client by an "
                       "emergency switch", scope=EMERG.ALL, source="env")


API._dispatch = _halted
try:
    got = API.handle("POST", f"{PREFIX}automation/start",
                     headers={}, body=b"{}")
    check("it returns something at all", got is not None,
          "None here is the dead socket this file exists for")
    status, payload = got if got else (None, {})
    err = (payload or {}).get("error") or {}
    check("with a status, not a closed connection", status is not None,
          str(status))
    # 503 and not 409: the request was fine and the service is deliberately
    # stopped. That is what tells a client this is not theirs to fix.
    check("a 503, because the service is stopped rather than the request bad",
          status == 503, str(status))
    check("carrying the halt's own code", err.get("code") == "HALTED_ALL",
          str(err.get("code")))
    check("and the sentence an operator wrote",
          "emergency" in str(err.get("message", "")).lower(),
          str(err.get("message")))
    check("and which switch it was", err.get("scope") == EMERG.ALL,
          str(err.get("scope")))
finally:
    API._dispatch = _real_dispatch


# ── 2. and so does ANY other exception type ─────────────────────────────────
print("\n[2] no exception type can produce a non-answer")
# The point of this half: fixing Halted alone leaves the class open. These are
# types nothing in the clause list names.
for exc in (RuntimeError("engine blew up"),
            KeyError("missing"),
            TypeError("wrong shape"),
            AttributeError("none has no attribute"),
            ZeroDivisionError("division by zero")):
    def _boom(*a, _e=exc, **kw):
        raise _e

    API._dispatch = _boom
    try:
        got = API.handle("POST", f"{PREFIX}automation/start",
                         headers={}, body=b"{}")
        status, payload = got if got else (None, {})
        err = (payload or {}).get("error") or {}
        check(f"{type(exc).__name__} answers 500, not silence",
              status == 500 and err.get("code") == "INTERNAL_ERROR",
              f"{status} {err.get('code')}")
    finally:
        API._dispatch = _real_dispatch


# ── 3. the answer leaks nothing, and claims nothing it cannot know ──────────
print("\n[3] the catch-all answer is safe and honest")


def _boom_secret(*a, **kw):
    raise RuntimeError("redis://user:hunter2@10.0.0.5:6379 refused")


API._dispatch = _boom_secret
try:
    _st, _pl = API.handle("POST", f"{PREFIX}automation/start",
                          headers={}, body=b"{}")
    msg = str(((_pl or {}).get("error") or {}).get("message", ""))
    check("the exception text does not reach the client",
          "hunter2" not in msg and "redis://" not in msg, msg)
    # It must NOT say "nothing was changed": this branch cannot know that,
    # because the exception may have been raised after a partial write. An
    # unverified reassurance is the exact habit that produced six bugs this
    # week.
    check("and it does not promise the request had no effect",
          "nothing was changed" not in msg.lower(), msg)
    check("while telling the client what to actually do",
          "check" in msg.lower(), msg)
finally:
    API._dispatch = _real_dispatch


# ── 4. a path that is not ours still returns None ───────────────────────────
print("\n[4] the guard does not answer for routes this module does not own")
# `_handle` returns None so this can mount inside another server. Turning that
# into a 500 would have this module answering for the whole site.
check("an unrelated path is still not ours",
      API.handle("GET", "/some/other/thing", headers={}, body=None) is None)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All API answer-always checks passed.")
