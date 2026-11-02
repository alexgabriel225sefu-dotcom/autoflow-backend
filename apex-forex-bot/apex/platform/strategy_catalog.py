"""The platform's safe view of the engine's strategy registry.

WHAT WAS WRONG

A client arriving from the Telegram bot could choose between fifteen
strategies. The platform exposed exactly one — `platform_rule`, the custom
rule builder — because `engine_config.translate` writes
`applied["strategy"] = RULE_STRATEGY_ID` for every rule there is. So the owner's
own description of the product ("you connect your account and you choose
yourself how you want to trade") was true of the bot and false of the platform:
the only way to trade here was to write a rule from scratch, and fourteen
strategies the engine already ships were unreachable.

THE RULE THIS FILE FOLLOWS

**Never offer a strategy that is not registered, and never claim behaviour the
class does not have.**

Both halves are enforced rather than intended:

  * `describe()` intersects the table below with the LIVE registry. A
    description for something nothing registers is not served — the client is
    never shown a strategy the loop would then refuse with
    "no strategy module is loaded for ...".
  * every registered id must appear in exactly one of `_PRESETS` (offered) or
    `_WITHHELD` (registered, deliberately not offered, with the reason). A
    strategy added to the engine and to neither table is reported by `drift()`
    and by this module's API payload, and `tests/test_strategy_catalog.py`
    fails on it. The catalogue cannot silently fall behind the engine, and it
    cannot silently get ahead of it either.

WHERE THE DESCRIPTIONS COME FROM

Each one was written from the code that produces the verdict, and carries a
`source` pointer at it. For the ten adapters in `apex/strategy_modules.py`
that is the `apex/ai.py` engine the adapter calls — the class body there is
four lines of id and label, so describing the CLASS would describe nothing.
For `apex/strategy_extra.py` it is the class itself.

The `label` is read from the registry, never from this table. A label that
could disagree with the class is a label that eventually will.

WHAT THE WORDING IS FOR

A client has to be able to read what a strategy does BEFORE choosing it, and
the useful half of that is not what it trades — it is what it refuses. Five of
these (`fvg`, `ifvg`, `supply_demand`, `liquidity_sweep`, `evc`) forward a
detector's side with a fixed confidence and no trend, session or volatility
filter at all, and `refuses` says exactly that rather than leaving a blank
where the other ten have a sentence. The blurbs in `ai.STRATEGY_MODES` were
NOT reused: they call one strategy "Recommended" and another
"high-probability", and neither claim is in the code.
"""

from apex import strategy_api as _api
from apex.platform import engine_config as _ecfg

# What a preset selection is called inside a RuleDoc. Declared here because
# this module owns the concept; `ruledoc` validates the field and must not
# import this one (see `ruledoc.validate`'s `known_strategy_ids`).
PRESET_FIELD = "strategy"


