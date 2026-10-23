"""The client's emergency button says only what it has verified.

WHY THIS FILE IS STRICT

A panic button that prints "all closed" while one position is open is the most
expensive sentence this product can show. The Telegram bot's /emergency stopped
the loop and said so; the web needs the same button, and it must not claim more
than it measured.

WHAT THESE TESTS WILL NOT ACCEPT

* Closing before the stop (a loop could reopen what was just closed).
* `allFlat` true on the strength of the closes' own replies: it must come from
  a fresh read of the account.
* A failed re-read counted as flat.
* A failed stop hiding the closes, or a failed close hiding the stop.
* A refusal swallowed: every refusal keeps its own code and sentence.
* More than the cap of closes in one press, or the overflow going unmentioned.
* The API acting without `confirm: true`, or closing positions on an account
  the caller did not select.

Run: python3 tests/test_emergency_stop.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-panic-")
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


from apex.platform import emergency_stop as ES              # noqa: E402
from apex.platform import position_close as PC              # noqa: E402

USER = "panic-user"


class World:
    """A tiny account: open positions, a log of what was done, and knobs."""

    def __init__(self, positions=2, *, stop_error=None, refuse=None,
                 unknown=None, partial=None, reread_error=False,
                 close_but_stay_open=(), open_error=None):
        self.open = [{"positionId": 100 + i, "symbol": "EURUSD", "side": "BUY"}
                     for i in range(positions)]
        self.log = []
        self.stop_error, self.refuse = stop_error, refuse or {}
        self.unknown, self.partial = unknown or set(), partial or set()
        self.reread_error = reread_error
        self.close_but_stay_open = set(close_but_stay_open)
        self.open_error = open_error
        self.reads = 0

    def stopper(self, uid):
        self.log.append("stop")
        if self.stop_error:
            raise RuntimeError(self.stop_error)
        return {"stopped": True, "alreadyStopped": False}

    def opener(self, uid, ctid=None, connection_fn=None, broker_fn=None):
        self.reads += 1
        if self.open_error:
            return None, {"status": "unavailable", "reason": self.open_error}
        if self.reread_error and self.reads > 1:
            raise RuntimeError("socket closed")
        world = self

        class B:
            def get_all_positions(self_inner):
                world.log.append("read")
                return list(world.open)

        return B(), {}

    def closer(self, uid, *, ctid, position_id):
        self.log.append(f"close:{position_id}")
        pid = int(position_id)
        if pid in self.refuse:
            raise PC.CloseRefused(self.refuse[pid], "refused for test")
        if pid in self.unknown:
            raise PC.CloseUnknown("result unknown")
        if pid in self.partial:
            return {"status": "PARTIAL"}
        if pid not in self.close_but_stay_open:
            self.open = [p for p in self.open if p["positionId"] != pid]
        return {"status": "FILLED"}


def run(w, **kw):
    kw.setdefault("mode_fn", lambda uid, ctid: "demo")
    return ES.run(USER, ctid="501", stopper=w.stopper, opener=w.opener,
                  closer=w.closer, **kw)


# ── 1. the happy path, in the right order ───────────────────────────────────
print("\n[1] stop first, close each, then look again")
w = World(2)
r = run(w)
check("the stop was actually requested", "stop" in w.log, str(w.log))
check("the stop happens before any close",
      "stop" in w.log and w.log.index("stop") < min(i for i, x in enumerate(w.log)
                                if x.startswith("close:")), str(w.log))
check("every position was closed",
      [c["outcome"] for c in r["closes"]] == ["closed", "closed"], str(r["closes"]))
check("flat is claimed only after a fresh read found none",
      r["allFlat"] is True and r["verified"]["stillOpen"] == 0, str(r["verified"]))
check("and that read came AFTER the last close",
      w.log[-1] == "read" and w.log.index("close:101") < len(w.log) - 1, str(w.log))
check("the sentence says it is confirmed", "Confirmed: no positions" in r["sentence"],
      r["sentence"])

# ── 2. stop only ────────────────────────────────────────────────────────────
print("\n[2] stop without closing leaves positions alone and says so")
w = World(2)
r = run(w, close_positions=False)
check("no close was attempted", not [x for x in w.log if x.startswith("close:")], str(w.log))
check("closes is null, not an empty list that reads as 'nothing to close'",
      r["closes"] is None and r["allFlat"] is None, str(r))
check("the sentence says they keep their stop and target",
      "stop and target" in r["sentence"], r["sentence"])

# ── 3. a failed stop does not hide the closes (nor the reverse) ─────────────
print("\n[3] each step is attempted whatever the other did")
w = World(1, stop_error="redis down")
r = run(w)
check("positions were still closed", r["closes"][0]["outcome"] == "closed", str(r))
check("the failed stop is said loudly",
      r["automation"]["stopped"] is False and "could NOT be stopped" in r["sentence"],
      r["sentence"])
check("and carries the cause", "redis down" in (r["automation"]["error"] or ""))

# ── 4. refusals keep their code; the rest still go ahead ────────────────────
print("\n[4] one refusal does not stop the others, and is not swallowed")
w = World(3, refuse={101: "NOT_OWNER"})
r = run(w)
outs = {c["positionId"]: c for c in r["closes"]}
check("the refused one carries its code", outs["101"]["code"] == "NOT_OWNER", str(outs["101"]))
check("the others were closed", outs["100"]["outcome"] == "closed"
      and outs["102"]["outcome"] == "closed", str(outs))
check("not flat, and counted from the re-read",
      r["allFlat"] is False and r["verified"]["stillOpen"] == 1, str(r["verified"]))
check("the NOT_OWNER sentence tells the client what to do",
      "ten minutes" in r["sentence"] and "cTrader" in r["sentence"], r["sentence"])

# ── 5. the closes' own replies are not trusted ──────────────────────────────
print("\n[5] 'filled' with the position still there is not flat")
w = World(1, close_but_stay_open={100})
r = run(w)
check("the close reported closed", r["closes"][0]["outcome"] == "closed")
check("but the fresh read found it, so flat is NOT claimed",
      r["allFlat"] is False and r["verified"]["stillOpen"] == 1, str(r))
check("and the sentence says one is still open",
      "still open" in r["sentence"], r["sentence"])

print("\n[5b] a re-read that fails is unverified, never flat")
w = World(1, reread_error=True)
r = run(w)
check("closes succeeded", r["closes"][0]["outcome"] == "closed")
check("allFlat is False, not None and not True",
      r["allFlat"] is False and r["verified"]["readable"] is False, str(r))
check("the sentence says it is NOT confirmed flat",
      "NOT confirmed flat" in r["sentence"], r["sentence"])

# ── 6. unknown and partial are not counted as closed ────────────────────────
print("\n[6] unknown and partial results are not 'closed'")
w = World(2, unknown={100}, partial={101})
r = run(w)
outs = {c["positionId"]: c["outcome"] for c in r["closes"]}
check("unknown is unknown", outs["100"] == "unknown", str(outs))
check("partial is partial", outs["101"] == "partial", str(outs))
import re                                                   # noqa: E402
check("neither is reported as a closed position",
      not re.search(r"\d+ positions? closed\.", r["sentence"]), r["sentence"])
check("and the account is not called flat", r["allFlat"] is False)

# ── 7. positions that cannot be read ────────────────────────────────────────
print("\n[7] if the positions cannot be read, nothing is closed and it says so")
w = World(2, open_error="cTrader account unavailable")
r = run(w)
check("no close attempted", not [x for x in w.log if x.startswith("close:")], str(w.log))
check("positions unreadable, flat not claimed",
      r["positions"]["readable"] is False and r["allFlat"] is False, str(r))
check("the stop still happened", r["automation"]["stopped"] is True)
check("the sentence names the cause and the fallback",
      "cTrader account unavailable" in r["sentence"] and "close them in cTrader" in r["sentence"],
      r["sentence"])

# ── 8. the cap ──────────────────────────────────────────────────────────────
print("\n[8] a single press closes at most MAX_CLOSES and says about the rest")
w = World(ES.MAX_CLOSES + 5)
r = run(w)
check("attempted exactly the cap", len(r["closes"]) == ES.MAX_CLOSES, str(len(r["closes"])))
check("the overflow is reported", r["positions"]["notAttempted"] == 5, str(r["positions"]))
check("not flat, and the sentence says to press again",
      r["allFlat"] is False and "press again" in r["sentence"], r["sentence"])

# ── 9. nothing to close ─────────────────────────────────────────────────────
print("\n[9] an empty account is reported as such")
r = run(World(0))
check("flat and says there was nothing to close",
      r["allFlat"] is True and "no open positions to close" in r["sentence"], r["sentence"])

# ── 10. no exception ever escapes ───────────────────────────────────────────
print("\n[10] a closer that explodes is a result, not a crash")


def boom(uid, *, ctid, position_id):
    raise ValueError("kaboom")


w = World(1)
r = ES.run(USER, ctid="501", stopper=w.stopper, opener=w.opener, closer=boom,
           mode_fn=lambda uid, ctid: "demo")
check("outcome failed with the cause", r["closes"][0]["outcome"] == "failed"
      and "kaboom" in r["closes"][0]["detail"], str(r["closes"]))
check("and flat is not claimed", r["allFlat"] is False)

# ── 10b. a non-demo account is never touched ───────────────────────────────
print("\n[10b] closing is refused up front on anything that is not a demo account")
for bad_mode in ("live", "", None, "unknown"):
    w = World(2)
    r = run(w, mode_fn=lambda uid, ctid, m=bad_mode: m)
    check(f"mode {bad_mode!r}: no position was listed or closed",
          not [x for x in w.log if x.startswith("close:") or x == "read"], str(w.log))
    check(f"mode {bad_mode!r}: the stop still ran (the client asked for it)",
          r["automation"]["stopped"] is True)
    check(f"mode {bad_mode!r}: flat is not claimed, and the reason is demo-only",
          r["allFlat"] is False and "demo account" in r["sentence"], r["sentence"])

def _mode_boom(uid, ctid):
    raise RuntimeError("link record unreadable")

w = World(1)
r = run(w, mode_fn=_mode_boom)
check("an unreadable account mode is treated as not-demo, not as demo",
      not [x for x in w.log if x.startswith("close:")] and r["allFlat"] is False, str(w.log))

# ── 11. the route ───────────────────────────────────────────────────────────
print("\n[11] the API requires explicit confirmation and a selected account")
src = open(os.path.join(ROOT, "apex", "platform", "api.py")).read()
seg = src.split('if route == "emergency/stop":', 1)[1].split("# ── automation control", 1)[0]
check("confirm must be exactly True", 'b.get("confirm") is not True' in seg)
check("the session is re-checked, not read from cache", "fresh=True" in seg)
check("POST only", 'method != "POST"' in seg)
check("it calls the module under test", "_panic.run(" in seg)
import apex.platform.ratelimit as RL                          # noqa: E402
check("it is metered as a control action",
      RL.classify("POST", "emergency/stop") == "control", RL.classify("POST", "emergency/stop"))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All emergency-stop checks passed.")
