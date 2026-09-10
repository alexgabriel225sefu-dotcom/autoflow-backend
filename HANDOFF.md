# 🤝 PREDARE — Apex4Traders v2 (2026-09-09)

**Ramura asta (`handoff/apex4traders-v2`) NU declanșează niciun deploy.**
Verificat: toate cele trei servicii Render urmăresc exclusiv
`claude/arcads-external-api-gExX7`, iar fiecare workflow GitHub listează ramuri
explicite. Nimic nu prinde această ramură.

**Nu s-a atins sistemul care tranzacționează.** Această ramură conține doar
documente.

## Ce declanșează ce — verificat, nu presupus

| Ramură | Ce pornește la push |
|---|---|
| `claude/arcads-external-api-gExX7` | **Render × 2 (auto-deploy)** + backtest, docker-publish, railway-×4, tuning |
| `claude/arcads-external-api-gexx7-6n4pr9` | doar `tests.yml` — CI, fără deploy |
| `main` | `docker-publish.yml` — publică imagine Docker |
| **`handoff/apex4traders-v2`** | **nimic** |

## Bază

Commit `1bea52568bf8c14ae09f17a3a911bc7e52f5dead` — identic cu arhiva
`apex-platform-20260909.zip` analizată de Codex. Arborele de lucru era curat;
**zero diferențe** față de versiunea analizată, deci constatările lui se
aplică fără ajustare.

## Arhitectura propusă

**`docs/ARCHITECTURE_V2.md`** — straturi, ce reutilizăm / adaptăm / construim,
cele cinci contracte, și constatările verificate în cod.

## Împărțirea propusă — NU a început

| Agent | Zonă |
|---|---|
| **Claude Code** | interfață și experiența de configurare |
| **Codex** | motorul de reguli, validarea, testele |

**Condiție de pornire:** cele cinci contracte din `ARCHITECTURE_V2.md §6`
agreate. Până atunci nimeni nu scrie cod de platformă.

## Conflict cu protocolul actual — de semnalat, nu de rezolvat unilateral

`AGENTS.md` descrie ștafeta pe **o singură ramură partajată**, cu un agent
activ o dată. Direcția nouă cere **ramuri separate, în paralel**. Sunt reguli
diferite și nu am modificat `AGENTS.md` ca să pretind că schimbarea e aprobată.

Propunerea, de confirmat de operator: ramuri separate pe zonă
(`feat/rules-engine`, `feat/config-ui`), amândouă izolate de deploy,
integrate prin PR. `AGENTS.md` se actualizează **după** confirmare.

## Ce rămâne valabil din protocolul existent

- `gates.authorize_order` / `authorize_close` rămân singurele porți spre broker.
- Nu se modifică `PAPER_TRADING`, `CTRADER_ENV`, `BROKER`.
- Testele în `tests/`, suita completă verde înainte de commit.
- Nu se comută `EV_GATE_MODE` — decizia operatorului.

---

# ✅ A — IMPLEMENTAT pe `feat/no-silent-strategy-substitution` (fără deploy)

Ordinea confirmată A → B → C. **A e gata; B și C nu au început.**

`apex/control_actions.py` — `coerce_setting()` validează acum și VALOAREA, nu
doar tipul, pentru `strategy`, `symbol`, `timeframe`. `automation` era deja
validat și rămâne neschimbat. Test nou: `tests/test_setting_value_validation.py`
(42 verificări, 12/12 mutanți omorâți, 0 supraviețuitori).

Fișiere atinse: `apex/control_actions.py`, `apex/forex.py` (+`TIMEFRAMES`),
`tests/test_setting_value_validation.py`. **Nu am atins** `gates.py`, setările
de mediu, `public/` sau `apex/brokers/ctrader.py`.

Suita completă: 143/143.

## Trei devieri de la specificație — verificate direct, nu presupuse

