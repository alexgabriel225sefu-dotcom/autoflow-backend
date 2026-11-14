"""Account kinds: demo, live or unverified, from what cTrader reported.

WHAT THESE TESTS WILL NOT ACCEPT

* An account of unknown type shown or treated as demo.
* A live account described as ready to trade when the deployment does not allow
  live accounts, or when the pilot is unset or does not list it.
* A kind invented from a label, an id or anything but the recorded mode.

Run: python3 tests/test_account_kind.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-kind-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
for v in ("A4T_LIVE_PILOT_PAIRS", "A4T_LIVE_PILOT_SYMBOLS", "A4T_LIVE_PILOT_MAX_UNITS"):
    os.environ.pop(v, None)
from apex.platform import account_kind as K   # noqa: E402

fails = []
def check(n, c, d=""):
    print(f"  {'ok  ' if c else 'FAIL'} {n}" + (f"  {d}" if d and not c else ""))
    if not c: fails.append(n)

def status(accounts, live_allowed=False, selected=None):
    return {"connected": True, "accounts": accounts, "liveAllowed": live_allowed,
            "selected": {"ctid": selected} if selected else None}

ACC = [{"ctid": 1, "mode": "demo", "label": "Demo EUR"},
       {"ctid": 2, "mode": "live", "label": "Live USD"},
       {"ctid": 3, "mode": None, "label": "Demo-looking name"},
       {"ctid": 4, "mode": "paper"}]

print("[1] kinds come from the recorded mode only")
out = K.classify("u1", status(ACC, selected=2))
kinds = {r["ctid"]: r["kind"] for r in out["accounts"]}
check("demo", kinds[1] == "demo")
check("live", kinds[2] == "live")
check("missing mode is unverified, whatever the label says", kinds[3] == "unverified")
check("an unexpected mode is unverified", kinds[4] == "unverified")
check("summary counts", out["summary"] == {"demo": 1, "live": 1, "unverified": 2})
check("selected flagged", [r["ctid"] for r in out["accounts"] if r["selected"]] == [2])

print("[2] a live account says what stands in the way")
check("not enabled on this deployment", out["accounts"][1]["liveState"] == "not_enabled")
out2 = K.classify("u1", status(ACC, live_allowed=True))
check("pilot not set up", out2["accounts"][1]["liveState"] == "pilot_unconfigured")
os.environ["A4T_LIVE_PILOT_PAIRS"] = "u1:2"
os.environ["A4T_LIVE_PILOT_SYMBOLS"] = "EURUSD"
os.environ["A4T_LIVE_PILOT_MAX_UNITS"] = "1000"
out3 = K.classify("u1", status(ACC, live_allowed=True))
check("in the pilot", out3["accounts"][1]["liveState"] == "in_pilot")
check("in_pilot text does not promise an order", "still needs" in out3["accounts"][1]["liveText"])
out4 = K.classify("someone-else", status(ACC, live_allowed=True))
check("another user is not in the pilot", out4["accounts"][1]["liveState"] == "not_in_pilot")

print("[3] unverified is closed, demo is open")
check("unverified text says no order", "no order" in out["accounts"][2]["liveText"])
check("demo has no live state", out["accounts"][0]["liveState"] is None)

print("[4] not connected / malformed")
check("not connected", K.classify("u1", {"connected": False})["accounts"] == [])
check("junk status", K.classify("u1", None)["connected"] is False)
check("junk account rows skipped", len(K.classify("u1", status([None, 5, {"ctid": 1, "mode": "demo"}]))["accounts"]) == 1)
print("\nFAILED: " + ", ".join(fails) if fails else "\nALL OK")
sys.exit(1 if fails else 0)
