# HANDOFF — Apex Trade Bot

> **Fișier de stare partajat între agenți (Claude Code și Codex).**
> Se citește la începutul fiecărei sesiuni și se actualizează la sfârșit.
> Protocolul de ștafetă e în `AGENTS.md`.

---

# STARE CURENTĂ

**Ultima actualizare:** 2026-09-07
**Branch de lucru:** `claude/arcads-external-api-gexx7-6n4pr9`
**Teste:** 134/135 trec (`python apex-forex-bot/tests/run_all.py`) — singurul eșec
e `test_backfill_trades.py`, în zona lui Codex (fus orar), nu s-a schimbat.

---

# 🔴 CINE CE LUCREAZĂ ACUM (actualizat 2026-09-07)

Agenții lucrează **în paralel**, pe zone care nu se ating. Nu ieși din zona ta.

> **Notă:** Codex rulează în aplicația **Codex Desktop**, separat de VS Code —
> nu în panourile Claude. Trebuie să i se deschidă proiectul ca „local project"
> (folderul `proiect-codex`), altfel stă într-un folder gol.
Dacă ai terminat și vrei alt task, actualizează tabelul ăsta ÎNTÂI, apoi lucrează.

| Agent | Zona lui — NUMAI aici | Task |
|---|---|---|
| **Claude cloud** (claude.ai/code) | `public/*.html` | Rescrie limbajul: platformă de automatizare, nu „bot care câștigă" |
| **Claude local #2** (panoul liber) | `apex-forex-bot/scripts/`, `apex/cot.py` | Fix fus orar în `backfill_trades.py` — **reatribuit de la Codex** |
| **Codex Desktop** | `apex-forex-bot/apex/brokers/` | Ordine autorizate care nu se execută |
| **Claude local #1** (VS Code) | ✅ TERMINAT | ~~Contorul zilnic blocat~~ — livrat în 9add7d5, 135/135 verde |

**Regula:** dacă `git pull` îți aduce modificări în fișierele tale, oprește-te și
întreabă operatorul. Nu rezolva conflicte peste munca altui agent.

## Detaliile task-urilor

### Codex — fus orar în backfill
`_ts()` din `scripts/backfill_trades.py:78` face `.timestamp()` pe un datetime
naiv, deci îl citește ca oră **locală**. Jurnalul stochează **UTC**. În România
decalajul de 3h depășește `_TIME_SLACK_S` (90 min) → „no deal matches".
Testul `tests/test_backfill_trades.py` trece pe UTC și pică pe RO — reprodus cu
`TZ=Europe/Bucharest`.

Repară cum face deja codul în `apex/miniapp_api.py:65`:
`.replace(tzinfo=timezone.utc)` înainte de `.timestamp()`.
**Nu modifica testul — testul e corect.** Verifică și `apex/cot.py:217`
(`time.mktime` e tot oră locală).

### Codex — ordine trimise în gol
Pe 6 sept, două ordine SELL USDCHF au fost autorizate și trimise la 21:06:51 și
21:12:46 UTC (identice: 23.063 unități, SL 0.812953, TP 0.804095). În log apare
`order` + `AUTHORIZED` pentru amândouă, dar **niciun eveniment `trade`** după,
și poziția nu apare la broker. Nicio eroare logată.

Comparație — un ordin reușit arată așa (USDCAD, 21:35):
`order` → `AUTHORIZED` → ~10s → `trade  BUY USDCAD price=1.38376`.
La USDCHF, al treilea pas lipsește de două ori.

Caută în `apex/brokers/ctrader.py`, `place_order()` (linia ~978): ce se întâmplă
când brokerul respinge sau nu confirmă execuția? Se înghite excepția? Se ignoră
un cod de eroare? Un ordin care eșuează trebuie să lase urmă în log.
**Zona ta: `apex/brokers/` — atât.** Nu atinge `user_loop.py` sau `scripts/`.

### Claude local — contorul zilnic ✅ REZOLVAT (2026-09-07)
**Cauza:** nici una din cele două ipoteze — resetarea (`_reset_daily_if_needed`,
apelată din `should_stop()`) SE declanșează la fiecare tick, dar nu se persista
NICIODATĂ pe disc (doar `record_trade()` scria sesiunea, ca efect secundar).
`record_trade()` rulează ÎNAINTEA lui `should_stop()` în 6 din 9 puncte din
`user_loop.py` (liniile 1880/2249/2761/2825/3043/3272 vs. 3493) — o poziție
închisă devreme într-un tick, imediat după un restart, incrementa și persista
contorul ZILEI ANTERIOARE în loc să pornească ziua nouă de la 1. Exact tabloul
raportat: `dailyTrades: 5, lastResetDay:` trei zile în urmă.

**Fix** (`apex/strategies.py`, ~30 linii, fără atingere `public/` sau `scripts/`):
1. Reset-ul persistă imediat (`_persist_session` chemat din interiorul reset-ului).
2. `record_trade()` face rollover-ul ZILEI ÎNAINTE de a incrementa — nu mai
   depinde de ordinea apelurilor din tick.
3. `get_session()` face rollover chiar la încărcare — un cititor care nu trece
   niciodată prin `should_stop()`/`record_trade()` (dashboard-ul, `/report`)
   nu mai vede contorul zilei precedente imediat după un restart.

**Test nou:** `tests/test_daily_reset_persist.py` (RED pe codul vechi, GREEN
după fix). `test_strategies.py` și `test_loss_streak_rollover.py` — fără
regresii. Suita completă: 134/135 (singurul eșec e bug-ul de fus orar al lui
Codex, neatins).

**Următorul pas, dacă preiei aici:** niciunul — task-ul e închis. Zona e liberă
pentru un task nou.

### Claude cloud — limbajul
`public/ad.html` conține cifre **inventate** prezentate ca rezultate
(`+$191.80`, „30-Day Results", citat „+$284") și perechi crypto care nu mai
sunt produsul. Risc de chargeback și de închidere Digistore24. Se rescrie pe
execuție/control al riscului, fără promisiuni de performanță.


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
