"""Telegram alerts + interactive command polling (port of telegram.js).

Polling runs in a background daemon thread. Authorized to TELEGRAM_CHAT_ID only.
"""
import time
import json
import threading
import requests
from apex import config as cfg

TOKEN = cfg.TELEGRAM_BOT_TOKEN
CHAT_ID = cfg.TELEGRAM_CHAT_ID
DASHBOARD_URL = cfg.DASHBOARD_URL
_API = f"https://api.telegram.org/bot{TOKEN}"

_get_dash = lambda: None
_exchange = None
_update_id = 0


def send(text, extra=None):
    if not TOKEN or not CHAT_ID:
        return
    try:
        requests.post(f"{_API}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", **(extra or {})}, timeout=6)
    except Exception as e:
        print(f"[TELEGRAM] Send error: {e}")


def send_to(chat_id, text, extra=None):
    if not TOKEN:
        return
    try:
        requests.post(f"{_API}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", **(extra or {})}, timeout=6)
    except Exception as e:
        print(f"[TELEGRAM] Send error: {e}")


def mini_chart(closes):
    n = min(len(closes), 24)
    sl = closes[-n:]
    lo, hi = min(sl), max(sl)
    rng = hi - lo or 1
    blocks = "▁▂▃▄▅▆▇█"
    return "".join(blocks[min(7, int((c - lo) / rng * 8))] for c in sl)


def _dashboard_keyboard():
    if not DASHBOARD_URL:
        return {}
    return {"reply_markup": json.dumps(
        {"inline_keyboard": [[{"text": "📊 Live Dashboard", "web_app": {"url": DASHBOARD_URL}}]]})}


def _build_status(dash, chart=""):
    sb = dash.get("startBalance", 0)
    pnl_pct = ((dash.get("balance", 0) - sb) / sb * 100) if sb > 0 else 0.0
    sign = "+" if pnl_pct >= 0 else ""
    trades = dash.get("trades", [])
    wins = sum(1 for t in trades if t.get("win"))
    total = len(trades)
    win_rate = f"{wins / total * 100:.0f}%" if total else "—"
    chart_line = (f"\n<code>{chart}</code>  <b>${dash.get('currentPrice', 0):.4f}</b>") if chart else ""
    pos_line = "📭 No open position"
    if dash.get("openPosition"):
        op = dash["openPosition"]
        d = "🟢 LONG" if op["side"] == "BUY" else "🔴 SHORT"
        pnl = op.get("currentPnl", 0)
        pos_line = (f"{d} <b>{op['symbol']}</b>\n  Entry: ${op['entryPrice']}  "
                    f"SL: ${(op.get('stopLoss') or 0):.4f}\n  PnL: <b>{'+' if pnl >= 0 else ''}${pnl:.4f}</b>")
    return (f"⚡ <b>APEX TRADE BOT</b>  {dash.get('mode', '')} · {dash.get('exchange', '')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance: <b>${dash.get('balance', 0):.2f}</b>  ({sign}{pnl_pct:.2f}%){chart_line}\n\n"
            f"{pos_line}\n\n"
            f"📈 {total} trades · {wins}W/{total - wins}L · Win: {win_rate}\n"
            f"⏱️ Last tick: {dash.get('lastTick', '—')}")


def _handle_status(chat_id):
    dash = _get_dash()
    if not dash or not dash.get("exchange"):
        return send_to(chat_id, "⏳ Bot starting, please wait...")
    chart = ""
    if _exchange:
        try:
            candles = _exchange.get_candles(dash.get("currentSymbol"), "5m", 24)
            chart = mini_chart([c["close"] for c in candles])
        except Exception:
            pass
    send_to(chat_id, _build_status(dash, chart), _dashboard_keyboard())


_HELP = ("📋 <b>Commands:</b>\n"
         "/status — live snapshot\n"
         "/help — this list")


