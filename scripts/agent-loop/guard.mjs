// Ce nu are voie bucla să facă. Scris primul, deliberat: dacă limitele sunt
// adăugate la sfârșit, sunt limitele pe care le-a permis implementarea, nu
// limitele pe care le-ai cerut tu.
//
// Fiecare regulă de aici vine dintr-o instrucțiune explicită a operatorului,
// citată în comentariu. Nu inventa altele și nu le relaxa fiindcă o rundă e
// blocată — o rundă blocată e un rezultat valid.

import { execSync } from "node:child_process";

// „Verifică ce ramuri declanșează deploy automat. Nu face push pe ele."
// Verificat în render.yaml + .github/workflows/: deploy-ul urmărește gExX7,
// main și apex-deploy. tests.yml pornește pe gexx7-6n4pr9 — CI, nu deploy.
export const DEPLOY_BRANCHES = [
  "claude/arcads-external-api-gExX7",
  "main",
  "apex-deploy",
  "release/apex-bot",
];

// „Nu atinge gates.py, setările de mediu sau public/." (Codex, confirmat)
// gates.authorize_order / authorize_close sunt singurele care pot permite un
// ordin. O buclă automată nu are ce căuta acolo.
export const FROZEN_PATHS = [
  "apex-forex-bot/apex/gates.py",
  "public/",
  ".env",
  "render.yaml",
  ".github/workflows/",
];

// „Nu modifica PAPER_TRADING, CTRADER_ENV sau BROKER."
// „nu comuta tu EV_GATE_MODE — trecerea pe enforce e decizia operatorului."
export const FROZEN_SETTINGS = [
  "EV_GATE_MODE", "PAPER_TRADING", "CTRADER_ENV", "BROKER",
  "TOKEN_ENCRYPTION_KEY", "CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET",
];

const sh = (cmd) => execSync(cmd, { encoding: "utf8" }).trim();

export function currentBranch() {
  return sh("git rev-parse --abbrev-ref HEAD");
}

/** Aruncă dacă ramura curentă declanșează un deploy. Rulat ÎNAINTE de orice rundă. */
export function assertSafeBranch() {
  const b = currentBranch();
  if (DEPLOY_BRANCHES.includes(b)) {
    throw new Error(
      `OPRIT: ești pe '${b}', care declanșează deploy automat.\n` +
      `Bucla nu rulează pe ramuri cu deploy. Treci pe o ramură de lucru:\n` +
      `    git checkout -b work/$(date +%Y%m%d)`
    );
  }
  return b;
}

/** Aruncă dacă runda a atins un fișier înghețat. Rulat DUPĂ fiecare agent. */
export function assertNoFrozenChanges() {
  const changed = sh("git status --porcelain")
    .split("\n").filter(Boolean).map((l) => l.slice(3).trim());
  const hits = changed.filter((f) =>
    FROZEN_PATHS.some((p) => f === p || f.startsWith(p)));
  if (hits.length) {
    throw new Error(
      `OPRIT: runda a modificat fișiere interzise:\n  ${hits.join("\n  ")}\n` +
      `Nimic nu s-a commituit. Verifică manual cu 'git diff'.`
    );
  }
  return changed;
}

/** Aruncă dacă diff-ul atinge o setare înghețată. Prinde și un one-liner strecurat. */
export function assertNoFrozenSettings() {
  let diff = "";
  try { diff = sh("git diff -U0"); } catch { return; }
  const added = diff.split("\n").filter((l) => l.startsWith("+") && !l.startsWith("+++"));
  const hits = FROZEN_SETTINGS.filter((s) => added.some((l) => l.includes(s)));
  if (hits.length) {
    throw new Error(
      `OPRIT: runda atinge setări care sunt decizia ta, nu a buclei:\n  ${hits.join(", ")}\n` +
      `Trecerea pe enforce, live sau alt broker nu se face automat.`
    );
  }
}

/** Push doar pe ramura curentă, și doar dacă nu e una cu deploy. */
export function safePush() {
  const b = assertSafeBranch();
  execSync(`git push -u origin ${b}`, { stdio: "inherit" });
  return b;
}

