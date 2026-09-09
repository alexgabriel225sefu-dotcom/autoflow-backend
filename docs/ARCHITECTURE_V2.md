# Apex4Traders v2 — arhitectură propusă

**Stare:** propunere. Nimic din ce urmează nu e implementat.
**Bază:** commit `1bea525`, identic cu arhiva analizată de Codex.
**Regulă:** sistemul care tranzacționează acum nu se atinge până nu există
contracte agreate și o cale de migrare.

---

## 1. Ce e produsul, exprimat ca invariant

> Când condițiile definite de client sunt îndeplinite, execută acțiunea
> configurată, respectând limitele activate.

Din asta decurge tot ce urmează. Trei consecințe care nu sunt negociabile,
pentru că fără ele propoziția de mai sus devine falsă:

1. **Determinism.** Aceeași configurație + aceleași date de piață = aceeași
   decizie. Fără selecție automată, fără fallback, fără AI în cale.
2. **Trasabilitate.** Fiecare ordin trebuie să spună *care versiune de
   configurație* l-a produs și *care condiții* s-au potrivit.
3. **Refuz explicit.** Ce nu se poate executa conform specificației nu se
   execută aproximativ. Se refuză și se înregistrează.

Punctul 3 e cel mai des încălcat în codul actual — vezi §4.

---

## 2. Straturile

| Strat | Rol | Sursă |
|---|---|---|
| **Config versionată** | documentul de reguli, imutabil după activare | **construit** |
| **Evaluator determinist** | (config, snapshot) → decizie. Funcție pură. | **construit** |
| **Bibliotecă de condiții** | indicatori și tipare, cu definiții matematice | **construit** |
| **Verificări de risc** | limite, expunere, ownership, idempotency | **reutilizat** (`gates.py`) |
| **Execuție + reconciliere** | ordine, confirmări, poziții la broker | **reutilizat** (`brokers/ctrader.py`) |
| **Gestionarea pozițiilor** | SL/TP/trailing/parțiale, după restart | **adaptat** (din `user_loop.py`) |
| **Jurnal + explicații** | ce s-a întâmplat și de ce | **adaptat** (`user_store` + `ev`) |
| **Interfață** | conectare, grafice, constructor, automatizări, jurnal | **construit** |
| **Acces și licențe** | drepturi, revalidare, revocare | **reutilizat** (`access.py`, `gates`) |

---

## 3. Ce reutilizăm — și de ce merită

Nu pornim de la zero. Aceste componente au fost auditate și au teste care
prind regresii reale:

- **`apex/gates.py`** — autorizare centralizată. `authorize_order` /
  `authorize_close` verifică drepturi, expunere, ownership și idempotency
  într-un singur loc. Un audit recent a confirmat că nu există scurtătură în
  stratul de broker. **Rămâne singura poartă.**
- **`apex/brokers/ctrader.py`** — OAuth, protobuf, reconectare, paginare,
  limitator de rată (5/s istoric, 50/s restul, per conexiune), plafon de
  alunecare. Aici sunt lunile de muncă pe care o rescriere le-ar pierde.
- **`apex/ledger.py`** — registrul de idempotență a ordinelor.
- **`apex/user_store.py`** — înregistrări versionate cu compare-and-set, acum
  și pentru jurnal. **Exact primitiva de care are nevoie configurația
  versionată.**
- **`apex/access.py`** + serverul de licențe — drepturi și revocare.
- **Disciplina de testare** — 142 de fișiere, inclusiv un meta-test care
  respinge aserțiunile pe text de comentariu. Se păstrează ca standard.

## 4. Ce adaptăm

- **`apex/builder.py`** → devine autorarea configurației în interfață. Azi
  produce *patch-uri* peste o configurație globală; trebuie să producă un
  **document de reguli** de sine stătător.
- **`apex/forex.py::calc_units`** → matematica dimensionării e corectă. Ce se
  schimbă: riscul vine **exclusiv** din configurație, fără multiplicator.
- **`apex/user_loop.py`** → bucla de tick, datele de piață și gestionarea
  pozițiilor se păstrează. **Partea de decizie se înlocuiește** cu evaluatorul.

## 5. Ce construim

### 5.1 Documentul de reguli (`RuleDoc`)

Imutabil după activare. Versionat cu aceeași primitivă CAS ca înregistrarea
utilizatorului. Fiecare ordin poartă `ruleDocId` + `version`.

Acoperă exact ce a cerut clientul să controleze: cont și instrumente,
timeframe și momentul evaluării (intrabar / la închidere), condiții de intrare
și ieșire cu praguri și perioade, combinare AND/OR, direcții permise, tip de
ordin și expirare, volum fix sau formulă de risc, SL/TP/trailing/break-even/
parțiale, program și fus orar, limite de poziții și expunere, comportament la
atingerea pragurilor, și starea (draft / activ / oprit).

**Cele trei comportamente la prag sunt câmpuri distincte**, nu un singur
comutator: *blochează intrări noi*, *anulează ordine în așteptare*, *închide
poziții*. Sunt operații diferite și se configurează separat.

### 5.2 Evaluatorul determinist