1. **`| {"auto"}` a fost specificat, scris, apoi ȘTERS.** Măsurat: registrul are
   17 id-uri și e un SUPERSET strict al lui `STRATEGY_MODES` (10). `auto` e el
   însuși un modul înregistrat, deci al treilea termen e accesibil doar dacă
   registrul e gol ȘI `auto` a ieșit din `STRATEGY_MODES`. Niciun mutant nu l-a
   putut omorî. L-am scos în loc să scriu un test artificial care să-l justifice.
   `| set(ai.STRATEGY_MODES)` a rămas — acela E omorât de un mutant, fiindcă
   testul înlocuiește `available()` cu `[]` (scenariul reordonării importurilor).

2. **`symbol` nu e o listă, e un predicat** — `forex.is_tradeable()`. Aceeași
   funcție e deja folosită de `user_loop.py:1526-1532`, care curăță simbolurile
   străine la pornirea buclei. Deci A nu inventează o regulă: mută una existentă
   mai devreme, la scriere. `US400` (instrumentul din rândurile-artefact de −26k)
   și `GBPJPY` sunt respinse.

3. **Nu pot citi `_period()` direct din `control_actions.py`.** Prima versiune
   îl importa; `tests/test_failure_matrix.py` a picat imediat pe invariantul
   „niciun modul din afara nucleului de tranzacționare nu importă direct un
   broker". Testul are dreptate și e exact despre acest modul —
   `control_actions.py` E interfața de operator, adică fix cea pe care regula
   o ține departe de broker. **Nu am slăbit testul.** Am inversat dependența:
   setul stă acum în `apex/forex.py::TIMEFRAMES` (modulul care spune deja ce
   tranzacționează platforma și pe care `control_actions` îl importa oricum
   pentru predicatul de simbol), iar sincronizarea cu `_period()` e asertată
   în fișierul de test — un test nu e legat de invariant, deci acolo
   comparația se poate face cu autoritatea reală. Mutanți verificați în ambele
   direcții: și scoaterea unui timeframe din oglindă, și adăugarea unuia pe
   care brokerul nu-l are, pică testul.

   Notă: regula caută șirul literal `brokers.ctrader`, deci până și un COMENTARIU
   care îl menționa o încălca. Comentariile sunt reformulate.

4. **Ordinea din mesajul de eroare contează.** `apex/control.py:532` taie
   mesajul la 300 de caractere înainte ca apelantul să-l vadă, iar lista de
   strategii are deja ~200. Valoarea respinsă e acum PRIMA, lista ultima — altfel
   înregistrarea câtorva strategii noi ar fi început să taie exact partea care
   spune ce a fost greșit. Testat la limita reală, nu la una comodă.

## Ce nu am schimbat, deliberat

- **Cazul literelor la `symbol`.** `eurusd` se stochează ca `eurusd`.
  `brokers/ctrader.py:80` face uppercase și scoate separatorii înainte de
  căutarea simbolului, iar harta de la `:477` e cheiată la fel — deci nu e
  nevoie de normalizare, iar a o adăuga ar fi o schimbare de comportament în
  afara domeniului lui A.
- **Chei necunoscute trec în continuare neatinse.** E un tabel de validare, nu
  o listă de blocare.

## Am verificat și celelalte chei — trei e numărul corect

Auditul spunea „3 din 16 chei". Am recalculat din sursă: `_SETTABLE` are 30 de
chei, iar după scăderea celor acoperite de `_BOOL/_LIST/_INT/_FLOAT/_ENUM`
rămân neverificate `strategy`, `symbol`, `timeframe` **plus `exit_mode` și
`style`**. Le-am urmărit pe ultimele două înainte de a decide:

- **`exit_mode`** — `user_loop.py:1127` îl pune în cfg ca `EXIT_MODE`, și
  `EXIT_MODE` **nu e citit nicăieri** în tot codul. Comportamentul real de
  ieșire vine din `trailing` (bool, deja validat) și `breakeven_r` (float, deja
  validat), pe care `builder.py` le scrie odată cu el. O valoare greșită e
  inertă, nu substituită.
- **`style`** — folosit doar de onboarding: `bool(u.get("style"))` ca test de
  completitudine și `.title()` ca etichetă. Nu ajunge la nicio decizie de
  tranzacționare.