# ── the catalogue ───────────────────────────────────────────────────────────
# id -> {family, what, decides, refuses, source}
#
#   what      one sentence: what this strategy trades
#   decides   how the verdict is actually reached, with the numbers that gate
#             it, and how it leaves an open position
#   refuses   the conditions it declines to trade in. The most important field
#             on the screen: it is the difference between a strategy and a
#             signal generator.
#   source    the code the description was read from, so a reviewer can check
#             the sentence against the function rather than trusting it
_PRESETS = {
    "auto": {
        "family": "adaptive",
        "what": "Reads the market regime every cycle and runs whichever of "
                "three strategies fits it.",
        "decides": "The loop calls strategies.detect_regime on the current "
                   "candles: a trending read runs Trend Following, a ranging "
                   "read runs Mean Reversion, a volatile read runs Turtle "
                   "Breakout. Whichever is picked then decides exactly as it "
                   "would on its own, and the dashboard says which one ran.",
        "refuses": "New entries while the regime reads quiet. Asked outside "
                   "the loop (a backtest), it follows a confirmed Livermore "
                   "trend and otherwise falls back to Mean Reversion.",
        # Three, because this one's behaviour is split: the loop holds the
        # regime switch, strategies.py makes the regime read, and ai.py holds
        # the fallback for callers that are not the loop.
        "source": "apex/user_loop.py; apex/strategies.py:detect_regime; "
                  "apex/ai.py:auto_engine",
    },
    "mean_reversion": {
        "family": "reversion",
        "what": "Fades a stretched price back towards the Bollinger mean.",
        "decides": "Scores Bollinger position, RSI, Stochastic RSI and "
                   "divergence into one number; +3 or more buys, -3 or less "
                   "sells, and confidence rises with the size of the score. "
                   "An open long is closed once price is back at 65% of the "
                   "band, a short at 35%; otherwise the stop and the target "
                   "manage it.",
        "refuses": "Bollinger bandwidth under 0.05 — there is no range to "
                   "fade. And a counter-trend fade whenever EMA50 and EMA200 "
                   "are more than 0.5% apart, unless the score is extreme AND "
                   "points the same way as that trend.",
        "source": "apex/ai.py:mean_reversion_signal",
    },
    "trend": {
        "family": "trend",
        "what": "Buys pullbacks inside a confirmed uptrend and sells rallies "
                "inside a confirmed downtrend. Never fades.",
        "decides": "Needs EMA50 above EMA200 with price above EMA200 (mirrored "
                   "for a sell), then adds Livermore structure and Soros "
                   "momentum to a score — and still only enters on a pullback "
                   "to EMA20 with RSI between 35 and 65. A score of 3 or more "
                   "AND that pullback. It closes early only when market "
                   "structure flips against the position at strength 0.8 or "
                   "more; otherwise the stop and the target manage it.",
        "refuses": "Entries with no confirmed trend, and entries with no "
                   "pullback — it will not chase a move that has already "
                   "left.",
        "source": "apex/ai.py:trend_signal",
    },
    "breakout": {
        "family": "breakout",
        "what": "Enters a fresh break of the 20-bar high or low.",
        "decides": "Takes the side from the Turtle channel read, then adds a "
                   "point each for agreeing momentum, an agreeing MACD "
                   "histogram and Bollinger bandwidth at 0.12 or more; a score "
                   "of 3 or more enters. An opposite channel break closes the "
                   "position — the classic channel exit.",
        "refuses": "A break with no confirmation behind it, and a break that "
                   "has already run (RSI 82 or more on a buy, 18 or less on a "
                   "sell).",
        "source": "apex/ai.py:breakout_signal",
    },
    "fibonacci": {
        "family": "structure",
        "what": "Trades a rejection at a Fibonacci retracement or extension "
                "level of the current swing.",
        "decides": "The level reaction comes from the Fibonacci read in "
                   "apex/indicators.py. RSI, EMA20-against-EMA50 alignment and "
                   "the MACD histogram then add to or subtract from the setup, "
                   "and the confidence moves with that score instead of being "
                   "a constant. While a position is open it holds and lets the "
                   "stop and the target manage it.",
        "refuses": "A level reaction whose score falls to -1 or below — for "
                   "instance buying a bounce into an already overbought tape.",
        "source": "apex/ai.py:fibonacci_signal",
    },
    "fvg": {
        "family": "structure",
        "what": "Enters when price trades back into an unfilled fair value "
                "gap.",
        "decides": "Takes the side straight from the fair-value-gap read in "
                   "apex/indicators.py and reports a fixed confidence of 70. "
                   "It notes whether that side agrees with market structure "
                   "but does not require it. While a position is open it "
                   "holds, so the stop and the target are the exit.",
        "refuses": "Only the absence of a gap. There is no trend, session or "
                   "volatility filter on this one, so it will take a gap "
                   "entry in any market the engine hands it.",
        "source": "apex/ai.py:fvg_signal",
    },
    "ifvg": {
        "family": "structure",
        "what": "Trades a rejection at a fair value gap that price has "
                "already invalidated.",
        "decides": "Takes the side straight from the inverse-FVG read in "
                   "apex/indicators.py at a fixed confidence of 68. While a "
                   "position is open it holds, so the stop and the target are "
                   "the exit.",
        "refuses": "Only the absence of a rejection. No trend, session or "
                   "volatility filter.",
        "source": "apex/ai.py:ifvg_signal",
    },
    "supply_demand": {
        "family": "structure",
        "what": "Enters when price returns to a supply or a demand zone.",
        "decides": "Takes the side straight from the supply/demand read in "
                   "apex/indicators.py at a fixed confidence of 72. RSI is "
                   "reported beside the verdict but does not gate it. While a "
                   "position is open it holds, so the stop and the target are "
                   "the exit.",
        "refuses": "Only the absence of a zone. No trend, session or "
                   "volatility filter.",
        "source": "apex/ai.py:supply_demand_signal",
    },
    "liquidity_sweep": {
        "family": "structure",
        "what": "Enters the reversal after a false break past a swing high "
                "or low.",
        "decides": "Takes the side straight from the liquidity-sweep read in "
                   "apex/indicators.py at a fixed confidence of 74, and names "
                   "the level that was swept. While a position is open it "
                   "holds, so the stop and the target are the exit.",
        "refuses": "Only the absence of a sweep. No trend, session or "
                   "volatility filter.",
        "source": "apex/ai.py:liquidity_sweep_signal",
    },
    "evc": {
        "family": "structure",
        "what": "Enters off a balanced-volume (equilibrium) candle at a key "
                "level.",
        "decides": "Takes the side straight from the equilibrium-volume read "
                   "in apex/indicators.py at a fixed confidence of 68. An "
                   "equilibrium candle with no direction behind it holds. "
                   "While a position is open it holds, so the stop and the "
                   "target are the exit.",
        "refuses": "Only the absence of an equilibrium candle with a "
                   "direction. No trend, session or volatility filter.",
        "source": "apex/ai.py:evc_signal",
    },
    "momentum": {
        "family": "momentum",
        "what": "Rides momentum that is already established, and will not buy "
                "a move that has already run.",
        "decides": "ADX must be 20 or more. Then RSI at 52 or above with a "
                   "positive MACD histogram and price above EMA20 buys; "
                   "mirrored for a sell. Confidence rises with ADX up to 88, "
                   "and it advises 1.1x size when ADX is 30 or more — advice "
                   "the risk engine clamps into its own band. It closes when "
                   "the MACD histogram flips against the position.",
        "refuses": "ADX below 20, because a momentum reading in chop is noise. "
                   "And RSI above 75 on a buy or below 25 on a sell: the move "
                   "is late and it is not chasing the top.",
        "source": "apex/strategy_extra.py:MomentumStrategy",
    },
    "session_breakout": {
        "family": "breakout",
        "what": "Breaks of a quiet 16-bar range, taken only while a session "
                "is live.",
        "decides": "Measures the high and low of the 16 closed bars before the "
                   "forming one, and enters when price clears an edge by 0.15 "
                   "ATR. Confidence rises with the volume ratio up to 85. It "
                   "closes when the MACD histogram flips against the position.",
        "refuses": "A closed session — a break with no liquidity behind it is "
                   "the false one. A 'range' more than 6 ATR wide, which is a "
                   "trend rather than a range. And price still inside the "
                   "range.",
        "source": "apex/strategy_extra.py:SessionBreakoutStrategy",
    },
    "opening_range": {
        "family": "breakout",
        "what": "The same range break on a tighter, faster window.",
        "decides": "Identical logic to Session Breakout with a 6-bar range and "
                   "a 0.10 ATR buffer, so it reacts sooner and to smaller "
                   "ranges — and to more false ones.",
        "refuses": "The same three: a closed session, a range wider than 6 "
                   "ATR, and price still inside the range.",
        "source": "apex/strategy_extra.py:OpeningRangeStrategy",
    },
    "zscore": {
        "family": "statistical",
        "what": "Fades a deviation that is extreme in standard deviations "
                "rather than against a fixed band.",
        "decides": "Computes the z-score of price against the mean of the last "
                   "40 closes; -2σ or lower buys, +2σ or higher sells, and "
                   "confidence rises with the size of the deviation up to 85. "
                   "It closes when price is back at the mean — the thesis is "
                   "complete — or when the deviation widens past 4σ, because "
                   "the mean is not holding.",
        "refuses": "ADX above 25. It will not fade a trend; that is how mean "
                   "reversion produced the losing week this engine already "
                   "lived through. And fewer than 10 usable closes, where "
                   "there is no z-score to compute.",
        "source": "apex/strategy_extra.py:ZScoreStrategy",
    },
    "vol_regime": {
        "family": "statistical",
        "what": "Waits for a volatility squeeze to break, then trades the "
                "direction it broke in.",
        "decides": "Bollinger bandwidth must be above 0.12 and at least 1.4x "
                   "the bandwidth of the prior window. Then price at 70% or "
                   "more of the band with a positive MACD histogram buys, 30% "
                   "or less with a negative one sells. It closes when the MACD "
                   "histogram flips against the position.",
        "refuses": "A bandwidth still inside the squeeze, an expansion too "
                   "small against the prior window, and an expansion with no "
                   "direction yet — it does not guess which way a squeeze "
                   "will break.",
        "source": "apex/strategy_extra.py:VolRegimeStrategy",
    },
}

