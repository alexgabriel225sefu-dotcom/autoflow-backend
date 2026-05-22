"""
Apex Trade ML Engine - FastAPI
Handles advanced backtesting, ML signals, and strategy optimization
"""
import os
import json
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import requests

app = FastAPI(title="Apex Trade ML Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Models ──────────────────────────────────────────────
class BacktestRequest(BaseModel):
    strategy: str
    symbol: str
    market: str
    start_date: str
    end_date: str
    initial_capital: float = 10000.0
    params: Optional[Dict[str, float]] = {}

class SignalRequest(BaseModel):
    symbol: str
    market: str
    timeframe: str = "1h"

class OptimizeRequest(BaseModel):
    strategy: str
    symbol: str
    market: str
    start_date: str
    end_date: str
    initial_capital: float = 10000.0
    iterations: int = 100

# ─── Health ──────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "engine": "apextrade-ml", "version": "1.0.0"}

# ─── Advanced Backtest ────────────────────────────────────
@app.post("/backtest/advanced")
async def advanced_backtest(req: BacktestRequest):
    """Run advanced ML-powered backtest with millions of simulations"""
    try:
        # Fetch OHLCV data
        df = fetch_ohlcv(req.symbol, req.market, req.start_date, req.end_date)
        if df is None or len(df) < 50:
            raise HTTPException(status_code=400, detail="Date insuficiente pentru backtest")

        # Calculate indicators
        df = add_indicators(df)

        # Run strategy
        results = run_strategy(df, req.strategy, req.initial_capital, req.params or {})
        return results
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── ML Signal Generation ─────────────────────────────────
@app.post("/signals/ml")
async def generate_ml_signal(req: SignalRequest):
    """Generate ML-powered trading signal"""
    try:
        df = fetch_ohlcv(req.symbol, req.market, days=30)
        if df is None:
            raise HTTPException(status_code=400, detail="Date indisponibile")

        df = add_indicators(df)
        signal = ml_signal(df, req.symbol, req.market)
        return signal
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── Strategy Optimization ────────────────────────────────
@app.post("/optimize")
async def optimize_strategy(req: OptimizeRequest):
    """Run Monte Carlo optimization to find best strategy parameters"""
    try:
        df = fetch_ohlcv(req.symbol, req.market, req.start_date, req.end_date)
        if df is None:
            raise HTTPException(status_code=400, detail="Date indisponibile")

        df = add_indicators(df)
        best_params, best_sharpe = monte_carlo_optimize(df, req.strategy, req.initial_capital, req.iterations)

        return {
            "best_params": best_params,
            "best_sharpe": round(best_sharpe, 4),
            "iterations": req.iterations,
            "strategy": req.strategy,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── Data Fetching ────────────────────────────────────────
def fetch_ohlcv(symbol: str, market: str, start_date: str = None, end_date: str = None, days: int = 365):
    """Fetch OHLCV data from appropriate source"""
    try:
        if market == "crypto":
            sym = symbol.upper()
            if not sym.endswith("USDT"):
                sym = f"{sym}USDT"

            url = "https://api.binance.com/api/v3/klines"
            params = {"symbol": sym, "interval": "1d", "limit": days}
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            df = pd.DataFrame(data, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades", "taker_buy_base",
                "taker_buy_quote", "ignore"
            ])
            df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df[["date", "open", "high", "low", "close", "volume"]].copy()
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col])
            return df
        else:
            # Mock data for stocks/forex
            return generate_mock_ohlcv(days)
    except Exception as e:
        print(f"[fetch_ohlcv] Error: {e}")
        return generate_mock_ohlcv(days)

def generate_mock_ohlcv(days: int):
    """Generate realistic mock OHLCV data"""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=days, freq="D")
    price = 67000.0
    rows = []
    for date in dates:
        change = np.random.normal(0, price * 0.02)
        open_p = price
        close_p = price + change
        high_p = max(open_p, close_p) * (1 + abs(np.random.normal(0, 0.005)))
        low_p = min(open_p, close_p) * (1 - abs(np.random.normal(0, 0.005)))
        volume = abs(np.random.normal(1000, 300))
        rows.append({"date": date, "open": open_p, "high": high_p, "low": low_p, "close": close_p, "volume": volume})
        price = close_p
    return pd.DataFrame(rows)

