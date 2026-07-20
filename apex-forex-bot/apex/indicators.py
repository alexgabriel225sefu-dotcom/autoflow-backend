"""Technical indicators (faithful port of indicators.js). None == JS null."""
import math


def sma(data, period):
    out = []
    for i in range(len(data)):
        if i < period - 1:
            out.append(None)
        else:
            window = data[i - period + 1: i + 1]
            out.append(sum(window) / period)
    return out


def ema(data, period):
    k = 2 / (period + 1)
    out = []
    prev = None
    for i in range(len(data)):
        if i < period - 1:
            out.append(None)
            continue
        if prev is None:
            prev = sum(data[:period]) / period
            out.append(prev)
            continue
        prev = data[i] * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(closes, period=14):
    """RSI using Wilder's exponential smoothing (matches TradingView/cTrader)."""
    n = len(closes)
    if n < period + 1:
        return [None] * n
    out = [None] * period
    gains = losses = 0.0
    for j in range(1, period + 1):
        d = closes[j] - closes[j - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    avg_gain = gains / period
    avg_loss = losses / period
    out.append(100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        out.append(100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss))
    return out


def _positional_sma(data, period):
    """SMA preserving positional alignment — None gaps reset the window."""
    out = []
    buf = []
    for v in data:
        if v is None:
            out.append(None)
            buf.clear()
        else:
            buf.append(v)
            if len(buf) >= period:
                out.append(sum(buf[-period:]) / period)
            else:
                out.append(None)
    return out


def stoch_rsi(closes, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
    rsi_vals = rsi(closes, rsi_period)
    stoch = []
    for i in range(len(rsi_vals)):
        if i < stoch_period - 1 or rsi_vals[i] is None:
            stoch.append(None)
            continue
        window = rsi_vals[i - stoch_period + 1: i + 1]
        if any(v is None for v in window):
            stoch.append(None)
            continue
        lo, hi = min(window), max(window)
        stoch.append(0 if hi == lo else (rsi_vals[i] - lo) / (hi - lo) * 100)
    k_line = _positional_sma(stoch, k_period)
    d_line = _positional_sma(k_line, d_period)
    last_k = next((v for v in reversed(k_line) if v is not None), None)
    last_d = next((v for v in reversed(d_line) if v is not None), None)
    return {"k": last_k, "d": last_d}


def macd(closes, fast=12, slow=26, signal=9):
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [f - s if f is not None and s is not None else None for f, s in zip(ema_fast, ema_slow)]
    valid = [v for v in macd_line if v is not None]
    sig = ema(valid, signal)
    full_sig = [None] * len(macd_line)
    si = 0
    for i in range(len(macd_line)):
        if macd_line[i] is not None:
            full_sig[i] = sig[si] if si < len(sig) else None
            si += 1
    hist = [m - s if m is not None and s is not None else None for m, s in zip(macd_line, full_sig)]
    return {"macd": macd_line, "signal": full_sig, "histogram": hist}


def bollinger_bands(closes, period=20, multiplier=2):
    mid_line = sma(closes, period)
    out = []
    for i, mid in enumerate(mid_line):
        if mid is None:
            out.append({"upper": None, "mid": None, "lower": None, "bandwidth": None})
            continue
        window = closes[i - period + 1: i + 1]
        mean = sum(window) / period
        std = math.sqrt(sum((b - mean) ** 2 for b in window) / period)
        upper, lower = mid + multiplier * std, mid - multiplier * std
        out.append({"upper": upper, "mid": mid, "lower": lower, "bandwidth": (upper - lower) / mid * 100})
    return out


def atr(candles, period=14):
    tr = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sma(tr, period)


def detect_divergence(closes, rsi_values, lookback=5):
    last = len(closes) - 1
    if last < lookback + 1:
        return "NONE"
    prev_price_min = min(closes[last - lookback: last])
    prev_rsi_min = min(v for v in rsi_values[last - lookback: last] if v is not None)
    if closes[last] < prev_price_min and rsi_values[last] is not None and rsi_values[last] > prev_rsi_min:
        return "BULLISH"
    prev_price_max = max(closes[last - lookback: last])
    prev_rsi_max = max(v for v in rsi_values[last - lookback: last] if v is not None)
    if closes[last] > prev_price_max and rsi_values[last] is not None and rsi_values[last] < prev_rsi_max:
        return "BEARISH"
    return "NONE"


def market_structure(candles, lookback=20):
    recent = candles[-lookback:]
    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    hh = ll = hl = lh = 0
    for i in range(2, len(recent)):
        if highs[i] > highs[i - 1] and highs[i] > highs[i - 2]:
            hh += 1
        if lows[i] > lows[i - 1] and lows[i] > lows[i - 2]:
            hl += 1
        if highs[i] < highs[i - 1] and highs[i] < highs[i - 2]:
            lh += 1
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2]:
            ll += 1
    if hh >= 2 and hl >= 2:
        return "UPTREND"
    if lh >= 2 and ll >= 2:
        return "DOWNTREND"
    return "SIDEWAYS"


def fibonacci_levels(candles, lookback=50):
    """Fibonacci retracement & extension levels from the recent swing high/low."""
    if len(candles) < lookback:
        return {"levels": {}, "trend": "NEUTRAL", "nearest": None, "signal": None}
    recent = candles[-lookback:]
    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    swing_high = max(highs)
    swing_low = min(lows)
    hi_idx = highs.index(swing_high)
    lo_idx = lows.index(swing_low)
    price = candles[-1]["close"]
    diff = swing_high - swing_low
    if diff < 1e-10:
        return {"levels": {}, "trend": "NEUTRAL", "nearest": None, "signal": None}
    trend = "UP" if lo_idx < hi_idx else "DOWN"
    ratios = [0.236, 0.382, 0.5, 0.618, 0.786]
    levels = {}
    if trend == "UP":
        for r in ratios:
            levels[f"{r*100:.1f}%"] = round(swing_high - diff * r, 6)
        levels["ext_1.272"] = round(swing_high + diff * 0.272, 6)
        levels["ext_1.618"] = round(swing_high + diff * 0.618, 6)
    else:
        for r in ratios:
            levels[f"{r*100:.1f}%"] = round(swing_low + diff * r, 6)
        levels["ext_1.272"] = round(swing_low - diff * 0.272, 6)
        levels["ext_1.618"] = round(swing_low - diff * 0.618, 6)
    nearest = min(levels.items(), key=lambda kv: abs(kv[1] - price))
    tolerance = diff * 0.02
    signal = None
    if abs(price - nearest[1]) < tolerance:
        if trend == "UP" and price <= nearest[1]:
            signal = "BUY"
        elif trend == "DOWN" and price >= nearest[1]:
            signal = "SELL"
    return {"levels": levels, "trend": trend, "nearest": nearest[0],
            "nearestPrice": nearest[1], "signal": signal,
            "swingHigh": round(swing_high, 6), "swingLow": round(swing_low, 6)}


def fair_value_gap(candles, lookback=30):
    """Detect Fair Value Gaps (3-candle imbalance zones)."""
    if len(candles) < lookback:
        return {"bullish": [], "bearish": [], "signal": None}
    recent = candles[-lookback:]
    bullish_gaps = []
    bearish_gaps = []
    for i in range(2, len(recent)):
        c1, c2, c3 = recent[i - 2], recent[i - 1], recent[i]
        if c3["low"] > c1["high"]:
            bullish_gaps.append({"top": c3["low"], "bottom": c1["high"],
                                 "mid": (c3["low"] + c1["high"]) / 2, "idx": i})
        if c1["low"] > c3["high"]:
            bearish_gaps.append({"top": c1["low"], "bottom": c3["high"],
                                 "mid": (c1["low"] + c3["high"]) / 2, "idx": i})
    price = candles[-1]["close"]
    signal = None
    for gap in reversed(bullish_gaps[-5:]):
        if gap["bottom"] <= price <= gap["top"]:
            signal = "BUY"
            break
    if not signal:
        for gap in reversed(bearish_gaps[-5:]):
            if gap["bottom"] <= price <= gap["top"]:
                signal = "SELL"
                break
    return {"bullish": bullish_gaps[-5:], "bearish": bearish_gaps[-5:],
            "signal": signal, "count": len(bullish_gaps) + len(bearish_gaps)}


def inverse_fvg(candles, lookback=50):
    """Detect Inverse FVGs — gaps that got filled and now act as rejection zones."""
    if len(candles) < lookback:
        return {"zones": [], "signal": None}
    recent = candles[-lookback:]
    zones = []
    for i in range(2, len(recent) - 3):
        c1, c2, c3 = recent[i - 2], recent[i - 1], recent[i]
        gap_top = gap_bot = None
        direction = None
        if c3["low"] > c1["high"]:
            gap_top, gap_bot = c3["low"], c1["high"]
            direction = "bullish"
        elif c1["low"] > c3["high"]:
            gap_top, gap_bot = c1["low"], c3["high"]
            direction = "bearish"
        if gap_top is None:
            continue
        filled = False
        for j in range(i + 1, len(recent)):
            if direction == "bullish" and recent[j]["low"] <= gap_bot:
                filled = True
                break
            if direction == "bearish" and recent[j]["high"] >= gap_top:
                filled = True
                break
        if filled:
            zones.append({"top": gap_top, "bottom": gap_bot,
                          "mid": (gap_top + gap_bot) / 2,
                          "originalDirection": direction})
    price = candles[-1]["close"]
    signal = None
    for z in reversed(zones[-5:]):
        if z["bottom"] <= price <= z["top"]:
            if z["originalDirection"] == "bullish":
                signal = "SELL"
            else:
                signal = "BUY"
            break
    return {"zones": zones[-5:], "signal": signal}


def supply_demand_zones(candles, lookback=50):
    """Identify supply/demand zones from strong impulsive moves."""
    if len(candles) < lookback:
        return {"supply": [], "demand": [], "signal": None}
    recent = candles[-lookback:]
    supply_zones = []
    demand_zones = []
    atr_vals = atr(recent, min(14, len(recent) - 2))
    avg_atr = 0
    valid_atr = [v for v in atr_vals if v is not None]
    if valid_atr:
        avg_atr = sum(valid_atr) / len(valid_atr)
    threshold = avg_atr * 1.5 if avg_atr else 0
    for i in range(1, len(recent) - 1):
        body = abs(recent[i]["close"] - recent[i]["open"])
        if body < threshold:
            continue
        if recent[i]["close"] > recent[i]["open"]:
            zone_top = max(recent[i - 1]["open"], recent[i - 1]["close"])
            zone_bot = min(recent[i - 1]["low"], recent[i]["low"])
            demand_zones.append({"top": zone_top, "bottom": zone_bot,
                                 "strength": body / avg_atr if avg_atr else 1})
        else:
            zone_top = max(recent[i - 1]["high"], recent[i]["high"])
            zone_bot = min(recent[i - 1]["open"], recent[i - 1]["close"])
            supply_zones.append({"top": zone_top, "bottom": zone_bot,
                                 "strength": body / avg_atr if avg_atr else 1})
    price = candles[-1]["close"]
    signal = None
    for z in sorted(demand_zones, key=lambda x: -x["strength"])[:5]:
        if z["bottom"] <= price <= z["top"]:
            signal = "BUY"
            break
    if not signal:
        for z in sorted(supply_zones, key=lambda x: -x["strength"])[:5]:
            if z["bottom"] <= price <= z["top"]:
                signal = "SELL"
                break
    return {"supply": supply_zones[-5:], "demand": demand_zones[-5:], "signal": signal}


def liquidity_sweep(candles, lookback=20):
    """Detect liquidity sweeps (stop hunts past swing highs/lows that reverse)."""
    if len(candles) < lookback + 3:
        return {"signal": None, "type": None, "swept": None}
    body = candles[-lookback:-3]
    swing_highs = []
    swing_lows = []
    for i in range(1, len(body) - 1):
        if body[i]["high"] > body[i - 1]["high"] and body[i]["high"] > body[i + 1]["high"]:
            swing_highs.append(body[i]["high"])
        if body[i]["low"] < body[i - 1]["low"] and body[i]["low"] < body[i + 1]["low"]:
            swing_lows.append(body[i]["low"])
    if not swing_highs and not swing_lows:
        return {"signal": None, "type": None, "swept": None}
    last3 = candles[-3:]
    top_level = max(swing_highs) if swing_highs else None
    bot_level = min(swing_lows) if swing_lows else None
    if top_level is not None:
        swept_high = any(c["high"] > top_level for c in last3)
        closed_below = last3[-1]["close"] < top_level
        if swept_high and closed_below:
            return {"signal": "SELL", "type": "high_sweep",
                    "swept": round(top_level, 6)}
    if bot_level is not None:
        swept_low = any(c["low"] < bot_level for c in last3)
        closed_above = last3[-1]["close"] > bot_level
        if swept_low and closed_above:
            return {"signal": "BUY", "type": "low_sweep",
                    "swept": round(bot_level, 6)}
    return {"signal": None, "type": None, "swept": None}


def evc(candles, lookback=20):
    """Equilibrium Volume Candles — candles with balanced volume at key levels."""
    if len(candles) < lookback:
        return {"signal": None, "equilibrium": False, "level": None}
    recent = candles[-lookback:]
    volumes = [c.get("volume", 0) for c in recent]
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    if avg_vol == 0:
        return {"signal": None, "equilibrium": False, "level": None}
    last = candles[-1]
    body = abs(last["close"] - last["open"])
    wick_upper = last["high"] - max(last["open"], last["close"])
    wick_lower = min(last["open"], last["close"]) - last["low"]
    total_range = last["high"] - last["low"]
    if total_range < 1e-10:
        return {"signal": None, "equilibrium": False, "level": None}
    body_ratio = body / total_range
    vol_ratio = last.get("volume", 0) / avg_vol if avg_vol else 0
    is_equilibrium = (body_ratio < 0.35 and 0.7 <= vol_ratio <= 1.5 and
                      abs(wick_upper - wick_lower) / total_range < 0.3)
    if not is_equilibrium:
        return {"signal": None, "equilibrium": False, "level": None}
    mid = (last["high"] + last["low"]) / 2
    prev = candles[-2]
    signal = None
    if prev["close"] > prev["open"] and last["close"] < mid:
        signal = "SELL"
    elif prev["close"] < prev["open"] and last["close"] > mid:
        signal = "BUY"
    return {"signal": signal, "equilibrium": True, "level": round(mid, 6),
            "bodyRatio": round(body_ratio, 3), "volRatio": round(vol_ratio, 2)}


def _fmt(v, n):
    return None if v is None else f"{v:.{n}f}"


def analyze(candles):
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]

    rsi_values = rsi(closes)
    macd_data = macd(closes)
    bb_data = bollinger_bands(closes)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    atr_values = atr(candles)
    srsi = stoch_rsi(closes)

    last = len(closes) - 1
    price = closes[last]
    current_atr = next((v for v in reversed(atr_values) if v is not None), 0) or 0
    atr_pct = f"{current_atr / price * 100:.3f}"

    vol_recent = sum(volumes[-5:]) / 5
    vol_avg20 = sum(volumes[-20:]) / 20
    has_volume = vol_avg20 > 0  # Twelve Data forex has no tick volume — neutral, not 0
    volume_ratio = f"{vol_recent / vol_avg20:.2f}" if has_volume else "1.00"

    divergence = detect_divergence(closes, rsi_values)
    structure = market_structure(candles)
    bb_last = bb_data[last]
    bb_position = (f"{(price - bb_last['lower']) / (bb_last['upper'] - bb_last['lower']) * 100:.0f}"
                   if bb_last.get("upper") and bb_last.get("lower") else None)

    fib = fibonacci_levels(candles)
    fvg = fair_value_gap(candles)
    ifvg = inverse_fvg(candles)
    sd_zones = supply_demand_zones(candles)
    liq_sweep = liquidity_sweep(candles)
    evc_data = evc(candles)

    return {
        "price": price,
        "rsi": _fmt(rsi_values[last], 2),
        "macd": _fmt(macd_data["macd"][last], 6),
        "macdSignal": _fmt(macd_data["signal"][last], 6),
        "macdHist": _fmt(macd_data["histogram"][last], 6),
        "ema20": _fmt(ema20[last], 6),
        "ema50": _fmt(ema50[last], 6),
        "ema200": _fmt(ema200[last], 6),
        "bb_upper": _fmt(bb_last.get("upper"), 6),
        "bb_mid": _fmt(bb_last.get("mid"), 6),
        "bb_lower": _fmt(bb_last.get("lower"), 6),
        "bb_bandwidth": _fmt(bb_last.get("bandwidth"), 2),
        "bb_position": bb_position,
        "atr": f"{current_atr:.6f}",
        "atrPct": atr_pct,
        "volume": f"{volumes[last]:.0f}",
        "volumeAvg": f"{vol_avg20:.0f}",
        "volumeRatio": volume_ratio,
        "hasVolume": has_volume,
        "high24h": f"{max(highs[-96:]):.6f}",
        "low24h": f"{min(lows[-96:]):.6f}",
        "emaTrend": "BULLISH" if (ema20[last] or 0) > (ema50[last] or 0) else "BEARISH",
        "ema200Trend": "BULLISH" if (ema50[last] or 0) > (ema200[last] or 0) else "BEARISH",
        "priceVsEma20": (f"{(price - ema20[last]) / ema20[last] * 100:.2f}%" if ema20[last] else "0%"),
        "stochRsiK": _fmt(srsi["k"], 2),
        "stochRsiD": _fmt(srsi["d"], 2),
        "divergence": divergence,
        "marketStructure": structure,
        "fibonacci": fib,
        "fvg": fvg,
        "ifvg": ifvg,
        "supplyDemand": sd_zones,
        "liquiditySweep": liq_sweep,
        "evc": evc_data,
        "recentCandles": [{
            "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"],
            "direction": "🟢" if c["close"] > c["open"] else "🔴",
            "bodyPct": f"{abs(c['close'] - c['open']) / c['open'] * 100:.2f}",
        } for c in candles[-5:]],
    }