# Registered, and deliberately NOT offered. Each reason is the one a client
# would be given if they asked, because they will: somebody who used the bot
# knows these ids exist.
#
# This is not a blocklist for its own sake. It is the other half of the drift
# guard: a registered strategy has to be in one table or the other, so the
# answer to "why can I not pick grid" is written down rather than being an
# absence nobody can account for.
_WITHHELD = {
    _ecfg.RULE_STRATEGY_ID: {
        "reason": "This is the rule builder, not a preset. It decides nothing "
                  "itself — it asks the account's running rule on every bar. "
                  "Choosing it is what building a rule already does.",
        "kind": "rule_builder",
    },
    "grid": {
        "reason": "Registered but not offered here. It adds exposure to a "
                  "position that is already losing. apex/strategy_specialized"
                  ".py caps it hard — one position at a time, 0.5x advisory "
                  "size, and a full halt after 3 consecutive losses — and "
                  "those caps are the only reason shipping it is defensible. "
                  "The platform has no screen that states them, and offering "
                  "the strategy without them stated is the dishonest half of "
                  "that trade.",
        "kind": "high_risk",
    },
    "martingale": {
        "reason": "Registered but not offered here, for the same reason as "
                  "grid: it increases size after a loss. The advisory band "
                  "tops out at 1.2x so it is a lean rather than a doubling, "
                  "and it stops entirely after 3 losses — but a client "
                  "picking the word 'martingale' off a list would be choosing "
                  "the thing the word usually means, which is not what this "
                  "is.",
        "kind": "high_risk",
    },
}