```
evaluate(rule_doc, snapshot) -> Decision
```

Funcție **pură**: fără I/O, fără ceas, fără rețea. Ceasul și datele intră prin
`snapshot`, ceea ce face evaluatorul testabil cu fișiere-etalon.

`Decision` conține acțiunea, **fiecare condiție evaluată cu rezultatul ei**, și
motivul. Asta e sursa explicațiilor din interfață — nu un text generat separat
care poate să nu corespundă.

**Fără fallback.** O strategie sau condiție necunoscută e o eroare de
validare, nu un motiv de substituție.

### 5.3 Biblioteca de condiții — set inițial, definit

Nu promitem orice strategie imaginabilă. Set inițial propus, fiecare cu
definiție matematică și parametri documentați:

- **Indicatori:** EMA, SMA, RSI, MACD, ATR, Bollinger, Stochastic
- **Structură:** HH/HL/LH/LL, break of structure
- **Nivel:** preț vs nivel, vs indicator, vs bandă
- **Timp:** sesiune, interval orar, zi a săptămânii
- **Tipare, cu definiție explicită:** FVG, liquidity sweep, supply/demand

Ultimele trei intră **numai** cu definiție matematică scrisă și parametri
expuși clientului. Fără asta, un client nu poate ști ce a configurat, iar noi
nu putem susține că platforma execută conform specificației.

---

## 6. Contractele — de stabilit ÎNAINTE de împărțirea muncii

Cinci contracte. Până nu sunt agreate, împărțirea pe agenți nu poate începe.

| # | Contract | Cine depinde de el |
|---|---|---|
| 1 | `RuleDoc` — schema JSON, versionare, validare | interfața și motorul, amândoi |
| 2 | `MarketSnapshot` — ce primește evaluatorul | motorul; interfața pentru previzualizare |
| 3 | `Decision` — ce întoarce, inclusiv condiții evaluate | motorul produce, interfața afișează |
| 4 | `ExecutionRequest` — inclusiv constrângeri obligatorii | motorul produce, execuția consumă |
| 5 | Intrarea de jurnal — legată de versiunea configurației | toate |

**Contractul 4 conține regula pe care Codex a propus-o și pe care o susțin:**
o constrângere de execuție marcată obligatorie și care nu poate fi respectată
**blochează intrarea**. Nu o degradează tăcut.

---

## 7. Constatări tehnice care contrazic direcția — verificate în cod

Fiecare a fost verificată pe `1bea525`, nu preluată din raport.

| Loc | Ce face acum | De ce contrazice direcția |
|---|---|---|
| `ai.py:1054` | `STRATEGY_MODES.get(mode, STRATEGY_MODES["mean_reversion"])` | un mod **necunoscut** devine tăcut mean reversion — exact substituția interzisă |
| `user_loop.py:3135-3148` | `active_mode == "auto"` → strategia aleasă după regim | selecție automată a strategiei |
| `user_loop.py:4280→4317` | `druckenmiller_multiplier(...)` → `calc_units(mult=...)` | riscul variază **0,4×–1,2×** fără ca clientul să aleagă |
| `user_loop.py:4303` | `if regime == "volatile": risk_mult *= 0.5` | plafonul efectiv coboară la **0,2×** |
| `brokers/ctrader.py:1110-1116` | fără cotație → ordinul rămâne `MARKET`, fără plafon | protecția configurată e abandonată tăcut |
| `builder.py` | wizard peste strategii existente | nu e constructor de condiții |

**Rafinare față de raportul Codex, punctul 4:** `advise_risk()` din
`strategy_modules.py` **este** consultativ și **este** plafonat de
`_sanitize_advice` în `[0.4, 1.2]` — dar **bucla nu îl consumă deloc**. Calea
vie e apelul **direct** din `user_loop.py:4280`, care ocolește API-ul
consultativ. Plafonarea vine din interiorul funcției, nu din `_sanitize_advice`.
Deci: API consultativ dormant, apel direct viu. Ambele trebuie tratate, dar
sunt lucruri diferite.

---

## 8. Ce NU stabilim aici

Faptul că un client își alege setările **nu decide de la sine** răspunderea
furnizorului și nu stabilește încadrarea juridică a produsului. Constatările
de mai sus sunt tehnice.

Necesită verificare juridică, separat: încadrarea produsului, formularea
răspunderii, ce se poate afirma despre praguri de pierdere, și obligațiile față
de client. **Un prag de pierdere nu e o garanție împotriva gapurilor sau a
alunecării** — asta e o constatare tehnică, dar formularea ei către client e
juridică.

---

## 9. Prima etapă concretă

Nu implementare. **Contractul 1 și scheletul contractului 3.**

1. Schema `RuleDoc` ca JSON Schema, cu validare care refuză explicit orice
   condiție sau strategie necunoscută.
2. Trei configurații-exemplu complete, scrise în schemă, ca fișiere-etalon.
3. Structura `Decision`, cu fiecare condiție evaluată vizibilă.
4. Teste care afirmă că **validarea refuză** — configurație invalidă, condiție
   necunoscută, parametru lipsă, prag imposibil — fără substituție.

Abia după ce astea sunt agreate se împarte munca.
