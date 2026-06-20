# APEX TRADE BOT — Documentație Completă

## 1. ARHITECTURA

```
Oracle Cloud VM (152.70.54.90)
└── systemd: apex-bot.service
    └── node src/index-server.js
        └── telegram-mt.js  ← polling Telegram, izolat per user
            ├── botManager.js  ← pornește/oprește bot per user
            ├── runner.js      ← tick la fiecare minut
            ├── userStore.js   ← date user criptate pe disc
            └── accessControl.js ← whitelist
```

**Un singur proces Node.js** servește toți clienții simultan.
Fiecare user are propriul state, setări, poziție, și balanță — total izolat.

---

## 2. FLOW SETUP CLIENT NOU

### Pasul 1 — Dai acces
Clientul îți trimite mesaj la bot → bot-ul îi arată ID-ul lui.
Tu faci: `/grant 123456789`
Clientul primește: "✅ Access granted! Send /start to set up your bot."

### Pasul 2 — Clientul face setup
```
/start
  → alege: 📝 Paper Trading SAU 🔴 Real Exchange
  → dacă Real: alege exchange (Binance, Bybit, OKX...)
  → trimite API Key
  → trimite API Secret
  → trimite Groq key (sau Skip)
  → DONE → apasă ▶️ Start Trading
```

### Pasul 3 — Bot activ
Bot-ul face tick la fiecare minut.
La fiecare 6 tick-uri (6 minute) trimite heartbeat în Telegram.
Când deschide/închide trade → mesaj automat.

---

## 3. COMENZI ADMIN (DOAR TU)

| Comandă | Ce face |
|---------|---------|
| `/grant 123456789` | Dă acces unui client plătitor |
| `/revoke 123456789` | Retrage accesul (bot oprit instant) |
| `/users` | Listează toți clienții cu acces |
| `/admin` | Afișează panoul admin |
| `/usage 123456789` | Raport complet: date activare, tick-uri, trade-uri → pentru Stripe dispute |
| `/deploy` | Actualizează codul botului fără SSH (pull din GitHub + restart) |

---

## 4. COMENZI UTILIZATOR (CLIENȚI)

### Navigare
| Comandă / Buton | Ce face |
|-----------------|---------|
| `/menu` sau `/m` | Afișează meniul cu butoane |
| `/status` sau `/s` | Status curent: balanță, poziție deschisă, semnal AI |
| `/config` sau `/c` | Afișează setările curente |
| `/trades` sau `/t` | Ultimele 10 trade-uri |
| `/help` | Lista tuturor comenzilor |

### Control bot
| Comandă / Buton | Ce face |
|-----------------|---------|
| `/pause` sau buton ⏸ | Oprește trading (nu închide poziția deschisă) |
| `/resume` sau buton ▶️ | Pornește trading |

### Simbol & Strategie
| Comandă | Exemplu | Ce face |
|---------|---------|---------|
| `/symbol` | `/symbol BTCUSDT` | Schimbă perechea (BTC/ETH/SOL/XRP/DOGE/ADA/BNB/AVAX) |
| `/method` | `/method auto` | Schimbă strategia |

**Strategii disponibile:**
- `auto` — AI alege singur (recomandat)
- `turtle` — Turtle Trading (breakout)
- `livermore` — Jesse Livermore (trend)
- `soros` — George Soros (macro)
- `ptj` — Paul Tudor Jones (momentum, minim 85% confidence)
- `druckenmiller` — Stanley Druckenmiller (size up pe convicție)

### Risk Management
| Comandă | Exemplu | Limită | Default |
|---------|---------|--------|---------|
| `/risk` | `/risk 5` | 0.1–10% | 5% |
| `/sl` | `/sl 1.6` | 0.1–20% | 1.6% |
| `/tp` | `/tp 3.2` | 0.1–50% | 3.2% |
| `/confidence` | `/confidence 70` | 50–99% | 62% |

### Altele
| Comandă | Ce face |
|---------|---------|
| `/groq gsk_CHEIE` | Setează cheie Groq AI personală (gratis pe console.groq.com) |
| `/keys` | Resetează cheile API exchange (dacă expiră sau se schimbă) |

---

## 5. MENIU BUTOANE

```
📊 Status    📋 Trades
💎 Symbol    ⚙️ Config
🎯 Method    ❓ Help
📈 Live Chart
▶️ Start Trading / ⏸ Pause Bot
```

Toate butoanele funcționează. Dacă un buton pare că nu face nimic, verifică:
1. Setup complet? (`/status` — dacă arată "Setup not complete" → `/start`)
2. Bot pornit? (apasă ▶️ Start Trading)

---

## 6. NOTIFICĂRI AUTOMATE BOT → CLIENT

### Heartbeat (la 6 minute)
```
💓 Tick #432  💼 $10,247.50
📭 No position
/menu for controls
```

### Trade deschis
```
🟢 LONG OPENED — BTCUSDT
💰 Entry: $67,432.10  Qty: 0.007
🛡 SL: $66,344.25  🎯 TP: $69,580.78
```

### Trade închis
```
✅ TAKE PROFIT — BTCUSDT
$67,432.10 → $69,580.78
PnL: +$14.23  💼 Balance: $10,261.73
```

