"""“Why isn't it trading?” — answered, with the one reason that is true.

WHY THIS EXISTS

The Telegram bot had /why. The platform's equivalent was the Render log: a
client watching a Running dashboard with no trade could not tell a bot that was
working from one that was broken, and "spread too wide" existed only in a log
they cannot open. Silence makes a working bot look broken.

WHAT THESE TESTS WILL NOT ACCEPT

* A reason that is not the most explanatory TRUE one (stopped must beat
  "market closed"; a halt must beat everything).
* “Running” being reported when the loop is not active on this server.
* An empty refusal list being worded as "there was no reason".
* A source that cannot be read turning the whole answer into an error.
* Anything credential-shaped in the answer.

Run: python3 tests/test_automation_why.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-why-")
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


from apex.platform import automation as AU                  # noqa: E402
from apex.platform import emergency as EM                   # noqa: E402

USER = "why-user"


def put(state, level="full"):
    AU._write(USER, {"state": state, "ruleDocId": "r1", "mode": "demo",
                     "appliedTerms": {"automation": level}})


def ask(*, alive=True, dash=None, rows=None, market=True, rows_error=False,
        loop_error=False):
    def loop_reader(_uid):
        if loop_error:
            raise RuntimeError("loop registry unavailable")
        return alive, (dash if dash is not None else {})

    def declines_reader(_uid):
        if rows_error:
            raise RuntimeError("log unavailable")
        return rows or []

    return AU.why(USER, loop_reader=loop_reader,
                  declines_reader=declines_reader, market_open=lambda: market)


# ── 1. each reason, and its order ───────────────────────────────────────────
print("\n[1] the reason named is the most explanatory one that is true")
put(AU.STOPPED)
r = ask(market=False)
check("stopped beats market-closed", r["reason"] == "stopped", r["reason"])
put(AU.PAUSED)
check("paused is its own reason", ask()["reason"] == "paused")

put(AU.RUNNING, "full")
check("running + loop alive + market open = watching",
      ask()["reason"] == "watching", ask()["reason"])
check("market closed is named when that is all there is",
      ask(market=False)["reason"] == "market_closed")
r = ask(dash={"openPosition": {"symbol": "EURUSD"}, "maxpos": 1})
check("an open position at the limit is the reason",
      r["reason"] == "position_open" and "EURUSD" in r["summary"], str(r))

r = ask(alive=False)
check("Running but no loop here is said, not hidden",
      r["reason"] == "loop_inactive" and r["loopActive"] is False, str(r))
check("and the wait is stated honestly (it is minutes, not seconds)",
      "fifteen minutes" in r["summary"], r["summary"])

put(AU.RUNNING, "approval")
r = ask()
check("a level that does not place orders says so",
      r["reason"] == "level_no_orders" and "Approval Required" in r["summary"],
      str(r))
put(AU.RUNNING, "signals")
check("signals only too", ask()["reason"] == "level_no_orders")

# The level explanation must outrank a closed market: the client changing the
# level is the only thing that changes the outcome.
check("level beats market-closed", ask(market=False)["reason"] == "level_no_orders")

# ── 2. a halt beats everything ──────────────────────────────────────────────
print("\n[2] an emergency stop outranks every other reason")
put(AU.RUNNING, "full")
_real = AU._emerg.check


def _halt(**_k):
    raise EM.Halted("HALTED", "stopped", scope="global")


AU._emerg.check = _halt
try:
    r = ask(dash={"openPosition": {"symbol": "EURUSD"}}, market=False)
    check("halted wins over position/market", r["reason"] == "halted"
          and r["halted"] is True, str(r))
finally:
    AU._emerg.check = _real

# ── 3. refusals: kept apart, and an empty list is not "no reason" ───────────
print("\n[3] refusals, honestly worded")
put(AU.RUNNING, "full")
dash = {"skipsToday": 3, "skips": [
    {"time": "09:15", "reason": "spread too wide"},
    {"time": "08:45", "reason": "cooldown after loss"}]}
rows = [{"ts": 1700000000.0, "symbol": "EURUSD",
         "payload": {"reason": "daily loss limit"}}]
r = ask(dash=dash, rows=rows)
check("in-memory refusals are carried with their time",
      r["skips"][0] == {"time": "09:15", "reason": "spread too wide"}, str(r["skips"]))
check("the persistent log is carried with its instrument",
      r["recorded"][0]["symbol"] == "EURUSD"
      and r["recorded"][0]["reason"] == "daily loss limit", str(r["recorded"]))
check("the two lists are not merged", r["skips"] != r["recorded"])
check("skipsToday is the engine's count", r["skipsToday"] == 3)

r = ask(dash={}, rows=[])
check("nothing recorded is reported as a count of zero, not as an answer",
      r["recordedCount"] == 0 and r["recordedReadable"] is True, str(r))
check("and no summary claims refusals did not happen",
      "no refus" not in r["summary"].lower()
      and "no reason" not in r["summary"].lower(), r["summary"])

# ── 4. unreadable sources degrade, never raise ──────────────────────────────
print("\n[4] an unreadable source is reported, and the answer still comes")
r = ask(rows_error=True)
check("log unreadable → still ok, flagged",
      r["status"] == "ok" and r["recordedReadable"] is False, str(r))
r = ask(loop_error=True)
check("loop state unreadable → still ok, loopActive unknown (not False)",
      r["status"] == "ok" and r["loopActive"] is None, str(r))
check("and unknown is never turned into 'the loop is dead'",
      r["reason"] != "loop_inactive", r["reason"])

# ── 5. bounded, and no secret ───────────────────────────────────────────────
print("\n[5] bounded output with no credentials in it")
big = {"skips": [{"time": "1", "reason": "x" * 5000}] * 50}
r = ask(dash=big)
check("at most 10 in-memory refusals", len(r["skips"]) <= 10, str(len(r["skips"])))
check("each reason is capped", all(len(s["reason"]) <= 120 for s in r["skips"]))
flat = repr(ask(dash=dash, rows=rows)).lower()
check("nothing credential-shaped", not any(
    w in flat for w in ("token", "secret", "password", "apikey")), flat[:200])

# ── 5b. the Risk Guard ──────────────────────────────────────────────────────
print("\n[5b] the Risk Guard's last report is carried, and never invented")
HOLD = lambda uid: ("holding", ["daily loss limit 4% reached"])      # noqa: E731
OKR = lambda uid: ("ok", [])                                           # noqa: E731
UNK = lambda uid: ("unknown", [])                                      # noqa: E731


def ask_risk(reader, *, alive=True, level="full"):
    put(AU.RUNNING, level)
    return AU.why(USER, loop_reader=lambda u: (alive, {}),
                  declines_reader=lambda u: [], market_open=lambda: True,
                  risk_reader=reader)


r = ask_risk(HOLD)
check("a holding guard is the stated reason, with its own reasons",
      r["reason"] == "risk_holding" and "daily loss limit 4% reached" in r["summary"],
      str(r))
check("and the guard block is carried for the screen",
      r["riskGuard"] == {"state": "holding", "reasons": ["daily loss limit 4% reached"]},
      str(r["riskGuard"]))
check("a holding guard outranks 'this level places no orders'",
      ask_risk(HOLD, level="approval")["reason"] == "risk_holding")
check("but a dead loop is still named first",
      ask_risk(HOLD, alive=False)["reason"] == "loop_inactive")
check("an ok guard does not change the verdict",
      ask_risk(OKR)["reason"] == "watching" and ask_risk(OKR)["riskGuard"]["state"] == "ok")
check("a guard that has not reported is 'unknown', never 'ok'",
      ask_risk(UNK)["riskGuard"]["state"] == "unknown", str(ask_risk(UNK)["riskGuard"]))


def _raises(uid):
    raise RuntimeError("dash unavailable")


check("an unreadable guard is 'unknown' and does not raise",
      AU.risk_guard(USER, reader=_raises) == {"state": "unknown", "reasons": []})
check("an unrecognised state from the reader is 'unknown', not passed through",
      AU.risk_guard(USER, reader=lambda u: ("fine", [])) ["state"] == "unknown")
check("reasons are bounded",
      len(AU.risk_guard(USER, reader=lambda u: ("holding", ["x"] * 50))["reasons"]) <= 5)
put(AU.RUNNING, "full")
check("status() carries the guard so every screen can show it",
      "riskGuard" in AU.status(USER) and AU.status(USER)["riskGuard"]["state"] in ("ok", "holding", "unknown"),
      str(AU.status(USER).get("riskGuard")))

# The loop idles through the weekend close window before it publishes a Risk
# Guard report, so a loop revived on a Saturday has none. status() says WHY the
# report may be absent, so the chip need not read as a guard that failed to
# start. None — not False — when unreadable: never claim a closed market that
# was not checked.
check("status() says the weekend window is in force when it is",
      AU.status(USER, weekend_reader=lambda: True)["marketClosed"] is True)
check("and that it is not when it is not",
      AU.status(USER, weekend_reader=lambda: False)["marketClosed"] is False)


def _boom():
    raise RuntimeError("clock unreadable")


check("an unreadable clock is None, never a guess",
      AU.status(USER, weekend_reader=_boom)["marketClosed"] is None)

# ── 6. the route exists and is a GET ────────────────────────────────────────
print("\n[6] GET /automation/why is routed")
src = open(os.path.join(ROOT, "apex", "platform", "api.py")).read()
check("api routes 'why' to automation.why",
      'action == "why"' in src and "_auto.why(" in src)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All why-no-trade checks passed.")
