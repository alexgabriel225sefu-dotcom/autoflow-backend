# A → B → C — predare pentru recenzia Codex

**STATUS:** READY_FOR_CODEX_REVIEW

**BRANCH:** `claude/apex4traders-ab-c-hold` (pornit din `handoff/apex4traders-v2`)

**COMMIT:** `a753adcfddfb9cce39a53d00328816371686e7dc`

---

## FILES_CHANGED

```
apex-forex-bot/apex/control_actions.py     +110 −9    A — validare la scriere
apex-forex-bot/apex/forex.py                +21       A — TIMEFRAMES (vezi nota 2)
apex-forex-bot/apex/user_loop.py            +55 −22   B — refuz la decizie
apex-forex-bot/apex/ai.py                   +73 −9    C-HOLD + instanța a patra
apex-forex-bot/tests/test_setting_value_validation.py       nou, 282 linii
apex-forex-bot/tests/test_unknown_strategy_holds.py         nou, 221 linii
apex-forex-bot/tests/test_signal_for_mode_refuses.py        nou, 173 linii
apex-forex-bot/tests/test_no_silent_strategy_substitution.py nou, 218 linii
apex-forex-bot/tests/test_strategy_registry.py              actualizat, +24 −8
```

`HANDOFF.md` **nu** a fost modificat pe ramura asta. `gates.py`, setările de
mediu, `public/`, OAuth-ul și execuția brokerului — neatinse.

## TESTS_RUN

```
python apex-forex-bot/tests/run_all.py      # comanda din AGENTS.md
```

`pytest -q` **nu a putut rula**: pytest nu e instalat în mediul de execuție.
Suita proiectului e alcătuită din scripturi executabile, iar `run_all.py` e
runnerul oficial declarat în `AGENTS.md` — el a fost folosit.

## TESTS_PASSING

**146 / 146 fișiere de test.**

Cele patru teste noi, cu numărul de verificări și mutanți omorâți:

| Test | Verificări | Mutanți |
|---|---|---|
| `test_setting_value_validation.py` | 42 | 12/12 |
| `test_unknown_strategy_holds.py` | 35 | 8/8 |
| `test_signal_for_mode_refuses.py` | 59 | 8/8 |
| `test_no_silent_strategy_substitution.py` | 21 | 2/2 |

Total **157 verificări**, **30 de mutanți omorâți, zero supraviețuitori**.

Cele opt teste marcate „în risc" în brief — toate trec:
`test_control_actions`, `test_remote_config_allowlist`, `test_config_reaches_loop`,
`test_strategy_registry`, `test_strategy_equivalence`, `test_client_experience`,
`test_ai_contract`, `test_ai`.

Doar unul a avut nevoie de actualizare deliberată — vezi nota 3.

## TESTS_FAILING

Niciunul.

---

## SECURITY_NOTES

**Configurația invalidă nu ajunge în storage.** `coerce_setting()` ridică
`ValueError` la `control_actions.py:389`; `user_store.update()` e la linia 411.
Excepția precedă orice scriere, deci valoarea respinsă nu e persistată.

**Zero ordine pentru un mod necunoscut — verificat pe toți cei șase apelanți:**

| Apelant | Verdict pentru mod necunoscut |
|---|---|
| `ai.signal_for_mode` | HOLD |
| `ai.get_signal` | HOLD (iese pe return-ul timpuriu) |
| `strategy_modules.signal` | HOLD |
| `strategy_modules.advise_risk` | multiplicator, nu ordin |
| `strategy_modules.exit` | HOLD, `exit=False` |
| `scanner.scan_symbol` | HOLD → niciun setup |

Niciunul nu aruncă excepție. Niciunul nu poate produce o intrare.

**Legătura HOLD → fără ordin e asertată, nu presupusă.** Poarta de intrare din
`user_loop.py` cere `action in ("BUY", "SELL")`; verdictul refuzului pică acel
test. Asta e verificat în `test_unknown_strategy_holds.py`, secțiunea 7.

**`gates.authorize_order` / `authorize_close` — necoate, neocolite.**

---

## KNOWN_LIMITATIONS

### 1. Termenul `| {"auto"}` nu e scris literal — dar mulțimea e identică

Brief-ul cere o sursă **echivalentă cu**
`set(strategy_api.available()) | set(ai.STRATEGY_MODES) | {"auto"}`.

Implementarea scrie `set(strategy_api.available()) | set(ai.STRATEGY_MODES)`.

Verificat prin execuție: **ambele produc exact 17 valori, diferență zero,
`auto` prezent**. Motivul: `auto` e el însuși un modul înregistrat în registru
ȘI o cheie în `STRATEGY_MODES`, deci al treilea termen e matematic redundant.

Fusese scris inițial, apoi eliminat: niciun mutant al funcției nu putea face
testele să observe absența lui. Cod care nu poate eșua se citește ca o
garanție fără să garanteze nimic. Dacă preferi termenul literal pentru
lizibilitate, îl pun înapoi — nu schimbă comportamentul.

### 2. `timeframe` nu citește direct `_period()` — invariantul de arhitectură o interzice

