"""Backtest pe STRATEGIA REALĂ — rubrica AI calculată mecanic + filtrele +
exiturile live din apex/position.py (același cod care tranzacționează).

Rulare:
    python backtest.py                          # OANDA/TD cu cheile din .env
    BT_SYMBOL=GBP_USD python backtest.py
    BT_SYNTHETIC=true python backtest.py        # fără internet — validare motor

Ce simulează fidel: criteriile de intrare din promptul AI, MIN_CRITERIA,
filtrul de trend 1h, veto-ul Livermore+Turtle, cooldown după pierdere, sizing
pe risc 2%, spread plătit la intrare, slippage, exituri identice cu live-ul
(SL/TP/breakeven/trailing/runner) evaluate la close — cum face botul la tick.
Ce NU simulează: judecata LLM-ului (filtru suplimentar la live → live-ul ia de
regulă MAI PUȚINE trade-uri). Rezultatele trecute nu garantează profit.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PAPER_TRADING", "true")

from apex import config as cfg, forex, indicators, strategies, logger  # noqa: E402
from apex import position as position_mod  # noqa: E402
from apex.position import calc_entry_sltp, trail_stop, exit_trigger  # noqa: E402

SYMBOL = os.getenv("BT_SYMBOL") or cfg.SYMBOL
START_BAL = float(os.getenv("BT_BALANCE") or 1000)
CANDLES = int(os.getenv("BT_CANDLES") or 2000)
SLIPPAGE_PIPS = float(os.getenv("BT_SLIPPAGE_PIPS") or 0.3)
SPREAD_PIPS = float(os.getenv("BT_SPREAD_PIPS") or 1.0)
SYNTHETIC = os.getenv("BT_SYNTHETIC") == "true"
MIN_CRITERIA = int(os.getenv("MIN_CRITERIA") or 4)
# Per-user settings live in Redis, not cfg — the live loop reads them off the
# user record, so they have to be injectable here or the backtest silently
# simulates a different account than the one trading (e.g. cfg risk 1.25% vs
# the 35% actually configured on the forex bot).
RISK = float(os.getenv("BT_RISK") or cfg.RISK_PER_TRADE)
TRAILING = (os.getenv("BT_TRAILING") or "true") != "false"
BREAKEVEN_R = float(os.getenv("BT_BREAKEVEN_R") or 0)
HTF_ON = (os.getenv("BT_HTF") or ("true" if cfg.HTF_FILTER else "false")) != "false"
# Trail one CONSTANT risk-unit behind price instead of live's recomputed
# abs(entry - cur_sl). See position.trail_stop() — off by default so the
# baseline run stays a faithful mirror of what trades today.
FIXED_R_TRAIL = os.getenv("BT_FIXED_R_TRAIL") == "true"
# BT_STRATEGY: criteria (rubrica AI istorică) | mean_reversion | trend | breakout
BT_STRATEGY = (os.getenv("BT_STRATEGY") or "criteria").lower().replace("mean", "mean_reversion") if (os.getenv("BT_STRATEGY") or "criteria").lower() == "mean" else (os.getenv("BT_STRATEGY") or "criteria").lower()  # 4/5 — forex: mc4>mc5 (mc5 prea puține semnale pe 3000 lumânări)

logger.info = lambda *a, **k: None  # fără spam pe mii de lumânări


def criteria_signal(ind, strat):
    """Rubrica din promptul AI (apex/ai.py), calculată mecanic."""
    rsi, macd_h = float(ind["rsi"]), float(ind["macdHist"])
    price, ema20 = float(ind["price"]), float(ind["ema20"])
    has_vol = ind.get("hasVolume", True)
    vol_ok = float(ind["volumeRatio"]) > 1.2 if has_vol else None
    srsi_k = float(ind["stochRsiK"])

    def score(direction):
        s = 0
        bull = direction == "BUY"
        if ind["emaTrend"] == ("BULLISH" if bull else "BEARISH"):
            s += 1
        if (rsi < 50 if bull else rsi > 50) or ind["divergence"] == ("BULLISH" if bull else "BEARISH"):
            s += 1
        if (macd_h > 0) == bull:
            s += 1
        # criteriul de volum — la fel ca ai.py: fără volum → Stoch RSI aliniat
        if vol_ok if vol_ok is not None else ((srsi_k < 50) == bull):
            s += 1
        if (price < ema20) == bull:
            s += 1
        liv, tur, sor = strat["livermore"], strat["turtle"], strat["soros"]
        if ((tur.get("breakoutStr") == "STRONG" and tur.get("signal") == direction)
                or (liv["trend"] == ("BULLISH" if bull else "BEARISH") and liv.get("strength", 0) >= 0.5)
                or sor["direction"] == ("BULLISH" if bull else "BEARISH")):
            s += 1
        return min(5, s)

    b, s = score("BUY"), score("SELL")
    if b >= MIN_CRITERIA and b > s:
        return {"action": "BUY", "criteriaScore": b}
    if s >= MIN_CRITERIA and s > b:
        return {"action": "SELL", "criteriaScore": s}
    return {"action": "HOLD", "criteriaScore": 0}


def resample_1h(candles, ratio=12):
    out = []
    for i in range(0, len(candles) - ratio + 1, ratio):
        grp = candles[i:i + ratio]
        out.append({"time": grp[0]["time"], "open": grp[0]["open"],
                    "close": grp[-1]["close"],
                    "high": max(c["high"] for c in grp),
                    "low": min(c["low"] for c in grp),
                    "volume": sum(c["volume"] for c in grp)})
    return out


def synthetic_candles(n):
    seed = [42]

    def rnd():
        seed[0] = (seed[0] * 1103515245 + 12345) % 2 ** 31
        return seed[0] / 2 ** 31

    out, p, drift = [], 1.0850, 0.0
    for i in range(n):
        if i % 250 == 0:
            drift = (rnd() - 0.5) * 0.00006
        ret = drift + (rnd() - 0.5) * 0.0004
        o, p = p, max(0.5, p * (1 + ret))
        out.append({"time": i, "open": o, "close": p,
                    "high": max(o, p) * (1 + rnd() * 0.0001),
                    "low": min(o, p) * (1 - rnd() * 0.0001),
                    "volume": 0})
    return out


def fetch_candles():
    if SYNTHETIC:
        return synthetic_candles(CANDLES + 300)
    from apex.brokers import get_broker
    broker = get_broker()
    return broker.get_candles(SYMBOL, cfg.TIMEFRAME, min(CANDLES + 300, 5000))


def run():
    pip = forex.pip_size(SYMBOL)
    half_spread = SPREAD_PIPS / 2 * pip
    slip = SLIPPAGE_PIPS * pip
    print("\n" + "═" * 64)
    print(f"  📊 APEX FOREX BACKTEST — metoda: {BT_STRATEGY} (exituri user_loop)")
    print(f"  {'⚠️  DATE SINTETICE — validare motor, NU concluzii de profit' if SYNTHETIC else f'Symbol: {SYMBOL} | TF: {cfg.TIMEFRAME}'}")
    print(f"  Balanță: ${START_BAL:.0f} | SL {position_mod.USERLOOP_SL_ATR_MULT:g}×ATR / "
          f"TP {position_mod.USERLOOP_TP_ATR_MULT:g}×ATR | risc {RISK * 100:g}% (pe startBalance) | "
          f"spread {SPREAD_PIPS:g}p | slippage {SLIPPAGE_PIPS:g}p")
    print(f"  Trailing: {'1R' if TRAILING else 'off'} | breakeven: "
          f"{f'{BREAKEVEN_R:g}R' if BREAKEVEN_R else 'off'} | HTF: {'on' if HTF_ON else 'off'} | "
          f"exit SL/TP intrabar (high/low)"
          f"{' | trail=1R FIX' if FIXED_R_TRAIL else ''}")
    print("═" * 64)

    candles = fetch_candles()
    if len(candles) < 400:
        raise SystemExit(f"Doar {len(candles)} lumânări — minim 400")

    balance, position, trades = START_BAL, None, []
    last_loss_idx = -10 ** 9
    # Live blocks re-entry for _LOSS_COOLDOWN_MIN (15) after a losing close,
    # not cfg.COOLDOWN_AFTER_LOSS_MIN (3 in scalp mode) — another silent gap.
    cooldown_bars = max(1, int(os.getenv("BT_COOLDOWN_MIN") or 15) // 5)
    peak, max_dd, spread_cost = START_BAL, 0.0, 0.0

    def close(exit_mid, reason, i):
        nonlocal balance, position, last_loss_idx, peak, max_dd, spread_cost
        d = 1 if position["side"] == "BUY" else -1
        exit_px = exit_mid - d * (half_spread + slip)
        pnl = forex.pnl_usd(position["side"], position["entryPrice"], exit_px,
                            position["quantity"], SYMBOL)
        spread_cost += (half_spread + slip) * position["quantity"] * (1 if SYMBOL.endswith("_USD") else 1 / exit_mid)
        balance += pnl
        pips = forex.to_pips(
            (exit_px - position["entryPrice"]) * d, SYMBOL, exit_px)
        trades.append({"side": position["side"], "pnl": pnl, "reason": reason,
                       "pips": round(pips, 1)})
        if pnl < 0:
            last_loss_idx = i
        position = None
        peak = max(peak, balance)
        max_dd = max(max_dd, (peak - balance) / peak)

    for i in range(300, len(candles)):
        window = candles[:i + 1]
        bar = candles[i]
        mid = bar["close"]

        if position:
            # Order matters and mirrors live: cTrader holds SL/TP server-side,
            # so they fill intrabar against THIS bar's range using the stop
            # that was already resting when the bar opened. Only after that
            # does the bot's own 5-min tick get to trail the stop, and it sees
            # the close — never the wick it would have needed to react to.
            trigger = exit_trigger(position["side"], position["stopLoss"],
                                   position["takeProfit"], bar["high"], bar["low"])
            if trigger:
                # Broker fills AT the resting order's level, not at the close.
                level = (position["stopLoss"] if trigger == "STOP_LOSS"
                         else position["takeProfit"])
                close(level, trigger, i)
                continue
            moved = trail_stop(position["side"], position["entryPrice"],
                               position["stopLoss"], mid,
                               trailing=TRAILING, breakeven_r=BREAKEVEN_R,
                               initial_risk=(position["initialRisk"]
                                             if FIXED_R_TRAIL else None))
            if moved is not None:
                position["stopLoss"] = moved
        if position or balance < 10:
            continue
        if i - last_loss_idx < cooldown_bars:
            continue

        ind = indicators.analyze(window)
        strat = strategies.analyze(window)
        if BT_STRATEGY == "criteria":
            sig = criteria_signal(ind, strat)
        else:
            from apex import ai
            s2 = ai.signal_for_mode(BT_STRATEGY, ind, strat, None)
            sig = ({"action": s2["action"], "criteriaScore": s2.get("criteriaScore", 3)}
                   if s2["action"] in ("BUY", "SELL") and s2.get("confidence", 0) >= 62
                   else {"action": "HOLD", "criteriaScore": 0})
        if sig["action"] == "HOLD":
            continue

        liv, tur = strat["livermore"], strat["turtle"]
        contra = ("BUY" if liv["trend"] == "BEARISH" and tur.get("signal") == "SELL"
                  else "SELL" if liv["trend"] == "BULLISH" and tur.get("signal") == "BUY" else None)
        if liv.get("strength", 0) >= 0.8 and sig["action"] == contra:
            continue
        if HTF_ON:
            htf = strategies.htf_trend(resample_1h(window[-720:]))
            if os.getenv("BT_HTF_STRICT") == "true" or cfg.HTF_STRICT:
                # strict: intră DOAR pe direcția trendului 1h (NEUTRAL = HOLD)
                if htf != ("BULLISH" if sig["action"] == "BUY" else "BEARISH"):
                    continue
            elif ((sig["action"] == "BUY" and htf == "BEARISH")
                    or (sig["action"] == "SELL" and htf == "BULLISH")):
                continue

        d = 1 if sig["action"] == "BUY" else -1
        entry = mid + d * (half_spread + slip)  # intrarea plătește spread + slippage
        sl_px, tp_px = calc_entry_sltp(sig["action"], entry, float(ind["atr"]),
                                       SYMBOL, spread_pips=SPREAD_PIPS,
                                       sl_pips=cfg.STOP_LOSS_PIPS,
                                       tp_pips=cfg.TAKE_PROFIT_PIPS)
        stop_pips = forex.to_pips(abs(entry - sl_px), SYMBOL)
        mult = strategies.druckenmiller_multiplier(70, sig["criteriaScore"], liv, tur)
        # Live sizes off startBalance, never the running balance — deliberately,
        # so the same setup keeps the same lot size instead of drifting with
        # P&L. Compounding off `balance` here (as this did) inflates results
        # against a bot that does not compound.
        units = forex.calc_units(START_BAL, RISK, stop_pips, SYMBOL, entry,
                                 leverage=cfg.LEVERAGE, mult=mult)
        floor = forex.safe_min_units(SYMBOL, balance, entry, cfg.LEVERAGE,
                                     cfg.MARGIN_CAP)
        if floor == 0:  # account can't margin even one micro-lot — live skips
            continue
        units = forex.round_units(max(units, floor), SYMBOL)
        if units <= 0:
            continue
        position = {"symbol": SYMBOL, "side": sig["action"], "entryPrice": entry,
                    "quantity": units, "stopLoss": sl_px, "takeProfit": tp_px,
                    "initialStop": sl_px,
                    "initialRisk": abs(entry - sl_px)}
    if position:
        close(candles[-1]["close"], "END", len(candles) - 1)

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gw = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    days = (len(candles) - 300) * 5 / 1440
    print(f"\n  Perioadă: ~{days:.1f} zile | Trades: {len(trades)} (✅ {len(wins)} / ❌ {len(losses)})")
    if trades:
        print(f"  Win rate: {len(wins) / len(trades) * 100:.1f}% | "
              f"Profit factor: {'∞' if gl == 0 else f'{gw / gl:.2f}'}")
        print(f"  Rezultat net: {(balance - START_BAL) / START_BAL * 100:+.2f}% (${balance:.2f}) | "
              f"Max DD: -{max_dd * 100:.1f}%")
        print(f"  Expectancy: {sum(t['pnl'] for t in trades) / len(trades):+.2f} $/trade | "
              f"Cost spread+slippage: ~${spread_cost:.2f}")
        reasons = {}
        for t in trades:
            reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
        print("  Exituri: " + " | ".join(f"{r}×{n}" for r, n in reasons.items()))
    print("\n  ⚠️  Stratul AI nu e simulat (la live filtrează în plus). Rezultatele")
    print("      trecute nu garantează nimic. Paper trading înainte de live.")
    print("═" * 64 + "\n")


if __name__ == "__main__":
    run()
