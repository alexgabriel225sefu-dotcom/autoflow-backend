"""Two checks that used to fail OPEN now fail CLOSED on a live account.

1. The pre-send spread re-check swallowed every exception (`except: pass`), so
   a quote that could not be read sent the order with no spread check at all.
   Live: the order is refused. Demo: it is still sent, but the failure is
   logged instead of vanishing.

2. `ownership.acquire()` answers None when there is no shared backend (no
   Redis), and `start()` read that as "uncontended, carry on" — a live loop
   could run with no cross-container fence, which is how one account ends up
   managed by two containers during a deploy. Live (or an account whose mode
   cannot be read in production) now refuses to start; demo continues with a
   warning.

Run: python tests/test_engine_live_fail_closed.py
"""
import contextlib
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["PAPER_TRADING"] = "true"

from apex import user_loop  # noqa: E402
from apex import ownership  # noqa: E402
from apex.platform import ctrader_link  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + ("" if cond else f"  {detail}"))
    if not cond:
        failures.append(name)


with open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8") as fh:
    SRC = fh.read()

print("\n1. The spread re-check fails closed on live")
i0 = SRC.find("_rb, _ra = broker.get_bid_ask(symbol)")
i1 = SRC.find("if _skip_exec:", i0)
block = SRC[i0:i1]
check("the re-check block is found", i0 > 0 and i1 > i0)
check("it no longer swallows exceptions with a bare pass",
      "except Exception:\n                        pass" not in block)
exc = block[block.find("except Exception as _spread_err:"):]
check("the except names the error", "except Exception as _spread_err:" in block)
check("live refuses the order",
      "_is_live_cfg(cfg)" in exc and "_skip_exec = True" in exc, exc[:400])
check("demo logs it", "demo" in exc.lower() and "print(" in exc, exc[:400])

print("\n2. start() fence: live refuses without a lease backend")
_orig = (user_loop._entitled, ownership.acquire, ownership.start_renewer,
         user_loop._loop, ctrader_link.selected_mode, user_loop._mode_of,
         user_loop.user_store.update)
started = []
try:
    user_loop._entitled = lambda uid: True
    ownership.acquire = lambda uid: None          # no shared backend
    ownership.start_renewer = lambda uid, on_lost=None: None
    user_loop._loop = lambda uid, fn, gen: started.append(uid)
    user_loop.user_store.update = lambda uid, patch: None

    def _run(uid, platform_mode, legacy_mode, app_env="test"):
        ctrader_link.selected_mode = lambda u: platform_mode
        user_loop._mode_of = lambda u: legacy_mode
        old_env = os.environ.get("APP_ENV")
        os.environ["APP_ENV"] = app_env
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                ok = user_loop.start(uid)
        finally:
            os.environ["APP_ENV"] = old_env
            with user_loop._lock:
                user_loop._loops.pop(str(uid), None)
        return ok, out.getvalue()

    ok, log = _run("fence-live-legacy", None, "live")
    check("legacy LIVE account refuses to start unfenced", ok is False, log)
    check("...and says why", "REFUSED" in log and "lease" in log.lower(), log)

    ok, log = _run("fence-live-platform", "live", None)
    check("platform LIVE account refuses to start unfenced", ok is False, log)

    ok, log = _run("fence-demo-legacy", None, "demo")
    check("legacy demo account still starts", ok is True, log)
    check("...with a warning", "WARNING" in log and "unfenced" in log.lower(), log)

    ok, log = _run("fence-demo-platform", "demo", None)
    check("platform demo account still starts", ok is True, log)

    ok, log = _run("fence-unknown-prod", "unknown", None, app_env="production")
    check("an unknown mode in production refuses", ok is False, log)
    ok, log = _run("fence-unknown-test", "unknown", None, app_env="test")
    check("an unknown mode outside production still starts", ok is True, log)

    def _boom(u):
        raise RuntimeError("store down")
    ctrader_link.selected_mode = _boom
    user_loop._mode_of = lambda u: None
    os.environ["APP_ENV"] = "production"
    try:
        req, why = user_loop._start_fence_required("fence-boom")
    finally:
        os.environ["APP_ENV"] = "test"
    check("an unreadable mode in production requires the fence", req is True, why)

    print("\n3. A held or contested lease is unaffected")
    ownership.acquire = lambda uid: False
    ctrader_link.selected_mode = lambda u: "demo"
    with contextlib.redirect_stdout(io.StringIO()):
        check("another instance owning it still refuses",
              user_loop.start("fence-owned") is False)
    ownership.acquire = lambda uid: True
    ctrader_link.selected_mode = lambda u: "live"
    with contextlib.redirect_stdout(io.StringIO()):
        ok = user_loop.start("fence-held-live")
    with user_loop._lock:
        user_loop._loops.pop("fence-held-live", None)
    check("a live account WITH the lease starts", ok is True)
finally:
    (user_loop._entitled, ownership.acquire, ownership.start_renewer,
     user_loop._loop, ctrader_link.selected_mode, user_loop._mode_of,
     user_loop.user_store.update) = _orig

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - live fails closed where it used to carry on.")
