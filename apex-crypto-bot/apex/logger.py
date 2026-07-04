"""Console logging + run stats (port of logger.js)."""
from datetime import datetime, timezone
from apex import config as cfg

_stats = {"trades": 0, "wins": 0, "losses": 0, "totalPnL": 0.0, "startBalance": 0.0, "currentBalance": 0.0}


def set_start_balance(b):
    _stats["startBalance"] = b
    _stats["currentBalance"] = b


def update_balance(b):
    _stats["currentBalance"] = b


def log(m):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {m}")


def info(m):
    print(f"\033[36m[INFO]\033[0m  {m}")


def warn(m):
    print(f"\033[33m[WARN]\033[0m  {m}")


def error(m):
    print(f"\033[31m[ERROR]\033[0m {m}")


def good(m):
    print(f"\033[32m[WIN]\033[0m   {m}")


def bad(m):
    print(f"\033[31m[LOSS]\033[0m  {m}")


def print_signal(signal, ind):
    emoji = {"BUY": "📈", "SELL": "📉", "CLOSE": "🔄"}.get(signal.get("action"), "⏸️")
    print("\n" + "─" * 60)
    print(f"{emoji}  AI SIGNAL: {signal.get('action')}  ({signal.get('confidence')}% confidence | "
          f"{signal.get('riskLevel')} risk | criteria: {signal.get('criteriaScore', '?')}/5)")
    print(f"💭 {signal.get('reasoning')}")
    print(f"📊 RSI: {ind.get('rsi')} | StochRSI K: {ind.get('stochRsiK')} | MACD Hist: {ind.get('macdHist')}")
    print(f"📈 Trend: {ind.get('emaTrend')} | Structure: {ind.get('marketStructure')} | Divergence: {ind.get('divergence')}")
    print(f"💰 Price: ${ind.get('price')} | ATR: {ind.get('atrPct')}% | Volume: {ind.get('volumeRatio')}x avg")
    if signal.get("keyFactors"):
        print(f"🔑 Key factors: {' • '.join(signal['keyFactors'])}")
    print("─" * 60)


def print_trade(type_, symbol, price, quantity, pnl=None):
    if pnl is not None:
        _stats["trades"] += 1
        _stats["totalPnL"] += pnl
        if pnl > 0:
            _stats["wins"] += 1
            good(f"PROFIT: +${pnl:.4f} | {symbol} {type_} @ ${price}")
        else:
            _stats["losses"] += 1
            bad(f"LOSS: -${abs(pnl):.4f} | {symbol} {type_} @ ${price}")
    else:
        info(f"TRADE: {type_} {quantity} {symbol} @ ${price}")


def print_stats(balance, open_position=None, current_price=None):
    from apex import forex
    total_value = balance
    position_note = ""
    if open_position and current_price:
        symbol = open_position.get("symbol", cfg.SYMBOL)
        unrealized = forex.pnl_usd(open_position["side"], open_position["entryPrice"],
                                   current_price, open_position["quantity"], symbol)
        total_value = balance + unrealized
        side = "LONG" if open_position["side"] == "BUY" else "SHORT"
        position_note = (f" | {side} {open_position['quantity']:,} {symbol} "
                         f"@ {open_position['entryPrice']} | PnL: {'+' if unrealized >= 0 else ''}${unrealized:.2f}")
    pnl_pct = ((total_value - _stats["startBalance"]) / _stats["startBalance"] * 100) if _stats["startBalance"] > 0 else 0
    win_rate = (_stats["wins"] / _stats["trades"] * 100) if _stats["trades"] > 0 else 0
    mode = "📝 PAPER" if cfg.PAPER_TRADING else ("🧪 PRACTICE" if cfg.OANDA_ENV == "practice" else "🔴 LIVE")
    print("\n📊 STATS:")
    print(f"   Equity: ${total_value:.2f} ({'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%){position_note}")
    print(f"   Closed trades: {_stats['trades']} | ✅ {_stats['wins']} | ❌ {_stats['losses']} | Win Rate: {win_rate:.0f}%")
    print(f"   Realized PnL: {'+' if _stats['totalPnL'] >= 0 else ''}${_stats['totalPnL']:.2f}")
    print(f"   Mode: {mode}\n")


def print_banner(balance):
    mode = "📝 PAPER TRADING (no real risk)" if cfg.PAPER_TRADING else (
        "🧪 OANDA PRACTICE" if cfg.OANDA_ENV == "practice" else "🔴 LIVE TRADING")
    print("\n" + "═" * 60)
    print("  💱 APEX FOREX BOT — AI Powered Trading")
    print(f"  Pair: {cfg.SYMBOL} | Timeframe: {cfg.TIMEFRAME}")
    print(f"  Mode: {mode}")
    print(f"  Starting balance: ${balance:.2f}")
    print(f"  Analysis interval: {cfg.LOOP_INTERVAL_MS / 60000} minutes")
    print(f"  Stop Loss: {cfg.STOP_LOSS_PIPS:g} pips | Take Profit: {cfg.TAKE_PROFIT_PIPS:g} pips | Leverage 1:{cfg.LEVERAGE:g}")
    print("═" * 60 + "\n")
