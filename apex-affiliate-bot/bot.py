"""Apex Affiliate Bot — Telegram front-end for the affiliate program.

Affiliates sign up on the site (name + email) and are handed off here via a
signed deep-link. This bot links their Telegram chat to their affiliate account
on the main server, hands them their referral link, and shows live earnings.
All data lives on the main server (Supabase) — this bot is just the front-end.
"""
import os
import time
import requests

TOKEN = os.getenv("AFFILIATE_BOT_TOKEN", "").strip()
SITE_URL = os.getenv("SITE_URL", "https://aicashsystem.space").rstrip("/")
SECRET = os.getenv("AFFILIATE_BOT_SECRET", "apex-affiliate-bridge")

_API = f"https://api.telegram.org/bot{TOKEN}"
_update_id = 0
SIGNUP = f"{SITE_URL}/affiliate.html"


def _send(chat_id, text, extra=None):
    if not TOKEN:
        return
    try:
        requests.post(f"{_API}/sendMessage",
                      json={"chat_id": chat_id, "text": text,
                            "parse_mode": "HTML", "disable_web_page_preview": True,
                            **(extra or {})},
                      timeout=8)
    except Exception as e:
        print(f"[BOT] send error: {e}")


def _money(cents):
    try:
        return f"${cents / 100:.2f}"
    except Exception:
        return "$0.00"


def _api_link(token, chat_id):
    r = requests.post(f"{SITE_URL}/api/affiliates/telegram-link",
                      json={"token": token, "chatId": chat_id, "secret": SECRET}, timeout=12)
    return r.json()


def _api_stats(chat_id):
    r = requests.post(f"{SITE_URL}/api/affiliates/telegram-stats",
                      json={"chatId": chat_id, "secret": SECRET}, timeout=12)
    return r.json()


def _welcome(chat_id, name, link):
    first = (name or "").split(" ")[0] or "creator"
    _send(chat_id,
          f"🎉 <b>You're connected, {first}!</b>\n\n"
          f"Here is your referral link — share it anywhere:\n\n"
          f"🔗 <code>{link}</code>\n\n"
          f"Anyone who buys the crypto ($297) or forex ($497) bot through it counts as your sale, "
          f"and you earn <b>30%</b> commission.\n\n"
          f"I'll ping you the moment someone buys. Check anytime:\n"
          f"• /stats — your earnings\n"
          f"• /link — your referral link\n"
          f"• /help")


def _show_stats(chat_id):
    try:
        d = _api_stats(chat_id)
    except Exception as e:
        _send(chat_id, f"⚠️ Couldn't reach the server. Try again in a moment.\n<code>{e}</code>")
        return
    if d.get("error"):
        _send(chat_id, "⚠️ Something went wrong. Try again shortly.")
        return
    if not d.get("linked"):
        _send(chat_id, f"You're not connected yet. Sign up here, then tap the Telegram button:\n{SIGNUP}")
        return
    avail, pend, paid = d.get("availableCents", 0), d.get("pendingCents", 0), d.get("paidCents", 0)
    recent = d.get("recent", [])
    lines = [
        "📊 <b>Your earnings</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💸 Sales: <b>{d.get('totalSales', 0)}</b>  ·  Rate: <b>{d.get('commissionPercent', 30)}%</b>",
        f"🟢 Available: <b>{_money(avail)}</b>",
        f"⏳ Pending: <b>{_money(pend)}</b>  <i>(matures after {d.get('refundWindowDays', 14)} days)</i>",
        f"✅ Paid out: <b>{_money(paid)}</b>",
    ]
    if recent:
        lines.append("\n<b>Recent sales</b>")
        for s in recent:
            prod = "Forex $497" if s.get("product") == "apex-forex" else "Crypto $297"
            tag = "↩️ refunded" if s.get("refunded") else ("✅ paid" if s.get("paid") else "⏳ pending")
            lines.append(f"• {prod} — <b>{_money(s.get('commission', 0))}</b>  {tag}")
    lines.append(f"\n🔗 <code>{d.get('link')}</code>")
    lines.append(f"\n<i>Minimum payout {_money(d.get('minPayoutCents', 5000))}. Request payouts from the site.</i>")
    _send(chat_id, "\n".join(lines))


def _show_link(chat_id):
    try:
        d = _api_stats(chat_id)
    except Exception:
        _send(chat_id, "⚠️ Couldn't reach the server. Try again shortly.")
        return
    if not d.get("linked"):
        _send(chat_id, f"You're not connected yet. Sign up here first:\n{SIGNUP}")
        return
    _send(chat_id, f"🔗 Your referral link:\n\n<code>{d.get('link')}</code>\n\nShare it anywhere — you earn 30% on every sale.")


def _handle(msg):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    low = text.lower()

    if low.startswith("/start"):
        parts = text.split(maxsplit=1)
        token = parts[1].strip() if len(parts) > 1 else ""
        if token:
            try:
                d = _api_link(token, chat_id)
            except Exception as e:
                _send(chat_id, f"⚠️ Couldn't connect right now. Try again.\n<code>{e}</code>")
                return
            if d.get("ok"):
                _welcome(chat_id, d.get("name", ""), d.get("link", ""))
            elif d.get("error") == "invalid token":
                _send(chat_id, f"That link looks invalid or expired. Sign up again here:\n{SIGNUP}")
            else:
                _send(chat_id, f"Couldn't connect your account. Sign up here first:\n{SIGNUP}")
        else:
            try:
                d = _api_stats(chat_id)
            except Exception:
                d = {}
            if d.get("linked"):
                _welcome(chat_id, d.get("name", ""), d.get("link", ""))
            else:
                _send(chat_id,
                      "👋 <b>Apex Affiliate</b>\n\nTo get your referral link and track sales, "
                      f"sign up here, then tap the Telegram button:\n{SIGNUP}")
        return

    if low.startswith("/stats") or low.startswith("/earnings"):
        _show_stats(chat_id); return
    if low.startswith("/link"):
        _show_link(chat_id); return
    if low.startswith("/help"):
        _send(chat_id,
              "🤖 <b>Apex Affiliate Bot</b>\n\n"
              "• /stats — your earnings & recent sales\n"
              "• /link — your referral link\n"
              "• /help — this message\n\n"
              f"Not connected yet? Sign up: {SIGNUP}")
        return

    _send(chat_id, "Send /stats for your earnings or /link for your referral link. /help for more.")


def _poll_once():
    global _update_id
    try:
        r = requests.get(f"{_API}/getUpdates",
                         params={"offset": _update_id + 1, "timeout": 25}, timeout=30)
        for upd in r.json().get("result", []):
            _update_id = upd["update_id"]
            msg = upd.get("message") or upd.get("edited_message")
            if msg and "text" in msg:
                try:
                    _handle(msg)
                except Exception as e:
                    print(f"[BOT] handle error: {e}")
    except Exception as e:
        print(f"[BOT] poll error: {e}")
        time.sleep(3)


def run():
    if not TOKEN:
        print("[BOT] AFFILIATE_BOT_TOKEN missing — bot disabled.")
        return
    print(f"[APEX AFFILIATE BOT] Polling started. Site: {SITE_URL}")
    while True:
        _poll_once()


if __name__ == "__main__":
    run()
