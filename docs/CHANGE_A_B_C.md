# A → B → C — inventar înainte de codare

**Stare:** ordine confirmată de Codex. **Nimic implementat.** Acest document
listează exact ce se atinge, ce teste apar și ce teste existente sunt în risc.

**Bază:** `1bea525` (producție curentă). **Nu se ating:** `apex/gates.py`,
setări de mediu (`PAPER_TRADING`, `CTRADER_ENV`, `BROKER`), `public/`.

---

## Constrângeri descoperite la verificare — citiți înainte de implementare

### 1. Registrul de strategii e GOL la import (blochează A dacă se ignoră)

```
from apex import strategy_api            -> available() == 0
+ strategy_modules, _extra, _specialized -> available() == 17
```

Registrul se populează prin **efect secundar** al importului modulelor de
strategie. `control_actions.py` importă azi doar `automation, user_store,
user_loop, config`.

**Consecință:** o listă construită la nivel de modul în `control_actions.py`
poate fi **goală**, și atunci A respinge **fiecare** strategie validă. Exact
riscul semnalat, dar mai grav decât părea.

**Cerință:** lista se calculează **leneș, în interiorul validării**, nu la
import.

**Precedent existent în cod:** `telegram.py:3699` face deja
`{sid: sid for sid in strategy_api.available()}` **în interiorul**
`_handle_strategy()`, la apel. Același tipar.

### 2. Cinci din șase apelanți ai `signal_for_mode` crapă pe `None` (schimbă forma lui C)

| Apelant | Funcție | Consumă | `None` |
|---|---|---|---|
| `ai.py:217` | `get_signal()` | `rule_sig.get(...)` | ❌ AttributeError |
| `strategy_modules.py:48` | `signal()` | `self.stamp(verdict)` | ❌ |
| `strategy_modules.py:58` | `advise_risk()` | `own.get(...)` | ❌ AttributeError |
| `strategy_modules.py:81` | `exit()` | `verdict.get(...)` | ❌ AttributeError |
| `telegram.py:3626,3635` | `_sim_strategy()` | `sx.get(...)` | ❌ AttributeError |
| `scanner.py:143` | `scan_symbol()` | `... or {}` în `try` | ✅ sigur |

**Consecință:** „întoarce `None`" nu e forma potrivită — ar transforma o
strategie invalidă dintr-o substituție tăcută într-o excepție în cinci locuri
neprotejate.

**Două variante, ambele satisfac criteriile tale:**

- **C-excepție** — `signal_for_mode` ridică `UnknownStrategyMode`.
  `scanner.py` o prinde deja (→ `setups.invalid`, corect). Ceilalți **cinci**
  au nevoie de tratare explicită. Refuz cel mai vizibil, cost cel mai mare.
- **C-HOLD** — întoarce un verdict `{"action": "HOLD", "reasoning": "<mod>
  necunoscut — nicio intrare"}`. Sigur la toate șase fără modificarea lor,
  păstrează numele invalid în motiv, zero ordine.

**Recomandarea mea: C-HOLD.** E refuz explicit, nu fallback — nu tranzacționează
nimic și numește valoarea invalidă. C-excepție cere atingerea a cinci fișiere
în plus pentru același rezultat observabil. **Decizia e a ta** — spune care.

---

## A — validare la scriere

**Modificat:** `apex/control_actions.py` — `_ENUM_KEYS` (linia 99) și
`coerce_setting()` (104-133).

`strategy`, `symbol`, `timeframe` sunt azi singurele trei chei din `_SETTABLE`
(16 total) fără nicio validare — restul de 13 au conversie de tip.

Sursa listei: `strategy_api.available()` ∪ `ai.STRATEGY_MODES` ∪ `{"auto"}`,
**calculată la apel**. Fără liste scrise de mână.

**Test nou:** `tests/test_setting_value_validation.py`
- fiecare strategie din registru e acceptată
- id necunoscut **respins la scriere**, mesajul listează valorile permise
- idem pentru `symbol` și `timeframe`
- **registru, nu listă:** înregistrează o strategie fictivă în `_REGISTRY` și
  verifică că devine setabilă — pică dacă lista e duplicată
