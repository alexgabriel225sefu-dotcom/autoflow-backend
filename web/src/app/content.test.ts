/**
 * What the product is allowed to say.
 *
 * The previous product's copy survived three separate cleanups by hiding in
 * pages nobody was looking at — a metadata title, a legal page linked only
 * from a footer, a post-purchase route reachable only by URL. A grep run by
 * hand finds it once; a test finds it every time.
 *
 * Comments are stripped before searching, because several files legitimately
 * explain in a comment what the old copy said and why it was removed. The
 * test is about what a client can read, not about what a maintainer can.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");

function sources(dir = SRC, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) sources(full, out);
    else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

/** The file with `//` and block comments removed. */
function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

const FILES = sources().map((f) => ({
  path: f.replace(`${SRC}/`, ""),
  body: withoutComments(readFileSync(f, "utf8")),
}));

describe("the previous product's identity is gone from what clients read", () => {
  it.each([
    ["Apex Trade Bot", /Apex\s*Trade\s*Bot/i],
    ["a crypto product", /crypto(currency)?\b/i],
    ["a source-code sale", /source\s*code/i],
    ["the old price", /\$\s*297|\b29700\b/],
    ["the old SKU", /apex-bot/i],
    ["another brand's support address", /aicashsystem/i],
  ])("no %s", (_label, pattern) => {
    const hits = FILES.filter((f) => pattern.test(f.body)).map((f) => f.path);
    expect(hits, `found in ${hits.join(", ")}`).toEqual([]);
  });

  it("the word 'bot' is not used for the product", () => {
    // "robot", "bottom" and "botanical" are not the thing being banned.
    const hits = FILES.filter((f) => /\bbots?\b/i.test(f.body)).map((f) => f.path);
    expect(hits, `found in ${hits.join(", ")}`).toEqual([]);
  });
});

describe("no profit claims and no invented figures", () => {
  it.each([
    [/guaranteed\s+(profit|return|income)/i, "a guarantee of profit"],
    [/\b(risk[-\s]?free|no\s+risk)\b/i, "a risk-free claim"],
    [/\bwin\s*rate\b/i, "a win rate"],
    [/\b\d+(\.\d+)?%\s*(monthly|weekly|daily|annual|per\s+month|return)/i, "a periodic return"],
    [/passive\s+income/i, "passive income"],
  ])("nothing matching %s", (pattern, label) => {
    const hits = FILES.filter((f) => pattern.test(f.body)).map((f) => f.path);
    expect(hits, `${label} found in ${hits.join(", ")}`).toEqual([]);
  });
});

