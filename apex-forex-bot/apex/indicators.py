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
    out = []
    for i in range(len(closes)):
        if i < period:
            out.append(None)
            continue
        gains = losses = 0.0
        for j in range(i - period + 1, i + 1):
            diff = closes[j] - closes[j - 1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        ag, al = gains / period, losses / period
        out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return out


def stoch_rsi(closes, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
    rsi_vals = rsi(closes, rsi_period)
    stoch = []
    for i in range(len(rsi_vals)):
        if i < stoch_period - 1 or rsi_vals[i] is None:
            stoch.append(None)
            continue
        sl = [v for v in rsi_vals[i - stoch_period + 1: i + 1] if v is not None]
        if len(sl) < stoch_period:
            stoch.append(None)
            continue
        lo, hi = min(sl), max(sl)
        stoch.append(0 if hi == lo else (rsi_vals[i] - lo) / (hi - lo) * 100)
    k_line = sma([v for v in stoch if v is not None], k_period)
    d_line = sma([v for v in k_line if v is not None], d_period)
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
        "recentCandles": [{
            "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"],
            "direction": "🟢" if c["close"] > c["open"] else "🔴",
            "bodyPct": f"{abs(c['close'] - c['open']) / c['open'] * 100:.2f}",
        } for c in candles[-5:]],
    }
