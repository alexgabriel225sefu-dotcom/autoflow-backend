"""Which market a strategy is allowed to take an ENTRY in.

THE DEFECT THIS EXISTS FOR

The loop picks a strategy from the regime only in AUTO:

    if active_mode == "auto":
        picked = {"trending": "trend", "ranging": "mean_reversion",
                  "volatile": "breakout"}.get(regime["regime"])

The live account runs `strategy: fibonacci` — pinned, not auto — so that
mapping never runs and a retracement engine trades in every regime, including
the one it is designed to lose in. Measured on the account's own labelled
journal, 42 labelled trades:

    fibonacci in ranging    n=14   net +132.52   win 71.4%
    fibonacci in trending   n= 7   net -180.47   win 28.6%

The last five trending trades were all SELL and all losses (XAUUSD -28.32,
EURUSD -50.60, EURUSD -41.70, GBPUSD -40.50, NZDUSD -41.25): 59% of the
account's recent losses, from a strategy selling into strength because a
retracement is what it looks for. The theory and the tape agree, which is the
only reason a 7-trade sample is worth acting on at all.

WHY AN ALLOWLIST, NOT A LIST OF BAD PAIRINGS

`forex.is_tradeable` is the precedent: it names the instruments the forex bot
may trade and refuses everything else, so an instrument class nobody thought
about is rejected rather than silently admitted. The same property is what
matters here. `strategies.detect_regime` has four states today; the next one
added would be traded by fibonacci from the moment it ships if this were a
denylist of {fibonacci: trending}, with nobody having measured it. Named
strategy + unnamed regime = refused.

The other half of that rule is the DEFAULT, which is deliberately explicit
rather than absent: a strategy this table does not name is not regime-
sensitive and trades wherever it likes. `trend`, `breakout` and the ICT-family
engines are unmeasured, and refusing an entry on no evidence costs real money
in the same direction as taking a bad one.

WHY `volatile` AND `quiet` STAY ON FIBONACCI'S LIST

Only trending has evidence against it. Removing the two regimes nobody
measured would be inventing a result, and this gate spends real trades to buy
its refusals — the same reason `regime.Reading.fits()` returns None rather
than False when it does not know.

WHY `unknown` IS NOT A REFUSAL

`detect_regime` answers "unknown" below 130 candles. That is a statement that
the market could not be read, not a market state, and standing a live account
down while its history warms up is a bug wearing a gate's clothes.
`regime.Reading.fits()` already draws this exact line: "UNKNOWN fits nothing
and blocks nothing."

THE SETTING, AND WHY IT DEFAULTS TO ENFORCE

REGIME_GATE=off|shadow|enforce, default `enforce` — unlike EV_GATE_MODE,
SENTINEL_MODE and INSTITUTIONAL_GATE, which all ship in `shadow`. Those three
are MODELS: a calibration, an AI read, a macro feed. What they would refuse
cannot be known without watching them, so watching them first is the only
honest option. This is a fixed six-line table with no inputs beyond a strategy
name and a regime name — shadow mode would report back exactly what the table
already says, while the account kept paying -180 a week for the answer.

Seven trades is still seven trades, so the retreat is one environment variable
and no deploy: REGIME_GATE=shadow to watch it, REGIME_GATE=off to remove it.
"""

# ── Modes ────────────────────────────────────────────────────────────────
OFF = "off"
SHADOW = "shadow"
ENFORCE = "enforce"
MODES = (OFF, SHADOW, ENFORCE)
DEFAULT_MODE = ENFORCE

# ── The allowlist ────────────────────────────────────────────────────────
# Strategy → the regimes it may take an ENTRY in. A strategy absent from this
# table is not regime-sensitive (see the module docstring); a regime absent
# from a named strategy's set is refused.
#
# Both entries here are mean-reversion shaped: they enter AGAINST the last
# move, betting it retraces. That is the trade a trend punishes and a range
# pays for, which is what the journal measured.
ENTRY_REGIMES = {
    "fibonacci":      frozenset({"ranging", "volatile", "quiet"}),
    "mean_reversion": frozenset({"ranging", "volatile", "quiet"}),
}

# The one answer `detect_regime` gives that is not a market state: it means
# "not enough candles yet". Never a refusal.
UNREADABLE = frozenset({"", "none", "unknown"})


def _norm(value):
    """Lowercased, stripped, and never raising — callers pass whatever the
    journal or the broker handed them."""
    try:
        return str(value or "").strip().lower()
    except Exception:
        return ""


def mode(value):
    """Coerce a REGIME_GATE value to a known mode.

    An unrecognised value becomes the shipped default rather than silently
    disabling the gate: `REGIME_GATE=enforc` is a typo, and reading it as
    "off" would turn a fat finger into an untracked change of behaviour on a
    live account.
    """
    m = _norm(value)
    return m if m in MODES else DEFAULT_MODE


def entry_allowed(strategy, regime):
    """(allowed, reason) for one strategy in one regime. Pure table lookup.

    `regime` is the name from `strategies.detect_regime` — "trending",
    "ranging", "volatile", "quiet", "unknown".
    """
    name = _norm(strategy)
    allowed = ENTRY_REGIMES.get(name)
    if allowed is None:
        return True, f"{name or 'strategy'} is not regime-sensitive"

    where = _norm(regime)
    if where in UNREADABLE:
        return True, f"{name}: regime not classified yet — not gated"

    if where in allowed:
        return True, f"{name} trades {where}"

    return False, (f"{name} does not trade a {where} market "
                   f"(only {', '.join(sorted(allowed))})")


def decide(strategy, regime, gate_mode=DEFAULT_MODE):
    """(refuse, reason) — the loop's single entry point.

    Never raises. A gate that crashes must not be able to do more damage than
    the defect it corrects, so anything unexpected in here reports the fault
    and ALLOWS the trade.
    """
    try:
        m = mode(gate_mode)
        allowed, reason = entry_allowed(strategy, regime)
        if allowed or m != ENFORCE:
            return False, reason
        return True, reason
    except Exception as e:  # noqa: BLE001 — fail OPEN, deliberately
        return False, f"regime gate unavailable ({str(e)[:80]}) — allowing"
