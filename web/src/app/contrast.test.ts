/**
 * Contrast, asserted against the real stylesheet and the real cascade.
 *
 * WHY THIS TEST EXISTS
 *
 * `.a4t a { color: var(--a4t-accent) }` used to sit at specificity (0,1,1) and
 * outrank `.btn` at (0,1,0). Every LINK styled as a primary button therefore
 * rendered accent text on an accent fill — measured 1.00:1, invisible — while
 * every <button> was fine. Fifteen controls shipped that way, including
 * "Connect cTrader", the first action in onboarding.
 *
 * A test that only read the `.btn` rule would have passed: `.btn` declares a
 * colour. The bug was in the cascade, so the test has to run the cascade. It
 * loads globals.css, resolves the custom properties (jsdom does not), hands
 * the result to jsdom as a real stylesheet, mounts the real markup, and reads
 * back what the browser would compute.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const CSS = readFileSync(join(__dirname, "globals.css"), "utf8");

/** The custom properties declared on :root, resolved through each other. */
function tokens(css: string): Record<string, string> {
  const raw: Record<string, string> = {};
  for (const block of css.matchAll(/:root\s*\{([^}]*)\}/g)) {
    for (const decl of block[1].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      raw[decl[1]] = decl[2].trim();
    }
  }
  const seen = new Set<string>();
  const resolve = (v: string, depth = 0): string => {
    if (depth > 12) return v;
    return v.replace(/var\((--[\w-]+)(?:\s*,\s*([^)]*))?\)/g, (_m, name, fallback) =>
      raw[name] !== undefined ? resolve(raw[name], depth + 1) : (fallback ?? "").trim());
  };
  const out: Record<string, string> = {};
  for (const k of Object.keys(raw)) { seen.add(k); out[k] = resolve(raw[k]); }
  return out;
}

const TOKENS = tokens(CSS);

/** globals.css with every var() substituted, so jsdom can compute colours. */
function flattened(): string {
  let css = CSS;
  for (let i = 0; i < 12; i++) {
    const next = css.replace(/var\((--[\w-]+)(?:\s*,\s*([^)]*))?\)/g, (m, name, fb) =>
      TOKENS[name] ?? (fb !== undefined ? String(fb).trim() : m));
    if (next === css) break;
    css = next;
  }
  // jsdom's CSS parser drops whole rules it cannot parse. These functions are
  // only used for decorative fills, never for a foreground we assert on.
  return css
    .replace(/color-mix\([^()]*(?:\([^()]*\)[^()]*)*\)/g, "#808080")
    .replace(/@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, "");
}

/* ── colour maths ─────────────────────────────────────────────────────── */

/** A colour as [r, g, b, a]. Alpha matters: most fills here are washes. */
function rgba(value: string): [number, number, number, number] {
  const v = value.trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(v);
  if (hex) {
    const h = hex[1].length === 3 ? hex[1].split("").map((c) => c + c).join("") : hex[1];
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
    const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
    return [r, g, b, a];
  }
  const fn = v.match(/-?[\d.]+/g);
  if (!fn || fn.length < 3) throw new Error(`cannot parse colour: ${value}`);
  return [Number(fn[0]), Number(fn[1]), Number(fn[2]), fn[3] === undefined ? 1 : Number(fn[3])];
}

/**
 * `fg` painted over `backdrop`, the way a compositor does it.
 *
 * Without this, a translucent wash is compared as if it were opaque and every
 * `--*-wash` fill reads as 1.00:1 against its own hue — a false alarm that
 * would teach whoever hits it to relax the threshold.
 */
function over(fg: string, backdrop: string): string {
  const [r, g, b, a] = rgba(fg);
  if (a >= 1) return `rgb(${r}, ${g}, ${b})`;
  const [br, bg_, bb] = rgba(backdrop);
  const mix = (f: number, k: number) => Math.round(f * a + k * (1 - a));
  return `rgb(${mix(r, br)}, ${mix(g, bg_)}, ${mix(b, bb)})`;
}

function rgb(value: string): [number, number, number] {
  const [r, g, b] = rgba(value);
  return [r, g, b];
}

