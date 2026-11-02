"""The strategies this bot already trades, poured into the standard interface.

REFACTOR ONLY — no new trading logic lives here. Every verdict is produced by
the exact function the live loop calls today:

    signal()/exit()  -> apex.ai.signal_for_mode(mode, ind, strat, position)
    analyze()        -> apex.strategies.analyze / detect_regime / htf_trend
    advise_risk()    -> apex.strategies.druckenmiller_multiplier

so a module cannot decide anything different from the running bot. That
equivalence is asserted directly in tests/test_strategy_equivalence.py.

Two existing files are being adapted, because the bot's "strategy" is split
across both today:

  * apex/ai.py  holds the ten engines that emit BUY/SELL/HOLD/CLOSE
    (STRATEGY_MODES, selected by cfg.STRATEGY) — that is signal() and exit().
  * apex/strategies.py holds the market read those engines consume (turtle,
    Livermore, Soros, mean reversion, regime, HTF trend) and the sizing
    multiplier — that is analyze() and advise_risk().

What deliberately did NOT move here: the circuit breakers
(strategies.should_stop, record_trade, the daily/drawdown counters). Those are
Risk Engine state, not a strategy's opinion, and a strategy module must not be
able to reach them. advise_risk() returns a multiplier and nothing else; the
loss-streak and volatile-regime cuts the loop applies on top stay in the loop.
"""
from apex import ai, strategies
from apex.strategy_api import Strategy, register


class ModeStrategy(Strategy):
    """Adapter over one apex.ai STRATEGY_MODES engine."""

    mode = ""

    def analyze(self, market):
        """The read, not the decision. Identical to what the loop computes."""
        return self.stamp({
            "indicators": market.indicators,
            "strat": market.strat,
            "regime": strategies.detect_regime(market.candles),
            "htfTrend": strategies.htf_trend(market.candles),
        })

    def signal(self, market):
        """Byte-for-byte the current call, plus the §14 provenance stamp."""
        verdict = ai.signal_for_mode(self.mode, market.indicators,
                                     market.strat, market.open_position)
        return self.stamp(verdict)

    def advise_risk(self, market):
        """Advisory sizing multiplier — the Risk Engine decides what to do
        with it. Uses the post-AI confidence when the caller has one (the loop
        does), otherwise this strategy's own."""
        conf, crit = market.confidence, market.criteria_score
        if conf is None or crit is None:
            own = ai.signal_for_mode(self.mode, market.indicators,
                                     market.strat, market.open_position)
            if conf is None:
                conf = own.get("confidence", 0)
            if crit is None:
                crit = own.get("criteriaScore", 0)
        strat = market.strat or {}
        mult = strategies.druckenmiller_multiplier(
            conf, crit, strat.get("livermore"), strat.get("turtle"))
        return {"multiplier": mult, "basis": "druckenmiller_multiplier",
                "confidence": conf, "criteriaScore": crit}

    def exit(self, market):
        """The same engine, read for the position side of its verdict.

        The engines already answer both questions in one call — entry when
        flat, CLOSE/HOLD when in a trade. Splitting them per the blueprint is
        a view over that one call, not a second opinion.
        """
        pos = market.open_position
        if not pos:
            return self.stamp({"exit": False, "action": "HOLD",
                               "reason": "no open position"})
        verdict = ai.signal_for_mode(self.mode, market.indicators,
                                     market.strat, pos)
        action = verdict.get("action", "HOLD")
        return self.stamp({"exit": action == "CLOSE", "action": action,
                           "confidence": verdict.get("confidence"),
                           "reason": verdict.get("reasoning", ""),
                           "verdict": verdict})


# ── The first modules. One per engine the bot already ships, each versioned
#    independently so bumping one strategy's logic doesn't restamp the rest.
#    1.0.0 = "wraps the behaviour live on the account today". ──

@register
class AutoStrategy(ModeStrategy):
    mode = "auto"
    strategy_id = "auto"
    strategy_version = "1.0.0"
    label = "Auto (regime-adaptive)"


@register
class MeanReversionStrategy(ModeStrategy):
    mode = "mean_reversion"
    strategy_id = "mean_reversion"
    strategy_version = "1.0.0"
    label = "Mean Reversion"


@register
class TrendStrategy(ModeStrategy):
    mode = "trend"
    strategy_id = "trend"
    strategy_version = "1.0.0"
    label = "Trend Following"


@register
class BreakoutStrategy(ModeStrategy):
    mode = "breakout"
    strategy_id = "breakout"
    strategy_version = "1.0.0"
    label = "Turtle Breakout"


@register
class FibonacciStrategy(ModeStrategy):
    mode = "fibonacci"
    strategy_id = "fibonacci"
    strategy_version = "1.0.0"
    label = "Fibonacci"


@register
class FvgStrategy(ModeStrategy):
    mode = "fvg"
    strategy_id = "fvg"
    strategy_version = "1.0.0"
    label = "Fair Value Gap (FVG)"


@register
class IfvgStrategy(ModeStrategy):
    mode = "ifvg"
    strategy_id = "ifvg"
    strategy_version = "1.0.0"
    label = "Inverse FVG"


@register
class SupplyDemandStrategy(ModeStrategy):
    mode = "supply_demand"
    strategy_id = "supply_demand"
    strategy_version = "1.0.0"
    label = "Supply & Demand"


@register
class LiquiditySweepStrategy(ModeStrategy):
    mode = "liquidity_sweep"
    strategy_id = "liquidity_sweep"
    strategy_version = "1.0.0"
    label = "Liquidity Sweep"


@register
class EvcStrategy(ModeStrategy):
    mode = "evc"
    strategy_id = "evc"
    strategy_version = "1.0.0"
    label = "EVC (Equilibrium Volume)"
