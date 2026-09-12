#!/usr/bin/env node
// Bucla de colaborare Claude Code ↔ Codex.
//
//   Claude Code implementează → testele rulează → Codex recenzează →
//   verdictul intră în HANDOFF.md → runda următoare pornește de acolo.
//
// Repo-ul e memoria comună. Fiecare rundă începe prin a citi HANDOFF.md, deci
// bucla se poate opri și relua oricând fără să piardă contextul — inclusiv
// după ce închizi laptopul.
//
//   node scripts/agent-loop/run.mjs --rounds 3
//   node scripts/agent-loop/run.mjs --check          (doar verifică mediul)
//   node scripts/agent-loop/run.mjs --rounds 1 --push

import { execSync } from "node:child_process";
import { readFileSync, writeFileSync, appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { checkAgents, runAgent } from "./agents.mjs";
import { assertSafeBranch, assertNoFrozenChanges, assertNoFrozenSettings,
         safePush, currentBranch, FROZEN_PATHS } from "./guard.mjs";

const ROOT = execSync("git rev-parse --show-toplevel", { encoding: "utf8" }).trim();
const HANDOFF = join(ROOT, "HANDOFF.md");
const LOGDIR = join(ROOT, ".agent-loop");

const argv = process.argv.slice(2);
const arg = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const has = (n) => argv.includes(n);

const ROUNDS = Number(arg("--rounds", 1));
const PUSH = has("--push");
// --watch: rulează la nesfârșit, cu pauză între runde. Fără VPS, „non-stop"
// înseamnă „cât e laptopul treaz" — asta e tot ce poate oferi cinstit.
const WATCH = has("--watch");
const EVERY_MIN = Number(arg("--every", 15));
const TEST_CMD = arg("--test", "cd apex-forex-bot && python3 tests/test_no_silent_strategy_substitution.py");

const line = (s = "") => console.log(s);
const rule = () => line("─".repeat(66));

function log(name, text) {
  mkdirSync(LOGDIR, { recursive: true });
  const f = join(LOGDIR, `${new Date().toISOString().replace(/[:.]/g, "-")}-${name}.md`);
  writeFileSync(f, text);
  return f;
}

// ── ce i se cere fiecărui agent ───────────────────────────────────────────
// Prompturile poartă limitele. Un agent care nu le vede nu le poate respecta,
// iar guard.mjs le verifică oricum după — cele două straturi sunt intenționate.

const LIMITS = `
LIMITE ABSOLUTE (verificate automat după runda ta; încălcarea oprește bucla):
- NU atinge: ${FROZEN_PATHS.join(", ")}
- NU modifica EV_GATE_MODE, PAPER_TRADING, CTRADER_ENV, BROKER.
- NU face deploy și nu face push pe main / gExX7 / apex-deploy / release.
- NU executa ordine și nu porni botul.
- gates.authorize_order și gates.authorize_close sunt singurele care pot
  permite un ordin. Nu le ocoli niciodată.
- Dacă o schimbare importantă nu e confirmată în HANDOFF.md, propune-o acolo
  în loc să o implementezi.`;

const CLAUDE_PROMPT = `Citește HANDOFF.md și AGENTS.md din rădăcina repo-ului.

Ia URMĂTORUL pas nefăcut din secțiunea "Ce urmează". Un singur pas, nu mai multe.

Reguli de lucru:
- Scrie test înainte de implementare, apoi verifică-l prin mutație: strică
  intenționat codul și confirmă că testul pică. Un test care nu poate pica nu
  e un test.
- Rulează suita înainte să commituți.
- Commit cu mesaj care explică DE CE, nu doar CE.
- La final, actualizează HANDOFF.md: ce ai făcut, ce ai verificat direct
  (cu numere, nu impresii), ce ai găsit și nu era în plan, ce rămâne.
- Dacă pasul următor e ambiguu sau riscant, NU ghici: scrie întrebarea în
  HANDOFF.md sub "ÎNTREBARE PENTRU OPERATOR" și oprește-te.
${LIMITS}`;

const CODEX_PROMPT = `Ești recenzentul. Nu implementezi în runda asta.

Citește HANDOFF.md și diff-ul ultimului commit (git show HEAD).

Verifică, în ordine:
1. Ce afirmă HANDOFF.md chiar se regăsește în cod? Verifică, nu presupune.
2. Testele testează comportament, sau doar text și comentarii?
3. S-a strecurat vreo substituție tăcută — o valoare invalidă care devine un
   default în loc să fie refuzată?
4. Sunt atinse fișiere sau setări interzise?

Scrie verdictul în HANDOFF.md, la început, sub titlul
"## Recenzie Codex — <data>", cu: CE AM VERIFICAT, CE AM GĂSIT (cu fișier:linie),
CE PROPUN, RISCURI. Fii concret; „arată bine" nu e o recenzie.

Dacă găsești o problemă reală, spune clar dacă blochează pasul următor.
${LIMITS}`;

// ── verificarea mediului ──────────────────────────────────────────────────
function preflight() {
  rule(); line("VERIFICARE MEDIU"); rule();
  const agents = checkAgents();
  for (const a of agents) {
    line(`  ${a.ok ? "✅" : "❌"} ${a.label.padEnd(12)} ${a.ok ? a.path : "NEINSTALAT"}`);
    if (!a.ok) line(`     ↳ ${a.install.replace(/\n/g, "\n     ")}`);
  }
  let branch = null, branchOk = true;
  try { branch = assertSafeBranch(); line(`  ✅ ramura       ${branch} (fără deploy)`); }
  catch (e) { branchOk = false; line(`  ❌ ${e.message.split("\n")[0]}`); }
  const dirty = execSync("git status --porcelain", { encoding: "utf8" }).trim();
  line(`  ${dirty ? "⚠️ " : "✅"} arbore       ${dirty ? "are modificări necommituite" : "curat"}`);
  line();
  return { agents, branch, ready: agents.every((a) => a.ok) && branchOk };
}

// ── o rundă ───────────────────────────────────────────────────────────────
async function round(n) {
  rule(); line(`RUNDA ${n} — ${new Date().toISOString().slice(0, 16).replace("T", " ")}`); rule();

  line("\n▶ Claude Code implementează…\n");
  const c = await runAgent("claude", CLAUDE_PROMPT, { cwd: ROOT });
  log(`r${n}-claude`, c.out + "\n\n---STDERR---\n" + c.err);
  if (!c.ok) { line(`\n❌ Claude Code a eșuat după ${c.seconds}s\n${c.err.slice(0, 600)}`); return false; }
  line(`\n✅ Claude Code, ${c.seconds}s`);

  // Limitele se verifică pe ce s-a schimbat efectiv, nu pe ce a promis agentul.
  try { assertNoFrozenChanges(); assertNoFrozenSettings(); }
  catch (e) { line(`\n${e.message}`); return false; }

  line("\n▶ Testele…\n");
  try { execSync(TEST_CMD, { cwd: ROOT, stdio: "inherit", shell: true }); line("\n✅ testele trec"); }
  catch { line("\n❌ TESTELE PICĂ — bucla se oprește. Un agent nu repară o suită roșie nesupravegheat."); return false; }

  const agents = checkAgents();
  if (agents.find((a) => a.key === "codex")?.ok) {
    line("\n▶ Codex recenzează…\n");
    const r = await runAgent("codex", CODEX_PROMPT, { cwd: ROOT });
    log(`r${n}-codex`, r.out + "\n\n---STDERR---\n" + r.err);
    line(r.ok ? `\n✅ Codex, ${r.seconds}s` : `\n⚠️  Codex a eșuat (${r.seconds}s) — runda rămâne validă, recenzia lipsește`);
  } else {
    line("\n⏭  Codex nu e instalat — sar peste recenzie.");
    appendFileSync(HANDOFF, `\n\n> Runda ${n}: recenzia Codex a fost sărită (CLI neinstalat).\n`);
  }

  if (PUSH) { line("\n▶ Push…"); try { line(`✅ pushat pe ${safePush()}`); } catch (e) { line(`❌ ${e.message}`); return false; } }
  return true;
}

// ── main ──────────────────────────────────────────────────────────────────
const pre = preflight();
if (has("--check")) { line(pre.ready ? "Gata de pornire." : "Rezolvă ❌-urile de mai sus, apoi rulează din nou."); process.exit(pre.ready ? 0 : 1); }
if (!pre.branch) process.exit(1);
if (!checkAgents().find((a) => a.key === "claude")?.ok) { line("Claude Code lipsește — bucla nu poate porni."); process.exit(1); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let done = 0, i = 0;
// Ctrl+C o oprește curat, fără să lase o rundă la jumătate.
let stopping = false;
process.on("SIGINT", () => {
  if (stopping) process.exit(130);
  stopping = true;
  line("\n\n⏹  Opresc după runda curentă. Încă un Ctrl+C forțează.");
});

while (!stopping) {
  i++;
  const ok = await round(i);
  if (ok) done++;
  else {
    line(`\nOprit la runda ${i}. Rundele terminate: ${done}.`);
    // În --watch o rundă picată nu e sfârșitul lumii, DAR nu insistăm orbește:
    // dacă testele pică, problema nu se rezolvă repetând. Ieșim.
    break;
  }
  if (!WATCH && i >= ROUNDS) break;
  if (stopping) break;
  if (WATCH) {
    line(`\n⏸  Pauză ${EVERY_MIN} min. Ctrl+C oprește. (runde reușite: ${done})\n`);
    await sleep(EVERY_MIN * 60_000);
  }
}
rule();
line(`${done} ${done === 1 ? "rundă reușită" : "runde reușite"}. Jurnale în .agent-loop/`);
line(`Ramura: ${currentBranch()}${PUSH ? " (pushată)" : " (nepushată — adaugă --push)"}`);
if (!WATCH) line(`Continuu: node scripts/agent-loop/run.mjs --watch --every 15 --push`);
rule();
