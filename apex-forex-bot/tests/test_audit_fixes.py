"""Regressions for the defects the full-project audit turned up.

Every one of these passed the 84-file suite before it was fixed, which is the
point: each bug lived in a place no assertion looked at. They are grouped by
what they cost, worst first.

  * REALISED P&L charged the spread twice on every live close. `entryPrice`
    and the exit are the broker's own fills — a buy fills at the ask, its
    close at the bid — so the round trip is already inside `gross`. Charging
    the entry-spread estimate on top made every live trade read worse than the
    same trade in cTrader's History tab, and corrupted the journal and every
    stat built on it. cTrader's own number is grossProfit + swap - commission:
    no spread term. In PAPER the prices are candle mids with no spread in
    them, so there the estimate is the only thing modelling the cost and it
    MUST still be charged. That asymmetry is the fix.
  * The MINIMUM-LOT FLOOR overrode risk sizing without limit. `max(units,
    floor)` with nothing checking the result still fit the risk budget: on a
    $3,243 account at 0.5%, a 200-pip EUR_USD stop risked 1.23x and a 500-pip
    stop 3.08x — and it gets worse as the account shrinks, so it bites
    hardest right after a drawdown.
  * NEWS PROTECTION fails open on an unrecognised symbol: `_currency_legs`
    returning [] means high_impact_window([]) matches nothing and returns
    None, so the symbol trades straight through NFP/CPI/FOMC with the filter
    on and nothing logged. Everything traded today is a 6-character pair, but
    the by-name split stays because the failure is silent.
  * EVERY ORDER-GATE REFUSAL was reported to the client as "an identical
    order was sent moments ago". A lapsed licence, a drawdown halt, an
    unreadable ownership lease and an unreachable backend all arrived as a
    duplicate-order message that was simply untrue and hid the real cause.
  * THRESHOLDS KEYED ON THE BUILD rather than the instrument. On a
    single-product build such a branch is not merely mistuned, it is dead —
    and its absence is silent. Every per-instrument value now resolves from
    the instrument at the point of use.
  * `open_position_snapshot` — the record of a live position across a restart
    — was the one piece of money-state left out of the compare-and-set
    allowlist, so any concurrent write could clobber it back to "flat".
  * FX CROSSES WITH NO USD LEG were sized through a margin cap that read one
    unit of GBP_JPY as $190 instead of ~$1.21: 1/31 of the intended risk.

Run: python tests/test_audit_fixes.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-audit-")

from apex import config as cfg, forex, user_loop, user_store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


def src(mod):
    return open(os.path.join(ROOT, "apex", mod), encoding="utf-8").read()


print("\n🔍  AUDIT REGRESSIONS\n")

# ── 1. Realised cost: spread once, not twice ──────────────────────────────
print("1. The spread is charged once, not twice")
POS = {"entrySpreadPips": 1.5, "side": "BUY", "entryPrice": 1.0800}
PV, UNITS = forex.pip_value_per_unit("EUR_USD", 1.0800), 10000

live = user_loop.realized_cost_usd(POS, {"commissionUsd": 3.0}, PV, UNITS, False)
check("live charges commission only", abs(live - 3.0) < 1e-9,
      f"got {live} — the fills already contain the round-trip spread")

paper = user_loop.realized_cost_usd(POS, None, PV, UNITS, True)
expected = 1.5 * PV * UNITS
check("paper still charges the spread estimate", abs(paper - expected) < 1e-9,
      f"got {paper}, expected {expected} — candle mids carry no spread")
paper_same = user_loop.realized_cost_usd(POS, {"commissionUsd": 3.0}, PV,
                                        UNITS, True)
check("paper costs more than live for the identical close",
      paper_same > live and abs(paper_same - (live + expected)) < 1e-9,
      f"paper {paper_same} vs live {live} — equal means the bug is back")

LSRC = src("user_loop.py")
check("no close site subtracts the raw spread estimate any more",
      'cost_usd = (open_pos.get("entrySpreadPips"' not in LSRC,
      "a close computing its own cost bypasses the live/paper distinction")
check("every close routes through the one helper",
      LSRC.count("realized_cost_usd(") >= 6,
      "5 call sites plus the definition")

# ── 2. The minimum-lot floor cannot outrun the risk budget ────────────────
print("\n2. The minimum lot cannot spend more than the configured risk")
BAL, RISK = 3243.0, 0.005
BUDGET = BAL * RISK
for stop, ok_expected in ((30, True), (200, False), (500, False)):
    sized = forex.round_units(
        max(forex.calc_units(BAL, RISK, stop, "EUR_USD", 1.08, leverage=30.0),
            forex.safe_min_units("EUR_USD", BAL, 1.08, 30.0, 0.5)), "EUR_USD")
    got = forex.floor_risk_ok(sized, "EUR_USD", 1.08, stop, BUDGET)
    risk = sized * forex.pip_value_per_unit("EUR_USD", 1.08) * stop
    check(f"EUR_USD {stop}-pip stop → {'allowed' if ok_expected else 'refused'}",
          got is ok_expected,
          f"{sized:.0f}u risks ${risk:.2f} against a ${BUDGET:.2f} budget")
check("the guard is read before the order branch, not inside it",
      LSRC.index("floor_risk_ok(units, symbol, price")
      < LSRC.index("_order_res = broker.place_order("),
      "setting entry_ok inside the executing branch stops nothing")

# ── 3. News legs ─────────────────────────────────────────────────────────
print("\n3. Every tradeable symbol has news legs")
for sym, legs in (("EURUSD", ["EUR", "USD"]), ("EUR_USD", ["EUR", "USD"]),
                  ("USDJPY", ["USD", "JPY"]), ("XAUUSD", ["XAU", "USD"]),
                  ("XAGUSD", ["XAG", "USD"]), ("NZDUSD", ["NZD", "USD"])):
    check(f"{sym} → {legs}", user_loop._currency_legs(sym) == legs,
          f"got {user_loop._currency_legs(sym)} — no legs means no news guard")
check("nonsense still yields no legs", user_loop._currency_legs("JUNK") == []
      and user_loop._currency_legs("") == [])
check("every Auto-Pilot candidate is guarded",
      all(user_loop._currency_legs(s) for s in cfg.FX_UNIVERSE),
      "an unguarded symbol trades through NFP with the filter on")

# ── 4. Per-instrument, never per-build ───────────────────────────────────
print("\n4. Thresholds resolve from the instrument, not the build")


class _Cfg:
    MAX_SPREAD_PCT = 0
    FLASH_SPIKE_PCT = 0.012
    LEVERAGE = 30.0


class _CfgExplicit:
    MAX_SPREAD_PCT = 0.1
    FLASH_SPIKE_PCT = 0.012
    LEVERAGE = 7.0
    LEVERAGE_EXPLICIT = True


check("the %-spread ceiling is off unless an operator sets one",
      user_loop.max_spread_pct_for(_Cfg(), "EUR_USD") == 0.0,
      "MAX_SPREAD_PIPS is the real guard here")
check("an explicit ceiling wins for every symbol",
      user_loop.max_spread_pct_for(_CfgExplicit(), "EUR_USD") == 0.1
      and user_loop.max_spread_pct_for(_CfgExplicit(), "XAUUSD") == 0.1)
check("an explicit leverage wins for a real symbol",
      user_loop.leverage_for_symbol(None, _CfgExplicit(), "EUR_USD") == 7.0,
      "the docstring promised this and the code reached it nowhere")
check("flash-spike threshold is read from config, not a build flag",
      user_loop.flash_spike_pct_for(_Cfg(), "EUR_USD") == 0.012
      and user_loop.flash_spike_pct_for(_Cfg(), "XAUUSD") == 0.012)

TG = src("telegram.py")
check("no asset-class branch survives in the instrument picker",
      "asset_class" not in TG,
      "the crypto product is gone; there is nothing to choose between")
check("the broker filter narrows the offered list",
      "for label, code in syms if code in offered" in TG)

# ── 5. Refusals are named honestly ────────────────────────────────────────
print("\n5. A refused order says why it was refused")
check("force_trade passes the gate's own reason up",
      '"error": _claim_why or "ORDER_REFUSED"' in LSRC,
      "reporting every refusal as a duplicate hides lapsed licences")
for reason in ("NOT_ENTITLED", "RISK_HALTED", "NOT_OWNER",
               "ENTITLEMENT_UNKNOWN", "STORE_UNREACHABLE",
               "COORDINATION_UNAVAILABLE", "DUPLICATE_ORDER"):
    check(f"{reason} has client-facing words", f'"{reason}":' in TG)

# ── 6. The open-position snapshot is CAS-protected ────────────────────────
print("\n6. Money-state is compare-and-set protected")
check("open_position_snapshot is in the allowlist",
      "open_position_snapshot" in user_store.CRITICAL_FIELDS,
      "a concurrent write could clobber a live position back to 'flat'")
for f in ("loss_streak", "ctrader_access_token", "risk", "active"):
    check(f"{f} still protected", f in user_store.CRITICAL_FIELDS)

# ── 7. Crosses without a USD leg ──────────────────────────────────────────
print("\n7. Instruments we cannot size correctly are refused")
for sym in ("GBP_JPY", "EUR_GBP", "AUD_CHF", "EURJPY"):
    check(f"{sym} refused", forex.is_tradeable(sym) is False,
          "no quote_usd_rate is ever passed, so the margin cap is 100x wrong")
for sym in ("EUR_USD", "USD_JPY", "USD_CHF", "XAUUSD", "XAGUSD"):
    check(f"{sym} still accepted", forex.is_tradeable(sym) is True)
check("no refused cross is offered on a quick-pick button",
      "GBP_JPY" not in TG.split("_QUICK_SYMS_FX")[1].split("]")[0],
      "offering one only produces a refusal a tap later")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — audit regressions covered.")
