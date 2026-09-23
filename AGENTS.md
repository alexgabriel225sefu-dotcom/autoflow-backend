# AGENTS.md — reguli pentru orice agent AI care lucrează în acest repo

Codex citește acest fișier automat. Claude Code citește `CLAUDE.md`.
**Regulile de cod sunt aceleași pentru amândoi și trăiesc în `CLAUDE.md` — citește-l.**
Fișierul de față adaugă doar ce e specific coordonării între agenți.

## Ce e proiectul

Repo-ul ține **două produse**, cu identități separate:

1. **Apex4Traders** (`apex-forex-bot/apex/platform/`, Python, + `web/`,
   Next.js) — platforma web de automatizare pe reguli, conectată la cTrader.
   Ăsta e produsul la care se lucrează acum. Identitatea clientului vine din
   Supabase, nu din Telegram. Automatizarea rulează **doar pe conturi demo**;
   tranzacționarea live nu e implementată.
2. **Apex Trade Bot** (restul din `apex-forex-bot/`, Python) — botul de forex
   pe Telegram, plus site-ul de vânzări (`server.js`, Node). E produsul
   anterior și încă rulează.

Brokerul e **cTrader** în ambele. OANDA e cod legacy, NU se folosește — nu
"repara" botul spre OANDA.

Cele două nu împart identitatea clientului și nici entitlement-ul:
`apex/stripe_license.py` e pe `chat_id` de Telegram, `apex/platform/licence.py`
e pe user id de Supabase. Nu le uni fără o migrare explicită.

## Branch

- Platforma Apex4Traders se dezvoltă pe **`claude/apex4traders-platform-v1`**.
- Botul de Telegram și site-ul se dezvoltă pe
  **`claude/arcads-external-api-gexx7-6n4pr9`**.
- `claude/arcads-external-api-gExX7` e branch-ul de deploy Render — se
  auto-deployează la fiecare commit. Se ține identic ca conținut.
- **`main` e vechi și divergent. Nu lucra pe `main`.**

Verifică pe ce branch ești înainte de primul commit. Cele două fire de lucru
ating aceleași fișiere din `apex-forex-bot/apex/` și un commit pe branch-ul
greșit ajunge în deploy.

## Teste — obligatoriu înainte de commit

```
python apex-forex-bot/tests/run_all.py
```

Toate trebuie să treacă. Nu comite cu teste roșii.

## Interziceri (bani reali, cont live)

- Nu comite secrete, chei, tokenuri, `.env`.
- Nu schimba `PAPER_TRADING`, `CTRADER_ENV`, `BROKER` — niciodată în numele unui client.
- Singurele lucruri care pot permite un ordin sunt `gates.authorize_order` /
  `gates.authorize_close`. Nu ocoli aceste funcții.
- **Nu comuta `EV_GATE_MODE` pe `enforce`.** E decizia operatorului, după ce
  citește logurile shadow.
- Nu rula tool-uri care execută tranzacții (`force_close`, `open_trade`,
  `bot_power`) — doar citiri.

Pentru Apex4Traders, în plus:

- Nu activa tranzacționarea live și nu adăuga o cale către ea. `LIVE_TRADING_ENABLED`
  nu are implementare în spate — `/readyz` refuză pornirea dacă e setat.
- Nu acorda licențe din cereri venite din browserul clientului. Vezi
  `docs/MANUAL_LICENCE_OPERATIONS.md`.
- Codul, UI-ul, testele, comentariile și documentația **nouă** din Apex4Traders
  se scriu în engleză. Fișierul de față rămâne în română pentru că e protocol
  de coordonare între agenți, nu produs.

---

# Protocol de ștafetă (Codex ↔ Claude Code)

Cei doi agenți lucrează pe **același branch**, dar **NU în același timp**.
Unul singur e activ. Când unul se oprește, celălalt continuă de unde a rămas.

Nu există predare automată — predarea se face prin git + `HANDOFF.md`.

## Când PORNEȘTI lucrul

```
git pull origin <branch-ul firului tău>   # vezi secțiunea „Branch" de mai sus
```

Apoi citește **`HANDOFF.md`**, secțiunea „STARE CURENTĂ". Acolo scrie ce a
făcut agentul dinainte și ce urmează.

## Când TERMINI (sau când dai de limită)

Nu te opri lăsând lucrul necomis. În ordinea asta:

1. Rulează testele.
2. Commit + push pe branch.
3. Actualizează „STARE CURENTĂ" din `HANDOFF.md`: ce ai terminat, ce ai lăsat
   pe jumătate, care e următorul pas concret.
4. Push și pentru `HANDOFF.md`.

Dacă simți că se apropie limita, fă pașii ăștia **mai devreme**, nu mai târziu.
Un commit mic și un HANDOFF corect valorează mai mult decât lucru pierdut.

## Regula anti-coliziune

Dacă `git pull` aduce modificări pe fișierele pe care tocmai le editai,
**oprește-te și spune-i operatorului**. Nu rezolva conflicte de unul singur
peste munca celuilalt agent.
