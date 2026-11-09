"""Reconnecting a broker must not wipe the account's settings.

The link callback writes credentials and the mirrored balance. It does not
rebuild the strategy, the symbol, or the open-position snapshot. A second
delivery of the same callback must not notify twice.

The cold socket after a link is why the balance read retries in one place.

Run: python tests/test_reconnect_no_reonboard.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OAUTH = open(os.path.join(ROOT, "apex", "ctrader_oauth.py"), encoding="utf-8").read()
CT = open(os.path.join(ROOT, "apex", "brokers", "ctrader.py"), encoding="utf-8").read()

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


print("\nlink callback keeps the account and notifies once")
check("the balance read retries in the broker module",
      "def account_balance_retry" in CT)
_bal = CT[CT.index("def account_balance_retry"):CT.index("def get_broker_name")]
check("it loops over attempts", "for attempt in range(1" in _bal)
check("it pauses between attempts", "time.sleep(pause)" in _bal)
check("it does not pause after the last attempt", "if attempt < attempts:" in _bal)
check("the link uses that one retry", "account_balance_retry(" in OAUTH)
check("a duplicate callback is claimed before a second note",
      "user_store.claim(" in OAUTH and "ttl_s=90" in OAUTH)
check("the note goes to the in-platform alerts",
      "client_alerts.note(" in OAUTH)
check("the callback does not clear the saved symbol or strategy",
      '"symbol"' not in OAUTH.split("updates = {")[1].split("user_store.update")[0])

print()
if failures:
    print(f"FAILED {len(failures)}")
    sys.exit(1)
print("ALL RECONNECT CHECKS PASSED.")
