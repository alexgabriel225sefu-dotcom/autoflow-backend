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
    export SMOKE_SELECT_CTID=<demo cTrader account id>  # optional
    export SMOKE_SYMBOL=EURUSD            # optional
    export SMOKE_TIMEFRAME=15m            # optional  (1m 5m 15m 30m 1h 4h 1d)
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

CONFIRM_VAR = "SMOKE_CONFIRM_DEMO_ONLY"
DEMO = "demo"


class Refused(RuntimeError):
    """The script will not start. Distinct from a step that failed."""


def guard_env(env=None):
    """The refusals that need nothing imported yet. Returns the user id.

    Separated from `guard` and run BEFORE importing `apex`, because
    `apex.platform.store` refuses at import time when TOKEN_ENCRYPTION_KEY is
    absent — by design, it fails closed rather than storing credentials in
    plaintext. That refusal used to be the first thing an operator saw when they
    had simply forgotten SMOKE_CONFIRM_DEMO_ONLY: a true statement about a
    different problem than the one they had, naming the wrong variable to set.
    Both orders refuse, so nothing was ever unsafe; only the message was wrong.
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

    return user_id


# Run as a script: refuse before importing anything, so the message names the
# variable the operator actually needs to set.
if __name__ == "__main__":
    try:
        guard_env()
    except Refused as _e:
        print(f"REFUSED: {_e}")
        sys.exit(2)

from apex import redact                                     # noqa: E402

# Before anything can print. Installing this after the first output would
# leave exactly the line that carried the token.
redact.install()

from apex.platform import broker_read as _read              # noqa: E402
from apex.platform import ctrader_link as _link             # noqa: E402
from apex.platform import decision as _dec                  # noqa: E402
from apex.platform import entitlement as _ent               # noqa: E402
from apex.platform import preview as _preview               # noqa: E402
from apex.platform import store as _store                   # noqa: E402


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
    user_id = guard_env(env)

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


def select_for_smoke(user_id, ctid, *, selector=None):
    """Select the demo account that this smoke run should exercise.

    Selection is a platform preference, not a broker action. It still goes
    through ctrader_link.select_account so the same ownership and live-account
    blocks apply here as in the HTTP API.
    """
    want = str(ctid or "").strip()
    if not want:
        return None
    status = (selector or _link.select_account)(user_id, want)
    selected = (status or {}).get("selected") or {}
    if str(selected.get("ctid") or "") != want:
        raise Refused("SMOKE_SELECT_CTID did not become the selected "
                      "account. Stop and inspect ctrader/select before "
                      "running broker reads")
    if selected.get("mode") != DEMO:
        raise Refused(
            f"SMOKE_SELECT_CTID selected a {selected.get('mode')!r} "
            f"account, not {DEMO!r}")
    return status


def _is_number(v):
    """A balance is a number. True is not one, whatever isinstance says."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _attempt(rep, name, call):
    """Call a reader; a raised exception becomes a failed step.

    Every reader in the sequence is contracted to answer with a status rather
    than raise, so an exception here is a defect rather than a state of the
    connection. It used to escape as a traceback, which aborted the run and
    left every later step unreported — and a traceback is not a test result.
    The step it belongs to now fails under its own name, and the caller gets
    None so that the steps depending on the answer are skipped rather than
    evaluated against a dict invented here.
    """
    try:
        return call()
    except Exception as e:                                  # noqa: BLE001
        rep.step(name, False, f"{type(e).__name__}: {redact.scrub(str(e))}")
        return None