- **importul leneș:** validarea funcționează chiar dacă modulele de strategie
  nu au fost importate înainte de `control_actions`

**Teste existente în risc:** `test_control_actions.py`,
`test_remote_config_allowlist.py`, `test_config_reaches_loop.py`.
Dacă vreunul setează o strategie inventată, va începe să pice — **corect**,
dar trebuie actualizat deliberat, nu ocolit.

## B — refuz la decizie

**Modificat:** `apex/user_loop.py` — `_rule_signal()`, blocul 3181-3203.

Azi apărarea de la 3194 e **în ramura `except`**: acoperă „modulul a crăpat",
nu „modulul nu există". Un `strategy_api.get()` care întoarce `None` sare tot
blocul `if _strategy is not None` și cade pe `ai.signal_for_mode` la 3203.

Se extinde la: modul absent **și** necunoscut în `ai.STRATEGY_MODES` → `HOLD`,
cu motivul care păstrează numele cerut.

**Test nou:** `tests/test_unknown_strategy_holds.py`
- modul absent → `HOLD`, **zero** apeluri `place_order`
- motivul conține **valoarea invalidă**, nu pe cea substituită
- modul prezent care aruncă → comportament actual, **neschimbat**
- **mutație:** reintroducerea căderii pe `signal_for_mode` trebuie să pice testul

**Teste existente în risc:** `test_strategy_registry.py:329` afirmă literal
`"ai.signal_for_mode(active_mode, ind, strat_data, open_pos)"` în sursă.
Rămâne valid dacă linia nu se șterge, dar dacă se restructurează trebuie
actualizat — cu aserțiune pe **comportament**, nu pe șir.
Plus `test_strategy_equivalence.py`, `test_client_experience.py`.

## C — refuz la sursă

**Modificat:** `apex/ai.py:1053-1055` (`signal_for_mode`).
**Plus, doar la varianta C-excepție:** `ai.py:217`, `strategy_modules.py:48/58/81`,
`telegram.py:3626/3635`.

**Test nou:** `tests/test_signal_for_mode_refuses.py`
- mod necunoscut → refuz, niciodată un verdict de mean reversion
- fiecare mod cunoscut → neschimbat
- **fiecare din cei șase apelanți** tratează refuzul fără să crape
- mutație: reintroducerea `default=STRATEGY_MODES["mean_reversion"]` pică

**Teste existente în risc:** `test_ai_contract.py:144`, `test_ai.py:98`,
`test_strategy_equivalence.py` (5 apeluri). Toate folosesc moduri **valide**,
deci ar trebui să treacă neschimbate — de confirmat la rulare.

---

## Traversal — testul care contează cel mai mult

**Nou:** `tests/test_no_silent_strategy_substitution.py`

Structural, pe AST, în tiparul `test_live_path_invariants.py` — **nu pe șiruri
de text**. Afirmă că nicio cale de la o valoare de configurație la o decizie de
tranzacționare nu poate schimba tăcut strategia.

E singurul test care rămâne valid dacă cineva rescrie ulterior oricare din cele
trei locuri.

---

## Rezumat: ce se atinge

| Fișier | A | B | C |
|---|---|---|---|
| `apex/control_actions.py` | ✏️ | | |
| `apex/user_loop.py` | | ✏️ | |
| `apex/ai.py` | | | ✏️ |
| `apex/strategy_modules.py` | | | ✏️ doar C-excepție |
| `apex/telegram.py` | | | ✏️ doar C-excepție |

**Teste noi:** 4. **Teste existente de reverificat:** 10.
**Neatinse, confirmat:** `gates.py`, `public/`, setările de mediu.

## Ce aștept de la Codex

1. **C-HOLD sau C-excepție?** Datele sunt în §2 de mai sus.
2. Obiecții la calcularea leneșă a listei din A?
3. Confirmarea că testele existente pe care le-am marcat „în risc" se
   actualizează deliberat, nu se ocolesc.

**Nicio linie de cod până la confirmare.**
