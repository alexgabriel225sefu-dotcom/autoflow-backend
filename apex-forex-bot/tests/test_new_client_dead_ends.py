"""Two dead ends a brand-new client hits, and nobody had ever been one.

Found by tracing a verified-but-empty account from the landing page to a
running rule. Both are the same defect in different clothes: the product
accepts something, says it worked, and then cannot do it.

── 1. A RULE SAVED BEFORE AN ACCOUNT WAS SELECTED COULD NEVER GET ONE ──────

`api._create` derives `accountId` from the client's selected account. Only
at creation. The dashboard's own "Create a rule" button and the builder's
"what happens next" list both invite building a rule BEFORE connecting a
broker, and nothing on that path says otherwise.

Such a rule stores `accountId: ""` and stays that way forever: `save_draft`
never derives it, and the edit form never sends it. Validation then refused
it with "connect and select an account, then save the rule again" — and
saving again changed nothing. Validate, Preview and Activate all said the
same thing. The only escape was to work out that the rule was unfixable and
start a second one.

A refusal that names an action which cannot work is worse than one that
names none: the client does it, nothing changes, and they conclude the
product is broken. They are not wrong.

── 2. A CHOSEN READY-MADE STRATEGY WAS NEVER RUN BY ANYTHING ───────────────

`strategy_catalog.preset_of` says the preset field is judged "at the
boundaries that care — activation, and the engine hand-off". Activation was
wired. The hand-off was not: `engine_config.translate` wrote
`RULE_STRATEGY_ID` unconditionally and never read the document's preset.

So "Choose a strategy" → pick one → activate → Start pointed the loop at
`platform_rule`, which asks the rule evaluator, which refuses a preset
document on every bar because a preset carries no conditions to judge. The
dashboard said "Watching market". The journal filled with holds. Nothing
traded, and no screen said why.

The rule page had been telling the truth about the intent the whole time —
"using the X strategy, which decides its own entries and exits" — while the
backend did not do it. That is the recurring shape: the screen asserts a
state that is not true.

Run: python3 tests/test_new_client_dead_ends.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-deadend-")
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
from apex.platform import ctrader_link as CTL               # noqa: E402
from apex.platform import engine_config as EC               # noqa: E402
from apex.platform import ruledoc as RD                     # noqa: E402
from apex.platform import store as PS                       # noqa: E402
from apex.platform import strategy_catalog as SC            # noqa: E402

USER = "cccccccc-3333-4333-8333-cccccccccccc"
COND = {"id": "rsi", "params": {"period": 14, "comparator": "below",
                                "value": 30}}


# ── 1. the accountless rule ─────────────────────────────────────────────────
print("\n[1] a rule built before an account was selected")

# The exact state a new client is in: verified, no broker connected, and a
# rule page inviting them to build something.
doc = RD.blank(user_id=USER, account_id="", symbols=["EURUSD"],
               timeframe="5m")
doc["entry"] = {"mode": "all", "conditions": [COND]}
doc["sides"] = "BUY"
rid = doc["ruleDocId"]
PS.create(USER, doc)
check("it saves with no account, as it did before",
      PS.get(USER, rid).get("accountId") == "")

probs = RD.validate(PS.get(USER, rid), known_condition_ids={"rsi"})
_acct = [str(p) for p in probs if str(p).startswith("accountId")]
check("and validation refuses it", bool(_acct), str(probs))
check("telling the client to save the rule again",
      any("save the rule again" in p for p in _acct), str(_acct))

print("\n[2] the client connects an account and saves again, as told")
CTL._store._write(CTL._k_conn(USER), {
    "userId": USER,
    "accessToken": "tok-not-a-real-token",
    "expiresAt": 9_999_999_999,
    "accounts": [{"ctid": "778899", "mode": CTL.DEMO, "label": "demo"}],
    "selectedCtid": "778899",
    "selectedMode": CTL.DEMO,
})

# Driven through the REAL PUT route, not store.save_draft directly. The fix
# lives at the API boundary (which is where the selection is readable), and
# the whole bug was that the layer below never derived it — so a test that
# called the layer below would have passed before the fix.
_real_auth = API._authenticate


class _P:
    user_id = USER
    email_verified = True


API._authenticate = lambda headers, **kw: _P()
try:
    st, payload = API.handle("PUT", f"{API.PREFIX}rules/{rid}",
                             headers={}, body=b'{"name":"My first rule"}')
    check("the save succeeds", st == 200, str(st))
    saved = PS.get(USER, rid)
    check("and the rule now carries the selected account",
          saved.get("accountId") == "778899", str(saved.get("accountId")))
    check("so saving again did what the refusal said it would",
          not [p for p in RD.validate(saved, known_condition_ids={"rsi"})
               if str(p).startswith("accountId")],
          str(RD.validate(saved, known_condition_ids={"rsi"})))

    print("\n[3] and a rule that already names an account keeps it")
    # Re-pointing a rule at a different account on an unrelated save is not
    # an edit the client asked for.
    PS.save_draft(USER, {"ruleDocId": rid, "accountId": "111222"})
    API.handle("PUT", f"{API.PREFIX}rules/{rid}",
               headers={}, body=b'{"name":"renamed"}')
    check("an existing accountId is not overwritten",
          PS.get(USER, rid).get("accountId") == "111222",
          str(PS.get(USER, rid).get("accountId")))
finally:
    API._authenticate = _real_auth


# ── 4. the preset hand-off ──────────────────────────────────────────────────
print("\n[4] a chosen strategy is what the loop is pointed at")
_offered = SC.ids()
check("the platform offers at least one preset", bool(_offered),
      "without one this section cannot test anything — "
      "a harness that cannot detect a positive proves nothing")

if _offered:
    sid = _offered[0]
    pdoc = SC.apply_to(
        RD.blank(user_id=USER, account_id="778899", symbols=["EURUSD"],
                 timeframe="5m"), sid)
    applied, missed = EC.translate(pdoc)
    check(f"translate points the loop at {sid!r}, not at the rule evaluator",
          applied.get("strategy") == sid,
          f"{applied.get('strategy')} — platform_rule here is the bug: the "
          f"evaluator refuses a preset document on every bar")
    check("and does not report the strategy as a term it ignores",
          not [m for m in missed if m.get("term") == "Strategy"],
          str([m for m in missed if m.get("term") == "Strategy"]))

print("\n[5] a rule built from conditions is still run by the evaluator")
applied_c, _ = EC.translate(
    dict(doc, entry={"mode": "all", "conditions": [COND]}))
check("a condition rule gets the rule strategy",
      applied_c.get("strategy") == EC.RULE_STRATEGY_ID,
      str(applied_c.get("strategy")))

print("\n[6] a preset the platform no longer offers is NOT pointed at")
# The withdrawn-after-activation case. Falling back silently is what caused
# the original bug, so the fallback must be VISIBLE.
gone = dict(doc)
gone["strategy"] = "a_strategy_that_was_withdrawn"
applied_g, missed_g = EC.translate(gone)
check("the loop is not pointed at a strategy nothing loads",
      applied_g.get("strategy") == EC.RULE_STRATEGY_ID,
      str(applied_g.get("strategy")))
_rep = [m for m in missed_g if m.get("term") == "Strategy"]
check("and the client is told, per rule, rather than left to wonder",
      bool(_rep), str(missed_g))
check("in words that name what to do",
      _rep and ("choose a strategy" in _rep[0]["why"]
                or "rebuild it" in _rep[0]["why"]),
      str(_rep))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All new-client dead-end checks passed.")
