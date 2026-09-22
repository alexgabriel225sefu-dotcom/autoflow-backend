# Apex4Traders Platform v1 — inventar și plan

**Ramură:** `claude/apex4traders-platform-v1`, pornită din `8e26e4fc8`
**Faza 1 — audit.** Nimic din execuție nu e modificat în acest commit.

Acest document spune ce EXISTĂ în cod, nu ce spune documentația. Fiecare
afirmație de mai jos a fost verificată prin citire directă.

---

## 1. Ce am găsit — inventar verificat

### Două backend-uri, nu unul

| | Ce e | Rol |
|---|---|---|
| `server.js` | Node/Express, 3.513 linii | Site de vânzări + Stripe + email + produse fără legătură (heygen, creatify, tiktok). **NU e backendul de trading.** |
| `apex-forex-bot/` | Python | Motorul de trading. Server HTTP propriu în `apex/bot.py` (`ThreadingHTTPServer` + `BaseHTTPRequestHandler`), nu Flask/FastAPI. |

Rutele HTTP care există deja în `apex/bot.py`:
`/api/session`, `/api/session/logout`, `/api/app/ask`, `/api/app/automation`,
`/api/app/close`, `/api/voice`, `/api/stripe/webhook`, `/app`, `/go`.

### Frontend: `web/` e Next.js, nu `public/`

- **Next.js 15, app router**, TypeScript, Tailwind, shadcn/ui, Radix,
  framer-motion, lucide-react.
- Pagini existente: `/` (landing), `/configurator`, `/terms`, `/privacy`.
- O singură rută API: `src/app/api/create-payment-intent/route.ts`.
- `public/*.html` sunt pagini statice de marketing servite de `server.js` —
  **nu** sunt aplicația.

**Decizie:** platforma se construiește în `web/`, pe stack-ul existent. Nu
introduc alt framework.

### Ce e deja construit și se REUTILIZEAZĂ

Astea nu se rescriu. Sunt fundația.

| Modul | Linii | Ce oferă |
|---|---|---|
| `apex/gates.py` | 319 | `authorize_order` / `authorize_close` — **poarta unică**. Entitlement, mediu broker, demo/live. |
| `apex/ctrader_oauth.py` | 488 | OAuth complet: state semnat, CSRF, `handle_callback`, `broker_gate_reason`, refuz stateless în producție. |
| `apex/user_store.py` | 1.002 | `encrypt_value` / `decrypt_value` (Fernet), CAS pe jurnal, refuz de pornire fără cheie. |
| `apex/access.py` | 238 | Licențiere: `is_allowed`, `allowed_state`, `grant`, `revoke`, admini. |
| `apex/http_session.py` | — | Sesiuni pe cookie: `create`, `valid`, `revoke`, `set_cookie_value`. |
| `apex/http_security.py` | — | CSP, `RateLimiter`, detecție HTTPS. Limitatoare gata definite. |
| `apex/ledger.py` | 166 | **Idempotență**: `request_id`, `claim`, `record`, `release`. Asta E deduplicarea de ExecutionRequest. |
| `apex/brokers/ctrader.py` | 1.459 | Conector: rate limiter (5/s istoric, 50/s restul), plafon de slippage, poziții. |
| `apex/setups.py` | 208 | `SetupCandidate` cu `READY` / `WATCH` / `INVALID` — foarte aproape de Decision. |
| `apex/strategy_api.py` | 284 | `Market` (lumânări, indicatori, poziție, preț, sold, timeframe) — aproape de MarketSnapshot. |

### Ce NU există și trebuie construit

RuleDoc, MarketSnapshot complet, Decision de regulă, ExecutionRequest,
JournalEntry, biblioteca de condiții, API-ul REST al platformei, ecranele.

---

## 2. Două probleme de arhitectură găsite la audit

### 2.1 Coliziune de nume: `Decision` există deja

`apex/gates.py:47` definește `class Decision` — verdictul de **autorizare**:
`(allowed, reason, detail)`. Răspunde la „poate trece acest ordin?".

Brief-ul cere un `Decision` care răspunde la altă întrebare: „ce spune
regula?" — `BUY / SELL / CLOSE / HOLD / REJECT`.

