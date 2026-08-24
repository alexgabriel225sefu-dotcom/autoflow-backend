"""Strategy Builder — a guided setup assistant.

The client composes a strategy from realistic building blocks (style → entry
setup → confirmation → risk → exit). Every choice maps to a REAL engine
parameter that changes how the bot trades — nothing here is decorative.
One-tap presets bundle coherent settings for the two markets.

The entry-setup step mirrors the full onboarding method list (ai.STRATEGY_MODES)
exactly — generated from that single source of truth so every method (Auto,
Mean Reversion, Fibonacci, FVG, iFVG, Supply & Demand, Liquidity Sweep, EVC...)
is always selectable here too, never a stale subset.

This is a *setup assistant*, not signal advice: the bot executes exactly what
the user selected, and the user owns the outcome.

Forex only: pip-based stops, session filters and a news guard.
"""
from apex import config as cfg
from apex import ai


# ─── Presets ───────────────────────────────────────────────
# Each preset is a full patch of user_store fields. Values are deliberately
# conservative-to-balanced; the client can fine-tune any of them afterwards.
def presets():
    """The preset strategy profiles a client can pick from."""
    return {
        "forex_scalp": {
            "label": "⚡ Forex-Scalping",
            "desc": "1m, tight pip stops, London/NY sessions, news guard",
            "patch": {
                "style": "scalping", "timeframe": "1m",
                "risk": 0.005, "min_confidence": 55, "atr_stops": False,
                "sl_pips": 15, "tp_pips": 30,
                "exit_mode": "fixed", "trailing": False, "breakeven_r": 0,
                "news_filter": True, "session_filter": ["London", "New York"],
                "max_trades_day": 15, "max_dd_pct": 15, "max_daily_loss_pct": 3,
            },
        },
        "forex_swing": {
            "label": "📈 Forex-Swing",
            "desc": "1h, wider stops, all sessions, trailing + break-even",
            "patch": {
                "style": "swing", "timeframe": "1h",
                "risk": 0.005, "min_confidence": 60, "atr_stops": True,
                "sl_pips": 25, "tp_pips": 60,
                "exit_mode": "trail", "trailing": True, "breakeven_r": 1.0,
                "news_filter": True, "session_filter": [],
                "max_trades_day": 4, "max_dd_pct": 20, "max_daily_loss_pct": 4,
            },
        },
    }


# ─── Custom wizard steps ───────────────────────────────────
# Ordered list of (key, prompt, options). Each option carries a patch applied to
# the in-progress draft.
def _style_step():
    return {
        "key": "style",
        "title": "1️⃣ Trading style",
        "sub": "Sets the timeframe and stop scale — pip stops scale with the style.",
        "options": [
            {"label": "⚡ Scalping (1m)", "patch": {
                "style": "scalping", "timeframe": "1m",
                "sl_pips": 15, "tp_pips": 30, "atr_stops": False}},
            {"label": "📅 Day trading (5m)", "patch": {
                "style": "day", "timeframe": "5m",
                "sl_pips": 20, "tp_pips": 40, "atr_stops": True}},
            {"label": "📈 Swing (1h)", "patch": {
                "style": "swing", "timeframe": "1h", "atr_stops": True,
                "sl_pips": 25, "tp_pips": 60}},
            {"label": "🎯 Position (4h)", "patch": {
                "style": "position", "timeframe": "4h", "atr_stops": True,
                "sl_pips": 50, "tp_pips": 150}},
        ],
    }


_STRAT_EMOJI = {
    "auto": "🤖", "mean_reversion": "⭐", "trend": "📈", "breakout": "🚀",
    "fibonacci": "🌀", "fvg": "🕳️", "ifvg": "🔄", "supply_demand": "🏛️",
    "liquidity_sweep": "🎯", "evc": "⚖️",
}


def _setup_step():
    """Entry-setup step — built straight from ai.STRATEGY_MODES so it always
    lists every real engine, not a hand-copied subset that goes stale."""
    return {
        "key": "strategy",
        "title": "2️⃣ Entry setup",
        "sub": "The engine that decides WHEN to enter.",
        "options": [
            {"label": f"{_STRAT_EMOJI.get(key, '▫️')} {m['label']}", "patch": {"strategy": key}}
            for key, m in ai.STRATEGY_MODES.items()
        ],
    }


_CONFIRM_STEP = {
    "key": "confirm",
    "title": "3️⃣ Confirmation",
    "sub": "How strict the filters are before a trade fires.",
    "options": [
        {"label": "🎯 Price action only", "patch": {"confirm": "price", "min_confidence": 50, "htf": False}},
        {"label": "📊 Indicators (standard)", "patch": {"confirm": "indicator", "min_confidence": 55, "htf": False}},
        {"label": "📈 Volume + volatility", "patch": {"confirm": "volume", "min_confidence": 60, "htf": False}},
        {"label": "🕐 Multi-timeframe", "patch": {"confirm": "mtf", "min_confidence": 62, "htf": True}},
    ],
}