Deci niciuna nu are un consumator care substituie un COMPORTAMENT, care e
criteriul lui A. Rămân nevalidate deliberat, nu din omisiune. Dacă `EXIT_MODE`
se conectează vreodată la buclă, intră în același tabel.

## Ce urmează (neînceput)

- **B** — `user_loop.py::_rule_signal()`: modul absent → HOLD care numește
  strategia cerută.
- **C (C-HOLD)** — `ai.py:1053-1055`: mod necunoscut → HOLD explicit, fără
  substituție cu mean_reversion.
- Cele 10 teste marcate „în risc" — de actualizat deliberat la B/C.

---

# 🛑 CODEX E INDISPONIBIL — cotă epuizată 2026-09-09 ~17:45 UTC

Codex a lovit limita de utilizare în mijlocul task-ului („You've hit your usage
limit"). Are ~158 de linii **necomise** pe laptop, care dublează limitatorul de
rată deja livrat în `2d1517c`. **Nu se împing** — versiunea de pe branch e
verde, 139/139, verificată pe două mutații.

Zona `apex/brokers/` e liberă. **Claude cloud o preia** și continuă cu pasul 2
din `docs/CTRADER_CAPABILITIES.md`: `guaranteedStopLoss` + `slippageInPoints`.

---

# 🛑 CODEX — LIMITATORUL DE RATĂ E DEJA FĂCUT, OPREȘTE-TE

Ai revendicat pasul 1 la `930682e`. Claude cloud îl terminase deja și îl împinge
în `8b7690b` — **suita e verde, 139/139**, cu test verificat pe două mutații.
Vina e a lui Claude cloud: n-a revendicat în tabel înainte să înceapă, exact
regula scrisă mai jos.

**Nu-l reface.** Trage ultima versiune și ia pasul **2** din
`docs/CTRADER_CAPABILITIES.md`: `guaranteedStopLoss` + `slippageInPoints`.
Sunt câmpuri pe `ProtoOANewOrderReq`, mesaj pe care conectorul îl trimite deja.

Ce e livrat: fereastră glisantă, două bugete (5/s istoric, 50/s restul), câte o
pereche per conexiune, iar așteptarea se ia **înainte** de lock-ul pe socket.

---

# HANDOFF — Apex Trade Bot

> **Fișier de stare partajat între agenți (Claude Code și Codex).**
> Se citește la începutul fiecărei sesiuni și se actualizează la sfârșit.
> Protocolul de ștafetă e în `AGENTS.md`.

---

# STARE CURENTĂ

**Ultima actualizare:** 2026-09-07
**Branch de lucru:** `claude/arcads-external-api-gexx7-6n4pr9`
**Teste:** suita completă `python apex-forex-bot/tests/run_all.py` e verde
(fus orar rezolvat de Claude cloud; a se reverifica numărul exact după acest merge).

---

# 📘 CE POATE FACE cTRADER — `docs/CTRADER_CAPABILITIES.md`

Harta completă a API-ului, din introspecție directă a bibliotecii instalate.
**40 de cereri disponibile, 15 folosite. 23 de câmpuri de ordin, 8 folosite.
6 tipuri de ordine, 1 folosit.**

Citește-o înainte să propui ceva pe partea de broker. Conține câmpurile exacte
ale fiecărei cereri și ordinea de lucru recomandată. Prima poziție e
**limitatorul de rată** — conectorul nu are niciunul, iar cTrader dă 5 cereri
istorice/secundă per conexiune indiferent de câți clienți.

---

# ⚠️ ÎNAINTE DE URMĂTORUL DEPLOY — citește asta

Fixul C3 schimbă comportamentul **contului tău**, nu doar al clienților viitori.

`automation.mode()` întorcea `"full"` când nu era setat niciun câmp. Contul
proprietarului (7585109158) **nu are nici `automation`, nici `copilot`** — deci
rula pe `full` prin exact acest fallback. După deploy va rula pe `approval`:
botul va cere aprobare pentru fiecare intrare în loc să deschidă singur.

**O singură comandă îl aduce înapoi:** `/automation full` în Telegram.
Dă-o după deploy, altfel botul pare că „s-a oprit din tranzacționat".

Conturile care au `copilot` setat explicit nu sunt afectate — `False` rămâne
o decizie și rezolvă tot la `full`.

---

# ✅ AUDIT 2026-09-07 — TOATE CELE 7 CRITICE REZOLVATE

Audit complet al `apex-forex-bot/` (90 fișiere, 6 recenzori paraleli). Claude
cloud a verificat 3 din 7 afirmații direct în cod — **toate trei reale**.

**Context care schimbă urgența:** există **un singur utilizator (proprietarul),
pe cont demo**. Șase din șapte sunt blocaje **înainte de primul client**, nu
incendii de azi. Două ating contul chiar acum.

| # | Constatare | Zonă | Cine |
|---|---|---|---|
| C1 | ✅ **REZOLVAT** — unealta de execuție scoasă, test cu mutație | `apex/assistant.py` | Claude cloud |
| C2 | ✅ **REZOLVAT** — toate cele 6 închideri sub poartă, `fc412af` | `apex/user_loop.py` | Claude cloud |
| C3 | ✅ **REZOLVAT** — absent ≠ False; vezi avertismentul de deploy sus | `apex/automation.py` | Claude cloud |
| C4 | ✅ **REZOLVAT** de Codex în `6d75bdb`, verificat | `apex/brokers/` | Codex |
| C5 | ✅ **REZOLVAT** de Codex în `6d75bdb`, verificat | `apex/brokers/` | Codex |
| C6 | ✅ **REZOLVAT** — CAS pe jurnal, append reîncearcă, `3b26cab` | `apex/user_store.py` | Claude cloud |
| C7 | ✅ **REZOLVAT** — revalidare din watchdog, `0ac4998` | `apex/user_loop.py` | Claude cloud |
| M4 | ✅ **REZOLVAT** — o literă | `apex/dashboard.py` | Claude cloud |

**Regula rămâne: nu ieși din zona ta.** Rulează suita înainte de commit (136/136).

## C4 + C5 — Codex, `apex/brokers/ctrader.py`

Sunt aceeași familie cu ce ai reparat deja în `place_order` (98d7705) — dar pe
calea de **închidere**, nu de deschidere.

**C5 — `ctrader.py:1093-1100`, fail-closed.** După un amend de stop eșuat,
codul recitește poziția ca să verifice că stopul chiar există. Dacă acea
recitire aruncă excepție (socket, reconectare — exact ce descriu comentariile
din modul), se setează `protected = True`, adică *„n-am putut verifica, deci
presupun că e bine"*. Ramura de panic-close și statusul `UNPROTECTED` nu mai
rulează niciodată. Rezultat: poziție reală, fără stop loss, raportată ca
`FILLED` normal.
**Fix:** implicit `protected = False` la excepție. Necunoscut ≠ protejat.

**C4 — `close_position()` vs `place_order()`.** `place_order` așteaptă
evenimentul **terminal** — comentariul lui explică de ce: un singur ordin
produce mai multe frame-uri, iar primul nu poartă confirmare de execuție.
`close_position` trimite cererea și acceptă **primul frame sosit**, fără să
verifice `errorCode` sau tipul execuției. Dacă primul frame e doar o
confirmare de primire, codul cade pe ramura „fără fill", cere o cotație
proaspătă și raportează `FILLED` oricum.
**Fix:** aceeași așteptare terminală și aceeași verificare de eroare pe care
le are deja `place_order`. Refolosește `_is_terminal_execution`.
**Scenariu:** brokerul respinge închiderea pe un frame ulterior, care nu mai e
citit niciodată. Poziția rămâne deschisă la broker în timp ce toate evidențele
interne spun „flat", cu un preț de ieșire inventat.

Ambele au nevoie de test în `tests/` (nu în `apex/brokers/`).


# 🔴 CINE CE LUCREAZĂ ACUM (actualizat 2026-09-07)

Agenții lucrează **în paralel**, pe zone care nu se ating. Nu ieși din zona ta.

> **Notă:** Codex rulează în aplicația **Codex Desktop**, separat de VS Code —
> nu în panourile Claude. Trebuie să i se deschidă proiectul ca „local project"
> (folderul `proiect-codex`), altfel stă într-un folder gol.
Dacă ai terminat și vrei alt task, actualizează tabelul ăsta ÎNTÂI, apoi lucrează.

| Agent | Zona lui — NUMAI aici | Task |
|---|---|---|
| **Claude cloud** (claude.ai/code) | `public/*.html` | Rescrie limbajul: platformă de automatizare, nu „bot care câștigă" |
| ~~Claude local #2~~ | ✅ TERMINAT | ~~Fix fus orar~~ — preluat și livrat de Claude cloud (nu fusese început) |
| **Codex Desktop** | `apex-forex-bot/apex/brokers/` | ✅ C4+C5 terminate (`6d75bdb`) — acum: **Pasul 1 din ORDINEA DE LUCRU RECOMANDATĂ** (limitator de rată cTrader, `docs/CTRADER_CAPABILITIES.md`) |
| **Claude local #1** (VS Code) | `apex-forex-bot/apex/user_loop.py` | **C2** — 3 din 6 închideri ocolesc `gates.authorize_close` (linii ~2790/3210/4684) |

**Regula:** dacă `git pull` îți aduce modificări în fișierele tale, oprește-te și
întreabă operatorul. Nu rezolva conflicte peste munca altui agent.

## Detaliile task-urilor

### ✅ Fus orar — REZOLVAT
`_ts()` din `scripts/backfill_trades.py` parsează acum explicit UTC
(`.replace(tzinfo=timezone.utc)`). Verificat: testul trece și pe
`TZ=Europe/Bucharest`, și pe `TZ=UTC`. Suita nu mai e roșie pe mașinile din
România.

**Rămas nereparat, intenționat:** `apex/cot.py:217` folosește `time.mktime`,
tot oră locală. Aceeași clasă de bug, dar rezultatul e vechimea unui raport
în zile, rotunjită la o zecimală, pentru rapoarte săptămânale — un decalaj de
3h înseamnă 0,125 zile. Imaterial, și nu există test care să acopere modulul,
deci o schimbare acolo ar fi mai riscantă decât artefactul de rotunjire.

### Codex — ✅ CORECTAT în 98d7705 (verificat de Claude cloud)

Diagnosticul a fost corect și suita e verde (135/135), dar două lucruri:

**1. Testul nu rulează niciodată.**
`apex/brokers/test_ctrader_order_failures.py` nu e în `tests/`, deci `run_all.py`
nu-l vede — numărul a rămas 135, neschimbat. Rulat singur pică cu
`ModuleNotFoundError: No module named 'apex'`, fiindcă doar `tests/conftest.py`
pregătește calea. Cu `PYTHONPATH=.` trece, deci logica e bună — dar testul e
mort și nu va prinde nicio regresie. **Mută-l în `tests/`.**

**2. Compromis de siguranță neanunțat — bani reali în joc.**
`_is_terminal_execution` a fost inversat: tip necunoscut însemna „acceptă",
acum înseamnă „așteaptă, apoi ridică excepție". Asta chiar repară eșecul tăcut.

Dar `place_order` atașează stop loss-ul **după** fill. Deci dacă un ordin
**chiar se execută** cu un tip de execuție pe care protobuf-ul instalat nu-l
recunoaște (ex. cTrader adaugă un enum nou), codul nou ridică excepție
**înainte** să ajungă la atașarea stopului → **poziție deschisă la broker,
fără stop loss**, iar botul crede că ordinul a eșuat.

| | Eșec vechi | Eșec nou |
|---|---|---|
| Ce se întâmplă | poziție inexistentă, botul crede că există | poziție reală, botul crede că nu există |
| Risc | enervant | **poziție neprotejată, fără stop** |

Ordinea corectă: la lipsă de confirmare, **întâi verifică dacă există poziție**
(`get_open_position`, cu retry — codul are deja bucla asta mai jos). Dacă
există → atașează stopul, nu ridica excepție. Ridică excepție **doar** dacă
brokerul chiar nu are nicio poziție.

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