Două clase `Decision` în aceeași cale de ordine, cu sensuri diferite, e o
capcană reală: cine citește `decision.allowed` pe obiectul greșit primește
`AttributeError` în cel mai bun caz și o confuzie tăcută în cel mai rău.

**Decizie, cu deviere conștientă de la denumirea din brief:** verdictul de
regulă se numește **`RuleDecision`**, în pachetul nou `apex/platform/`.
`gates.Decision` rămâne neatins. Un test va asserta că cele două nu pot fi
confundate. Dacă preferi totuși `Decision`, îl redenumesc — dar recomand să
nu.

### 2.2 `strategy_api.Market` acoperă ~60% din MarketSnapshot

Are: lumânări, simbol, indicatori, strat, poziție deschisă, preț, sold,
timeframe.
Îi lipsesc, față de ce cere brief-ul: spread, sesiune, ordine în așteptare,
equity, expunere, starea contului, timestamp explicit.

**Decizie:** `MarketSnapshot` e un tip nou care **conține** un `Market` pentru
compatibilitate cu strategiile existente, nu un înlocuitor. Motorul actual
continuă să primească `Market`; evaluatorul nou primește `MarketSnapshot`.

---

## 3. Planul pe faze

| Fază | Ce | Atinge execuția? |
|---|---|---|
| 1 | Audit + acest document | Nu |
| 2 | Contracte: RuleDoc, MarketSnapshot, RuleDecision, ExecutionRequest, JournalEntry + validatoare + teste | Nu |
| 3 | Evaluator pur + biblioteca de condiții | Nu |
| 4 | API backend (auth, licență, ownership, RuleDoc, preview, jurnal) | Nu |
| 5 | Conectare cont cTrader, demo-first | Nu |
| 6 | Frontend MVP în `web/` | Nu |
| 7 | Integrare controlată — doar prin `ExecutionRequest` → `gates` | **Da, ultima** |
| 8 | Hardening: teste de mutație, audit AST, securitate | Nu |

Fazele 1–6 nu ating deloc calea de execuție. Faza 7 e singura care o atinge,
și numai prin poarta existentă.

---

## 4. Limite respectate

- Fără deploy, fără trading live, fără modificarea mediului.
- `PAPER_TRADING`, `CTRADER_ENV`, brokerul implicit — neatinse.
- `gates.authorize_order` / `authorize_close` rămân singura cale spre broker.
  Nu se creează a doua cale.
- Conectorul cTrader se reutilizează, nu se rescrie.
- Tokenurile se stochează criptat prin `user_store.encrypt_value` și nu ajung
  niciodată în răspunsurile API.
