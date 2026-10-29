"""Every entry logs ONE order line: symbol, side, units, SL, TP, risk $ and risk %.

Before this the engine never wrote down what it was about to risk. The size,
the stop and the balance were all known at the moment of the order, but a
reader of the log (or the journal) had to reconstruct the dollar risk from
three places — and the min-lot disclosure, the one case where the risk is
deliberately NOT what the client asked for, did not carry the SL/TP at all.

Run: python tests/test_entry_order_line.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ["PAPER_TRADING"] = "true"

from apex import forex  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + ("" if cond else f"  {detail}"))
    if not cond:
        failures.append(name)


print("\n1. entry_risk measures dollars and percent")
pv = forex.pip_value_per_unit("EURUSD", 1.1618)
usd, pct = forex.entry_risk(10_000, "EURUSD", 1.1618, 15, 3000.0)
check("dollars = units x pip value x stop pips",
      abs(usd - 10_000 * pv * 15) < 1e-6, str(usd))
check("percent of the balance", abs(pct - usd / 3000.0 * 100) < 1e-6, str(pct))
check("no balance -> percent is None, not a divide error",
      forex.entry_risk(10_000, "EURUSD", 1.1618, 15, 0)[1] is None)

print("\n2. order_line carries every field")
line = forex.order_line("EURUSD", "BUY", 10_000, 1.16030, 1.16480, 15.0, 0.5)
for part in ("EURUSD", "BUY", "units=10000", "SL=1.1603", "TP=1.1648",
             "risk=$15.00", "0.50% of balance"):
    check(f"contains {part!r}", part in line, line)
check("a missing TP is shown as none, not dropped",
      "TP=none" in forex.order_line("XAUUSD", "SELL", 1, 4080.0, None, 40.0, 1.2))
check("an unknown percent is shown as such",
      "n/a" in forex.order_line("XAUUSD", "SELL", 1, 4080.0, 4000.0, 40.0, None))

print("\n3. The loop logs it and journals it for every entry and the disclosure")
with open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8") as fh:
    SRC = fh.read()
i_line = SRC.find("_order_line = forex.order_line(")
i_auth = SRC.find("_decision, _rid = gates.authorize_order(")
check("the order line is built before the gate", 0 < i_line < i_auth,
      f"{i_line} vs {i_auth}")
check("it is printed", 'print(f"[UserLoop:{user_id}] ORDER {_order_line}")' in SRC)
check("the gate verdict journal carries riskUsd/riskPct",
      SRC.count('"riskUsd": _risk_usd') >= 2 and SRC.count('"riskPct": _risk_pct') >= 2)
check("...and the order line itself", SRC.count('"orderLine": _order_line') >= 2)
i_notice = SRC.find('dash["minLotNotice"] = {')
check("the min-lot disclosure carries the order line too",
      i_notice > 0 and '"orderLine"' in SRC[i_notice:i_notice + 700])

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - every entry states what it risks.")