class Report:
    """Steps and their outcomes. Everything printed goes through scrub()."""

    def __init__(self, out=None):
        self.out = out if out is not None else sys.stdout
        self.failures = []
        self.steps = []
        self.skipped = []

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

    def skip(self, name, why):
        """A step that did not run — said out loud, and counted.

        A skipped step must never be invisible. `exit 0` with a step missing
        looks exactly like `exit 0` with every step passing: the only
        difference is the number in the summary line, and nobody compares that
        between runs. X1 gets closed on the strength of this script's exit
        code, so a quiet skip is precisely how an untested path would end up
        recorded as proven.

        Not a failure. There is nothing wrong with having no rule to preview;
        what is wrong is a report that does not say so.
        """
        self.skipped.append((name, why))
        self.say(f"  SKIP  {name}  —  {why}")


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
    # apex.forex.TIMEFRAMES, not cTrader's M15/H1 notation: broker_read
    # validates against the platform's own names and raises on anything
    # else, so a default in the broker's dialect could never reach a bar.
    timeframe = timeframe or (os.getenv("SMOKE_TIMEFRAME") or "15m").strip()

    status = _attempt(rep, "accounts reads ok",
                      lambda: r["accounts"](user_id))
    if status is None:
        return rep
    selected = status.get("selected") or {}
    rep.say(f"\naccount {mask_ctid(selected.get('ctid'))}  "
            f"mode={selected.get('mode')}  symbol={symbol}  tf={timeframe}")
    rep.say("")

    cap = _attempt(rep, "the server says this client may automate",
                   lambda: r["capability"](user_id))
    if cap is None:
        return rep
    rep.step("the server says this client may automate",
             cap.get("canAutomate") is True, cap.get("message"))
    rep.step("and that live execution is off",
             cap.get("liveExecutionEnabled") is False)
    rep.step("and the badge is DEMO", cap.get("badge") == "DEMO",
             str(cap.get("badge")))

    bal = _attempt(rep, "balance reads ok", lambda: r["balance"](user_id))
    if bal is not None:
        rep.step("balance reads ok", bal.get("status") == "ok",
                 str(bal.get("reason") or ""))
        # The amount is not asserted, and neither is a currency. The account's
        # balance is whatever it is, and inventing an expectation for it would
        # be the one thing this product does not do; the currency is not in
        # broker_read's contract at all, so a step demanding one was asserting
        # against a key nothing produces and nothing reads. What IS a contract
        # is the type — a dashboard formats this number.
        rep.step("and the balance is a number, not a string or a None",
                 bal.get("status") != "ok" or _is_number(bal.get("balance")),
                 type(bal.get("balance")).__name__)

    pos = _attempt(rep, "positions reads ok",
                   lambda: r["positions"](user_id))
    if pos is not None:
        rep.step("positions reads ok", pos.get("status") == "ok",
                 str(pos.get("reason") or ""))
        rep.step("and an empty list is a FACT, not a missing key",
                 pos.get("status") != "ok"
                 or isinstance(pos.get("positions"), list))

    orders = _attempt(rep, "orders reads ok", lambda: r["orders"](user_id))
    if orders is not None:
        rep.step("orders reads ok", orders.get("status") == "ok",
                 str(orders.get("reason") or ""))

    cds = _attempt(rep, "candles read ok",
                   lambda: r["candles"](user_id, symbol=symbol,
                                        timeframe=timeframe, limit=200))
    ok_c = cds is not None and cds.get("status") == "ok"
    if cds is not None:
        rep.step("candles read ok", ok_c, str(cds.get("reason") or ""))
    rows = (cds or {}).get("candles") or []
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
            # symbol, timeframe and ts are all passed on purpose.
            #
            # build_snapshot REFUSES without `ts` rather than reading the
            # clock, because a timestamp the platform chose would silently
            # answer every session and weekday condition in the rule. The
            # honest value is the last CLOSED bar, which is what these bars
            # are — the forming bar is not in them.
            #
            # Without symbol and timeframe it falls back to the rule's own,
            # which would label these bars as an instrument and a period they
            # did not come from, and the evaluator would then compare the
            # rule's instrument against itself and always agree.
            out = _preview.preview(doc, {
                "candles": rows, "symbol": symbol, "timeframe": timeframe,
                "ts": rows[-1]["time"],
            })
            # The verdict lives on the decision, not at the top level, and the
            # set of verdicts is decision.VERDICTS rather than a tuple written
            # out here — a hand-written one drifts, and this step once checked
            # for a "SETUP" that has never been a verdict in this product.
            d = out.get("decision") or {}
            rep.step("preview runs on real bars",
                     d.get("verdict") in _dec.VERDICTS,
                     f"{d.get('verdict')} — {d.get('reason') or ''}"[:120])
            rep.step("and the verdict is explained, not asserted",
                     bool(d.get("conditions") or d.get("reason")))
            # A preview is never executable, whatever the verdict. Asserted
            # here because this is the only place the real evaluator runs on
            # real market data, which is exactly where that must hold.
            rep.step("and the preview is reported as unexecutable",
                     out.get("executable") is False,
                     str(out.get("executable")))
        except Exception as e:                              # noqa: BLE001
            rep.step("preview runs on real bars", False,
                     f"{type(e).__name__}: {redact.scrub(str(e))}")
    elif rule_id:
        rep.step("preview runs on real bars", False,
                 "no candles to preview on — the step above failed")
    else:
        rep.skip("preview runs on real bars",
                 "no SMOKE_RULE_ID was given, so the evaluator has still "
                 "only ever seen synthetic candles")

    return rep


def summarise(rep):
    """The last thing an operator reads, and the exit code. 0, or 1.

    Separated from main() on purpose: this is where a skipped step either
    survives into the summary or quietly disappears, and main() cannot be
    exercised at all without a broker — so without this split the summary is
    the one part of the script no test can reach.
    """
    rep.say("")
    if rep.failures:
        rep.say(f"FAILED ({len(rep.failures)}):")
        for f in rep.failures:
            rep.say(f"  - {f}")
        rep.say("\nThe connected path is NOT working. Do not record X1 as "
                "closed.")
        return 1
    rep.say(f"All {len(rep.steps)} steps passed against a real demo account.")
    if rep.skipped:
        rep.say(f"\nBut {len(rep.skipped)} step(s) did NOT run, so this is "
                f"not a complete pass:")
        for name, why in rep.skipped:
            rep.say(f"  - {name}: {why}")
        rep.say("Record what was SKIPPED next to what passed, or the record "
                "claims more than the run proved.")
    rep.say("\nRecord this in docs/RELEASE_READINESS.md, with the date and "
            "the masked account number.")
    return 0


def main(argv=None):
    rep = Report()
    try:
        user_id = guard()
        select_ctid = (os.getenv("SMOKE_SELECT_CTID") or "").strip()
        if select_ctid:
            selected_status = select_for_smoke(user_id, select_ctid)
            selected = selected_status.get("selected") or {}
            rep.say(f"selected account {mask_ctid(selected.get('ctid'))} "
                    "for this smoke run")
        selected = demo_only(user_id)
    except Refused as e:
        rep.say(f"\nREFUSED: {redact.scrub(str(e))}")
        rep.say("Nothing was contacted.")
        return 2
    except _link.LinkError as e:
        rep.say(f"\nREFUSED: {e.code}: {redact.scrub(e.detail)}")
        rep.say("Nothing was contacted.")
        return 2
    rep.say(f"cTrader demo smoke test — account {mask_ctid(selected['ctid'])}")
    run(user_id, report=rep)
    return summarise(rep)


if __name__ == "__main__":
    sys.exit(main())