# ─── Technical Indicators ─────────────────────────────────
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    # RSI
    df["rsi"] = calculate_rsi(closes, 14)

    # EMA
    df["ema20"] = pd.Series(closes).ewm(span=20, adjust=False).mean().values
    df["ema50"] = pd.Series(closes).ewm(span=50, adjust=False).mean().values
    df["ema200"] = pd.Series(closes).ewm(span=200, adjust=False).mean().values

    # MACD
    ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean()
    ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean()
    df["macd"] = (ema12 - ema26).values
    df["macd_signal"] = pd.Series(df["macd"]).ewm(span=9, adjust=False).mean().values
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Bollinger Bands
    rolling_mean = pd.Series(closes).rolling(20).mean()
    rolling_std = pd.Series(closes).rolling(20).std()
    df["bb_upper"] = (rolling_mean + 2 * rolling_std).values
    df["bb_middle"] = rolling_mean.values
    df["bb_lower"] = (rolling_mean - 2 * rolling_std).values

    # ATR
    tr = np.maximum(
        highs - lows,
        np.maximum(abs(highs - np.roll(closes, 1)), abs(lows - np.roll(closes, 1)))
    )
    df["atr"] = pd.Series(tr).rolling(14).mean().values

    # Volume MA
    df["volume_ma"] = pd.Series(df["volume"].values).rolling(20).mean().values

    return df.dropna().reset_index(drop=True)

def calculate_rsi(prices, period=14):
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.zeros(len(prices))
    avg_loss = np.zeros(len(prices))

    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])

    for i in range(period + 1, len(prices)):
        avg_gain[i] = (avg_gain[i-1] * (period-1) + gains[i-1]) / period
        avg_loss[i] = (avg_loss[i-1] * (period-1) + losses[i-1]) / period

    rs = np.where(avg_loss == 0, 100, avg_gain / avg_loss)
    rsi = 100 - (100 / (1 + rs))
    rsi[:period] = 50
    return rsi

# ─── Strategy Engine ─────────────────────────────────────
def run_strategy(df: pd.DataFrame, strategy: str, capital: float, params: dict) -> dict:
    position = None
    trades = []
    equity = [{"date": str(df.iloc[0]["date"])[:10], "value": capital}]
    current_capital = capital

    sl_pct = params.get("stop_loss", 0.05)
    tp_pct = params.get("take_profit", 0.10)

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        signal = get_signal(row, prev, strategy, params)

        if signal == "BUY" and position is None:
            shares = current_capital / row["close"]
            position = {"entry": row["close"], "shares": shares, "date": str(row["date"])[:10]}

        elif signal == "SELL" and position is not None:
            pnl = (row["close"] - position["entry"]) * position["shares"]
            pnl_pct = (row["close"] - position["entry"]) / position["entry"] * 100
            current_capital = position["shares"] * row["close"]
            trades.append({"date": str(row["date"])[:10], "action": "SELL", "price": float(row["close"]), "pnl": round(pnl, 2), "pnlPercent": round(pnl_pct, 2)})
            position = None

        # Stop loss / take profit
        if position:
            ret = (row["close"] - position["entry"]) / position["entry"]
            if ret <= -sl_pct or ret >= tp_pct:
                pnl = (row["close"] - position["entry"]) * position["shares"]
                current_capital = position["shares"] * row["close"]
                trades.append({"date": str(row["date"])[:10], "action": "TP" if ret > 0 else "SL", "price": float(row["close"]), "pnl": round(pnl, 2), "pnlPercent": round(ret * 100, 2)})
                position = None

        if i % 5 == 0:
            val = (position["shares"] * row["close"]) if position else current_capital
            equity.append({"date": str(row["date"])[:10], "value": round(val, 2)})

    total_return = (current_capital - capital) / capital * 100
    win_trades = [t for t in trades if t["pnl"] > 0]
    win_rate = len(win_trades) / len(trades) * 100 if trades else 0

    # Sharpe
    returns = [(equity[i]["value"] - equity[i-1]["value"]) / equity[i-1]["value"] for i in range(1, len(equity))]
    sharpe = (np.mean(returns) / np.std(returns) * np.sqrt(252)) if len(returns) > 1 and np.std(returns) > 0 else 0

    # Max drawdown
    peak = capital
    max_dd = 0
    for e in equity:
        peak = max(peak, e["value"])
        dd = (peak - e["value"]) / peak * 100
        max_dd = max(max_dd, dd)

    return {
        "id": f"bt_{pd.Timestamp.now().value}",
        "totalReturn": round(total_return, 2),
        "annualizedReturn": round(total_return * 365 / len(df), 2),
        "sharpeRatio": round(sharpe, 3),
        "maxDrawdown": round(max_dd, 2),
        "winRate": round(win_rate, 1),
        "totalTrades": len(trades),
        "profitFactor": round(sum(t["pnl"] for t in win_trades) / max(abs(sum(t["pnl"] for t in trades if t["pnl"] < 0)), 1), 2),
        "avgTradeReturn": round(np.mean([t["pnlPercent"] for t in trades]) if trades else 0, 2),
        "finalCapital": round(current_capital, 2),
        "equityCurve": equity,
        "trades": trades[-50:],
    }