- Fără date fabricate în interfață: stări reale („Not connected", „No active
  automation") în locul cifrelor inventate.
- Suita existentă rulează cu `python apex-forex-bot/tests/run_all.py`.
  **pytest nu e instalat în acest mediu** — folosesc runnerul oficial al
  proiectului, declarat în `AGENTS.md`, și consemnez asta aici în loc să
  modific testele.

---

## 5. Ce rămâne de decis de operator

1. **`RuleDecision` vs `Decision`** — vezi 2.1. Recomand `RuleDecision`.
2. **Unde trăiește API-ul platformei.** Serverul HTTP e scris de mână în
   `apex/bot.py`. Adaug rutele acolo (consistent, fără dependențe noi) sau
   introduc un serviciu separat? Recomand primul: `http_session` și
   `http_security` sunt deja acolo, iar a doua cale ar dubla suprafața de
   autentificare.

---

# Schimbare de direcție — Telegram eliminat, Supabase Auth ca identitate

Decisă de operator după Faza 3. Cele două întrebări deschise de mai sus sunt
acum închise: `RuleDecision` a rămas `RuleDecision`, iar API-ul platformei
trăiește în `apex/platform/api.py` și se montează în serverul existent.

## Ce s-a schimbat în model

Identitatea platformei este **`supabase_user_id`**. Nu `chat_id`.

Asta a fost posibil fără a rescrie motorul dintr-un singur motiv, verificat în
cod: `user_loop.py` are 18 referințe la Telegram și **zero la `chat_id`** —
folosește `user_id` ca șir opac, exact ce cere `user_store`. Un id Supabase
este tot un șir. Motorul nu observă diferența.

## Ce e implementat și verificat

| Modul | Regula pe care o impune |
|---|---|
| `platform/identity.py` | o configurare greșită nu e niciodată o permisiune |
| `platform/store.py` | nu poți citi un document fără să spui al cui e |
| `platform/licence.py` | o autorizare necunoscută nu e o autorizare |
| `platform/api.py` | autentificat · deținut · licențiat · cinstit |

Verificare: **150/150** fișiere în `python3 apex-forex-bot/tests/run_all.py`.
Mutație pe codul nou: 19/19 (evaluator), 18/18 (identitate + stocare), 14/15
(API — unul echivalent, documentat în commit).

### De ce tokenul se verifică la Supabase, nu local

Contrar sfatului obișnuit, și din trei motive: revocarea chiar funcționează (un
JWT verificat local rămâne valid până expiră, deci un client delogat sau un
cont blocat continuă să tranzacționeze); supraviețuiește migrării de chei a
Supabase (HS256 cu secret partajat la proiectele vechi, asimetric prin JWKS la
cele noi); și nu adaugă nicio dependență — `requests` e deja pinuit, `PyJWT` nu.

Prețul e un apel de rețea per cerere, amortizat de un cache de 60s. Prețul
cache-ului e spus pe față: un token revocat acum câteva secunde mai merge până
expiră intrarea. De aceea **orice operație distructivă cere `fresh=True`**.

## Variabile de mediu necesare

`apex-forex-bot/.env.example` **nu a putut fi modificat** — e acoperit de o
regulă de refuz pe fișiere `.env*` din setările de permisiuni ale operatorului.
Regula a fost respectată, nu ocolită. Adaugă manual:

```
SUPABASE_URL=https://<proiect>.supabase.co
SUPABASE_ANON_KEY=<cheia anon publică>
```

`SUPABASE_URL` există deja în `render.yaml`. `SUPABASE_ANON_KEY` e nouă.

Este cheia **anon**, nu `SUPABASE_SERVICE_KEY`. Cheia de serviciu ocolește Row
Level Security; nu trebuie folosită pentru verificarea unei sesiuni și nu
trebuie să ajungă niciodată unde o poate citi un client.

## Inventarul Telegram — măsurat, nu presupus

24 de fișiere din `apex/` ating Telegram sau `chat_id`:

| Fișier | `chat_id` | `telegram` | Ce înseamnă |
|---|---|---|---|
| `telegram.py` | 953 | 85 | botul în sine, 6742 linii |
| `ctrader_oauth.py` | 33 | 21 | **fluxul OAuth e cheiat pe `chat_id`** |
| `access.py` | 33 | 2 | listele admin/allowed |
| `stripe_license.py` | 25 | 4 | entitlement pe `chat_id` |
| `bot.py` | 24 | 67 | serverul HTTP + cablajul Telegram |
| `user_loop.py` | 0 | 18 | doar notificări — motorul e curat |
| `gates.py` | 0 | 2 | poarta e aproape curată |

**Nimic nu a fost încă șters sau izolat.** Calea nouă a fost construită alături
de cea veche, iar fluxul nou nu importă `telegram.py`. Eliminarea propriu-zisă
vine cu fazele de mai jos, ca să nu rupă motorul care rulează azi.

## Ce rămâne

1. **Notification port** — `user_loop` trimite azi direct în Telegram. Trebuie
   o interfață de notificare cu livrare în platformă (notification center,
   activity feed), Telegram rămânând un adaptor opțional.
2. **OAuth cTrader pe web** — `ctrader_oauth.py` e cheiat pe `chat_id` și
   redirectează înapoi în Telegram. Necesită callback web legat de
   `supabase_user_id`, cu tokenul criptat și niciodată returnat în frontend.
3. **Endpointurile dependente de broker** — `accounts`, `positions`, `orders`,
   `journal`, `notifications`, `preview`. Răspund acum 501 UNSUPPORTED.
4. **Frontend** în `web/` (Next.js 16, Tailwind, shadcn deja prezente):
   sign up/login, dashboard, Rule Builder, preview, poziții, activitate,
   jurnal, licență, setări.
5. **Izolarea Telegram** — strat de compatibilitate marcat deprecated, pe care
   fluxul nou nu-l importă.

Niciun deploy. Niciun trading live. `PAPER_TRADING`, `CTRADER_ENV` și brokerul
implicit rămân neatinse.
