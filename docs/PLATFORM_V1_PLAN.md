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
