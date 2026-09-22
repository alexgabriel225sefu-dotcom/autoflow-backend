"""The five platform contracts, and the rules that give them their shape.

WHY THIS TEST EXISTS

Each contract exists to make one failure impossible. This file asserts those
failures stay impossible — not that the classes have the right fields.

  RuleDoc          an invalid document cannot be activated, and an active one
                   cannot be edited in place
  MarketSnapshot   the evaluator cannot read the clock
  RuleDecision     a refusal always carries a code; HOLD and REJECT are never
                   executable
  ExecutionRequest a required constraint that cannot be honoured is refused,
                   not dropped
  JournalEntry     a credential cannot enter the journal

Run: python tests/test_platform_contracts.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex import gates  # noqa: E402
from apex.platform import (decision as D, execution as E, journal as J,  # noqa: E402
                           ruledoc as R, snapshot as S)

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def raises(exc, fn):
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:
        return False


def good_doc():
    d = R.blank(user_id="u1", account_id="acc1", symbols=["EURUSD"])
    d["name"] = "Test rule"
    d["entry"]["conditions"] = [{"id": "rsi_below", "params": {"period": 14,
                                                               "value": 30}}]
    d["exit"]["conditions"] = [{"id": "rsi_above", "params": {"period": 14,
                                                              "value": 70}}]
    return d


print("\n1. RuleDoc — an invalid document cannot be activated")
check("a complete draft validates", R.is_valid(good_doc()),
      str(R.validate(good_doc()))[:80])

for field, bad in [("symbols", []), ("timeframe", ""), ("sides", "MAYBE"),
                   ("state", "running")]:
    d = good_doc()
    d[field] = bad
    check(f"{field}={bad!r} is refused", not R.is_valid(d))
    check(f"...and activate() raises for {field}",
          raises(R.RuleDocInvalid, lambda d=d: R.activate(d)))

d = good_doc()
d["entry"]["conditions"] = []
check("a rule with no entry conditions is refused", not R.is_valid(d))

d = good_doc()
d["stopLoss"] = {"mode": "none"}
check("a rule with no stop is refused — no defined worst case",
      not R.is_valid(d))

d = good_doc()
d["sizing"] = {"mode": "risk_percent", "riskPercent": 150}
check("riskPercent over 100 is refused", not R.is_valid(d))

print("\n2. RuleDoc — validate() reports EVERY problem, not the first")
d = good_doc()
d["symbols"] = []
d["timeframe"] = ""
d["sides"] = "NOPE"
probs = R.validate(d)
check("three broken fields produce three problems", len(probs) >= 3,
      f"{len(probs)}: {probs}")
check("each names its field",
      all(":" in p for p in probs), str(probs)[:80])

print("\n3. RuleDoc — unknown condition ids are caught when the library is passed")
d = good_doc()
d["entry"]["conditions"] = [{"id": "not_a_real_condition", "params": {}}]
check("unknown id passes shape validation alone", R.is_valid(d))
check("...but is refused against a known set",
      not R.is_valid(d, known_condition_ids={"rsi_below", "rsi_above"}))
check("...and the problem names the offending id",
      any("not_a_real_condition" in p for p in
          R.validate(d, known_condition_ids={"rsi_below"})))

print("\n4. RuleDoc — an ACTIVE document is immutable")
active = R.activate(good_doc())
check("activation produces state=active", active["state"] == R.ACTIVE)
check("activation stamps activatedAt", active["activatedAt"] is not None)
check("editing an active doc raises",
      raises(R.RuleDocInvalid, lambda: R.assert_editable(active)))
check("a draft is editable", R.assert_editable(good_doc()) is None)

src = good_doc()
frozen = R.activate(src)
check("activate() does not mutate its input", src["state"] == R.DRAFT,
      src["state"])

v2 = R.next_version(frozen)
check("next_version bumps the version", v2["version"] == frozen["version"] + 1)
check("next_version returns a draft", v2["state"] == R.DRAFT)
check("next_version clears activatedAt", v2["activatedAt"] is None)
check("the active version is untouched", frozen["state"] == R.ACTIVE)
check("...and keeps its own version number",
      frozen["version"] != v2["version"])

print("\n5. MarketSnapshot — the evaluator cannot read the clock")
check("a snapshot without ts is refused",
      raises(ValueError, lambda: S.MarketSnapshot(
          symbol="EURUSD", timeframe="1h", candles=[], price=1.1, ts=None)))
try:
    S.MarketSnapshot(symbol="EURUSD", timeframe="1h", candles=[], price=1.1,
                     ts=None)
    _msg = ""
except ValueError as e:
    _msg = str(e)
check("...and the error says why — the clock is the point", "clock" in _msg,
      _msg)

snap = S.MarketSnapshot(symbol="EURUSD", timeframe="1h", candles=[],
                        price=1.1, ts=1790000000.0, spread_pips=0.4,
                        open_positions=[{"symbol": "EURUSD"}], balance=1000)
check("ts is stored, not generated", snap.ts == 1790000000.0)
check("open_count counts positions", snap.open_count == 1)
check("positions_for normalises the symbol",
      len(snap.positions_for("EUR_USD")) == 1)
check("as_dict omits candles", "candles" not in snap.as_dict())
check("...but reports how many there were",
      "candleCount" in snap.as_dict())

print("\n6. RuleDecision — distinct from gates.Decision, on purpose")
rd = D.hold(rule_doc_id="r1", rule_doc_version=1, symbol="EURUSD",
            snapshot_ts=1.0)
gd = gates.Decision(True, "OK", "")
check("they are different classes", type(rd) is not type(gd))
check("gates.Decision answers 'allowed?'", hasattr(gd, "allowed"))
check("RuleDecision does not have .allowed", not hasattr(rd, "allowed"))
check("RuleDecision answers 'what verdict?'", hasattr(rd, "verdict"))
check("gates.Decision has no .verdict", not hasattr(gd, "verdict"))
check("the names differ so a reader cannot mix them",
      type(rd).__name__ == "RuleDecision" and type(gd).__name__ == "Decision")

print("\n7. RuleDecision — HOLD and REJECT never execute")
check("HOLD is not executable", not rd.executable)
rj = D.reject(rule_doc_id="r1", rule_doc_version=1, symbol="EURUSD",
              snapshot_ts=1.0, code=D.RULE_INVALID, reason="bad rule")
check("REJECT is not executable", not rj.executable)
check("REJECT carries its code", rj.refusal_code == D.RULE_INVALID)
check("a REJECT without a code is refused",
      raises(ValueError, lambda: D.RuleDecision(
          verdict=D.REJECT, rule_doc_id="r", rule_doc_version=1,
          symbol="EURUSD", snapshot_ts=1.0)))
buy = D.RuleDecision(verdict=D.BUY, rule_doc_id="r1", rule_doc_version=1,
                     symbol="EURUSD", snapshot_ts=1.0, side="BUY")
check("BUY is executable", buy.executable)
check("CLOSE is NOT executable here — it takes the close gate",
      not D.RuleDecision(verdict=D.CLOSE, rule_doc_id="r", rule_doc_version=1,
                         symbol="EURUSD", snapshot_ts=1.0).executable)
check("an invalid verdict is refused",
      raises(ValueError, lambda: D.RuleDecision(
          verdict="MAYBE", rule_doc_id="r", rule_doc_version=1,
          symbol="EURUSD", snapshot_ts=1.0)))
check("confidence stays None unless given — no invented numbers",
      rd.confidence is None)

print("\n8. ExecutionRequest — a required constraint is refused, not dropped")
doc = good_doc()
doc["order"]["maxSlippagePoints"] = 2
check("HOLD cannot become a request",
      raises(E.ExecutionRefused, lambda: E.from_decision(
          rd, doc, user_id="u1", account_id="a1", volume=1000, mode="demo",
          decision_id="d1", stop_loss=1.09)))
check("REJECT cannot become a request",
      raises(E.ExecutionRefused, lambda: E.from_decision(
          rj, doc, user_id="u1", account_id="a1", volume=1000, mode="demo",
          decision_id="d1", stop_loss=1.09)))
check("a request without a stop is refused",
      raises(E.ExecutionRefused, lambda: E.from_decision(
          buy, doc, user_id="u1", account_id="a1", volume=1000, mode="demo",
          decision_id="d1", stop_loss=None)))

req = E.from_decision(buy, doc, user_id="u1", account_id="a1", volume=1000,
                      mode="demo", decision_id="d1", stop_loss=1.09,
                      supported={"maxSlippagePoints"})
check("a supported constraint produces a request", req.side == "BUY")
check("the constraint is carried, not lost",
      any(c.name == "maxSlippagePoints" for c in req.required_constraints))
check("the request traces back to the rule version",
      req.rule_doc_version == buy.rule_doc_version)
check("the request traces back to the decision", req.decision_id == "d1")

try:
    E.from_decision(buy, doc, user_id="u1", account_id="a1", volume=1000,
                    mode="demo", decision_id="d1", stop_loss=1.09,
                    supported=set())
    check("an unsupported required constraint refuses", False, "it built one")
except E.ExecutionRefused as e:
    check("an unsupported required constraint refuses", True)
    check("...with the constraint named", e.constraint == "maxSlippagePoints")
    check("...and the code says why",
          e.code == E.CONSTRAINT_UNSUPPORTED, e.code)

check("mode must be stated — never defaulted to live",
      raises(ValueError, lambda: E.ExecutionRequest(
          user_id="u", account_id="a", symbol="EURUSD", side="BUY",
          order_type="MARKET", volume=1, rule_doc_id="r", rule_doc_version=1,
          decision_id="d", mode="", reason="")))

print("\n9. JournalEntry — a credential cannot enter the journal")
dirty = {"symbol": "EURUSD", "ctrader_access_token": "secret-abc",
         "nested": {"refresh_token": "r-123", "price": 1.1},
         "rows": [{"api_key": "k"}, {"ok": True}]}
clean = J.redact(dirty)
blob = str(clean)
check("a top-level token is redacted", "secret-abc" not in blob)
check("a nested token is redacted", "r-123" not in blob)
check("a token inside a list is redacted", '"k"' not in blob and "'k'" not in blob)
check("innocent data survives", clean["symbol"] == "EURUSD"
      and clean["nested"]["price"] == 1.1)

entry = J.for_evaluation(rd, snap, correlation_id="corr1", user_id="u1")
check("an evaluation entry is journalled", entry.kind == J.EVALUATION)
check("...even for a HOLD — 'why nothing happened' is a real question",
      entry.decision["verdict"] == "HOLD")
check("it carries the correlation id", entry.correlation_id == "corr1")
check("an entry without a correlation id is refused",
      raises(ValueError, lambda: J.JournalEntry(
          kind=J.ERROR, correlation_id="", user_id="u1")))

ereq = J.for_execution(req, correlation_id="corr1")
check("the execution entry shares the correlation id",
      ereq.correlation_id == entry.correlation_id)
check("...which is what joins the chain",
      ereq.rule_doc_id == entry.rule_doc_id)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - the five contracts refuse what they exist to refuse.")
