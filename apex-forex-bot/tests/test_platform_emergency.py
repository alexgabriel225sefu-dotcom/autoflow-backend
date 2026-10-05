"""The emergency stop, and the two ways it has to keep working.

§8 of docs/LIVE_EXECUTION_SPECIFICATION.md asks for a global switch that
does NOT depend on the shared backend being reachable and does NOT require a
deploy. Those pull apart: a stored key needs the store, an environment
variable needs a restart. So the interesting assertions here are not "does
the switch work" but "does it still work with each of its two halves broken".

Run: python3 tests/test_platform_emergency.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-emerg-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ["CTRADER_REDIRECT_URI"] = "https://apex4traders.test/api/v1/ctrader/callback"
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("A4T_EMERGENCY_HALT", None)

from apex import user_store                             # noqa: E402
from apex.platform import emergency as E                # noqa: E402
from apex.platform import store as _store               # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def refused(fn, **kw):
    """The Halted raised by `fn`, or None."""
    try:
        fn(**kw)
        return None
    except E.Halted as e:
        return e


def clear():
    os.environ.pop(E.ENV_VAR, None)
    try:
        _store._delete(E._k())
    except Exception:
        pass


print("\n[1] nothing pressed means nothing is stopped")
clear()
st = E.state()
check("scope is none", st["scope"] == E.NONE, st["scope"])
check("no source is claimed", st["source"] is None, str(st["source"]))
check("the store was reachable", st["storeReachable"] is True)
check("a demo client is not refused", refused(E.check, mode="demo") is None)
check("and neither is a live one", refused(E.check, mode="live") is None)

print("\n[2] the STORED switch — works with no deploy")
E.halt(E.ALL, reason="spread blowout across the book", by="owner")
st = E.state()
check("the scope is all", st["scope"] == E.ALL, st["scope"])
check("and it names the store as the source", st["source"] == E.SRC_STORE,
      str(st["source"]))
check("the reason is kept, because somebody will read it later",
      st["reason"] == "spread blowout across the book", str(st["reason"]))
check("so is who pressed it", st["by"] == "owner", str(st["by"]))
h = refused(E.check, mode="demo")
check("a DEMO client is stopped by an ALL halt", h is not None)
check("with a code to branch on", h and h.code == "HALTED_ALL", h and h.code)
check("a live one too", refused(E.check, mode="live") is not None)

print("\n[3] a halt with no reason or no actor is refused")
# The record somebody reads at the worst possible moment is this one.
for kw, why in ((dict(reason="", by="owner"), "no reason"),
                (dict(reason="x", by=""), "no actor")):
    try:
        E.halt(E.ALL, **kw)
        check(f"a halt with {why} is refused", False, "it was accepted")
    except ValueError:
        check(f"a halt with {why} is refused", True)

print("\n[4] release clears the stored switch")
E.release(by="owner")
check("the halt is gone", E.state()["scope"] == E.NONE, E.state()["scope"])
check("and nobody is refused", refused(E.check, mode="demo") is None)

print("\n[5] the ENVIRONMENT switch — works with the store unreachable")
clear()
os.environ[E.ENV_VAR] = "all"
st = E.state()
check("the environment alone halts everything", st["scope"] == E.ALL, st["scope"])
check("and names the environment as the source", st["source"] == E.SRC_ENV,
      str(st["source"]))
check("a demo client is stopped", refused(E.check, mode="demo") is not None)

# An unrecognised value is somebody trying to stop the product and mistyping.
# Reading that as "carry on" is the one interpretation that cannot be right.
os.environ[E.ENV_VAR] = "YES-STOP-NOW"
check("an unrecognised value halts rather than being ignored",
      E.state()["scope"] == E.ALL, E.state()["scope"])
os.environ[E.ENV_VAR] = "live"
check("'live' halts only live", E.state()["scope"] == E.LIVE, E.state()["scope"])
check("a demo client keeps running under a LIVE halt",
      refused(E.check, mode="demo") is None)
check("a live client does not", refused(E.check, mode="live") is not None)
check("and neither does an unknown mode — not knowing is not demo",
      refused(E.check, mode="unknown") is not None)
clear()

print("\n[5b] 'not looked up yet' is a THIRD state, not 'unknown'")
# This cost a real defect in the wiring. `automation._preflight` asks twice —
# once before the connection is resolved and once after — and the first call
# treating an absent mode as "unknown" refused every FREE DEMO CLIENT under a
# halt aimed at live accounts. Demo access is the product.
clear()
os.environ[E.ENV_VAR] = "live"
check("a caller that has not resolved the mode is NOT refused",
      refused(E.check, user_id="u-1", mode=E.NOT_RESOLVED) is None,
      "a LIVE halt must not stop a client whose mode nobody asked about yet")
check("but a caller that looked and could not tell IS refused",
      refused(E.check, user_id="u-1", mode=None) is not None,
      "'we could not tell' must stay strict")
check("the default is the safe-for-demo one, since that is the common caller",
      refused(E.check, user_id="u-1") is None)
# The levels that do not need a mode still apply to an unresolved caller.
os.environ[E.ENV_VAR] = "all"
check("an ALL halt still stops a caller that has not resolved the mode",
      refused(E.check, user_id="u-1", mode=E.NOT_RESOLVED) is not None)
clear()

print("\n[6] a stored release cannot overrule an environment halt")
# The harder switch was reached for because the easy one was not enough.
os.environ[E.ENV_VAR] = "all"
E.halt(E.ALL, reason="both at once", by="owner")
st = E.release(by="owner")
check("releasing the record leaves the environment halt standing",
      st["scope"] == E.ALL, st["scope"])
check("and says the environment is holding it",
      st["source"] == E.SRC_ENV, str(st["source"]))
check("so the client is still refused",
      refused(E.check, mode="demo") is not None)
clear()

print("\n[7] the widest halt wins when the two disagree")
os.environ[E.ENV_VAR] = "live"
E.halt(E.ALL, reason="store says everything", by="owner")
check("store ALL beats env LIVE", E.state()["scope"] == E.ALL, E.state()["scope"])
E.release(by="owner")
os.environ[E.ENV_VAR] = "all"
E.halt(E.LIVE, reason="store says live only", by="owner")
check("env ALL beats store LIVE", E.state()["scope"] == E.ALL, E.state()["scope"])
clear()

print("\n[8] per instrument and per client")
E.halt(E.NONE, reason="one pair is unusable", by="owner",
       instruments=["eurusd"], users=["u-42"])
check("a NONE-scoped record halts nobody globally",
      E.state()["scope"] == E.NONE, E.state()["scope"])
check("the symbol is normalised to upper case",
      E.state()["instruments"] == ["EURUSD"], str(E.state()["instruments"]))
h = refused(E.check, symbol="EURUSD", mode="demo")
check("the named instrument is stopped", h is not None)
check("with its own code", h and h.code == "HALTED_INSTRUMENT", h and h.code)
check("however it was typed", refused(E.check, symbol="eurusd", mode="demo") is not None)
check("another instrument runs", refused(E.check, symbol="GBPUSD", mode="demo") is None)
h = refused(E.check, user_id="u-42", mode="demo")
check("the named client is stopped", h is not None)
check("with its own code", h and h.code == "HALTED_CLIENT", h and h.code)
check("another client runs", refused(E.check, user_id="u-43", mode="demo") is None)
clear()

print("\n[9] an unreachable store stops LIVE and not DEMO")
# The asymmetry stated in the module docstring. Taken literally, "halt on
# uncertainty" would take down every free demo client over a Redis blip —
# a worse outcome than letting a loop that risks nothing continue.
_real = _store.read_raw


def _unreachable(key):
    raise user_store.StoreUnavailable("simulated outage")


_store.read_raw = _unreachable
try:
    st = E.state()
    check("the state still answers rather than raising", isinstance(st, dict))
    check("and says the store was NOT reachable", st["storeReachable"] is False)
    check("the effective scope is live", st["scope"] == E.LIVE, st["scope"])
    check("a DEMO client keeps running",
          refused(E.check, mode="demo") is None,
          "a Redis blip must not stop every free client")
    h = refused(E.check, mode="live")
    check("a LIVE account is refused", h is not None)
    check("and the code says WHY it was refused — not knowing, not a switch",
          h and h.code == "HALTED_UNCERTAIN", h and h.code)
    check("an unknown mode is refused too", refused(E.check, mode="unknown") is not None)

    # The environment half has to survive the store being gone. That is the
    # entire reason there are two sources.
    os.environ[E.ENV_VAR] = "all"
    check("the environment switch still works with the store down",
          E.state()["scope"] == E.ALL, E.state()["scope"])
    check("and stops a demo client", refused(E.check, mode="demo") is not None)
    os.environ.pop(E.ENV_VAR, None)
finally:
    _store.read_raw = _real
clear()

print("\n[10] a corrupt record is not an absent one")
_store.write_raw(E._k(), "{not json")
st = E.state()
check("it reads as unreachable rather than as no halt",
      st["storeReachable"] is False, str(st))
check("so a live account is refused", refused(E.check, mode="live") is not None)
clear()

print("\n[11] halt() refuses to report success if the write did not land")
_realw = _store.write_raw
_store.write_raw = lambda k, v: None          # silently drops the write
try:
    E.halt(E.ALL, reason="x", by="owner")
    check("a halt that did not store raises instead of returning", False,
          "it reported success")
except user_store.StoreUnavailable:
    check("a halt that did not store raises instead of returning", True)
except Exception as e:                                      # noqa: BLE001
    check("a halt that did not store raises instead of returning", False,
          f"{type(e).__name__}: {e}")
finally:
    _store.write_raw = _realw
clear()

print("\n[12] there is no HTTP route that can stop the product")
# Same reasoning as the waitlist's removal: a route that halts every client
# is a route worth attacking, and the one person who needs it has a shell.
api = open(os.path.join(ROOT, "apex", "platform", "api.py"),
           encoding="utf-8").read()
for name in ("emergency.halt", "emergency.release", "_emerg.halt",
             "_emerg.release"):
    check(f"the API never calls {name}", name not in api)

print("\n[13] the switch is WIRED, not merely written")
# Everything above tests the module. None of it would fail if nothing ever
# called it — which is the mistake this whole milestone exists to avoid, in
# reverse. So this builds a real link and a real activated rule, and presses
# the switch against the actual start path.
from apex.platform import automation as AU              # noqa: E402
from apex.platform import ctrader_link as CL            # noqa: E402
from apex.platform import ruledoc as _rd                # noqa: E402

USER = "cccccccc-1111-4111-8111-cccccccccccc"

# The rule is built through ruledoc and the store rather than through the HTTP
# API, because the API needs Supabase and this test is about the start path,
# not about authentication. The automation module reads the store either way.
begun = CL.begin(USER)
_state = begun["authorizeUrl"].split("state=")[1].split("&")[0]
CL.handle_callback({"code": "c", "state": _state},
                   exchanger=lambda c, u: {"accessToken": "TOK",
                                           "refreshToken": "REF",
                                           "expiresIn": 2592000})
CL.complete(USER, begun["nonce"], lister=lambda a: [{"ctid": 701,
                                                     "live": False}])
CL.select_account(USER, 701)

_doc = _rd.blank(user_id=USER, account_id="701", symbols=["EURUSD"],
                 timeframe="1h")
_doc["name"] = "emergency rule"
_doc["entry"]["conditions"] = [{"id": "rsi", "period": 14, "op": "below",
                                "value": 30}]
rid = _doc["ruleDocId"]
_store.create(USER, _doc)
_live = _store.activate(USER, rid, known_condition_ids={"rsi"})
check("a rule was built and activated for the walk",
      _live.get("state") == "active", str(_live.get("state")))

started = []


def try_start():
    return AU.start(USER, rid, starter=lambda uid: started.append("GO") or True)


clear()
try_start()
check("without a halt, the loop starts", "GO" in started, str(started))
AU.stop(USER, stopper=lambda uid: True)
started.clear()

E.halt(E.ALL, reason="walking the switch", by="test")
h = refused(try_start)
check("with a global halt, start is REFUSED", h is not None)
check("by the emergency switch, not by something else",
      h and h.code == "HALTED_ALL", h and getattr(h, "code", h))
check("and nothing was started", "GO" not in started, str(started))

E.release(by="test")
E.halt(E.NONE, reason="one pair", by="test", instruments=["EURUSD"])
h = refused(try_start)
check("a per-instrument halt refuses a rule that trades it", h is not None)
check("naming the instrument gate",
      h and h.code == "HALTED_INSTRUMENT", h and getattr(h, "code", h))
check("and nothing was started", "GO" not in started, str(started))

E.release(by="test")
E.halt(E.NONE, reason="this client", by="test", users=[USER])
h = refused(try_start)
check("a per-client halt refuses that client", h is not None)
check("naming the client gate",
      h and h.code == "HALTED_CLIENT", h and getattr(h, "code", h))

# A LIVE halt must not touch a demo client — the free tier is the product.
E.release(by="test")
E.halt(E.LIVE, reason="live only", by="test")
started.clear()
check("a LIVE halt leaves a free demo client running",
      refused(try_start) is None and "GO" in started, str(started))
AU.stop(USER, stopper=lambda uid: True)
E.release(by="test")
clear()

print("\n[14] stopping says whether it flattened — §8.1")
started.clear()
try_start()
rep = AU.stop(USER, stopper=lambda uid: True)
check("the stop reports the flatten decision explicitly",
      "flattened" in rep and "flattenDeclined" in rep, str(sorted(rep)))
check("this release declines to flatten", rep["flattened"] is False
      and rep["flattenDeclined"] is True, str(rep.get("flattened")))
check("and says why, in words a client can act on",
      "close it there" in (rep.get("flattenReason") or ""),
      str(rep.get("flattenReason"))[:120])
rep2 = AU.stop(USER, stopper=lambda uid: True)
check("stopping something already stopped answers the same way",
      rep2.get("flattenDeclined") is True and rep2.get("alreadyStopped") is True,
      str({k: rep2.get(k) for k in ("flattenDeclined", "alreadyStopped")}))

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All emergency-stop checks passed.")