function luminance(c: string): number {
  const [r, g, b] = rgb(c).map((n) => {
    const s = n / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast, with both colours first flattened onto the page. */
export function contrast(a: string, b: string): number {
  const page = TOKENS["--a4t-bg"] ?? "#000000";
  const back = over(b, page);
  const [hi, lo] = [luminance(over(a, back)), luminance(back)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/* ── the cascade, as a browser would run it ───────────────────────────── */

let style: HTMLStyleElement | null = null;
let host: HTMLElement | null = null;

function mount(html: string) {
  style = document.createElement("style");
  style.textContent = flattened();
  document.head.appendChild(style);
  host = document.createElement("div");
  host.innerHTML = html;
  document.body.appendChild(host);
  return host;
}

afterEach(() => {
  style?.remove();
  host?.remove();
  style = null;
  host = null;
});

/** The computed pair for one element, falling back to the inherited page. */
function pair(el: Element): { fg: string; bg: string } {
  const cs = getComputedStyle(el);
  const bg = cs.backgroundColor && cs.backgroundColor !== "transparent"
    && cs.backgroundColor !== "rgba(0, 0, 0, 0)"
    ? cs.backgroundColor
    : TOKENS["--a4t-bg"];
  const fg = cs.color || TOKENS["--a4t-text"];
  return { fg, bg };
}

/* ── the regression, stated directly ──────────────────────────────────── */

describe("button contrast in the real cascade", () => {
  const VARIANTS = ["btn", "btn btn-ghost", "btn btn-danger"];

  // Both tags, because the bug only ever affected one of them. A test that
  // checked <button> alone would have passed while the product was unusable.
  for (const cls of VARIANTS) {
    for (const tag of ["a", "button"] as const) {
      it(`<${tag} class="${cls}"> is readable`, () => {
        const root = mount(
          `<div class="a4t"><${tag} class="${cls}">Connect cTrader</${tag}></div>`,
        );
        const el = root.querySelector(cls.split(" ").map((c) => `.${c}`).join(""))!;
        const { fg, bg } = pair(el);
        const ratio = contrast(fg, bg);
        expect(
          ratio,
          `<${tag} class="${cls}"> renders ${fg} on ${bg} — ${ratio.toFixed(2)}:1`,
        ).toBeGreaterThanOrEqual(4.5);
      });
    }
  }

  it("a link inside .a4t still takes the accent when it is not a control", () => {
    const root = mount(`<div class="a4t"><a href="/x">All positions</a></div>`);
    const { fg, bg } = pair(root.querySelector("a")!);
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });

  it("the exact regression: an anchor button does not inherit the link colour", () => {
    const root = mount(
      `<div class="a4t"><a class="btn" href="/connect">Connect cTrader</a></div>`,
    );
    const { fg, bg } = pair(root.querySelector("a.btn")!);
    expect(fg).not.toBe(bg);
    expect(contrast(fg, bg)).toBeGreaterThan(3);
  });
});

/* ── the palette itself ───────────────────────────────────────────────── */

describe("palette", () => {
  const BG = () => TOKENS["--a4t-bg"];

  it("body text and muted text clear WCAG AA on the page background", () => {
    expect(contrast(TOKENS["--a4t-text"], BG())).toBeGreaterThanOrEqual(4.5);
    expect(contrast(TOKENS["--a4t-muted"], BG())).toBeGreaterThanOrEqual(4.5);
  });

  it("dim text clears the large-text threshold", () => {
    expect(contrast(TOKENS["--a4t-dim"], BG())).toBeGreaterThanOrEqual(3);
  });

  it("the accent is readable as text and as a fill", () => {
    expect(contrast(TOKENS["--a4t-accent"], BG())).toBeGreaterThanOrEqual(4.5);
    expect(contrast(TOKENS["--a4t-on-accent"], TOKENS["--a4t-accent"]))
      .toBeGreaterThanOrEqual(4.5);
  });

  it("the trading semantics are readable and distinguishable", () => {
    for (const t of ["--a4t-long", "--a4t-short", "--a4t-neutral"]) {
      expect(contrast(TOKENS[t], BG()), `${t} on the page`).toBeGreaterThanOrEqual(4.5);
    }
    // Long and short must not be confusable with each other or with the accent.
    expect(contrast(TOKENS["--a4t-long"], TOKENS["--a4t-short"])).toBeGreaterThan(1.3);
  });

  it("no amber or orange accent survives anywhere in the stylesheet", () => {
    // The previous product's accent. It came back once already, through the
    // shadcn token block, which is why this looks at the whole file.
    for (const banned of ["#f59e0b", "#fbbf24", "#d97706", "#b45309", "#ea580c"]) {
      expect(CSS.toLowerCase(), `${banned} is the old product's accent`)
        .not.toContain(banned);
    }
  });

  it("every declared accent token is the one accent, not a second hue", () => {
    // Hue is what makes a palette read as one system. Anything calling itself
    // an accent has to sit in the same blue-cyan band.
    const hueOf = (hex: string) => {
      const [r, g, b] = rgb(hex).map((n) => n / 255);
      const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
      if (!d) return 0;
      const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
      return ((h * 60) + 360) % 360;
    };
    for (const t of ["--a4t-accent", "--a4t-accent-strong", "--a4t-accent-dim"]) {
      const h = hueOf(TOKENS[t]);
      expect(h, `${t} is ${TOKENS[t]} (hue ${h.toFixed(0)}°)`).toBeGreaterThan(180);
      expect(h, `${t} is ${TOKENS[t]} (hue ${h.toFixed(0)}°)`).toBeLessThan(230);
    }
  });
});
