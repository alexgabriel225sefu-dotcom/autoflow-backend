# Apex4Traders — ce este, ce face, și unde se opreşte

Document de scop. Descrie produsul aşa cum este, nu aşa cum ar putea deveni.

---

## 1. Ce este Apex4Traders

**O platformă proprie de automatizare şi control al regulilor de tranzacţionare.**
Clientul îşi construieşte regulile din condiţii cu nume şi formule publicate,
vede exact ce ar decide fiecare regulă înainte s-o pornească, şi o poate opri
în orice moment.

### Ce NU este

| Nu este | De ce contează distincţia |
|---|---|
| **Un bot de Telegram** | Telegram nu e login, nu e identitate, nu e interfaţă de control şi nu e necesar pentru nicio funcţie. Un client fără cont de Telegram foloseşte platforma integral. |
| **Un broker** | Nu ţinem bani, nu deschidem conturi, nu suntem contraparte. Contul de tranzacţionare e al clientului, la brokerul lui, prin cTrader. |
| **Un serviciu de semnale** | Nu trimitem recomandări. Platforma execută regulile pe care clientul le scrie; dacă regula tace, platforma tace. |
| **Consultanţă de investiţii** | Nu evaluăm dacă o strategie e potrivită pentru cineva, nu promitem randamente şi nu publicăm statistici de performanţă. |

### cTrader este infrastructură, nu produs

cTrader e stratul prin care platforma se conectează la contul clientului, ia
date de piaţă şi — când clientul porneşte automatizarea — trimite ordine.
Clientul îl vede o singură dată, la conectare. Nu e brandul, nu e interfaţa, şi
nu e ceva ce ascundem: ecranul de conectare spune explicit că execuţia se face
printr-un cont cTrader pe care clientul îl conectează şi îl poate deconecta.

---

## 2. Ce este implementat acum

| Funcţie | Stare | Unde |
|---|---|---|
| **Supabase Auth** | complet | email + parolă, confirmare, resetare. Identitatea platformei e `supabase_user_id`. |
| **cTrader OAuth** | complet | flux în trei paşi, cu finalizare autentificată. Tokenurile se criptează la stocare şi nu ajung niciodată în frontend. |
| **Accounts** | complet | listare conturi conectate, selecţie, deconectare, demo/live marcat explicit. |
| **Positions** | citire | poziţii deschise, cu contul şi modul. |
| **Orders** | citire | ordine în aşteptare. |
| **Candles** | citire | date de piaţă pentru preview, prin acelaşi conector şi acelaşi cache ca motorul. |
| **RuleDoc / Rule Builder** | complet | 12 condiţii, validare, activare care îngheaţă o versiune, versionare. |
| **Preview pe date reale** | complet | evaluează regula pe lumânări luate din contul conectat. Nu plasează nimic, nu scrie nimic. |
| **Journal** | complet | 12 statusuri distincte, filtrare după cont/simbol/perioadă/regulă/status, paginare. |
| **Notifications** | complet | centru intern platformei. Fără Telegram. |
| **Demo automation** | complet | start, pause, resume, stop — doar pe conturi demo. Idempotent şi jurnalizat. |

Interfaţa web are **18 pagini de platformă** — landing, sign up, login,
confirmare email, resetare parolă, callback auth, dashboard, licenţă,
conectare cTrader, conturi, reguli, rule builder, detaliu regulă, poziţii,
ordine, jurnal, notificări, setări. Fiecare e legată de un endpoint real; nu
există ecran cu date fabricate. (În proiect mai există `terms`, `privacy` şi un
`configurator` preexistente, din afara platformei.)

---

## 3. Ce NU este implementat

| Lipseşte | Precizare |
|---|---|
| **Live trading** | Nu "dezactivat" — **neimplementat**. Nu există ramură de cod care porneşte o buclă live. |
| **Deploy public** | Platforma rulează local şi în staging. Nu e publicată. |
| **Plăţi / licenţă comercială** | `licence.grant()` se apelează manual pe server. Nu există checkout, facturare sau reînnoire. |
| **Execuţie reală pe cont live** | Vezi V2 şi V3 mai jos. |
| **Ştergerea fizică a codului Telegram** | Codul legacy există şi funcţionează. Vezi mai jos de ce. |

### De ce codul Telegram nu a fost şters

`apex/telegram.py` (6742 linii), `apex/ctrader_oauth.py` şi magaziile cheiate pe
`chat_id` sunt intacte, fiindcă **clienţii onboardaţi prin Telegram au
tokenurile stocate acolo** şi ştergerea i-ar lăsa fără cont.

Ce s-a făcut în schimb:

- `apex/ctrader_oauth.py` poartă un antet **DEPRECATED** care explică de ce nu
  a putut fi refolosit: e cheiat pe `chat_id`, îşi semnează state-ul OAuth cu
  tokenul de bot, şi finalizează legarea contului direct în callback.
- Un test verifică, prin AST, că **niciun modul din `apex/platform/` nu importă
  telegram** — pe tot pachetul, nu doar pe fişierul la care s-a uitat cineva.
- Un deployment fără `TELEGRAM_BOT_TOKEN` rulează platforma integral.

Codul vechi e **legacy şi nu face parte din Apex4Traders v1.**

---

## 4. Ce poate face cTrader Open API

Distincţia care contează aici nu e "ce permite cTrader" — permite tot ce e mai
jos. E **ce am cablat noi**, şi mai ales ce am cablat dar nu am expus.

