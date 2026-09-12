# Legătura Claude Code ↔ Codex, pe laptop, în VS Code

Ce e aici: o buclă care rulează pe calculatorul tău și îi pune pe cei doi
agenți să lucreze pe același repo, pe rând, cu testele între ei.

## Ce e și ce nu e

**Nu există canal direct între cei doi agenți, și nu e nevoie de unul.**
Bucla îi invocă pe rând ca procese, iar repo-ul e memoria comună.

Asta nu e un compromis, e varianta mai bună: ai istoric în git, poți citi
singur ce și-au spus, iar munca supraviețuiește oricărei sesiuni închise. Un
canal direct ar fi fost o conversație pe care nimeni nu o poate audita.

```
   HANDOFF.md
        │
        ▼
   Claude Code  ──implementează──▶  commit
        │                             │
        │                             ▼
        │                          testele
        │                             │
        │                    trec ────┴──── pică → bucla se OPREȘTE
        │                     │
        │                     ▼
        └──────────────    Codex  ──recenzează──▶ verdict în HANDOFF.md
                                                          │
                                              runda următoare pornește de aici
```

## Prima dată

**1. Instalează cele două CLI-uri.**

```bash
npm i -g @anthropic-ai/claude-code
claude login

npm i -g @openai/codex
codex login
```

### Dacă PowerShell refuză npm

```
npm : File C:\Program Files\nodejs\npm.ps1 cannot be loaded because
running scripts is disabled on this system.
```

Nu e o problemă de npm și nici de Codex — npm pe Windows are un wrapper
`.ps1`, iar politica de execuție PowerShell îl refuză. Orice comandă npm ar
pica la fel.

Cea mai simplă rezolvare, fără să schimbi nimic în sistem — adaugă `.cmd`:

```powershell
npm.cmd i -g @openai/codex
npm.cmd i -g @anthropic-ai/claude-code
```

Sau rezolvi o dată, pentru contul tău:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

`CurrentUser`, nu tot sistemul. `RemoteSigned` lasă scripturile locale să
ruleze și cere semnătură pentru cele descărcate — e setarea normală de lucru.
Nu folosi `Unrestricted` sau `Bypass` permanent: alea dezactivează protecția
cu totul, iar aici nu ai nevoie de asta.

`node` e un `.exe`, nu un `.ps1`, deci bucla însăși rulează chiar dacă
politica ramane restrictiva.

⚠️ **Codex Desktop e o aplicație separată și nu îți dă comanda `codex`.**
Aici a fost confuzia data trecută. Bucla are nevoie de comanda din terminal.
Verifici cu `codex --version`. Dacă zice „command not found", nu e instalat,
oricâte ferestre Codex ai deschise.

**2. Treci pe o ramură de lucru.** Bucla refuză să pornească pe o ramură cu
deploy — nu ca politețe, ci pentru că verifică și oprește.

```bash
git checkout -b work/$(date +%Y%m%d)
```

**3. Verifică mediul.**

```bash
node scripts/agent-loop/run.mjs --check
```

Îți spune exact ce lipsește. Nu trece mai departe până nu e totul verde.

## Rulare

În VS Code: `Ctrl+Shift+P` → **Tasks: Run Task** → alegi.

Sau în terminal:

```bash
node scripts/agent-loop/run.mjs --rounds 1     # o rundă
node scripts/agent-loop/run.mjs --rounds 3     # trei la rând
node scripts/agent-loop/run.mjs --rounds 1 --push
```

Jurnalele fiecărei runde ajung în `.agent-loop/` (ignorat de git).

## Ce oprește bucla

Sunt patru opriri, și toate sunt intenționate:

| Situație | Ce se întâmplă |
|---|---|
| Testele pică | Se oprește imediat. Un agent nu reparară o suită roșie nesupravegheat. |
| S-a atins `gates.py`, `public/`, `.env`, `render.yaml`, workflows | Se oprește, nu commitează. |
| Apare `EV_GATE_MODE`, `PAPER_TRADING`, `CTRADER_ENV`, `BROKER` în diff | Se oprește. Alea sunt decizia ta. |
| Ești pe `main`, `gExX7`, `apex-deploy`, `release/*` | Nici nu pornește. |

