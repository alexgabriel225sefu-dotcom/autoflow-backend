"""On a LIVE account the 1% per-trade cap holds at ORDER time, broker minimum or not.

The broker-minimum floor (`units = max(units, floor)`) can size a trade past
the client's risk setting. On demo that is allowed up to what is left of the
daily-loss limit and DISCLOSED (minLotNotice) — the owner's gold demo runs on
exactly that, so it is kept. On a live account the ceiling is the platform's
`maxRiskPercentLive` (1%), and a minimum lot that would risk more is REFUSED
with the numbers named, instead of being sent.

Run: python tests/test_live_min_lot_cap.py
"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["PAPER_TRADING"] = "true"

from apex import forex  # noqa: E402
from apex import user_loop  # noqa: E402
from apex.platform import risk_gates  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + ("" if cond else f"  {detail}"))
    if not cond:
        failures.append(name)


BAL = 3221.0
PX = 4040.0
PV = forex.pip_value_per_unit("XAUUSD", PX)
# A stop that costs 1 oz $48 — 1.49% of the account, the case in the audit.
STOP = 48.0 / PV

print("\n1. The cap is the platform's live cap, not a second number")
check("live cap equals risk_gates maxRiskPercentLive",
      forex.live_risk_cap_pct() == float(risk_gates.PLATFORM["maxRiskPercentLive"]),
      str(forex.live_risk_cap_pct()))

print("\n2. A minimum lot past 1% is refused on live, with the numbers named")
why = forex.live_risk_refusal(1, "XAUUSD", PX, STOP, BAL)
check("1 oz risking 1.49% is refused", bool(why), str(why))
check("the refusal names the dollars and the percent",
      why and "$48.00" in why and "1.49%" in why and "1%" in why, str(why))
check("the same trade is ALLOWED on demo under the daily headroom (unchanged)",
      forex.floor_risk_ok(1, "XAUUSD", PX, STOP, BAL * 0.005,
                          hard_ceiling_usd=forex.daily_loss_headroom_usd(BAL, 4.0, 0.0)))

print("\n3. Inside the cap is allowed; the boundary is exact")
check("risk of 0.9% passes", forex.live_risk_refusal(
    1, "XAUUSD", PX, (BAL * 0.009) / PV, BAL) is None)
check("risk of exactly 1% passes", forex.live_risk_refusal(
    1, "XAUUSD", PX, (BAL * 0.01) / PV, BAL) is None)
check("risk of 1.01% is refused (no 10% lot-step tolerance on live)",
      forex.live_risk_refusal(1, "XAUUSD", PX, (BAL * 0.0101) / PV, BAL) is not None)

print("\n4. Unmeasurable risk fails closed on live")
check("no stop -> refused", forex.live_risk_refusal(1, "XAUUSD", PX, 0, BAL) is not None)
check("no balance -> refused", forex.live_risk_refusal(1, "XAUUSD", PX, STOP, 0) is not None)

print("\n5. Live is read from the broker env AND the paper flag")
live = SimpleNamespace(CTRADER_ENV="live", PAPER_TRADING=False)
demo = SimpleNamespace(CTRADER_ENV="demo", PAPER_TRADING=False)
paper_live = SimpleNamespace(CTRADER_ENV="live", PAPER_TRADING=True)
check("cTrader live + broker-executed is live", user_loop._is_live_cfg(live) is True)
check("cTrader demo is not live", user_loop._is_live_cfg(demo) is False)
check("simulated fills on a live env are not live money",
      user_loop._is_live_cfg(paper_live) is False)
check("upper-case LIVE is still live",
      user_loop._is_live_cfg(SimpleNamespace(CTRADER_ENV="LIVE", PAPER_TRADING=False)))
check("missing fields are not live",
      user_loop._is_live_cfg(SimpleNamespace()) is False)

print("\n6. The loop asks the live cap BEFORE the order is sent")
with open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8") as fh:
    SRC = fh.read()
i_cap = SRC.find("forex.live_risk_refusal(")
i_send = SRC.find("_order_res = broker.place_order(")
check("the loop calls live_risk_refusal", i_cap > 0)
check("...before place_order", 0 < i_cap < i_send, f"{i_cap} vs {i_send}")
check("...only on a live account", "_is_live_cfg(cfg)" in SRC[i_cap - 600:i_cap])
check("...and the refusal reaches the skip log", "_skip(_live_why)" in SRC)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - a live minimum lot cannot exceed the 1% cap.")