def _poll_loop():
    global _update_id
    while True:
        try:
            r = requests.get(f"{_API}/getUpdates",
                             params={"offset": _update_id, "timeout": 10, "allowed_updates": json.dumps(["message"])},
                             timeout=15)
            for u in r.json().get("result", []):
                _update_id = u["update_id"] + 1
                msg = u.get("message", {})
                text = (msg.get("text") or "").strip().lower()
                chat_id = msg.get("chat", {}).get("id")
                if not text or chat_id is None:
                    continue
                if str(chat_id) != str(CHAT_ID):
                    continue
                if text in ("/status", "/s"):
                    _handle_status(chat_id)
                elif text == "/help":
                    send_to(chat_id, _HELP)
        except Exception:
            pass
        time.sleep(2)


def start_polling(get_dash, exchange):
    global _get_dash, _exchange
    if not TOKEN or not CHAT_ID:
        return
    _get_dash = get_dash
    _exchange = exchange
    threading.Thread(target=_poll_loop, daemon=True).start()
    print("[TELEGRAM] Command polling started. Try /status in your chat.")


def alert_open(side, symbol, price, quantity, stop_loss, take_profit, druck_mult=1.0):
    d = "🟢 LONG" if side == "BUY" else "🔴 SHORT"
    mult = f"\n📐 <b>Druckenmiller:</b> ×{druck_mult:.2f}" if druck_mult != 1.0 else ""
    send(f"{d} <b>OPENED — {symbol}</b>\n💰 @ ${price}  Qty: {quantity}\n"
         f"🛡 SL: ${stop_loss:.5f}\n🎯 TP: ${take_profit:.5f}{mult}", _dashboard_keyboard())


def alert_close(reason, symbol, side, entry_price, close_price, pnl, balance):
    icons = {"TAKE_PROFIT": "🎯 TAKE PROFIT", "STOP_LOSS": "🛑 STOP LOSS", "AI_CLOSE": "🤖 AI CLOSE"}
    d = "LONG" if side == "BUY" else "SHORT"
    send(f"{'✅' if pnl > 0 else '❌'} <b>{icons.get(reason, reason)} — {symbol}</b>\n"
         f"📊 {d}  ${entry_price} → ${close_price}\n"
         f"💵 PnL: <b>{'+' if pnl >= 0 else ''}${pnl:.4f}</b>\n💼 Balance: ${balance:.4f}", _dashboard_keyboard())


def alert_stop(reasons):
    send("🚨 <b>STRATEGY STOP</b>\n" + "\n".join(f"• {r}" for r in reasons))


def alert_filtered(action, livermore, turtle):
    send(f"⚡ <b>SIGNAL FILTERED</b>\nAI: {action} | Livermore: {livermore} | Turtle: {turtle}\n"
         f"<i>PTJ: Play defense</i>")


def alert_start(symbol, timeframe, balance, mode):
    send(f"🚀 <b>APEX TRADE BOT STARTED</b>\n📊 {symbol} | {timeframe} | ${balance:.2f}\n⚙️ {mode}\n"
         + (f"🌐 Dashboard: {DASHBOARD_URL}\n" if DASHBOARD_URL else "")
         + "<i>Send /status for a live snapshot</i>", _dashboard_keyboard())


def alert_heartbeat(tick_count, balance, open_position, current_price):
    pos_line = "📭 No position"
    if open_position and current_price:
        d = "LONG" if open_position["side"] == "BUY" else "SHORT"
        pnl = ((current_price - open_position["entryPrice"]) * open_position["quantity"]
               if open_position["side"] == "BUY"
               else (open_position["entryPrice"] - current_price) * open_position["quantity"])
        pos_line = (f"{'🟢' if open_position['side'] == 'BUY' else '🔴'} {d} <b>{open_position['symbol']}</b> "
                    f"@ ${open_position['entryPrice']}\nPnL: <b>{'+' if pnl >= 0 else ''}${pnl:.4f}</b>")
    send(f"💓 <b>ACTIVE</b>  tick #{tick_count}\n💼 Balance: ${balance:.4f}\n{pos_line}\n"
         f"<i>/status for details</i>", _dashboard_keyboard())
