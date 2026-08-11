"""Guards against settings that exist in config but never reach a live account.

Three defects of exactly this shape have already shipped:

  * EV_GATE_MODE / EV_MIN_PROBABILITY / EV_MIN_SAMPLES were absent from the
    per-user config the loop actually reads, so `EV_GATE_MODE=enforce` in the
    environment was silently ignored and the gate could only ever run in shadow.
  * MAX_SPREAD_PIPS was a hard-coded 3.0, overriding the strict 1.2p scalp
    ceiling — every entry was admitted up to 3 pips.
  * The news guard split "EURUSD" on "_", producing ["EURUSD"], which matches
    no ISO currency, so it never fired on any Auto-Pilot symbol.

Each is invisible at runtime: the setting is present, documented and wrong.

Run: python tests/test_config_reaches_loop.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-cfg-test-")
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import user_loop  # noqa: E402
from apex import config as appcfg  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


print("\n── the per-user config carries every setting the loop reads ──")
_, cfg = user_loop._make_broker({"ctrader_access_token": "x",
                                 "ctrader_account_id": "1"})

for key in ("EV_GATE_MODE", "EV_MIN_PROBABILITY", "EV_MIN_SAMPLES"):
    check(f"{key} present", hasattr(cfg, key),
          "missing → getattr() default wins and the env var does nothing")

check("EV_GATE_MODE tracks the product config",
      cfg.EV_GATE_MODE == appcfg.EV_GATE_MODE,
      f"{cfg.EV_GATE_MODE!r} vs {appcfg.EV_GATE_MODE!r}")
check("MAX_SPREAD_PIPS tracks the product config, not a literal",
      cfg.MAX_SPREAD_PIPS == appcfg.MAX_SPREAD_PIPS,
      f"{cfg.MAX_SPREAD_PIPS} vs {appcfg.MAX_SPREAD_PIPS}")

print("\n── per-user overrides are honoured ──")
_, cfg2 = user_loop._make_broker({"ctrader_access_token": "x",
                                  "ctrader_account_id": "1",
                                  "max_spread_pips": 0.8,
                                  "ev_min_probability": 0.72})
check("max_spread_pips override", cfg2.MAX_SPREAD_PIPS == 0.8,
      str(cfg2.MAX_SPREAD_PIPS))
check("ev_min_probability override", cfg2.EV_MIN_PROBABILITY == 0.72,
      str(cfg2.EV_MIN_PROBABILITY))

print("\n── the news guard resolves currencies from any symbol spelling ──")
cases = [
    ("EURUSD",  ["EUR", "USD"]),
    ("EUR_USD", ["EUR", "USD"]),
    ("eur/usd", ["EUR", "USD"]),
    ("GBPJPY",  ["GBP", "JPY"]),
    ("XAUUSD",  ["XAU", "USD"]),
]
for sym, expect in cases:
    got = user_loop._currency_legs(sym)
    check(f"{sym} → {expect}", got == expect, f"got {got}")

check("gold is still guarded against USD releases",
      "USD" in user_loop._currency_legs("XAUUSD"))
check("unparseable symbols yield no legs (guard stays fail-open)",
      user_loop._currency_legs("US30") == []
      and user_loop._currency_legs("") == []
      and user_loop._currency_legs(None) == [])

print("\n── regression: the old split would have matched nothing ──")
check("the bug is real — 'EURUSD'.split('_') matches no ISO code",
      "EURUSD".split("_") == ["EURUSD"]
      and "EURUSD" not in ("EUR", "USD"))


print("\n── the risk ladder can be corrected and expires with the day ──")
from apex import control_actions  # noqa: E402

check("loss_streak is remotely settable",
      "loss_streak" in control_actions._SETTABLE)
check("and is coerced to an int over the string transport",
      control_actions.coerce_setting("loss_streak", "2") == 2)

import time as _t  # noqa: E402

_YESTERDAY = _t.time() - 26 * 3600
_u_old = {"ctrader_access_token": "x", "ctrader_account_id": "1",
          "loss_streak": 4, "last_loss_at": _YESTERDAY}
_u_today = {"ctrader_access_token": "x", "ctrader_account_id": "1",
            "loss_streak": 4, "last_loss_at": _t.time() - 600}


def _streak_after_start(user):
    """Mirror the loop's startup rule without spinning a real loop."""
    from datetime import datetime as _dt
    ls = int(user.get("loss_streak") or 0)
    lla = float(user.get("last_loss_at") or 0)
    if ls and lla:
        if (_dt.fromtimestamp(lla).strftime("%Y-%m-%d")
                != _dt.now().strftime("%Y-%m-%d")):
            return 0
    return ls


check("a streak from a previous day is cleared",
      _streak_after_start(_u_old) == 0)
check("today's streak is kept", _streak_after_start(_u_today) == 4)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL CONFIG-REACHES-LOOP CHECKS PASSED.")
