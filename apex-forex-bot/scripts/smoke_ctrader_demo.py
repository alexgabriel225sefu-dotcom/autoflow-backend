"""Smoke test against a REAL cTrader demo account. Read-only, by construction.

WHY THIS EXISTS

Every connected path in this product is covered by contract tests and none of
it has ever spoken to cTrader. `docs/RELEASE_READINESS.md` calls that blocker
X1, and it is the largest single gap in the release: the success states — an
account with a balance in it, positions with data, a chart with real bars, a
preview judged on live candles — have been exercised against stubs and never
against a broker.

A test cannot close that, because it needs a credential that belongs on a
deployment and not in a repository. So this is a script, and it goes to the
credentials rather than the other way round.

WHAT IT WILL NOT DO

It places no order, closes nothing, and amends nothing. It imports no
execution module at all — `tests/test_smoke_harness.py` reads this file and
asserts that, because a comment promising it is worth nothing.

It refuses to run unless the operator states, in the environment, that the
account is a demo account; and it refuses again if the platform's own record
says the selected account is not demo. Two statements from two different
places, because the whole point of the exercise is that this one is being run
against something real.

It prints no token. `apex.redact` is installed over stdout and stderr before
any output at all, so even an exception traceback from deep inside a broker
library is scrubbed on the way out.

RUN IT

    export SMOKE_CONFIRM_DEMO_ONLY=yes
    export SMOKE_USER_ID=<the Supabase user id whose link to exercise>
    export SMOKE_SYMBOL=EURUSD            # optional
    export SMOKE_TIMEFRAME=M15            # optional
    export SMOKE_RULE_ID=<a ruleDocId>    # optional — also previews it
    cd apex-forex-bot && python3 scripts/smoke_ctrader_demo.py

EXIT CODES

    0  every step passed
    1  a step failed — the connected path is not working
    2  refused to run, and said why. Nothing was contacted.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import redact                                     # noqa: E402

# Before anything can print. Installing this after the first output would
# leave exactly the line that carried the token.
redact.install()

from apex.platform import broker_read as _read              # noqa: E402
from apex.platform import ctrader_link as _link             # noqa: E402
from apex.platform import entitlement as _ent               # noqa: E402
from apex.platform import preview as _preview               # noqa: E402
from apex.platform import store as _store                   # noqa: E402

CONFIRM_VAR = "SMOKE_CONFIRM_DEMO_ONLY"
DEMO = "demo"


class Refused(RuntimeError):
    """The script will not start. Distinct from a step that failed."""


def mask_ctid(ctid):
    """An account number is not a credential, and it does identify a person.

    Enough of it survives to match against a broker statement; not enough to
    be pasted into an issue and identify the client.
    """
    s = str(ctid or "")
    return s if len(s) <= 3 else "…" + s[-3:]


def guard(env=None):
    """Raise Refused unless it is safe and sensible to start.

    Every refusal names the variable to set. A script that exits 2 without
    saying which of five conditions failed gets run again with a guess.
    """
    env = os.environ if env is None else env

    if (env.get(CONFIRM_VAR) or "").strip().lower() not in ("yes", "y", "true"):
        raise Refused(
            f"{CONFIRM_VAR} is not set to 'yes'. This talks to a real broker "
            f"account, so it will not start until an operator states that the "
            f"account is a DEMO account")

    user_id = (env.get("SMOKE_USER_ID") or "").strip()
    if not user_id:
        raise Refused("SMOKE_USER_ID is not set — there is no client whose "
                      "connection to exercise")

    if not (env.get("TOKEN_ENCRYPTION_KEY") or "").strip():
        raise Refused("TOKEN_ENCRYPTION_KEY is not set, so the stored broker "
                      "token cannot be decrypted. Run this where the "
                      "deployment's environment is")

    # If this is ever True, the release has changed underneath this script and
    # "read-only by construction" is no longer a claim it can make.
    if _ent.live_execution_enabled():
        raise Refused("live execution is reported as ENABLED. This script "
                      "assumes a release that cannot place a live order and "
                      "will not run against one that can")

    return user_id


def demo_only(user_id, *, status_fn=None):
    """The selected account, or Refused. The second of the two statements."""
    status = (status_fn or _link.public_status)(user_id)
    if not status.get("connected"):
        raise Refused("no cTrader account is connected for that user — "
                      "connect one first")
    selected = status.get("selected") or {}
    if not selected.get("ctid"):
        raise Refused("a cTrader account is connected but none is selected")
    if selected.get("mode") != DEMO:
        raise Refused(
            f"the selected account is {selected.get('mode')!r}, not "
            f"{DEMO!r}. This script refuses to touch anything else, whatever "
            f"the environment says")
    return selected


class Report:
    """Steps and their outcomes. Everything printed goes through scrub()."""

    def __init__(self, out=None):
        self.out = out if out is not None else sys.stdout
        self.failures = []
        self.steps = []

    def say(self, line):
        # Belt and braces: redact.install() already wraps stdout, and this
        # makes the guarantee hold for a Report writing somewhere else.
        print(redact.scrub(line), file=self.out)

    def step(self, name, ok, detail=""):
        self.steps.append((name, bool(ok)))
        if not ok:
            self.failures.append(name)
        self.say(f"  {'PASS' if ok else 'FAIL'}  {name}"
                 + (f"  —  {detail}" if detail else ""))
        return bool(ok)


# The read-only sequence. Named as data so a test can assert the order
# without running any of it, and so adding a write here is a visible diff.
SEQUENCE = ("accounts", "capability", "balance", "positions", "orders",
            "candles")


def run(user_id, *, report=None, readers=None, symbol=None, timeframe=None,
        rule_id=None):
    """Walk the read-only sequence. Returns the Report."""
    rep = report or Report()
    r = dict({
        "accounts": _link.public_status,
        "capability": _ent.capability,
        "balance": _read.account,
        "positions": _read.positions,
        "orders": _read.orders,
        "candles": _read.candles,
    }, **(readers or {}))

    symbol = symbol or (os.getenv("SMOKE_SYMBOL") or "EURUSD").strip()
    timeframe = timeframe or (os.getenv("SMOKE_TIMEFRAME") or "M15").strip()

    status = r["accounts"](user_id)
    selected = status.get("selected") or {}
    rep.say(f"\naccount {mask_ctid(selected.get('ctid'))}  "
            f"mode={selected.get('mode')}  symbol={symbol}  tf={timeframe}")
    rep.say("")

    cap = r["capability"](user_id)
    rep.step("the server says this client may automate",
             cap.get("canAutomate") is True, cap.get("message"))
    rep.step("and that live execution is off",
             cap.get("liveExecutionEnabled") is False)
    rep.step("and the badge is DEMO", cap.get("badge") == "DEMO",
             str(cap.get("badge")))

    bal = r["balance"](user_id)
    rep.step("balance reads ok", bal.get("status") == "ok",
             str(bal.get("reason") or ""))
    # A number is not asserted. The account's balance is whatever it is, and
    # inventing an expectation for it would be the one thing this product
    # does not do.
    if bal.get("status") == "ok":
        rep.step("and carries a currency", bool(bal.get("currency")),
                 str(bal.get("currency") or "none"))

    pos = r["positions"](user_id)
    rep.step("positions reads ok", pos.get("status") == "ok",
             str(pos.get("reason") or ""))
    rep.step("and an empty list is a FACT, not a missing key",
             pos.get("status") != "ok" or isinstance(pos.get("positions"), list))

    orders = r["orders"](user_id)
    rep.step("orders reads ok", orders.get("status") == "ok",
             str(orders.get("reason") or ""))

    cds = r["candles"](user_id, symbol=symbol, timeframe=timeframe, limit=200)
    ok_c = cds.get("status") == "ok"
    rep.step("candles read ok", ok_c, str(cds.get("reason") or ""))
    rows = cds.get("candles") or []
    if ok_c:
        rep.step("and there are bars in it", len(rows) > 0, f"{len(rows)} bars")
        rep.step("each bar has OHLC and a time",
                 all(all(k in c for k in ("time", "open", "high", "low",
                                          "close")) for c in rows[:5]))
        rep.step("and they are in ascending time order",
                 all(rows[i]["time"] <= rows[i + 1]["time"]
                     for i in range(min(len(rows), 50) - 1)))
        if rows:
            rep.say(f"       latest bar at {rows[-1]['time']} — compare this "
                    f"against the broker's own chart")

    rule_id = rule_id or (os.getenv("SMOKE_RULE_ID") or "").strip()
    if rule_id and ok_c and rows:
        # The one step that exercises the evaluator on real bars. It computes
        # a verdict and places nothing; preview has no execution path at all,
        # which tests/test_platform_http.py asserts structurally.
        try:
            doc = _store.get(user_id, rule_id)
            out = _preview.preview(doc, {"candles": rows})
            rep.step("preview runs on real bars",
                     out.get("verdict") in ("SETUP", "HOLD", "REJECT"),
                     str(out.get("verdict")))
            rep.step("and the verdict is explained, not asserted",
                     bool(out.get("conditions") or out.get("reason")))
        except Exception as e:                              # noqa: BLE001
            rep.step("preview runs on real bars", False,
                     f"{type(e).__name__}: {redact.scrub(str(e))}")
    elif rule_id:
        rep.step("preview runs on real bars", False,
                 "no candles to preview on — the step above failed")

    return rep


def main(argv=None):
    rep = Report()
    try:
        user_id = guard()
        selected = demo_only(user_id)
    except Refused as e:
        rep.say(f"\nREFUSED: {redact.scrub(str(e))}")
        rep.say("Nothing was contacted.")
        return 2
    rep.say(f"cTrader demo smoke test — account {mask_ctid(selected['ctid'])}")
    run(user_id, report=rep)
    rep.say("")
    if rep.failures:
        rep.say(f"FAILED ({len(rep.failures)}):")
        for f in rep.failures:
            rep.say(f"  - {f}")
        rep.say("\nThe connected path is NOT working. Do not record X1 as "
                "closed.")
        return 1
    rep.say(f"All {len(rep.steps)} steps passed against a real demo account.")
    rep.say("Record this in docs/RELEASE_READINESS.md, with the date and the "
            "masked account number.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