Limitele sunt în două locuri deodată: în prompturile agenților **și** în
`guard.mjs`, care verifică după fiecare rundă ce s-a schimbat efectiv. Un
agent poate ignora o instrucțiune din prompt; nu poate ignora o verificare pe
`git status`.

## Ce NU face bucla

Ca să nu te bazezi pe ce nu există:

- **Nu rulează 24/7.** Rulează cât o lași pornită. Laptopul intră în sleep,
  bucla se oprește. Pentru non-stop ai nevoie de un VPS.
- **Nu decide singură lucrurile mari.** Dacă pasul următor e ambiguu, agentul
  scrie întrebarea în HANDOFF.md sub „ÎNTREBARE PENTRU OPERATOR" și se oprește.
- **Nu face deploy, niciodată.**
- **Nu comută EV gate-ul pe enforce.** Aia rămâne a ta, după ce citești
  logurile shadow.

## Dacă Codex nu poate scrie în repo

Eroarea `403 Resource not accessible by integration` înseamnă că aplicația
GitHub are doar drept de citire. Se rezolvă în două minute:

GitHub → Settings → Applications → aplicația Codex → Permissions →
**Contents: Read and write** (și Issues, dacă vrei să comunice și prin issues).

Până atunci Codex citește dar nu scrie, iar bucla merge mai departe fără
recenzia lui — o notează în HANDOFF.md ca sărită, ca să nu pară că a aprobat.

## Fișiere

```
scripts/agent-loop/guard.mjs    limitele — scrise primele, verificate automat
scripts/agent-loop/agents.mjs   cum se invocă fiecare CLI, ce faci dacă lipsește
scripts/agent-loop/run.mjs      bucla
.vscode/tasks.json              aceleași comenzi, din paleta VS Code
```

## Continuu, fără VPS

```bash
node scripts/agent-loop/run.mjs --watch --every 15 --push
```

Rulează rundă după rundă, cu 15 minute pauză între ele, până o oprești cu
`Ctrl+C` (oprește curat, după runda curentă — al doilea Ctrl+C forțează).

Dacă o rundă pică, se oprește. Nu reîncearcă la nesfârșit: dacă testele pică,
problema nu se rezolvă repetând aceeași rundă de 40 de ori peste noapte.

### Ca să nu se oprească la sleep (Windows)

Bucla moare când laptopul adoarme. Cât timp o lași să lucreze:

```powershell
# ține laptopul treaz (schimbă doar cât e in priza)
powercfg /change standby-timeout-ac 0
powercfg /change monitor-timeout-ac 10

# inapoi la normal cand ai terminat
powercfg /change standby-timeout-ac 30
```

Sau, mai simplu, lași bucla să ruleze în terminalul din VS Code cât ești la
laptop, și o oprești când pleci. Munca e commituită după fiecare rundă, deci
nu pierzi nimic dacă o întrerupi.

### Repornire automată după restart (opțional)

Task Scheduler → Create Task → Trigger: *At log on* → Action:

```
Program:   node
Arguments: scripts\agent-loop\run.mjs --watch --every 15 --push
Start in:  C:\cale\catre\autoflow-backend
```

Asta repornește bucla la fiecare login. Tot nu e 24/7 — e „de fiecare dată
când pornești laptopul".

### Ce merge deja fără laptop și fără VPS

Verificarea zilnică a EV gate-ului rulează în cloud, programată, și îți
trimite raportul dimineața fără ca laptopul tău să fie pornit. Genul ăsta de
sarcină — citește starea, raportează, nu modifică nimic — nu are nevoie nici
de laptop, nici de VPS.

Ce are nevoie de laptop e bucla care **scrie cod**, fiindcă acolo rulează
CLI-urile celor doi agenți.
