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

/**
 * The marketing palette, declared on `.mkt` rather than `:root`.
 *
 * It is held to the same bar as the app's. The landing page is the surface an
 * advertisement pays to put in front of a stranger, and it is the one page
 * where a reader has no reason to persevere with text they cannot read.
 */
function scopedTokens(css: string, selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  const re = new RegExp(`\\${selector}\\s*\\{([^}]*)\\}`, "g");
  for (const block of css.matchAll(re)) {
    for (const decl of block[1].matchAll(/(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;/g)) {
      out[decl[1]] = decl[2].trim();
    }
  }
  return out;
}

const MKT = scopedTokens(CSS, ".mkt");

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

  /**
   * The accent is a FILL, not a foreground.
   *
   * Petrol teal is dark on purpose. Asserting it is readable as text would be
   * asserting a role it does not have, and would push whoever hit the failure
   * to lighten the fill until the buttons stopped looking like buttons. What
   * matters is the pair that actually renders: off-white ON teal.
   */
  it("the action fill carries its own foreground", () => {
    expect(contrast(TOKENS["--a4t-on-accent"], TOKENS["--a4t-accent"]))
      .toBeGreaterThanOrEqual(4.5);
  });

  it("the interactive foreground is readable as text", () => {
    // Links, focus rings and the active nav item. This one IS a foreground.
    expect(contrast(TOKENS["--a4t-link"], BG())).toBeGreaterThanOrEqual(4.5);
    expect(contrast(TOKENS["--a4t-link-strong"], BG())).toBeGreaterThanOrEqual(4.5);
  });

  it("the trading semantics are readable and distinguishable", () => {
    for (const t of ["--a4t-long", "--a4t-short", "--a4t-neutral"]) {
      expect(contrast(TOKENS[t], BG()), `${t} on the page`).toBeGreaterThanOrEqual(4.5);
    }
    // Long and short must not be confusable with each other.
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

  /**
   * One family per role, rather than a fixed hue band.
   *
   * A hardcoded band would have to be rewritten every time the palette is
   * re-approved, and a test nobody trusts gets relaxed rather than read. What
   * has to hold across any palette is that a family is a family: if a second
   * accent is introduced by accident, the spread opens up and this fails.
   */
  const hueOf = (hex: string) => {
    const [r, g, b] = rgb(hex).map((n) => n / 255);
    const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
    if (!d) return 0;
    const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return ((h * 60) + 360) % 360;
  };
  const spread = (hues: number[]) => {
    let worst = 0;
    for (const a of hues) for (const b of hues) {
      const d = Math.abs(a - b);
      worst = Math.max(worst, Math.min(d, 360 - d));
    }
    return worst;
  };

  it.each([
    ["action fill", ["--a4t-accent", "--a4t-accent-strong", "--a4t-accent-dim"]],
    ["interactive", ["--a4t-link", "--a4t-link-strong"]],
  ])("the %s tokens are one hue family, not two", (_name, names) => {
    const hues = (names as string[]).map((t) => hueOf(TOKENS[t]));
    expect(
      spread(hues),
      (names as string[]).map((t, i) => `${t}=${TOKENS[t]} (${hues[i].toFixed(0)}°)`).join(", "),
    ).toBeLessThanOrEqual(30);
  });

  it("the action fill and the interactive foreground are distinct roles", () => {
    // If these ever collapse to one token, the 1.00:1 bug becomes reachable
    // again: a link styled as a button would inherit the fill's own hue.
    expect(TOKENS["--a4t-accent"]).not.toBe(TOKENS["--a4t-link"]);
  });
});

describe("the marketing palette", () => {
  it("declares the tokens the landing page uses", () => {
    // If this ever reads empty the whole block below passes vacuously, which
    // is the failure mode of every palette test written without it.
    for (const name of [
      "--mkt-bg", "--mkt-text", "--mkt-muted", "--mkt-dim",
      "--mkt-accent", "--mkt-on-accent", "--mkt-accent-text",
    ]) {
      expect(MKT[name], `${name} is missing from .mkt`).toBeTruthy();
    }
  });

  it("body text and muted text clear WCAG AA on the page", () => {
    expect(contrast(MKT["--mkt-text"], MKT["--mkt-bg"])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(MKT["--mkt-muted"], MKT["--mkt-bg"])).toBeGreaterThanOrEqual(4.5);
  });

  it("dim text clears the large-text threshold", () => {
    expect(contrast(MKT["--mkt-dim"], MKT["--mkt-bg"])).toBeGreaterThanOrEqual(3);
  });

  it("the red fill carries its own foreground", () => {
    expect(
      contrast(MKT["--mkt-on-accent"], MKT["--mkt-accent"]),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("the red used AS TEXT is a different token, and readable", () => {
    // The whole reason there are two. The fill is dark enough to carry white,
    // which makes it far too dark to read as text on a near-black page.
    expect(
      contrast(MKT["--mkt-accent-text"], MKT["--mkt-bg"]),
    ).toBeGreaterThanOrEqual(4.5);
    expect(
      contrast(MKT["--mkt-accent"], MKT["--mkt-bg"]),
      "the fill would be unreadable as text — that is why it is not used as text",
    ).toBeLessThan(4.5);
    expect(MKT["--mkt-accent-text"]).not.toBe(MKT["--mkt-accent"]);
  });

  it("the marketing surface does not borrow the trading reds", () => {
    // --a4t-short means short/loss/destructive inside the product. If the
    // brand red were the same value, every losing position would be wearing
    // the brand and the reader would have to work out which red they were
    // looking at.
    expect(MKT["--mkt-accent"]).not.toBe(TOKENS["--a4t-short"]);
  });
});

/**
 * The app and the landing page are the same product.
 *
 * They were not. The landing page was rebuilt in black and red while the app
 * kept a petrol-teal accent on a midnight-blue page, so somebody who signed
 * up walked out of one product and into another — and nothing caught it,
 * because every test here held each palette to its own standard and no test
 * compared them. Opening the screens in a browser is what showed it.
 */
describe("the app wears the same brand as the landing page", () => {
  it("the action fill is the brand red, the same value in both", () => {
    expect(TOKENS["--a4t-accent"]).toBe(MKT["--mkt-accent"]);
  });

  it("the page is the same black in both", () => {
    expect(TOKENS["--a4t-bg"]).toBe(MKT["--mkt-bg"]);
  });

  it("the interactive foreground is NOT a red", () => {
    // Not taste. --a4t-short is coral and means a losing position; a link in
    // a near-coral red beside it is a pair somebody has to stop and decode.
    // This fails if anybody "simplifies" the link token back onto the accent.
    const h = (hex: string) => {
      const [r, g, b] = rgb(hex).map((n) => n / 255);
      const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
      if (!d) return 0;
      const x = max === r ? ((g - b) / d) % 6
        : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
      return ((x * 60) + 360) % 360;
    };
    const gap = (a: number, b: number) =>
      Math.min(Math.abs(a - b), 360 - Math.abs(a - b));
    expect(
      gap(h(TOKENS["--a4t-link"]), h(TOKENS["--a4t-short"])),
      `link ${TOKENS["--a4t-link"]} is too close in hue to short ` +
      `${TOKENS["--a4t-short"]}`,
    ).toBeGreaterThan(60);
  });

  it("no petrol teal survives anywhere in the stylesheet", () => {
    // The app's previous accent. Named here for the reason the amber check
    // above exists: it came back once through a token block nobody re-read.
    //
    // The rgb() forms are checked too, and that is not belt-and-braces: the
    // first version of this test looked for hexes only, passed, and a
    // teal glow shipped to production written as `rgba(11, 89, 96, .34)`
    // inside a dead landing-page block. A colour nobody can grep for is a
    // colour that comes back.
    const css = CSS.toLowerCase().replace(/\s+/g, "");
    for (const banned of [
      "#0b5960", "#0e6e77", "#1a3c4a",
      "11,89,96", "14,110,119", "26,60,74",
    ]) {
      expect(css, `${banned} was the app's teal accent`).not.toContain(banned);
    }
  });
});

/**
 * The pricing cards, which are read by somebody deciding whether to pay.
 *
 * These exist because the vendored component shipped its own tints and its
 * own alpha-based greys — `text-foreground/50` over a coloured card — and
 * nothing could tell anyone what those actually computed to. They rendered
 * as unreadable small print under the price. Every colour here is a token so
 * the number is checkable.
 */
describe("the pricing cards", () => {
  it("declares its surface tokens", () => {
    for (const name of [
      "--pc-card", "--pc-card-2", "--pc-head", "--pc-head-accent",
      "--pc-note", "--pc-note-accent",
    ]) {
      expect(MKT[name], `${name} is missing from .mkt`).toBeTruthy();
    }
  });

  it("the plan name and price are readable on both card heads", () => {
    for (const head of [MKT["--pc-head"], MKT["--pc-head-accent"]]) {
      expect(contrast(MKT["--mkt-text"], head)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("the small print under the price clears AA, on both heads", () => {
    // The description, the price note and the sentence saying the plan is
    // not on sale yet. All of it is the size that gets written off as
    // decoration and then shipped at 2:1.
    expect(contrast(MKT["--pc-note"], MKT["--pc-head"]))
      .toBeGreaterThanOrEqual(4.5);
    expect(contrast(MKT["--pc-note-accent"], MKT["--pc-head-accent"]))
      .toBeGreaterThanOrEqual(4.5);
  });

  it("the accent head is a red, not a borrowed hue", () => {
    // The specific failure this replaces: an amber card and a teal card on a
    // page with no amber and no teal in it.
    const [r, g, b] = [1, 3, 5].map((i) =>
      parseInt(MKT["--pc-head-accent"].slice(i, i + 2), 16));
    expect(r).toBeGreaterThan(g);
    expect(r).toBeGreaterThan(b);
  });

  it("feature ticks use the readable red, never the fill", () => {
    expect(contrast(MKT["--mkt-accent-text"], MKT["--pc-card"]))
      .toBeGreaterThanOrEqual(4.5);
  });
});

describe("the hero glow stays out of the layout", () => {
  /**
   * A decorative blur must never take a grid cell.
   *
   * `.mkt-hero > *` set position:relative on every direct child to lift
   * content above the glow. It also hit the glow, which killed its
   * position:absolute. Once the hero became a grid, the glow became a grid
   * ITEM: it took the first column, the copy moved to the second and the
   * terminal wrapped to its own row, leaving half the hero empty. Nothing
   * failed; it just looked wrong, on the page an advertisement pays for.
   *
   * Asserted through the real cascade rather than by reading the file, so
   * the order of the two rules is what is being tested.
   */
  afterEach(() => { document.head.querySelectorAll("style[data-glow]").forEach((n) => n.remove()); });

  function heroWith(children: string) {
    const style = document.createElement("style");
    style.setAttribute("data-glow", "1");
    style.textContent = flattened();
    document.head.appendChild(style);
    const root = document.createElement("main");
    root.className = "mkt";
    root.innerHTML = `<section class="mkt-hero mkt-hero-terminal">${children}</section>`;
    document.body.appendChild(root);
    return root;
  }

  it("the glow is absolutely positioned, so it is not a grid item", () => {
    const root = heroWith(
      `<span class="mkt-glow"></span><div class="mkt-hero-copy">c</div>`);
    const glow = root.querySelector(".mkt-glow")!;
    expect(getComputedStyle(glow).position).toBe("absolute");
    root.remove();
  });

  it("while the content beside it IS lifted, which is why the rule exists", () => {
    const root = heroWith(
      `<span class="mkt-glow"></span><div class="mkt-hero-copy">c</div>`);
    const copy = root.querySelector(".mkt-hero-copy")!;
    expect(getComputedStyle(copy).position).toBe("relative");
    root.remove();
  });
});
