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
from apex.position import calc_sltp, check_position  # noqa: E402

SYMBOL = os.getenv("BT_SYMBOL") or cfg.SYMBOL
START_BAL = float(os.getenv("BT_BALANCE") or 1000)
CANDLES = int(os.getenv("BT_CANDLES") or 2000)
SLIPPAGE_PIPS = float(os.getenv("BT_SLIPPAGE_PIPS") or 0.3)
SPREAD_PIPS = float(os.getenv("BT_SPREAD_PIPS") or 1.0)
SYNTHETIC = os.getenv("BT_SYNTHETIC") == "true"
MIN_CRITERIA = int(os.getenv("MIN_CRITERIA") or 4)  # 4/5 — forex: mc4>mc5 (mc5 prea puține semnale pe 3000 lumânări)

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
    print("  📊 APEX FOREX BACKTEST — strategia reală (rubrică AI + exituri live)")
    print(f"  {'⚠️  DATE SINTETICE — validare motor, NU concluzii de profit' if SYNTHETIC else f'Symbol: {SYMBOL} | TF: {cfg.TIMEFRAME}'}")
    print(f"  Balanță: ${START_BAL:.0f} | SL {cfg.STOP_LOSS_PIPS:g}p / TP {cfg.TAKE_PROFIT_PIPS:g}p | "
          f"risc {cfg.RISK_PER_TRADE * 100:g}% | spread {SPREAD_PIPS:g}p | slippage {SLIPPAGE_PIPS:g}p")
    print("═" * 64)

    candles = fetch_candles()
    if len(candles) < 400:
        raise SystemExit(f"Doar {len(candles)} lumânări — minim 400")

    balance, position, trades = START_BAL, None, []
    last_loss_idx = -10 ** 9
    cooldown_bars = max(1, cfg.COOLDOWN_AFTER_LOSS_MIN // 5)
    peak, max_dd, spread_cost = START_BAL, 0.0, 0.0

    def close(exit_mid, reason, i):
        nonlocal balance, position, last_loss_idx, peak, max_dd, spread_cost
        d = 1 if position["side"] == "BUY" else -1
        exit_px = exit_mid - d * (half_spread + slip)
        pnl = forex.pnl_usd(position["side"], position["entryPrice"], exit_px,
                            position["quantity"], SYMBOL)
        spread_cost += (half_spread + slip) * position["quantity"] * (1 if SYMBOL.endswith("_USD") else 1 / exit_mid)
        balance += pnl
        trades.append({"side": position["side"], "pnl": pnl, "reason": reason,
                       "pips": position.get("pnlPips", 0)})
        if pnl < 0:
            last_loss_idx = i
        position = None
        peak = max(peak, balance)
        max_dd = max(max_dd, (peak - balance) / peak)

    for i in range(300, len(candles)):
        window = candles[:i + 1]
        mid = candles[i]["close"]

        if position:
            trigger = check_position(position, mid)
            if trigger:
                close(mid, trigger, i)
                continue
        if position or balance < 10:
            continue
        if i - last_loss_idx < cooldown_bars:
            continue

        ind = indicators.analyze(window)
        strat = strategies.analyze(window)
        sig = criteria_signal(ind, strat)
        if sig["action"] == "HOLD":
            continue

        liv, tur = strat["livermore"], strat["turtle"]
        contra = ("BUY" if liv["trend"] == "BEARISH" and tur.get("signal") == "SELL"
                  else "SELL" if liv["trend"] == "BULLISH" and tur.get("signal") == "BUY" else None)
        if liv.get("strength", 0) >= 0.8 and sig["action"] == contra:
            continue
        if cfg.HTF_FILTER:
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
        sltp = calc_sltp(sig["action"], entry, float(ind["atr"]), SYMBOL)
        stop_pips = forex.to_pips(abs(entry - sltp["stopLoss"]), SYMBOL)
        mult = strategies.druckenmiller_multiplier(70, sig["criteriaScore"], liv, tur)
        units = forex.calc_units(balance, cfg.RISK_PER_TRADE, stop_pips, SYMBOL,
                                 entry, cfg.LEVERAGE, cfg.MARGIN_CAP, mult)
        if units <= 0:
            continue
        position = {"symbol": SYMBOL, "side": sig["action"], "entryPrice": entry,
                    "quantity": units, "stopLoss": sltp["stopLoss"],
                    "takeProfit": sltp["takeProfit"], "initialStop": sltp["stopLoss"],
                    "trailHigh": entry if d == 1 else None,
                    "trailLow": entry if d == -1 else None}
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
