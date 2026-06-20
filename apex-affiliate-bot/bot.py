"""Apex Affiliate Bot — Telegram polling + commands."""
import os
import json
import time
import threading
import requests
import store

TOKEN = os.getenv("AFFILIATE_BOT_TOKEN", "").strip()
ADMIN_IDS = [s.strip() for s in os.getenv("ADMIN_CHAT_ID", "").split(",") if s.strip()]
SITE_URL = os.getenv("SITE_URL", "https://aicashsystem.space")
COMMISSION_PCT = float(os.getenv("COMMISSION_PCT", "0.30"))

_API = f"https://api.telegram.org/bot{TOKEN}"
_update_id = 0


def _send(chat_id, text, extra=None):
    if not TOKEN:
        return
    try:
        requests.post(f"{_API}/sendMessage",
                      json={"chat_id": chat_id, "text": text,
                            "parse_mode": "HTML", **(extra or {})},
                      timeout=6)
    except Exception as e:
        print(f"[BOT] Send error: {e}")


def _is_admin(chat_id):
    return str(chat_id) in ADMIN_IDS


# ─── Handlers ─────────────────────────────────────────────

def _handle_start(chat_id, username):
    data, is_new = store.register(chat_id, username)
    link = f"{SITE_URL}/?ref={data['ref_code']}"
    if is_new:
        _send(chat_id,
              f"🎉 <b>Bun venit în programul de afiliat Apex Bot!</b>\n\n"
              f"Câștigă <b>{int(COMMISSION_PCT*100)}% comision</b> pe fiecare vânzare.\n\n"
              f"🔗 <b>Link-ul tău unic:</b>\n<code>{link}</code>\n\n"
              f"Distribuie-l pe TikTok, Instagram, YouTube și câștigă automat.\n\n"
              f"📊 /stats — statisticile tale\n"
              f"💸 /payout — solicită plata\n"
              f"❓ /help — ajutor")
    else:
        _send(chat_id,
              f"👋 <b>Ești deja înregistrat!</b>\n\n"
              f"🔗 Link-ul tău:\n<code>{link}</code>\n\n"
              f"📊 /stats — statisticile tale")


def _handle_link(chat_id):
    data = store.get(chat_id)
    if not data:
        return _send(chat_id, "❌ Nu ești înregistrat. Trimite /start.")
    link = f"{SITE_URL}/?ref={data['ref_code']}"
    _send(chat_id,
          f"🔗 <b>Link-ul tău de afiliat:</b>\n\n"
          f"<code>{link}</code>\n\n"
          f"Copiază și distribuie-l. Când cineva cumpără prin el, primești "
          f"<b>{int(COMMISSION_PCT*100)}% comision</b> automat.")


def _handle_stats(chat_id):
    data = store.get(chat_id)
    if not data:
        return _send(chat_id, "❌ Nu ești înregistrat. Trimite /start.")
    sales = data.get("sales", [])
    total_sales = len(sales)
    total_vol = sum(s.get("amount", 0) for s in sales)
    earned = data.get("total_earned", 0.0)
    paid = data.get("total_paid", 0.0)
    pending = round(earned - paid, 2)
    clicks = data.get("clicks", 0)
    cr = f"{total_sales/clicks*100:.1f}%" if clicks > 0 else "—"
    link = f"{SITE_URL}/?ref={data['ref_code']}"

    recent = ""
    for s in sorted(sales, key=lambda x: x["time"], reverse=True)[:5]:
        t = time.strftime("%d %b %H:%M", time.localtime(s["time"]))
        recent += f"\n  • {t} — ${s['amount']:.0f} → <b>+${s['commission']:.2f}</b>"

    _send(chat_id,
          f"📊 <b>STATISTICILE TALE</b>\n"
          f"━━━━━━━━━━━━━━━━━━━━\n"
          f"🔗 Cod: <code>{data['ref_code']}</code>\n"
          f"👁 Clicuri: <b>{clicks}</b>\n"
          f"🛒 Vânzări: <b>{total_sales}</b>  (CR: {cr})\n"
          f"💰 Volum total: <b>${total_vol:.2f}</b>\n\n"
          f"✅ Total câștigat: <b>${earned:.2f}</b>\n"
          f"💸 Plătit: <b>${paid:.2f}</b>\n"
          f"⏳ De primit: <b>${pending:.2f}</b>\n"
          + (f"\n📋 <b>Ultimele vânzări:</b>{recent}" if recent else "\n<i>Nicio vânzare încă.</i>") +
          f"\n\n🔗 <code>{link}</code>")


def _handle_payout(chat_id, args):
    data = store.get(chat_id)
    if not data:
        return _send(chat_id, "❌ Nu ești înregistrat. Trimite /start.")
    pending = round(data.get("total_earned", 0) - data.get("total_paid", 0), 2)
    if not args:
        _send(chat_id,
              f"💸 <b>Solicită plata</b>\n\n"
              f"De primit: <b>${pending:.2f}</b>\n"
              f"Minim: <b>$10</b>\n\n"
              f"Trimite:\n"
              f"<code>/payout paypal email@tau.com</code>\n"
              f"<code>/payout usdt adresa_wallet</code>\n"
              f"<code>/payout btc adresa_wallet</code>")
        return
    parts = args.strip().split(None, 1)
    if len(parts) < 2:
        return _send(chat_id, "❌ Format: <code>/payout paypal email@tau.com</code>")
    method, address = parts[0].lower(), parts[1]
    result = store.request_payout(chat_id, method, address)
    if isinstance(result, dict) and result.get("error") == "minimum":
        return _send(chat_id,
                     f"❌ Minim $10 pentru plată. Ai acum <b>${result['pending']:.2f}</b>.")
    if isinstance(result, dict) and result.get("error"):
        return _send(chat_id, "❌ Eroare. Încearcă din nou.")
    _send(chat_id,
          f"✅ <b>Cerere de plată trimisă!</b>\n\n"
          f"Sumă: <b>${result['amount']:.2f}</b>\n"
          f"Metodă: <b>{method.upper()}</b>\n"
          f"Adresă: <code>{address}</code>\n\n"
          f"Plata se procesează în 24-48h. Vei primi confirmare.")
    # Notifică admin
    for adm in ADMIN_IDS:
        _send(adm,
              f"💸 <b>CERERE PLATĂ AFILIAT</b>\n"
              f"ID: <code>{chat_id}</code>\n"
              f"Sumă: <b>${result['amount']:.2f}</b>\n"
              f"Metodă: {method.upper()} → <code>{address}</code>\n\n"
              f"/markpaid {chat_id} {result['amount']:.2f}")