| Capabilitate cTrader | Conectorul nostru | Platforma v1 o expune |
|---|---|---|
| **OAuth** (authorize, token, refresh) | da | **da** — fluxul de conectare |
| **Listare conturi** | da | **da** — `/accounts` |
| **Market data** (trendbars, bid/ask) | da | **parţial** — lumânări da, cotaţii live nu |
| **Positions** | da | **da**, doar citire |
| **Orders** | da | **da**, doar citire |
| **Place order** | da | **doar prin motor** — niciun endpoint al platformei nu plasează un ordin direct |
| **Close position** | da | **nu** — niciun endpoint nu închide o poziţie |
| **Amend SL/TP** | da | **nu** |
| **History** (deal history) | da | **nu** — jurnalul platformei e separat şi acoperă doar deciziile ei |
| **Balance / equity** | da | **parţial** — sold prin `/accounts/{id}`; equity live nu |

Coloana din mijloc e plină. Coloana din dreapta nu. Asta e deliberat: fiecare
capabilitate expusă e o suprafaţă care trebuie păzită, iar cele care nu aduc
nimic în v1 rămân necablate.

---

## 5. Versiuni

### V1 — platformă demo / paper *(versiunea curentă)*

Clientul se înregistrează, conectează un cont cTrader demo, construieşte
reguli, le previzualizează pe date reale, porneşte automatizarea pe demo şi
vede totul în jurnal. Nimic nu atinge bani reali.

### V2 — execuţie reală pe cont demo cTrader

Ordinele ajung efectiv la cTrader pe contul demo, prin motorul existent.
Diferenţa faţă de V1 nu e o funcţie nouă, ci **încredere câştigată**: jurnalul
trebuie să arate că fiecare ordin trimis a fost cel pe care regula l-a cerut, cu
stopul pe care regula l-a cerut.

### V3 — live trading

Doar după **audit** şi **clarificare legală**. Nu e o casetă de bifat: cere
revizuire a fluxului de execuţie, a limitelor de risc, a termenilor de serviciu
şi a obligaţiilor de reglementare din jurisdicţia în care se operează.

---

## 6. Despre execuţie — spus fără ocolişuri

**Platforma poate, tehnic, să plaseze ordine prin cTrader.** Conectorul are
`place_order`, `close_position` şi `amend_sltp`, iar motorul le foloseşte. A
pretinde altceva ar fi neadevărat.

**În versiunea curentă nu activăm live trading.** Trei refuzuri independente
stau în cale, şi fiecare e verificat de teste:

1. `ctrader_link.live_allowed()` cere `APP_ENV=production` **şi**
   `APEX_ALLOW_LIVE_ACCOUNTS=true`. Niciuna singură nu ajunge.
2. Selectarea unui cont live e refuzată când asta e fals — şi la citire, nu
   doar la tranzacţionare.
3. `automation._preflight()` refuză orice cont al cărui mod nu e `demo`.

**Orice execuţie trece prin acelaşi lanţ.** Fără excepţii şi fără scurtături:

- `ownership.may_trade` — instanţa care cere e cea care deţine contul;
- `gates.authorize_order` — entitlement, mediu de broker, risc, limite;
- `gates.audit` — decizia porţii e înregistrată;
- `ledger.claim` / `record` — idempotenţă, luată **înainte** de apelul la broker;
- abia apoi `broker.place_order`;
- iar totul intră în jurnal, inclusiv refuzurile.

**Nu există cale paralelă către broker.** Modulele platformei nu importă niciun
broker, nicio poartă şi niciun ledger — predau lucrul controlerului care le
are deja. Teste care parcurg AST-ul verifică asta pentru `broker_read.py`,
`preview.py`, `bridge.py` şi `automation.py`: absenţa apelurilor e o proprietate
a codului, nu o promisiune dintr-un comentariu.

---

## 7. Diagramă

```
   ┌──────────┐
   │   User   │  browser, Apex4Traders
   └────┬─────┘
        │  sesiune Supabase (Bearer)
        ▼
   ┌──────────────────┐
   │  Apex Platform   │  /api/v1 — auth, ownership, licenţă
   │                  │  RuleDoc, journal, notificări
   └────┬─────────────┘
        │  RuleDoc + MarketSnapshot
        ▼
   ┌──────────────────┐
   │   Rule Engine    │  evaluator pur — fără ceas, fără reţea
   │                  │  Decision: BUY / SELL / CLOSE / HOLD / REJECT
   └────┬─────────────┘
        │  ExecutionRequest   (doar BUY şi SELL ajung aici)
        ▼
   ┌──────────────────┐
   │   Risk Gates     │  ownership · authorize_order · audit · ledger
   │                  │  orice refuz opreşte aici şi se jurnalizează
   └────┬─────────────┘
        │
        ▼
   ┌──────────────────┐
   │   cTrader API    │  conectare · date · execuţie
   └──────────────────┘
```

HOLD, REJECT, o configuraţie invalidă sau o constrângere imposibil de respectat
se opresc **înainte** de porţi. Nu devin niciodată ordin.

---

## 8. Ce spunem clientului

- Apex4Traders execută reguli pe care le configurezi tu.
- Nu e consultanţă financiară şi nu administrăm bani.
- Execuţia se face printr-un cont cTrader pe care îl conectezi şi îl poţi
  deconecta oricând.
- Tranzacţionarea implică risc, inclusiv pierderea capitalului.
- Nu promitem randamente şi nu publicăm statistici de performanţă.