# ── reading the registry ────────────────────────────────────────────────────
def _registry():
    """{strategy_id: {label, version}} for everything actually registered.

    `load_builtins()` rather than trusting the registry to be populated: in
    the engine process `user_loop` has already called it at import, and in the
    API process nothing has. An empty registry would make this module answer
    "no strategies exist", which is a claim, and a false one.

    A failure to import the strategy modules answers with an EMPTY registry
    rather than raising. The caller then offers nothing, which is the
    fail-closed direction: a client sees "no presets available" instead of a
    list of strategies the loop could not run.
    """
    try:
        _api.load_builtins()
        return {d["strategy_id"]: {"label": d.get("label") or d["strategy_id"],
                                   "version": d.get("strategy_version") or ""}
                for d in _api.describe()}
    except Exception as e:                                   # noqa: BLE001
        print(f"[STRATEGY_CATALOG] the strategy registry could not be read "
              f"({type(e).__name__}: {e}) — offering nothing rather than a "
              f"list the loop cannot run")
        return {}


def describe():
    """Every preset this platform may offer, as the picker renders it.

    Sorted by family then id so the list is stable between calls — a picker
    whose order changes on refresh is a picker a client cannot learn.

    A described strategy that is not in the registry is LEFT OUT. That is the
    whole point of intersecting rather than returning the table: the loop
    refuses an unregistered id with "no strategy module is loaded for ...", and
    a client should never be able to select their way into that message.
    """
    live = _registry()
    out = []
    for sid, entry in _PRESETS.items():
        reg = live.get(sid)
        if reg is None:
            continue
        out.append({
            "id": sid,
            # From the class, through the registry. Never from _PRESETS.
            "label": reg["label"],
            "version": reg["version"],
            "family": entry["family"],
            "what": entry["what"],
            "decides": entry["decides"],
            "refuses": entry["refuses"],
            "source": entry["source"],
        })
    return sorted(out, key=lambda d: (d["family"], d["id"]))


def withheld():
    """The registered strategies this platform does not offer, with reasons.

    Served to the client rather than kept private. Somebody who used the
    Telegram bot will look for grid and martingale, and "they are not on the
    list" is an answer that reads like an omission. The reason reads like a
    decision, which is what it is.
    """
    live = _registry()
    return [dict(info, id=sid, label=live[sid]["label"])
            for sid, info in sorted(_WITHHELD.items()) if sid in live]


def ids():
    """The preset ids a client may choose, as a tuple.

    This — not `_PRESETS`, and not the registry — is what a boundary check
    uses. A rule may name a strategy only if the platform both describes it
    and the engine registers it.
    """
    return tuple(d["id"] for d in describe())


