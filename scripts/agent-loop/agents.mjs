// Cum vorbește bucla cu fiecare agent.
//
// Nu există canal direct între Claude Code și Codex, și nu e nevoie de unul.
// Fiecare agent e invocat ca proces, în modul lui neinteractiv, cu repo-ul ca
// memorie comună. Asta e mai bun decât un canal direct: are istoric în git,
// supraviețuiește oricărei sesiuni, și poți citi tu însuți ce și-au spus.

import { spawn, execFileSync } from "node:child_process";

const isWin = process.platform === "win32";

/** Găsește un executabil fără să pice dacă lipsește. */
function which(bin) {
  try {
    const out = execFileSync(isWin ? "where" : "which", [bin],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
    return out.split(/\r?\n/).find(Boolean) || null;
  } catch { return null; }
}

export const AGENTS = {
  claude: {
    label: "Claude Code",
    bin: "claude",
    // -p rulează neinteractiv și scrie răspunsul la stdout.
    args: (prompt) => ["-p", prompt, "--permission-mode", "acceptEdits"],
    install: "npm i -g @anthropic-ai/claude-code    (apoi: claude login)",
  },
  codex: {
    label: "Codex",
    bin: "codex",
    // `codex exec` e modul neinteractiv al CLI-ului OpenAI Codex.
    args: (prompt) => ["exec", prompt],
    install: "npm i -g @openai/codex    (apoi: codex login)\n" +
             "    Atenție: Codex Desktop e o aplicație SEPARATĂ și nu oferă CLI-ul.\n" +
             "    Bucla are nevoie de comanda 'codex' în terminal, nu de aplicație.",
  },
};

/** Ce e instalat și ce nu. Rulat înainte de prima rundă, ca să nu descoperi la mijloc. */
export function checkAgents() {
  const report = [];
  for (const [key, a] of Object.entries(AGENTS)) {
    const path = which(a.bin);
    report.push({ key, label: a.label, ok: Boolean(path), path, install: a.install });
  }
  return report;
}

/** Rulează un agent și întoarce ce a scris. Timeout, ca o rundă blocată să nu blocheze bucla. */
export function runAgent(key, prompt, { timeoutMs = 20 * 60_000, cwd } = {}) {
  const a = AGENTS[key];
  if (!a) throw new Error(`agent necunoscut: ${key}`);
  return new Promise((resolve) => {
    const started = Date.now();
    const child = spawn(a.bin, a.args(prompt), {
      cwd, shell: isWin, env: process.env,
    });
    let out = "", err = "";
    child.stdout.on("data", (d) => { const s = String(d); out += s; process.stdout.write(s); });
    child.stderr.on("data", (d) => { err += String(d); });
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      resolve({ ok: false, out, err: err + "\n[buclă] timeout depășit", timedOut: true,
                seconds: Math.round((Date.now() - started) / 1000) });
    }, timeoutMs);
    child.on("error", (e) => {
      clearTimeout(timer);
      resolve({ ok: false, out, err: `${e.message}\n\nInstalare:\n    ${a.install}`,
                seconds: Math.round((Date.now() - started) / 1000) });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, code, out, err,
                seconds: Math.round((Date.now() - started) / 1000) });
    });
  });
}
