"""A retracement strategy must not take entries in a trending market.

The account runs `strategy: fibonacci` — pinned, not `auto` — so the
regime→strategy mapping in the loop never runs and fibonacci trades in EVERY
regime. Measured on the live account's labelled journal, 42 labelled trades:

    fibonacci in ranging    n=14   net +132.52   win 71.4%
    fibonacci in trending   n= 7   net -180.47   win 28.6%

The last five trending trades were all SELL and all losses — XAUUSD -28.32,
EURUSD -50.60, EURUSD -41.70, GBPUSD -40.50, NZDUSD -41.25 — 59% of the
account's recent losses. A retracement engine in a trend sells into strength,
which is what the numbers say it did.

WHAT THIS FILE PINS DOWN, AND WHY EACH PART MATTERS

  * The table is an ALLOWLIST, not a list of bad pairings. The check that
    proves it is `fibonacci` against a regime name the table has never heard
    of: a denylist admits it, an allowlist refuses it. That is the same shape
    as `forex.is_tradeable`, and it is what stops the next regime added to
    `strategies.detect_regime` from being traded by a strategy nobody measured
    it against.
  * `ranging` SURVIVES. Fibonacci is the account's best performer there
    (+132.52 over 14 trades) and a fix that threw that away would cost more
    than the bleeding it stopped.
  * The gate REFUSES ENTRIES ONLY. It cannot close a position, cannot place an
    order and cannot reach `gates.authorize_order`.
  * A BROKEN gate allows the trade. Seven trades is a small sample; a bug in
    the thing correcting it must not be able to stand a live account down.

Run: python tests/test_regime_gate.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
# The shipped default is what section 4 asserts, so an inherited REGIME_GATE
# from the surrounding shell would make this file pass or fail on the
# environment it happened to run in.
os.environ.pop("REGIME_GATE", None)

import tempfile  # noqa: E402

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-regime-gate-test-")
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import regime_gate as G  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


print("\n🔒 REGIME ENTRY GATE — a retracement engine does not fade a trend\n")

print("1. The measured combination is refused, the profitable one is kept")
check("fibonacci does NOT enter a trending market",
      G.entry_allowed("fibonacci", "trending")[0] is False,
      "-180.47 over 7 trades, 28.6% win rate")
check("fibonacci STILL enters a ranging market",
      G.entry_allowed("fibonacci", "ranging")[0] is True,
      "+132.52 over 14 trades, 71.4% win — the account's best combination")
check("mean_reversion does NOT enter a trending market",
      G.entry_allowed("mean_reversion", "trending")[0] is False,
      "same shape as fibonacci: it fades what a trend rewards")
check("mean_reversion still enters a ranging market",
      G.entry_allowed("mean_reversion", "ranging")[0] is True)

print("\n2. It is an ALLOWLIST — the property a denylist cannot have")
# A denylist of {fibonacci: trending} admits every regime nobody has thought
# about yet. This is the check that tells the two apart.
check("a regime the table has never heard of is REFUSED, not admitted",
      G.entry_allowed("fibonacci", "reversal")[0] is False,
      "a denylist would have let this through")
check("and so is a second unheard-of one",
      G.entry_allowed("mean_reversion", "capitulation")[0] is False)
check("every regime a named strategy may trade is spelled out",
      "ranging" in G.ENTRY_REGIMES["fibonacci"]
      and "trending" not in G.ENTRY_REGIMES["fibonacci"])

print("\n3. Strategies nobody measured are handled by an explicit default")
# Not by having been forgotten: an unnamed strategy is not regime-sensitive
# and trades wherever it likes, which is exactly today's behaviour.
for strat in ("trend", "breakout", "fvg", "liquidity_sweep", "evc", "auto"):
    check(f"{strat} is unnamed → not regime-gated",
          G.entry_allowed(strat, "trending")[0] is True
          and G.entry_allowed(strat, "ranging")[0] is True)
check("a strategy that does not exist at all is not gated either",
      G.entry_allowed("no_such_strategy", "trending")[0] is True)

print("\n4. An unreadable market is not a refusal")
# detect_regime answers "unknown" while it is warming up (<130 candles). That
# is a statement that it could not read the market, not a market state — and
# apex.regime.Reading.fits() already takes exactly this line: "UNKNOWN fits
# nothing and blocks nothing".
check("unknown → allowed", G.entry_allowed("fibonacci", "unknown")[0] is True)
check("empty → allowed", G.entry_allowed("fibonacci", "")[0] is True)
check("None → allowed", G.entry_allowed("fibonacci", None)[0] is True)

print("\n5. AUTO mode is untouched — its own picks are all allowed")
# The loop maps trending→trend, ranging→mean_reversion, volatile→breakout.
# If this gate could refuse one of those, AUTO would gate itself.
for regime_name, picked in (("trending", "trend"), ("ranging", "mean_reversion"),
                            ("volatile", "breakout")):
    check(f"AUTO's pick for {regime_name} ({picked}) is not refused",
          G.entry_allowed(picked, regime_name)[0] is True)

print("\n6. The mode switch, and what each mode does")
check("enforce refuses", G.decide("fibonacci", "trending", "enforce")[0] is True)
check("shadow reports but never refuses",
      G.decide("fibonacci", "trending", "shadow")[0] is False)
check("off refuses nothing",
      G.decide("fibonacci", "trending", "off")[0] is False)
check("shadow still knows the answer it would have given",
      G.decide("fibonacci", "trending", "shadow")[1]
      == G.decide("fibonacci", "trending", "enforce")[1])
check("enforce lets the profitable combination through",
      G.decide("fibonacci", "ranging", "enforce")[0] is False)
check("a typo'd mode falls back to the shipped default, not to silence",
      G.mode("enforc") == G.DEFAULT_MODE and G.DEFAULT_MODE == G.ENFORCE)
check("case and whitespace do not change the mode",
      G.mode("  Enforce ") == G.ENFORCE and G.mode("OFF") == G.OFF)

print("\n7. The reason is legible to whoever reads the skip line")
_, why = G.entry_allowed("fibonacci", "trending")
check("it names the strategy", "fibonacci" in why, why)
check("it names the regime", "trending" in why, why)
check("it names what the strategy MAY trade", "ranging" in why, why)

print("\n8. A broken gate allows the trade")
# Seven trades is a small sample. The correction must not be able to do more
# damage than the defect: whatever goes wrong inside, the answer is "trade".
_orig = G.ENTRY_REGIMES


class _Exploding(dict):
    def get(self, *a, **k):
        raise RuntimeError("the table is broken")

    def __getitem__(self, k):
        raise RuntimeError("the table is broken")


try:
    G.ENTRY_REGIMES = _Exploding()
    refuse, reason = G.decide("fibonacci", "trending", "enforce")
    check("a table that raises does NOT refuse the entry", refuse is False,
          f"got refuse={refuse!r}")
    check("and the failure is reported, not swallowed silently",
          bool(reason and str(reason).strip()))
finally:
    G.ENTRY_REGIMES = _orig
check("the gate works again afterwards",
      G.decide("fibonacci", "trending", "enforce")[0] is True)

print("\n9. Junk input never raises — a gate is not a place to crash")
for strat, reg in ((None, None), (123, 456), (object(), object()),
                   ({"a": 1}, ["b"]), ("", ""), ("FIBONACCI", "TRENDING")):
    try:
        G.decide(strat, reg, "enforce")
        ok = True
    except Exception as e:  # noqa: BLE001 - that is the point
        ok = False
        print(f"      raised: {e}")
    check(f"decide({strat!r:.24}, {reg!r:.24}) survives", ok)
check("the symbol is normalised, not case-sensitive",
      G.entry_allowed("FIBONACCI", "TRENDING")[0] is False,
      "an upper-cased strategy name must not slip past the table")

print("\n10. The setting exists, defaults to enforce, and reaches the loop")
from apex import config as appcfg  # noqa: E402
from apex import user_loop  # noqa: E402

check("REGIME_GATE is a product setting", hasattr(appcfg, "REGIME_GATE"))
check("its shipped default is enforce", appcfg.REGIME_GATE == G.ENFORCE,
      f"got {getattr(appcfg, 'REGIME_GATE', None)!r}")
_, cfg = user_loop._make_broker({"ctrader_access_token": "x",
                                 "ctrader_account_id": "1"})
check("the per-user config the loop reads carries it",
      hasattr(cfg, "REGIME_GATE"),
      "missing → getattr(cfg, ...) default wins and REGIME_GATE=off does nothing")
check("and it tracks the product config rather than a literal",
      getattr(cfg, "REGIME_GATE", None) == appcfg.REGIME_GATE)

print("\n11. The loop consults it, in the ENTRY path, and does nothing else")
LSRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
check("the loop imports the gate", "regime_gate" in LSRC)
check("the loop asks it for a verdict", "regime_gate.decide(" in LSRC)
check("the verdict is surfaced to the operator", 'dash["regimeGate"]' in LSRC)

def _code_only(src):
    """`src` with COMMENT tokens blanked, spacing preserved.

    The checks below are about what the block DOES. Without this, the comment
    that explains "it never reaches authorize_order" fails the check that it
    never reaches authorize_order — the exact inversion tests/test_prose_
    assertions.py exists to catch, arrived at from the other direction.
    """
    import io as _io
    import tokenize

    lines = src.splitlines(keepends=True)
    try:
        spans = [(t.start, t.end) for t in
                 tokenize.generate_tokens(_io.StringIO(src).readline)
                 if t.type == tokenize.COMMENT]
    except (tokenize.TokenError, IndentationError):
        return src
    for (srow, scol), (erow, ecol) in spans:
        for row in range(srow, erow + 1):
            line = lines[row - 1]
            a = scol if row == srow else 0
            body = line.rstrip("\n")
            b = ecol if row == erow else len(body)
            nl = "\n" if line.endswith("\n") else ""
            lines[row - 1] = body[:a] + " " * (b - a) + body[b:] + nl
    return "".join(lines)


_lines = _code_only(LSRC).splitlines()
_at = next((i for i, ln in enumerate(_lines) if "regime_gate.decide(" in ln), -1)
check("the call site was found", _at >= 0)
BLOCK = "\n".join(_lines[max(0, _at - 14):_at + 20])

check("it sits in the entry path, guarded by entry_ok",
      "if entry_ok" in BLOCK)
check("its only effect is to refuse an entry",
      "entry_ok = False" in BLOCK)
check("it emits a skip reason like its neighbours", "_skip(" in BLOCK)
check("it never closes a position",
      "close_position" not in BLOCK and "_close_position" not in BLOCK
      and "CLOSE" not in BLOCK)
check("it never authorises an order", "authorize_order" not in BLOCK)
check("it never places an order",
      "place_order" not in BLOCK and "market_order" not in BLOCK)
check("it never calls the broker at all", "broker." not in BLOCK)
check("it is wrapped so a raise cannot stop the loop", "except" in BLOCK)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} FAILED: {', '.join(failures[:10])}")
    sys.exit(1)
print("✅ ALL REGIME-GATE CHECKS PASSED — a retracement engine stays out of a trend.")
