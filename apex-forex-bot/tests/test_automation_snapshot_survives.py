"""Stop must put back the client's OWN settings, however many times the loop restarted.

THE BUG, FOUND IN A READ-ONLY REVIEW BEFORE THE MONDAY DEMO

`automation.start` captures `engineSnapshot` — the account's settings as they
were before the rule touched them — so `stop()` can restore them. It captured
it by reading the account record, every time it ran.

`start` also runs on REVIVE (the supervisor restarting a loop after a deploy)
and on RESUME (after a pause). By then the account record already holds the
RULE's terms, so the "snapshot" taken was the rule's own settings, and it
overwrote the original one on the automation record. A Stop after any redeploy
or pause then "restored" the rule's settings, and the client's real ones were
gone for good: a rule that ran once left its risk, stop and target behind on
the account, which is the exact problem the snapshot exists to prevent.

The control case ([1]) is a plain start then stop. It passed before the fix,
and it is there to prove this harness CAN detect a restored account. A test
that passes in every state proves nothing.

Run: python3 tests/test_automation_snapshot_survives.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-snapshot-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ["CTRADER_REDIRECT_URI"] = "https://apex4traders.test/cb"
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("A4T_EMERGENCY_HALT", None)

from apex import user_store                             # noqa: E402
from apex.brokers import ctrader as _ct_broker          # noqa: E402
from apex.platform import automation as AU              # noqa: E402
from apex.platform import ctrader_link as CL            # noqa: E402
from apex.platform import plans as _plans               # noqa: E402
from apex.platform import ruledoc as _rd                # noqa: E402
from apex.platform import store as _store              # noqa: E402

_ct_broker.list_accounts = lambda token: [{"ctid": 901, "live": False}]

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


# Account settings that differ from the rule in every field compared below, so
# a match proves the ORIGINAL came back and not that two values coincided.
ENGINE_BEFORE = {
    "symbol": "GBPUSD", "timeframe": "5m",
    "sl_pips": 11, "tp_pips": 22, "risk": 0.07, "maxpos": 9,
    "max_trades_day": 8,
}
KEYS = ("sl_pips", "tp_pips", "risk", "max_trades_day")


def fresh_user(n):
    """A connected demo account with an active rule, from scratch."""
    uid = f"eeee0000-0000-4000-8000-{n:012d}"
    begun = CL.begin(uid)
    state = begun["authorizeUrl"].split("state=")[1].split("&")[0]
    CL.handle_callback({"code": "c", "state": state},
                       exchanger=lambda c, u: {"accessToken": "TOK",
                                               "refreshToken": "REF",
                                               "expiresIn": 2592000})
    CL.complete(uid, begun["nonce"],
                lister=lambda a: [{"ctid": 901, "live": False}])
    CL.select_account(uid, 901)
    _plans.start_trial(uid)
    user_store.save(uid, dict(ENGINE_BEFORE))

    doc = _rd.blank(user_id=uid, account_id="901", symbols=["EURUSD"],
                    timeframe="4h")
    doc["name"] = "snapshot rule"
    doc["entry"]["conditions"] = [{"id": "rsi", "period": 14, "op": "below",
                                   "value": 30}]
    doc["sides"] = "BUY"
    doc["sizing"] = {"mode": _rd.SIZING_RISK, "riskPercent": 0.25,
                     "fixedVolume": None}
    doc["stopLoss"] = {"mode": "pips", "atrMultiple": None, "pips": 77}
    doc["takeProfit"] = {"mode": "pips", "rr": None, "pips": 155}
    doc["limits"] = {"maxOpenPositions": 1, "maxDailyTrades": 2,
                     "maxExposurePercent": None, "maxSpreadPips": None,
                     "onLimit": "block"}
    rid = doc["ruleDocId"]
    _store.create(uid, doc)
    _store.activate(uid, rid, known_condition_ids={"rsi"})
    return uid, rid


def ok_starter(uid):
    return True


def restored(uid):
    """Which of the compared keys are back at the client's original value."""
    now = user_store.load(uid) or {}
    return {k: now.get(k) for k in KEYS}


WANT = {k: ENGINE_BEFORE[k] for k in KEYS}

# ── 1. control: a plain start then stop ─────────────────────────────────────
print("\n[1] control: start then stop restores the client's settings")
uid, rid = fresh_user(1)
AU.start(uid, rid, starter=ok_starter)
during = restored(uid)
check("while running, the RULE's terms are on the account",
      during != WANT and during["sl_pips"] == 77.0, str(during))
AU.stop(uid, stopper=lambda u: True)
check("after Stop the original settings are back",
      restored(uid) == WANT, f"{restored(uid)} != {WANT}")

# ── 2. REVIVE: the supervisor restarts the loop, then the client stops ──────
print("\n[2] a revive (redeploy) must not overwrite the original snapshot")
uid, rid = fresh_user(2)
AU.start(uid, rid, starter=ok_starter)
AU.start(uid, rid, starter=ok_starter, revive=True)   # what supervise() does
AU.stop(uid, stopper=lambda u: True)
check("Stop after a revive still restores the ORIGINAL settings",
      restored(uid) == WANT,
      f"{restored(uid)} != {WANT} — the revive recorded the rule's own "
      f"terms as if they were the client's")

# ── 3. RESUME: pause then resume then stop ──────────────────────────────────
print("\n[3] a pause and resume must not overwrite it either")
uid, rid = fresh_user(3)
AU.start(uid, rid, starter=ok_starter)
AU.pause(uid, stopper=lambda u: True)
AU.resume(uid, starter=ok_starter)
AU.stop(uid, stopper=lambda u: True)
check("Stop after pause + resume still restores the ORIGINAL settings",
      restored(uid) == WANT, f"{restored(uid)} != {WANT}")

# ── 4. several restarts in a row ────────────────────────────────────────────
print("\n[4] and so does a loop revived more than once")
uid, rid = fresh_user(4)
AU.start(uid, rid, starter=ok_starter)
for _ in range(3):
    AU.start(uid, rid, starter=ok_starter, revive=True)
AU.stop(uid, stopper=lambda u: True)
check("three revives in a row do not lose the original",
      restored(uid) == WANT, f"{restored(uid)} != {WANT}")

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All snapshot-survival checks passed.")
