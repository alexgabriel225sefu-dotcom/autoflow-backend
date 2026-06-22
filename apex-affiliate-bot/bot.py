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
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "7585109158").strip()

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


def _api_admin_list(chat_id):
    r = requests.post(f"{SITE_URL}/api/affiliates/admin-list",
                      json={"chatId": chat_id, "secret": SECRET}, timeout=15)
    return r.json()


def _welcome(chat_id, name, link):
    first = (name or "").split(" ")[0] or "creator"
    _send(chat_id,
          f"👋 <b>Welcome to the Apex Affiliate Program, {first}!</b>\n\n"
          f"You're all set up and ready to earn. 🚀\n\n"
          f"Every time someone buys through your link, you earn <b>30% commission</b>:\n"
          f"• <b>$89.10</b> on the Crypto bot ($297)\n"
          f"• <b>$149.10</b> on the Forex bot ($497)\n\n"
          f"💸 I'll ping you the <b>moment</b> someone buys, so you never miss a sale.\n\n"
          f"Anytime you want, just send:\n"
          f"• /stats — your live earnings\n"
          f"• /link — your referral link\n"
          f"• /help — all commands\n\n"
          f"Let's get you paid, {first}. 💰")
    # Send link as a separate message so it's easy to copy on mobile
    _send(chat_id, f"🔗 <b>Your referral link</b> (hold to copy):\n\n{link}")


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
    lines.append(f"\n<i>Minimum payout {_money(d.get('minPayoutCents', 5000))}. Request payouts from the site.</i>")
    _send(chat_id, "\n".join(lines))
    _send(chat_id, f"🔗 Your link (hold to copy):\n\n{d.get('link')}")


def _show_link(chat_id):
    try:
        d = _api_stats(chat_id)
    except Exception:
        _send(chat_id, "⚠️ Couldn't reach the server. Try again shortly.")
        return
    if not d.get("linked"):
        _send(chat_id, f"You're not connected yet. Sign up here first:\n{SIGNUP}")
        return
    _send(chat_id, f"🔗 Your referral link (hold to copy):\n\n{d.get('link')}\n\nShare it anywhere — you earn 30% on every sale.")


def _show_admin(chat_id):
    try:
        d = _api_admin_list(chat_id)
    except Exception as e:
        _send(chat_id, f"⚠️ Couldn't reach the server.\n<code>{e}</code>")
        return
    if d.get("error") == "not admin":
        _send(chat_id, "⛔ Not authorised.")
        return
    if d.get("error"):
        _send(chat_id, f"⚠️ Server error: {d['error']}")
        return
    affs = d.get("affiliates", [])
    total_affiliates = len(affs)
    total_sales = sum(a["sales"]["total"] for a in affs)
    total_paid = sum(a["sales"]["paid"] for a in affs)
    total_pending = sum(a["sales"]["pending"] for a in affs)
    lines = [
        "🛡️ <b>Admin Panel</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"👥 Affiliates: <b>{total_affiliates}</b>  |  📦 Sales: <b>{total_sales}</b>",
        f"💸 Paid out: <b>{_money(total_paid)}</b>  |  ⏳ Pending: <b>{_money(total_pending)}</b>",
        "",
    ]
    for a in affs[:20]:
        s = a["sales"]
        status_icon = "🟢" if a.get("status") == "active" else "🔴"
        name = (a.get("name") or a.get("email") or a.get("code") or "?")[:24]
        line = (f"{status_icon} <b>{name}</b> — {s['total']} sale(s)"
                f"  💵 {_money(s['paid'])} paid  ⏳ {_money(s['pending'])} pend")
        if s.get("refunded"):
            line += f"  ↩️ {s['refunded']} refund(s)"
        lines.append(line)
    if total_affiliates > 20:
        lines.append(f"\n<i>…and {total_affiliates - 20} more. Full list on the site.</i>")
    _send(chat_id, "\n".join(lines))


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
    if low.startswith("/admin"):
        if ADMIN_CHAT_ID and str(chat_id) == ADMIN_CHAT_ID:
            _show_admin(chat_id)
        else:
            _send(chat_id, "⛔ Not authorised.")
        return
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


def _clear_webhook():
    """Remove any stale webhook so getUpdates (long polling) works.

    The previous affiliate bot ran in webhook mode on the same token. If that
    webhook is still registered, Telegram blocks getUpdates with a 409 and the
    bot silently receives nothing. Deleting it on startup makes polling work.
    """
    try:
        r = requests.get(f"{_API}/deleteWebhook",
                         params={"drop_pending_updates": "false"}, timeout=10)
        print(f"[BOT] deleteWebhook -> {r.json()}")
    except Exception as e:
        print(f"[BOT] deleteWebhook error: {e}")


def run():
    if not TOKEN:
        print("[BOT] AFFILIATE_BOT_TOKEN missing — bot disabled.")
        return
    _clear_webhook()
    print(f"[APEX AFFILIATE BOT] Polling started. Site: {SITE_URL}")
    while True:
        _poll_once()


if __name__ == "__main__":
    run()
