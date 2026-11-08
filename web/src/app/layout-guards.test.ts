import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "globals.css"), "utf8");

describe("layout guards for narrow screens", () => {
  it("grid tracks can shrink, so a wide field cannot push a column off the screen", () => {
    // A bare `1fr` track cannot shrink below its widest item.
    expect(css).toMatch(/\.grid \{[^}]*grid-template-columns: minmax\(0, 1fr\)/);
    expect(css).toMatch(/\.grid-2 \{ grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
    expect(css).toMatch(/\.grid-3 \{ grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)/);
    expect(css).not.toMatch(/\.grid-[23] \{ grid-template-columns: (1fr 1fr|repeat\(3, 1fr\))/);
  });

  it("the orbs are not drawn behind the subtitle or the welcome text on a phone", () => {
    expect(css).toMatch(/@media \(max-width: 639px\) \{ \.dash-orb, \.wc-orb \{ display: none; \} \}/);
  });

  it("a segmented control with many options shrinks to the screen instead of running off it", () => {
    expect(css).toMatch(/\.segc \{[^}]*repeat\(var\(--n\), minmax\(0, 1fr\)\)/);
    expect(css).toMatch(/@media \(max-width: 479px\) \{ \.segc button \{ min-width: 0; padding: 0 \.3rem; \} \}/);
  });
});