Sursa de adevăr pentru timeframe-uri e harta `_period()` din modulul brokerului
cTrader. `control_actions.py` **nu are voie să o importe**:
`test_failure_matrix.py` interzice oricărui modul din afara nucleului de
tranzacționare să importe un broker, iar `control_actions.py` e chiar interfața
de operator pe care regula o protejează.

Testul nu a fost slăbit. Dependența a fost inversată: setul stă în
`apex/forex.py::TIMEFRAMES`, iar `test_setting_value_validation.py` secțiunea 7
asertează egalitatea cu cheile reale ale brokerului. Mutanți verificați în
ambele direcții — și scoaterea unui timeframe din oglindă, și adăugarea unuia
pe care brokerul nu-l are, fac testul să pice.

Nu e o listă scrisă de mână: e o oglindă cu egalitate impusă prin test.

### 3. Un singur test vechi actualizat deliberat

`test_strategy_registry.py` cerea **textual** un fallback NECONDIȚIONAT la
motor. Jumătatea corectă a intenției — „o problemă de registru nu trebuie să
oprească un cont care tranzacționează un mod pe care motorul chiar îl are" — e
păstrată. Cealaltă jumătate e acum condiționată, deci garda e asertată lângă
fallback. Motivul e scris în test, deasupra aserțiunii.

### 4. Mesajul de eroare pentru `symbol` descrie regula, nu enumeră valorile

`forex.is_tradeable()` e un **predicat**, nu o listă: acceptă perechile FX cu
picior USD plus metale. O enumerare ar fi o a doua copie care derivează de la
cea după care tranzacționează bucla. Mesajul spune regula:
`"'symbol' is not an instrument this platform trades (got 'US400'). Spot FX
with a USD leg, plus metals."`

Conține cheia și valoarea respinsă. Dacă vrei totuși o enumerare, spune.

### 5. `exit_mode` și `style` rămân nevalidate — deliberat

Sunt singurele alte chei din `_SETTABLE` fără validare de valoare, dar niciuna
nu substituie un **comportament**: `EXIT_MODE` e pus în cfg la
`user_loop.py:1127` și **nu e citit nicăieri** (ieșirea reală vine din
`trailing` + `breakeven_r`, ambele validate), iar `style` ajunge doar la o
etichetă de onboarding. Criteriul rundei e substituția tăcută a unui
comportament — ele nu-l îndeplinesc. Dacă `EXIT_MODE` se conectează vreodată la
buclă, intră în același tabel.

---

## ⚠️ INSTANȚA A PATRA — nu era în brief, și fără ea C ar fi fost cod mort

Testul structural pe AST a găsit-o imediat ce a fost scris. `ai.get_signal()`
avea, **cu o linie înainte** de apelul la `signal_for_mode()`:

```python
mode = (mode or "mean_reversion").lower()
if mode not in _MODE_INTRO:
    mode = "mean_reversion"
```

Modul invalid era rescris în `mean_reversion` **înainte** ca refuzul din C să
apuce să se declanșeze. Adică: C, singură, nu ar fi schimbat nimic pe calea pe
care trece fiecare intrare confirmată de AI — singurul apelant real fiind
`user_loop.py:3661`.

Nu e un `.get()` cu default și nu e un `or`: e o **reatribuire**. Un test pe
șiruri de text nu ar fi găsit-o niciodată. Traversal-ul pe AST cerut în brief a
găsit-o din prima rulare.

Rescrierea e ștearsă. Un mod necunoscut ajunge acum la `signal_for_mode()`,
primește HOLD, și iese pe return-ul timpuriu `if rule_action in ("CLOSE",
"HOLD")` — deci nu ajunge niciodată la prompt.

**Colateral:** `_MODE_INTRO` avea 9 chei din 10 (lipsea `auto`), iar promptul
citește `_MODE_INTRO[mode]` cu subscript direct. Fără rescriere, asta era un
KeyError latent. Am adăugat intrarea `auto` și un test care cere egalitatea
celor două seturi de chei, ca o strategie nouă să nu poată fi adăugată fără
textul ei de prompt.

---

## NEXT_RECOMMENDED_STEP

1. **Recenzia ta pe `a753adcfddfb9cce39a53d00328816371686e7dc`.** Mă interesează în special: mai există vreo cale
   de la configurație la decizie care poate schimba tăcut strategia și pe care
   cele patru teste nu o acoperă? Instanța a patra m-a învățat că analiza pe
   apelanți nu e suficientă — trebuie urmărit fluxul valorii, nu doar cine
   cheamă pe cine.

2. **Decizia operatorului** pe cele două puncte deschise din limitări:
   termenul `| {"auto"}` literal (nota 1) și enumerarea pentru `symbol`
   (nota 4). Ambele sunt cosmetice; niciuna nu schimbă comportamentul.

3. **Abia apoi** contractele RuleDoc și dashboard-ul din `ARCHITECTURE_V2.md`.
   Runda asta a închis substituția tăcută și a lăsat motorul fail-closed, care
   era condiția pentru etapa următoare.

---

*Fără deploy. Fără trading live. Fără merge. Niciun secret, token sau dată de
cont în acest document.*
