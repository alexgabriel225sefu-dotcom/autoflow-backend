import { describe, expect, it } from "vitest";
import { WIDGETS, parseHidden, toggle } from "./dashboard-layout";

describe("dashboard layout", () => {
  it("shows everything by default", () => {
    expect(parseHidden(null).size).toBe(0);
  });
  it("drops junk, unknown ids and non-arrays", () => {
    expect(parseHidden("not json").size).toBe(0);
    expect(parseHidden('{"a":1}').size).toBe(0);
    expect([...parseHidden('["market","approval","automation",5]')]).toEqual(["market"]);
  });
  it("toggles without mutating its input", () => {
    const a = new Set<"market">(["market"]);
    const b = toggle(a, "why");
    expect([...a]).toEqual(["market"]);
    expect([...b].sort()).toEqual(["market", "why"]);
    expect(toggle(b, "market").has("market")).toBe(false);
  });
  it("never lists the approval or the automation card as hideable", () => {
    const ids = WIDGETS.map((w) => w.id as string);
    expect(ids).not.toContain("approval");
    expect(ids).not.toContain("automation");
  });
});