describe("nothing external is embedded", () => {
  it("no iframe, no third-party script tag, no tracking pixel", () => {
    for (const f of FILES) {
      expect(f.body, `${f.path} contains an iframe`).not.toMatch(/<iframe/i);
      expect(f.body, `${f.path} loads an external script`)
        .not.toMatch(/<script\s+[^>]*src=["']https?:/i);
      for (const tracker of ["googletagmanager", "google-analytics", "gtag(",
                             "fbq(", "hotjar", "mixpanel", "segment.com",
                             "plausible.io", "posthog"]) {
        expect(f.body, `${f.path} references ${tracker}`).not.toContain(tracker);
      }
    }
  });
});

describe("the statements the product must make", () => {
  const terms = FILES.find((f) => f.path === "app/terms/page.tsx")!.body;
  const privacy = FILES.find((f) => f.path === "app/privacy/page.tsx")!.body;

  it.each([
    ["Apex4Traders is software", /Apex4Traders is\s+software/i],
    ["the client connects their own cTrader account", /cTrader account that you\s+choose/i],
    ["the client can disconnect it", /disconnect the account at any\s+time/i],
    ["the platform holds no funds", /never takes\s+custody/i],
    ["it is not a financial adviser", /not a financial\s+adviser/i],
    ["trading carries risk", /Trading carries\s+risk/i],
    ["demo is recommended", /demo account first is\s+strongly recommended/i],
    ["live trading is not available", /Live trading is not available in this\s+release/i],
  ])("the Terms state that %s", (_label, pattern) => {
    expect(terms).toMatch(pattern);
  });

  it("the Privacy policy states that broker tokens never reach the browser", () => {
    expect(privacy).toMatch(/never sent to your\s+browser/i);
  });

  it("the Privacy policy states there is no tracking", () => {
    expect(privacy).toMatch(/no advertising or analytics\s+tracking/i);
  });
});

describe("unfinished legal values are visibly unfinished", () => {
  const legal = FILES.filter((f) =>
    f.path === "app/terms/page.tsx" || f.path === "app/privacy/page.tsx");

  it("every placeholder is marked, so it can be found by grep", () => {
    for (const f of legal) {
      expect(f.body, `${f.path} has no placeholders — has it been finalised?`)
        .toContain("TO BE CONFIRMED");
    }
  });

  it("the pages say they are not final", () => {
    for (const f of legal) {
      expect(f.body, `${f.path} does not warn that it is unfinished`)
        .toMatch(/not final/i);
    }
  });

  /**
   * This test is meant to be deleted.
   *
   * When the owner supplies the values in docs/LEGAL_LAUNCH_BLOCKERS.md, the
   * placeholders go and this whole block goes with them. Until then it is the
   * thing that stops "we'll fill that in later" from becoming "we shipped".
   */
  it("the blockers document exists and lists them", () => {
    const doc = readFileSync(
      join(__dirname, "..", "..", "..", "docs", "LEGAL_LAUNCH_BLOCKERS.md"), "utf8");
    expect(doc).toContain("TO BE CONFIRMED");
    for (const id of ["L1", "L2", "L3", "L4"]) expect(doc).toContain(id);
  });
});

/**
 * The UI and the server have to say the same thing about live trading.
 *
 * The dashboard renders a constant sentence rather than whatever verdict
 * `me` last returned, because the account picker and `me` are polled on
 * different clocks. A constant can drift from the server's refusal, so this
 * reads the Python and pins the two together. If somebody softens one of
 * them, this fails rather than letting the product and its API disagree
 * about whether real money can move.
 */
describe("the UI and the backend refuse live trading in the same words", () => {
  const py = readFileSync(
    join(__dirname, "..", "..", "..", "apex-forex-bot", "apex", "platform",
      "entitlement.py"), "utf8");

  it("the backend's refusal is the sentence we think it is", () => {
    expect(py).toContain('LIVE_REFUSAL = "live trading is not available in this release"');
  });

  it("the dashboard says it too, and capitalised as a sentence", () => {
    const dash = readFileSync(
      join(__dirname, "(app)", "dashboard", "page.tsx"), "utf8");
    expect(dash).toContain("Live trading is not available in this release.");
  });

  it("the plan notice promises no price, date or outcome", () => {
    const notice = /PLAN_NOTICE = \(([\s\S]*?)\)\n/.exec(py)?.[1] ?? "";
    expect(notice).toContain("Demo accounts are free.");
    expect(notice).toContain("live execution is not enabled in this release");
    for (const word of ["soon", "guarantee", "profit", "$", "\u20ac"]) {
      expect(notice.toLowerCase()).not.toContain(word.toLowerCase());
    }
  });

  it("no component decides for itself whether live execution is on", () => {
    // The server answers this. A component that hardcodes it would be a
    // second source of truth, and the dangerous direction to be wrong in.
    //
    // The pattern is assembled at runtime so this file does not match itself
    // — the first version of this test failed on its own source, which is
    // funny once and useless afterwards.
    const flag = ["live", "Execution", "Enabled"].join("");
    const bad = new RegExp(`${flag}\\s*[:=]\\s*true`);
    for (const f of FILES) {
      expect(bad.test(f.body), `${f.path} sets the live-execution flag itself`)
        .toBe(false);
    }
  });
});
