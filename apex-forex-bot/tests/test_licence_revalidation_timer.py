"""A refund stops the bot even if the client never types again.

WHY THIS TEST EXISTS

Re-checking a licence against the verifier is the only path that can notice a
refund or a chargeback. _entitled() cannot: it reads the local access store and
the stored key, and neither of those changes when a payment is reversed — the
verifier's answer changes.

That re-check ran from exactly one place: inside the handler for an incoming
TEXT message. Button presses on already-drawn keyboards skipped it. The 180s
watchdog skipped it. Every new live order only consulted a cached local flag.

So the condition that defeated the check was the product's own advertised use
case: connect the broker and walk away. A client who never sent another message
after setup kept trading live on a refunded licence, with no time bound.

WHAT IS ASSERTED

That the sweep which already visits every active user each cycle now also asks
the verifier — and that asking cannot break the sweep. A licence server that is
slow, down, or throwing must not stop the watchdog from restarting dead loops
for everybody else; that would trade a billing hole for an availability one.

Run: python tests/test_licence_revalidation_timer.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


LOOP = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
TG = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
_wd = next(n for n in ast.walk(ast.parse(LOOP))
           if isinstance(n, ast.FunctionDef) and n.name == "start_watchdog")
_wd_src = ast.get_source_segment(LOOP, _wd) or ""

print("\n1. The periodic sweep asks the verifier")
check("the watchdog calls _revalidate_license",
      "_revalidate_license" in _wd_src,
      "without this the only caller is the incoming-text handler")
check("...for the user it is sweeping",
      "_revalidate_license(uid)" in _wd_src)

print("\n2. It is reached the way this module already reaches telegram")
check("the import is lazy, inside the function",
      "from apex import telegram as _tg" in _wd_src,
      "telegram imports user_loop; a module-level import would be circular")
check("the module still has no top-level telegram import",
      not any(line.startswith("from apex import telegram")
              or line.startswith("import telegram")
              for line in LOOP.splitlines()))

print("\n3. A failing verifier cannot break the sweep")
_calls = [n for n in ast.walk(_wd)
          if isinstance(n, ast.Call) and "revalidate" in ast.dump(n)]
check("the call exists in the AST", _calls)
_tries = [t for t in ast.walk(_wd) if isinstance(t, ast.Try)
          and "_revalidate_license" in ast.dump(t)]
check("it is wrapped in try/except", _tries,
      "one slow or throwing licence check must not stop the watchdog from "
      "restarting everybody else's dead loops")
if _tries:
    handlers = _tries[0].handlers
    check("the handler catches broadly", handlers and any(
        h.type is None or getattr(h.type, "id", "") == "Exception"
        for h in handlers))

print("\n4. The entitlement check still runs after it")
_rev_at = _wd_src.index("_revalidate_license(uid)")
_ent_at = _wd_src.index("if not _entitled(uid)")
check("revalidation comes BEFORE the entitlement check", _rev_at < _ent_at,
      "revalidation revokes; the check below is what completes the shutdown")

print("\n5. The re-check is throttled, so 180s is not 180s of HTTP")
check("_revalidate_license returns early on a recent check",
      "_REVALIDATE_SEC" in TG and "license_checked_at" in TG)
check("...and the interval is hours, not seconds",
      "_REVALIDATE_SEC = 12 * 3600" in TG,
      "at 180s the sweep would otherwise hammer the licence server")

print("\n6. BEHAVIOUR: a 503 does not revoke, an explicit 200 does")
# The verifier answers 503 with a valid:false body when its OWN store is down.
# Reading the body without the status would revoke every paying customer for
# the length of somebody else's outage — so this is exercised, not asserted
# about a comment.
from types import SimpleNamespace  # noqa: E402
from apex import telegram as tg, user_store as _us, access as _acc  # noqa: E402

CID = "revalidation-probe"
_saved = (tg.requests.post, _acc.revoke, _us.load, _us.update,
          tg.user_loop.stop, tg.send_to, _acc.is_admin)
revoked = []
try:
    _acc.is_admin = lambda c: False
    _acc.revoke = lambda c: revoked.append(c)
    _us.load = lambda c: {"license_key": "FORX-TEST", "license_checked_at": 0}
    _us.update = lambda c, u, **k: True
    tg.user_loop.stop = lambda c: None
    tg.send_to = lambda *a, **k: None

    tg.requests.post = lambda *a, **k: SimpleNamespace(
        status_code=503, json=lambda: {"valid": False})
    tg._revalidate_license(CID)
    check("a 503 saying valid:false does NOT revoke", CID not in revoked,
          "that body means the verifier's store is down, not that the "
          "customer stopped paying")

    revoked.clear()
    tg.requests.post = lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: {"valid": False})
    tg._revalidate_license(CID)
    check("a 200 saying valid:false DOES revoke", CID in revoked,
          "this is the refund/chargeback case the watchdog now reaches")
finally:
    (tg.requests.post, _acc.revoke, _us.load, _us.update,
     tg.user_loop.stop, tg.send_to, _acc.is_admin) = _saved

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - walking away no longer outlasts a refund.")
