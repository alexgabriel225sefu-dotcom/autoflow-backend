"""One instrument, one spelling — and named at the rule, not at the order.

TWO PROBLEMS, BOTH SEEN ON A REAL PHONE DURING THE FIRST WALK-THROUGH

The instruments field is free text and was stored EXACTLY as typed. An
autocorrect produced `EURUSd` and the rule saved with it. `eurusd`,
`EUR_USD` and `eur/usd` would each have stored differently too — the same
instrument as four documents that never compare equal, with the client's own
typo quoted back at them in the rule summary, the journal and the engine
config as if it were a product term.

And validation accepted any non-empty string. A rule naming something this
product does not trade saved, activated and started; the engine refuses it
far downstream, where no screen is watching, so the only symptom was
automation that ran and never did anything. That is the exact ambiguity this
project keeps paying for — "nothing happened" meaning two different things.

Run: python3 tests/test_ruledoc_symbols.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-symbols-")
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


from apex.platform import ruledoc as RD                     # noqa: E402
from apex.platform import store as PS                       # noqa: E402

USER = "symbols-user"
COND = {"id": "rsi", "params": {"period": 14, "comparator": "below",
                                "value": 30}}


# ── 1. every spelling of one instrument stores identically ──────────────────
print("\n[1] four ways of typing EURUSD become one document")
forms = ["EURUSd", "eurusd", "EUR_USD", "eur/usd", " EURUSD "]
got = {tuple(RD.normalise_symbols({"symbols": [f]})["symbols"]) for f in forms}
check("they all normalise to the same thing", got == {("EURUSD",)}, str(got))

print("\n[2] and the same instrument twice is one instrument")
out = RD.normalise_symbols({"symbols": ["EURUSD", "eurusd", "EUR_USD"]})
check("duplicates collapse", out["symbols"] == ["EURUSD"], str(out["symbols"]))
out = RD.normalise_symbols({"symbols": ["EURUSD", "USDJPY"]})
check("but genuinely different ones are kept, in order",
      out["symbols"] == ["EURUSD", "USDJPY"], str(out["symbols"]))

print("\n[3] a malformed field is left for validate() to report")
# Normalising must not swallow the real problem by raising or by inventing a
# value — the error the client needs is "every entry must be a string".
for bad in (None, "EURUSD", [123], []):
    r = RD.normalise_symbols({"symbols": bad})
    check(f"{bad!r} passes through untouched", r.get("symbols") == bad,
          str(r.get("symbols")))

# ── 4. an untradeable instrument is refused AT THE RULE ─────────────────────
print("\n[4] an instrument this product does not trade is refused on save")


def doc_with(sym):
    d = RD.blank(user_id=USER, account_id="901", symbols=[sym],
                 timeframe="5m")
    d["entry"] = {"mode": "all", "conditions": [COND]}
    d["sides"] = "BUY"
    return d


probs = RD.validate(doc_with("EURGBP"), known_condition_ids={"rsi"})
check("EURGBP (no USD leg) is rejected",
      any(str(p).startswith("symbols:") for p in probs), str(probs))
msg = " ".join(str(p) for p in probs)
check("and the refusal says what IS accepted",
      "USD" in msg and ("EURUSD" in msg or "XAUUSD" in msg), msg)
check("BTCUSD is rejected too",
      any(str(p).startswith("symbols:")
          for p in RD.validate(doc_with("BTCUSD"),
                               known_condition_ids={"rsi"})))
check("while EURUSD validates",
      not any(str(p).startswith("symbols:")
              for p in RD.validate(doc_with("EURUSD"),
                                   known_condition_ids={"rsi"})))
check("and XAUUSD does too",
      not any(str(p).startswith("symbols:")
              for p in RD.validate(doc_with("XAUUSD"),
                                   known_condition_ids={"rsi"})))

# ── 5. the normalisation is actually applied by the STORE ───────────────────
# Normalising in a function nobody calls is the shape of bug this project has
# hit repeatedly. This drives the real save path.
print("\n[5] the save path applies it, not just the helper")
d = doc_with("EURUSd")
rid = d["ruleDocId"]
PS.create(USER, d)
saved = PS.get(USER, rid)
check("create() stores the canonical spelling",
      saved["symbols"] == ["EURUSD"], str(saved["symbols"]))
PS.save_draft(USER, {"ruleDocId": rid, "symbols": ["eur_usd"]})
check("and so does save_draft()",
      PS.get(USER, rid)["symbols"] == ["EURUSD"],
      str(PS.get(USER, rid)["symbols"]))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All rule-document symbol checks passed.")
