/**
 * The Light theme and the personal accents, measured the way the Black theme
 * is in contrast.test.ts.
 *
 * Nothing here trusts a value because it looks right: every pair that renders
 * is computed from the stylesheet text. The accent list is the part that could
 * rot quietly (someone adds a green and the product's "up" colour stops
 * meaning anything), so the hue rule is asserted for every entry in both
 * themes.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  ACCENTS, NO_FLASH_SCRIPT, THEMES, setAccent, setTheme, useAppearance,
} from "./appearance";
import { SegmentedControl } from "@/components/app/segmented";

const CSS = readFileSync(join(__dirname, "..", "app", "globals.css"), "utf8");

function decls(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const d of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[d[1]] = d[2].trim();
  return out;
}
function blockFor(selectorPattern: string): Record<string, string> {
  const m = new RegExp(`${selectorPattern}[^{]*\\{([^}]*)\\}`).exec(CSS);
  if (!m) throw new Error(`no CSS block for ${selectorPattern}`);
  return decls(m[1]);
}

const DARK = decls(/:root\s*\{([^}]*)\}/.exec(CSS)![1]);
const LIGHT = { ...DARK, ...blockFor(String.raw`:root\[data-theme="light"\] `) };

function accentTokens(theme: "dark" | "light", id: string): Record<string, string> {
  const base = theme === "dark" ? DARK : LIGHT;
  const over = theme === "dark"
    ? blockFor(String.raw`:root\[data-accent="${id}"\]`)
    : blockFor(String.raw`:root\[data-theme="light"\]\[data-accent="${id}"\]`);
  return { ...base, ...over };
}

function lum(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((s) => (s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function ratio(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
function hue(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (!d) return 0;
  const x = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (x * 60 + 360) % 360;
}
const apart = (a: number, b: number) => { const d = Math.abs(a - b); return Math.min(d, 360 - d); };

it("the two themes really are a dark page and a light page", () => {
  // Without this, a selector that stopped matching would leave LIGHT equal to
  // DARK and every contrast check below would pass against the wrong values.
  expect(lum(DARK["--a4t-bg"])).toBeLessThan(0.05);
  expect(lum(LIGHT["--a4t-bg"])).toBeGreaterThan(0.8);
});

describe.each([["dark", DARK], ["light", LIGHT]] as const)("the %s theme", (name, T) => {
  it("text reads on the page and on a card", () => {
    for (const t of ["--a4t-text", "--a4t-muted", "--a4t-dim"]) {
      expect(ratio(T[t], T["--a4t-bg"]), `${t} on the page`).toBeGreaterThanOrEqual(4.5);
      expect(ratio(T[t], T["--a4t-surface"]), `${t} on a card`).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("links, long, short and neutral are readable as text", () => {
    for (const t of ["--a4t-link", "--a4t-link-strong", "--a4t-long", "--a4t-short", "--a4t-neutral"]) {
      expect(ratio(T[t], T["--a4t-bg"]), `${t} on the page`).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("long and short can be told apart by more than hue", () => {
    expect(ratio(T["--a4t-long"], T["--a4t-short"]), name).toBeGreaterThan(1.3);
  });
  it("the default action fill carries its own foreground and stands off the page", () => {
    expect(ratio(T["--a4t-on-accent"], T["--a4t-accent"])).toBeGreaterThanOrEqual(4.5);
    expect(ratio(T["--a4t-accent"], T["--a4t-bg"])).toBeGreaterThanOrEqual(3);
  });
});

describe.each(THEMES.map((t) => t.id))("accents in the %s theme", (theme) => {
  const base = theme === "dark" ? DARK : LIGHT;
  it.each(ACCENTS.filter((a) => a.id !== "cream").map((a) => a.id))("%s", (id) => {
    const T = accentTokens(theme, id);
    expect(T["--a4t-accent"], `${id}/${theme} must override the fill`).not.toBe(base["--a4t-accent"]);
    // The fill with its own text, in the resting and the hover state.
    expect(ratio(T["--a4t-on-accent"], T["--a4t-accent"])).toBeGreaterThanOrEqual(4.5);
    expect(ratio(T["--a4t-on-accent"], T["--a4t-accent-strong"])).toBeGreaterThanOrEqual(4.5);
    // Used as a graphic (the timeline rail and nodes, the active mark).
    expect(ratio(T["--a4t-accent"], T["--a4t-bg"])).toBeGreaterThanOrEqual(3);
    // Never close to the two hues the product spends on meaning.
    const h = hue(T["--a4t-accent"]);
    expect(apart(h, hue(T["--a4t-long"])), `${id} is too close to long green`).toBeGreaterThanOrEqual(40);
    expect(apart(h, hue(T["--a4t-short"])), `${id} is too close to short red`).toBeGreaterThanOrEqual(40);
    // And its swatch exists, so the picker can draw it.
    expect(CSS).toContain(`.sw[data-accent="${id}"]`);
  });
});

describe("the no-flash script", () => {
  const run = () => new Function(NO_FLASH_SCRIPT)();
  const reset = () => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-accent");
  };
  beforeEach(reset);
  afterEach(reset);

  it("applies a stored theme and accent before paint", () => {
    localStorage.setItem("a4t-theme", "light");
    localStorage.setItem("a4t-accent", "ice");
    run();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(document.documentElement.getAttribute("data-accent")).toBe("ice");
  });
  it("ignores anything that is not on the lists", () => {
    localStorage.setItem("a4t-theme", '"><script>x</script>');
    localStorage.setItem("a4t-accent", "neon");
    run();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(document.documentElement.hasAttribute("data-accent")).toBe(false);
  });
  it("leaves the default alone and survives unreadable storage", () => {
    run();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    const proto = Object.getPrototypeOf(localStorage);
    const real = Object.getOwnPropertyDescriptor(proto, "getItem")!;
    Object.defineProperty(proto, "getItem", { value() { throw new Error("blocked"); }, configurable: true });
    try { expect(run).not.toThrow(); } finally { Object.defineProperty(proto, "getItem", real); }
  });
});

describe("choosing", () => {
  const reset = () => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-accent");
  };
  beforeEach(reset);
  afterEach(reset);

  it("setTheme and setAccent write the attribute and remember it", () => {
    setTheme("light");
    setAccent("volt");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(document.documentElement.getAttribute("data-accent")).toBe("volt");
    expect(localStorage.getItem("a4t-theme")).toBe("light");
    expect(localStorage.getItem("a4t-accent")).toBe("volt");
    setAccent("cream");
    expect(document.documentElement.hasAttribute("data-accent")).toBe(false);
  });

  it("the hook follows a change made anywhere", () => {
    function Probe() { const a = useAppearance(); return <p>{a.theme}/{a.accent}</p>; }
    render(<Probe />);
    expect(screen.getByText("dark/cream")).toBeTruthy();
    act(() => { setTheme("light"); setAccent("lilac"); });
    expect(screen.getByText("light/lilac")).toBeTruthy();
  });
});

describe("SegmentedControl", () => {
  it("is a radio group with one tab stop, and arrows move the choice", () => {
    const seen: string[] = [];
    const options = [{ value: "a", label: "A" }, { value: "b", label: "B" }, { value: "c", label: "C" }];
    const { rerender } = render(
      <SegmentedControl label="Pick" value="a" options={options} onChange={(v) => seen.push(v)} />,
    );
    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => r.getAttribute("aria-checked"))).toEqual(["true", "false", "false"]);
    expect(radios.map((r) => r.tabIndex)).toEqual([0, -1, -1]);
    expect(screen.getByRole("radiogroup", { name: "Pick" }).style.getPropertyValue("--i")).toBe("0");

    fireEvent.keyDown(radios[0], { key: "ArrowRight" });
    fireEvent.keyDown(radios[0], { key: "ArrowLeft" });
    expect(seen).toEqual(["b", "c"]);          // ArrowLeft wraps from the first to the last

    rerender(<SegmentedControl label="Pick" value="c" options={options} onChange={() => {}} />);
    expect(screen.getByRole("radiogroup").style.getPropertyValue("--i")).toBe("2");
  });
});