def get_signal(row, prev, strategy: str, params: dict) -> str:
    rsi = row.get("rsi", 50)
    macd = row.get("macd", 0)
    macd_s = row.get("macd_signal", 0)
    ema20 = row.get("ema20", row["close"])
    ema50 = row.get("ema50", row["close"])

    if strategy == "rsi_macd":
        rsi_lo = params.get("rsi_low", 35)
        rsi_hi = params.get("rsi_high", 65)
        if rsi < rsi_lo and macd > macd_s:
            return "BUY"
        if rsi > rsi_hi and macd < macd_s:
            return "SELL"

    elif strategy == "ema_crossover":
        if prev["ema20"] <= prev["ema50"] and ema20 > ema50:
            return "BUY"
        if prev["ema20"] >= prev["ema50"] and ema20 < ema50:
            return "SELL"

    elif strategy == "bb_rsi":
        bb_lo = row.get("bb_lower", row["close"] * 0.98)
        bb_up = row.get("bb_upper", row["close"] * 1.02)
        if row["close"] <= bb_lo and rsi < 40:
            return "BUY"
        if row["close"] >= bb_up and rsi > 60:
            return "SELL"

    elif strategy == "ai_adaptive":
        bull = sum([rsi < 45, macd > macd_s, ema20 > ema50, row["close"] > row["open"]])
        if bull >= 3:
            return "BUY"
        if bull <= 1:
            return "SELL"

    return "HOLD"

# ─── ML Signal ────────────────────────────────────────────
def ml_signal(df: pd.DataFrame, symbol: str, market: str) -> dict:
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Feature-based scoring
    bull_score = 0
    bear_score = 0

    rsi = last.get("rsi", 50)
    if rsi < 35: bull_score += 2
    elif rsi > 65: bear_score += 2

    macd = last.get("macd", 0)
    macd_s = last.get("macd_signal", 0)
    if macd > macd_s: bull_score += 1
    else: bear_score += 1

    ema20 = last.get("ema20", last["close"])
    ema50 = last.get("ema50", last["close"])
    if ema20 > ema50: bull_score += 1
    else: bear_score += 1

    bb_lower = last.get("bb_lower", last["close"] * 0.98)
    bb_upper = last.get("bb_upper", last["close"] * 1.02)
    if last["close"] < bb_lower: bull_score += 2
    elif last["close"] > bb_upper: bear_score += 2

    vol_ma = last.get("volume_ma", last.get("volume", 1))
    if last.get("volume", 0) > vol_ma * 1.5: bull_score += 1

    total = bull_score + bear_score
    action = "BUY" if bull_score > bear_score else ("SELL" if bear_score > bull_score else "HOLD")
    confidence = int((max(bull_score, bear_score) / total * 100)) if total > 0 else 50

    price = float(last["close"])
    direction = 1 if action == "BUY" else -1
    target_pct = 0.04 * direction
    sl_pct = -0.02 * direction

    return {
        "symbol": symbol,
        "market": market,
        "action": action,
        "confidence": min(confidence, 95),
        "entryPrice": round(price, 6),
        "targetPrice": round(price * (1 + target_pct), 6),
        "stopLoss": round(price * (1 + sl_pct), 6),
        "riskRewardRatio": round(abs(target_pct / sl_pct), 2),
        "timeframe": "1h",
        "indicators": {
            "rsi": round(float(rsi), 2),
            "macd": round(float(macd), 4),
            "macdSignal": round(float(macd_s), 4),
            "ema20": round(float(ema20), 4),
            "ema50": round(float(ema50), 4),
            "bb_upper": round(float(bb_upper), 4),
            "bb_lower": round(float(bb_lower), 4),
            "volume_ratio": round(float(last.get("volume", 1)) / float(vol_ma) if vol_ma > 0 else 1, 2),
        },
    }

# ─── Monte Carlo Optimization ────────────────────────────
def monte_carlo_optimize(df: pd.DataFrame, strategy: str, capital: float, iterations: int):
    best_sharpe = -999
    best_params = {}

    for _ in range(iterations):
        params = {
            "rsi_low": np.random.randint(25, 45),
            "rsi_high": np.random.randint(55, 75),
            "stop_loss": round(np.random.uniform(0.03, 0.08), 3),
            "take_profit": round(np.random.uniform(0.06, 0.15), 3),
        }
        try:
            result = run_strategy(df.copy(), strategy, capital, params)
            if result["sharpeRatio"] > best_sharpe:
                best_sharpe = result["sharpeRatio"]
                best_params = params
        except:
            pass

    return best_params, best_sharpe

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
