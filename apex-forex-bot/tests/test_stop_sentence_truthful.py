"""What Stop tells the client about open positions must match what exists.

The sentence was wrong twice, in opposite directions (see the docstring of
`automation._flatten_answer`): first it over-claimed that nothing could place
an order, then it under-claimed once the demo Close existed ("no way to close a
position"). A client who presses Stop with a losing position open reads it and
acts on it, so it is tied here to the capability it describes.

Run: python3 tests/test_stop_sentence_truthful.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-stopsentence-")
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


from apex.platform import automation as AU              # noqa: E402

ans = AU._flatten_answer({})
msg = ans["flattenReason"]

print("\n[1] Stop still declines to flatten, and says so")
check("it reports that nothing was closed", ans["flattened"] is False)
check("and that it declined, as the spec requires", ans["flattenDeclined"] is True)
check("the sentence says open positions stay open",
      "does not close" in msg, msg)
check("and that the broker keeps their stop and target",
      "stop and target" in msg, msg)

print("\n[2] it does not deny a capability that exists")
try:
    from apex.platform import position_close as PC
    exists = callable(getattr(PC, "close_demo", None))
except Exception as e:                                   # noqa: BLE001
    exists = False
check("the demo Close is really there (the premise of this test)", exists)
check("so the sentence must not say there is no way to close",
      "no way to close" not in msg.lower(), msg)
check("and it points at where closing is available",
      "Positions" in msg and "cTrader" in msg, msg)
check("without implying it works on a live account",
      "demo" in msg.lower(), msg)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All Stop-sentence checks passed.")