def get(strategy_id):
    """One preset's catalogue entry, or None if it is not offered."""
    sid = str(strategy_id or "")
    for d in describe():
        if d["id"] == sid:
            return d
    return None


def is_preset(strategy_id):
    """True only for a strategy this platform offers as a preset.

    False for `platform_rule`, for grid and martingale, for an unregistered
    id, and for an id this release has no description of. Everything that is
    not a yes is a no — the caller is asking whether it may run this, and
    "probably" is not an answer to that.
    """
    return str(strategy_id or "") in ids()


def drift():
    """{"unclassified": [...], "stale": [...]} — the registry against this file.

    `unclassified`  registered, and in neither table. The engine grew a
                    strategy and this file did not notice. It is NOT offered
                    (describe() intersects), so the failure mode is a missing
                    option rather than a wrong one — but a missing option
                    nobody knows about is how fourteen strategies went missing
                    in the first place.
    `stale`         described or withheld here, and registered nowhere. A
                    rename or a deletion in the engine.

    Both are reported to the caller as well as to the test, because a drift
    that only a test can see is a drift that is invisible in production.
    """
    live = set(_registry())
    known = set(_PRESETS) | set(_WITHHELD)
    return {"unclassified": sorted(live - known),
            "stale": sorted(known - live)}


def catalogue():
    """The whole payload the API serves. One function, so the route is a line.

    `unclassified` is included only when it is non-empty: a key that is always
    there and almost always empty is a key the UI learns to ignore.
    """
    out = {"strategies": describe(), "withheld": withheld(),
           "ruleBuilderId": _ecfg.RULE_STRATEGY_ID,
           "presetField": PRESET_FIELD}
    unclassified = drift()["unclassified"]
    if unclassified:
        out["unclassified"] = unclassified
    return out


# ── wrapping a preset in a RuleDoc ──────────────────────────────────────────
class NotAPreset(ValueError):
    """The named strategy is not one this platform offers. Carries the id."""

    def __init__(self, strategy_id):
        self.strategy_id = str(strategy_id or "")
        super().__init__(
            f"{self.strategy_id!r} is not a strategy this platform offers — "
            f"it is either unregistered, withheld, or has no description in "
            f"this release")


def apply_to(doc, strategy_id):
    """`doc` as a preset-backed RuleDoc. Returns a NEW document.

    WHY A PRESET IS A RULEDOC AND NOT A SECOND KIND OF THING

    Everything downstream of "what is running" is built on a RuleDoc: the
    frozen, versioned copy the journal points at, `engine_config.translate`,
    the risk gates that read the rule's own terms, the Stop that restores the
    account's settings from `engineSnapshot`. A preset has no conditions, but
    it has every other term a rule has — instrument, timeframe, risk percent,
    stop, target, trailing, break-even, daily trade cap, spread cap. Those are
    the terms the gates act on, and they are exactly as real for a preset as
    for a hand-built rule.

    So the preset goes in the document as one more term, and nothing
    downstream learns a second shape.

    THE CONDITIONS ARE EMPTIED, AND THAT IS NOT TIDINESS

    A preset decides its own entries and exits. A condition left on the
    document would be a term the client can read on their rule page and the
    engine will never consult — the defect this codebase was rewritten to
    stop. `ruledoc.validate` refuses a preset document that carries any, so
    this is the only way to build one that will activate.

    Never mutates `doc`: the caller may be holding the client's draft.
    """
    sid = str(strategy_id or "")
    if not is_preset(sid):
        raise NotAPreset(sid)
    doc = dict(doc or {})
    entry = dict(doc.get("entry") or {})
    exit_ = dict(doc.get("exit") or {})
    entry["conditions"] = []
    exit_["conditions"] = []
    doc[PRESET_FIELD] = sid
    doc["entry"] = entry
    doc["exit"] = exit_
    return doc


def preset_of(doc):
    """The preset a document names, or "" for a rule built from conditions.

    Reads the field without judging it. Whether the id is one the platform
    offers is `is_preset`'s question and is asked at the boundaries that care
    — activation, and the engine hand-off — so that a document stored by an
    older release still reports what it says rather than being silently
    reclassified as a custom rule.
    """
    value = (doc or {}).get(PRESET_FIELD)
    return str(value) if isinstance(value, str) else ""