_RISK_STEP = {
    "key": "risk",
    "title": "4️⃣ Risk per trade",
    "sub": "How much of the balance is risked on each trade — and the safety limits.",
    "options": [
        {"label": "🟢 Low (0.5%)", "patch": {"risk": 0.005, "max_daily_loss_pct": 3, "max_dd_pct": 15, "max_trades_day": 6}},
        {"label": "🟡 Medium (1%)", "patch": {"risk": 0.01, "max_daily_loss_pct": 4, "max_dd_pct": 20, "max_trades_day": 10}},
        {"label": "🔴 High (2%)", "patch": {"risk": 0.02, "max_daily_loss_pct": 6, "max_dd_pct": 25, "max_trades_day": 15}},
    ],
}

_EXIT_STEP = {
    "key": "exit_mode",
    "title": "5️⃣ Exit management",
    "sub": "How the trade is closed once it's open.",
    "options": [
        {"label": "🎯 Fixed TP/SL", "patch": {"exit_mode": "fixed", "trailing": False, "breakeven_r": 0}},
        {"label": "📈 Trailing stop", "patch": {"exit_mode": "trail", "trailing": True, "breakeven_r": 0}},
        {"label": "🛡️ Break-even + trail", "patch": {"exit_mode": "be_trail", "trailing": True, "breakeven_r": 1.0}},
    ],
}

_SESSION_STEP = {  # forex only
    "key": "session_filter",
    "title": "6️⃣ Trading sessions",
    "sub": "When the bot is allowed to trade (forex reacts to session opens).",
    "options": [
        {"label": "🌍 All sessions", "patch": {"session_filter": []}},
        {"label": "🇬🇧🇺🇸 London + New York", "patch": {"session_filter": ["London", "New York"]}},
        {"label": "🌏 Asia only", "patch": {"session_filter": ["Asia"]}},
    ],
}


def steps():
    """Ordered wizard steps."""
    return [_style_step(), _setup_step(), _CONFIRM_STEP, _RISK_STEP,
            _EXIT_STEP, _SESSION_STEP]


# ─── Summary ───────────────────────────────────────────────
_EXIT_LABEL = {"fixed": "Fixed TP/SL", "trail": "Trailing stop",
               "be_trail": "Break-even + trail"}
_CONFIRM_LABEL = {"price": "Price action", "indicator": "Indicators",
                  "volume": "Volume + volatility", "mtf": "Multi-timeframe"}


def _strategy_label(key):
    """Display name for any strategy, V1 or later.

    STRATEGY_MODES only describes the ten methods with an engine in ai.py, and
    `.get(key, STRATEGY_MODES['auto'])` therefore reported *Auto* for every
    method added after V1 — so a client who had just picked Momentum read back
    a summary saying the bot would choose for them. Same class of bug as the
    one /status had. Ask the registry, which knows all of them.
    """
    k = (key or "auto").lower()
    m = ai.STRATEGY_MODES.get(k)
    if m:
        return m["label"]
    try:
        from apex import strategy_api
        cls = strategy_api._REGISTRY.get(k)
        if cls:
            return getattr(cls, "label", k)
    except Exception:
        pass
    return k


def summary(d):
    """Human-readable recap of a composed strategy (dict of fields)."""
    risk_pct = float(d.get("risk", 0.01)) * 100
    sess = d.get("session_filter") or []
    sess_txt = "All sessions" if not sess else " + ".join(sess)
    lines = [
        "📋 <b>Your strategy — Forex</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"• Style: <b>{(d.get('style') or 'swing').title()}</b> · {d.get('timeframe', '5m')}",
        f"• Entry setup: <b>{_strategy_label(d.get('strategy'))}</b>",
        f"• Confirmation: <b>{_CONFIRM_LABEL.get(d.get('confirm', 'indicator'), 'Indicators')}</b>",
        f"• Risk: <b>{risk_pct:g}%</b> per trade",
        f"• Exit: <b>{_EXIT_LABEL.get(d.get('exit_mode', 'fixed'), 'Fixed TP/SL')}</b>",
    ]
    lines.append(f"• Sessions: <b>{sess_txt}</b>")
    lines.append(f"• News guard: <b>{'ON' if d.get('news_filter', True) else 'OFF'}</b>")
    lines += [
        f"• Max trades/day: <b>{d.get('max_trades_day', 10)}</b>",
        f"• Daily loss stop: <b>{d.get('max_daily_loss_pct', 4):g}%</b> · Max drawdown: <b>{d.get('max_dd_pct', 20):g}%</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "<i>The bot executes exactly this — you stay in control and own the results.</i>",
    ]
    return "\n".join(lines)
