# HANDOFF — Apex Trade Bot

> **Fișier de stare partajat între agenți (Claude Code și Codex).**
> Se citește la începutul fiecărei sesiuni și se actualizează la sfârșit.
> Protocolul de ștafetă e în `AGENTS.md`.

---

# STARE CURENTĂ

**Ultima actualizare:** 2026-09-06
**Branch de lucru:** `claude/arcads-external-api-gexx7-6n4pr9`
**Teste:** 134/134 trec (`python apex-forex-bot/tests/run_all.py`)

## Ce s-a terminat recent

Analiza jurnalului a găsit de ce pierdea botul și de unde venea `-27k`:

- **Artefacte în jurnal.** 4 rânduri din 2026-08-19 cu `balance: 470.586` (unul pe
  `US400`, index pe care platforma nici nu-l poate tranzacționa) însumând
  **-26.586**, plus XAUUSD **-779,74** pe un cont de 3.002 (26% din cont, față de
  o limită de 2,5%). **Istoricul real: 71 trade-uri, +264,16, 45,1% win, R 1:1,60, PF 1,35.**
- **Cauzele pierderilor (94% explicat):** fibonacci în regim `trending`
  (5 trade-uri, **-202,37**) și poziții ținute peste NFP (2 trade-uri, **-116,67**).
- **Patru remedii livrate 2026-09-04:** `REGIME_GATE` (default `enforce` în cod),
  `NEWS_EXIT_MIN=15` (default în cod), `MIN_EXIT_R` și `INSTITUTIONAL_GATE`
  (setate prin env pe Render — verifică valorile acolo, defaults în cod sunt
  `1.0` respectiv `shadow`).

## 🔴 URMĂTORUL PAS — nefăcut

1. **`/markartefacts` NU a fost rulat încă.** Jurnalul arată în continuare 84 de
   rânduri, iar `/report` îi spune clientului **-$27.052**, cifră falsă.
   Comanda trebuie tastată de proprietarul contului (e în `_MSG_DENY`), din
   Telegram. Scriptul echivalent: `apex-forex-bot/scripts/mark_journal_artefacts.py`
   (dry-run implicit, `--apply` scrie, e idempotent).
2. **Verifică datele de luni.** Cele patru remedii au prins doar ~6 ore de piață
   deschisă vineri 2026-09-04. Fără o săptămână de date, nu se poate spune dacă
   au funcționat.
3. **`git fetch --unshallow`** în clonele locale — clonă shallow strică `git log`
   ca mecanism de transfer de context între agenți.

## Mediu local (laptop Windows)

`pip install -r requirements.txt` eșuează pe Python 3.14: **`twisted-iocpsupport`**
(dependință a `ctrader-open-api`) nu publică wheel pentru 3.14 pe Windows, deci
cere compilator C++. Soluție: **Python 3.11 sau 3.12**, unde există wheel
precompilat. Alternativ, Visual Studio Build Tools cu workload C++.

---

# CONTEXT PERMANENT

## Ce e proiectul
- **Apex Trade Bot** by **AI Cash Systems** (owner: Alex Otvos, România).
- Bot de trading Telegram vândut ca licență one-time + site de vânzări + program de afiliere.
  - `apex-forex-bot/` — Python, bot forex **$497**.
  - `server.js` + `public/` — site Node, checkout/IPN Digistore24, livrare licențe, API afiliere.
  - Afiliații se recrutează prin marketplace-ul Digistore24 (30% comision).

> **⚠️ BROKER:** botul forex folosește **cTrader** (contul e găzduit la
> **Pepperstone** — Pepperstone e doar brokerul unde stă contul cTrader, NU o
> integrare separată). Conectarea se face prin **cTrader Open API**
> (`apex/brokers/ctrader.py`, onboarding `/ctrader`). **OANDA e opțiune LEGACY
> rămasă în cod și în textele default, dar NU se folosește** — nu "repara" botul
> spre OANDA. `_make_broker()` alege brokerul per utilizator: token cTrader →
> cTrader; altfel token OANDA → OANDA; altfel paper → Yahoo.

## Servicii Render
- `autoflow-backend` — site-ul Node (`server.js`). `/api/health` → `sale_ready:true`.
- `autoflow-backend-2` — botul forex (Python). Callback: `/api/ctrader/callback`.
- Tier gratuit: ~3 săptămâni/lună uptime, se suspendă la final de lună, revine pe 1.

## Ce e construit și live
- **Legal**: renunțare Art.16(m) UE la checkout + termeni + emailuri; fără refund;
  banner cookies; refund/chargeback → licență revocată.
- **Securitate**: `/verify-license` autoritativ pe plată; `/api/health` diagnostic.
- **Onboarding client**: welcome, link referral Binance, paper vs real, chei AI
  per utilizator (Groq/Gemini/Claude), orice pereche.
- **cTrader**: OAuth onboarding (`/ctrader`, `/ctaccount`), conector protobuf sync,
  wiring `_make_broker`. Scope configurabil prin `CTRADER_SCOPE`.
- **Copilot (10 funcții)**: explicații per trade în alerte; mod copilot
  (`/copilot on|off`, butoane approve/reject); alerte "nu tranzacționa"; news
  guard + `/news`; breaker flash-crash.
- **Market Pulse** (`/market`): volatilitate/volum/trend/momentum + sesiuni
  (Sydney/Tokyo/London/NY din ceasul UTC).
- **News**: calendar economic FMP (`NEWS_API_KEY`); feed-ul default Forex Factory
  e blocat pe IP-uri de datacenter Render.
- **Lead funnel** (`public/free.html` + `POST /api/lead`): trafic DM → ofertă
  gratuită → captare email → promo → CTA cumpărare. Păstrează ref-ul de afiliat.

## Env vars (Render)
- bot forex (`autoflow-backend-2`): `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET`,
  `CTRADER_REDIRECT_URI=https://autoflow-backend-2.onrender.com/api/ctrader/callback`,
  `CTRADER_SCOPE`.
- ambele: `NEWS_API_KEY=<cheie FMP>`.
- site (`autoflow-backend`): `JWT_SECRET=<random 40+ caractere>`.

## Convenții
- Fișiere sub 500 de linii. Teste: `apex-forex-bot/tests/run_all.py`.
- Nu comite niciodată secrete. Push doar pe branch-ul de lucru.
- Restul regulilor: `CLAUDE.md` (Claude Code) și `AGENTS.md` (Codex + ștafetă).
