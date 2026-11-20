import { describe, expect, it } from "vitest";
import { delayAfter, frameAt, totalSteps } from "./terminal-sequence";

const RULE = "Buy EURUSD; risk 1%";
const REPLY = ["Market: EURUSD", "Preview only."];

describe("terminal sequence", () => {
  it("starts empty and finishes with the whole text", () => {
    expect(frameAt(0, RULE, REPLY)).toEqual({ typed: "", lines: [], done: false });
    const end = frameAt(totalSteps(RULE, REPLY), RULE, REPLY);
    expect(end).toEqual({ typed: RULE, lines: REPLY, done: true });
  });

  it("types the rule one character per step before any reply line", () => {
    expect(frameAt(3, RULE, REPLY)).toEqual({ typed: "Buy", lines: [], done: false });
    const typed = frameAt(RULE.length, RULE, REPLY);
    expect(typed.typed).toBe(RULE);
    expect(typed.lines).toEqual([]);
  });

  it("prints reply lines one at a time after the rule", () => {
    expect(frameAt(RULE.length + 1, RULE, REPLY).lines).toEqual(["Market: EURUSD"]);
    expect(frameAt(RULE.length + 2, RULE, REPLY).done).toBe(true);
  });

  it("clamps out-of-range steps", () => {
    expect(frameAt(-4, RULE, REPLY).typed).toBe("");
    expect(frameAt(9999, RULE, REPLY).done).toBe(true);
  });

  it("never invents text: every frame is a prefix of the final content", () => {
    for (let s = 0; s <= totalSteps(RULE, REPLY); s++) {
      const f = frameAt(s, RULE, REPLY);
      expect(RULE.startsWith(f.typed)).toBe(true);
      expect(f.lines).toEqual(REPLY.slice(0, f.lines.length));
    }
  });

  it("pauses longer once the rule is typed, and always returns a positive delay", () => {
    expect(delayAfter(RULE.length, RULE)).toBeGreaterThan(delayAfter(2, RULE));
    for (let s = 0; s <= totalSteps(RULE, REPLY); s++) {
      expect(delayAfter(s, RULE)).toBeGreaterThan(0);
    }
  });
});