### Strategy Stop (protecție automată)
```
🚨 STRATEGY STOP
• 3 consecutive losses — Seykota
/resume when conditions improve.
```

**Când se activează Strategy Stop:**
- 3 pierderi consecutive (Seykota rule)
- Pierdere zilnică > 3% (PTJ rule)
- Drawdown > 20% față de peak
- 10 trade-uri pe zi (Turtle rule)

---

## 7. MODURI: PAPER vs TESTNET vs LIVE

| Mod | Ce e | Bani reali? |
|-----|------|-------------|
| 📝 PAPER | Simulare, $100 virtual, nicio conexiune exchange | NU |
| 🔴 LIVE TESTNET | Conectat la testnet.binance.vision, $10,000 testnet | NU |
| (viitor) LIVE REAL | Binance real cu bani reali | DA |

**Testnet Binance:**
- Site separat: `testnet.binance.vision`
- Login cu cont GitHub (nu contul tău Binance normal)
- Cheile testnet NU funcționează pe Binance real și viceversa
- Balanță automată $10,000 USDT testnet

---

## 8. FLOW DEPLOY (UPDATE COD)

### Metoda 1 — Din Telegram (după primul deploy reușit)
```
Tu: /deploy
Bot: 🔄 Deploying latest code... (30 sec)
Bot: ✅ Deploy successful! Press ▶️ Start Trading when ready.
```
Funcționează pentru orice update viitor. Nu mai ai nevoie de SSH.

### Metoda 2 — GitHub Actions (prima dată sau dacă /deploy pică)
1. GitHub → Actions → **Deploy Apex Trade Bot** → Run workflow
2. Introduci IP: `152.70.54.90`
3. Aștepți 2-3 minute → verde = succes

### Dacă SSH nu răspunde (RAM plin pe VM)
1. Oracle Cloud Console → Compute → Instances → Stop → Start
2. Aștepți 60 secunde
3. Rulezi GitHub Actions deploy

---

## 9. RAPORT STRIPE (ANTI-REFUND)

Dacă un client cere refund pe Stripe, folosești `/usage ID`:

```
📊 USAGE REPORT — Client 123456789
━━━━━━━━━━━━━━━━━━━━
📅 Activated: 15/06/2025, 14:32:01
⏱ Days active: 5
🔢 Total ticks (minutes): 7,200
📈 Total trades executed: 47
🕐 Last active: 20/06/2025, 11:45:00
💼 Balance: $10,247.50
📊 Mode: BINANCE Live
```

**7,200 ticks = 7,200 minute de serviciu livrat** — dovadă solidă că serviciul a funcționat.

---

## 10. TROUBLESHOOTING

### "Butoanele nu fac nimic"
- Setup incomplet? → trimite `/start`
- Bot pauzat? → apasă ▶️ Start Trading
- Bot oprit de Strategy Stop? → `/resume`

### "Balance $0.00"
- Normal la setup nou cu LIVE TESTNET — apasă ▶️ Start Trading, botul preia balanța de pe exchange la primul tick

### "Bot ACTIVE dar nu mai primesc mesaje"
- Bot-ul face tick la 1 minut, heartbeat la 6 minute
- Dacă nu vine nimic în 10+ minute → `/status` pentru a vedea ultimul tick
- Dacă ultimul tick e de ore → `/deploy` din Telegram

### "Groq error / key invalid"
- Groq key expirată → obții altă cheie gratuită pe console.groq.com
- Trimiți: `/groq gsk_CHEIA_NOUA`
- Bot-ul continuă cu semnal de bază până se setează cheia nouă

### "API keys invalid" (testnet Binance)
- Verifici că cheile sunt de pe `testnet.binance.vision` (nu binance.com)
- Dacă expiră → `/keys` pentru a le re-introduce

### VM-ul nu răspunde
- Oracle Cloud Console → Stop → Start → aștepți 60s
- Systemd repornește botul automat după reboot
- 2GB swap instalat → RAM nu se mai umple

---

## 11. VARIABILE DE MEDIU (.env pe VM)

```env
TELEGRAM_BOT_TOKEN=    # de la @BotFather
GROQ_API_KEY=          # cheie server fallback (gratis pe console.groq.com)
MASTER_KEY=            # cheie AES-256 pentru criptarea cheilor API ale clienților
BINANCE_TESTNET=true   # true = toți userii pe testnet, false = live Binance
NODE_ENV=production
```

---

## 12. FIȘIERE IMPORTANTE PE VM

```
/opt/apex-bot/apex-trade-bot/
├── src/
│   ├── telegram-mt.js    ← handler principal
│   ├── runner.js          ← logică trading
│   ├── botManager.js      ← start/stop per user
│   ├── userStore.js       ← stocare date user
│   └── accessControl.js   ← whitelist
├── .env                   ← variabile mediu
└── /tmp/apex-users/       ← fișiere JSON per user (date criptate)

/var/log/apex-bot.log      ← logs bot (systemd)
/etc/systemd/system/apex-bot.service ← config restart automat
```

**Verifici logs pe VM:**
```bash
tail -50 /var/log/apex-bot.log
systemctl status apex-bot
```