def _handle_top(chat_id):
    if not _is_admin(chat_id):
        return _send(chat_id, "❌ Doar adminii pot vedea topul.")
    affiliates = store.all_affiliates()
    if not affiliates:
        return _send(chat_id, "📊 Niciun afiliat înregistrat.")
    lines = []
    for i, a in enumerate(affiliates[:15], 1):
        lines.append(f"{i}. @{a.get('username') or a['chat_id']} — "
                     f"{len(a.get('sales',[]))} vânzări · ${a.get('total_earned',0):.2f} câștigat")
    _send(chat_id, "🏆 <b>TOP AFILIAȚI</b>\n━━━━━━━━━━━━━━\n" + "\n".join(lines))


def _handle_markpaid(chat_id, args):
    if not _is_admin(chat_id):
        return _send(chat_id, "❌ Doar adminii.")
    parts = (args or "").strip().split()
    if len(parts) < 2:
        return _send(chat_id, "Format: <code>/markpaid CHAT_ID SUMA</code>")
    target_id, amount = parts[0], parts[1]
    try:
        amount = float(amount)
    except ValueError:
        return _send(chat_id, "❌ Sumă invalidă.")
    if store.mark_paid(target_id, amount):
        _send(chat_id, f"✅ Marcat ca plătit: ${amount:.2f} pentru <code>{target_id}</code>.")
        _send(target_id, f"✅ <b>Plata de ${amount:.2f} a fost procesată!</b>\nMulțumim!")
    else:
        _send(chat_id, "❌ Afiliat negăsit.")


def _handle_help(chat_id):
    is_adm = _is_admin(chat_id)
    text = ("📋 <b>APEX AFFILIATE BOT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "/start — înregistrare + link-ul tău\n"
            "/link — vezi link-ul tău unic\n"
            "/stats — clicuri, vânzări, comision câștigat\n"
            "/payout — solicită plata comisionului\n"
            "/help — această listă\n")
    if is_adm:
        text += ("━━━━━━━━━━━━━━━━━━━━\n"
                 "👑 <b>Admin</b>\n"
                 "/top — top afiliați\n"
                 "/markpaid ID SUMA — confirmă plată")
    _send(chat_id, text)


# ─── Poll loop ────────────────────────────────────────────

def _poll():
    global _update_id
    print(f"[AFFILIATE BOT] Polling... TOKEN={'set' if TOKEN else 'MISSING'}")
    while True:
        try:
            r = requests.get(f"{_API}/getUpdates",
                             params={"offset": _update_id, "timeout": 10,
                                     "allowed_updates": json.dumps(["message"])},
                             timeout=15)
            data = r.json()
            if not data.get("ok"):
                time.sleep(10)
                continue
            for u in data.get("result", []):
                _update_id = u["update_id"] + 1
                msg = u.get("message", {})
                raw = (msg.get("text") or "").strip()
                chat_id = msg.get("chat", {}).get("id")
                username = msg.get("from", {}).get("username", "")
                if not raw or chat_id is None:
                    continue
                first_line = raw.splitlines()[0].strip()
                cmd, _, args = first_line.partition(" ")
                cmd_l = cmd.lower().split("@")[0]
                if cmd_l == "/start":
                    _handle_start(chat_id, username)
                elif cmd_l == "/link":
                    _handle_link(chat_id)
                elif cmd_l in ("/stats", "/earnings"):
                    _handle_stats(chat_id)
                elif cmd_l == "/payout":
                    _handle_payout(chat_id, args)
                elif cmd_l == "/top":
                    _handle_top(chat_id)
                elif cmd_l == "/markpaid":
                    _handle_markpaid(chat_id, args)
                elif cmd_l == "/help":
                    _handle_help(chat_id)
        except Exception as e:
            print(f"[AFFILIATE BOT] Poll error: {e}")
        time.sleep(2)


def notify_sale(chat_id, amount, commission, product):
    """Called by webhook when a sale is recorded."""
    _send(chat_id,
          f"🎉 <b>VÂNZARE NOUĂ!</b>\n\n"
          f"Produs: <b>{product}</b>\n"
          f"Valoare: <b>${amount:.2f}</b>\n"
          f"Comisionul tău (30%): <b>+${commission:.2f}</b> 💰\n\n"
          f"Vezi toate vânzările cu /stats")


def start():
    if not TOKEN:
        print("[AFFILIATE BOT] AFFILIATE_BOT_TOKEN not set — bot disabled.")
        return
    t = threading.Thread(target=_poll, daemon=True)
    t.start()
    print("[AFFILIATE BOT] Started.")
