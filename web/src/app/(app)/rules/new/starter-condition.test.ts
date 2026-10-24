/**
 * The rule a new client is handed must be able to trade.
 *
 * WHY THIS FILE EXISTS
 *
 * The builder opened with the alphabetically first condition. That is `atr` —
 * a volatility filter, which says WHEN to trade and never which way — while
 * `sides` defaults to BOTH. The evaluator refuses that combination with
 * DIRECTION_AMBIGUOUS even when the condition is satisfied, so the rule
 * presented to every new client could not trade.
 *
 * Nothing failed visibly. The summary line read like a finished strategy
 * ("Buy or sell EURUSD on 1h when ATR(14, above, 10); risk 1% per trade..."),
 * the rule saved, validated and activated, and the first sign of trouble was
 * automation that ran and never did anything. It was found by opening the
 * page, not by reading the code.
 *
 * The page now picks the first condition that IMPLIES A DIRECTION, asking the
 * server which those are. This file pins the selection rule against the
 * regression — someone tidying the line back to `.sort()[0]` — and it is kept
 * separate from the page so it needs no DOM, no API and no session.
 */
import { describe, expect, it } from "vitest";
import type { ConditionSpec } from "@/lib/api";
// The module the PAGE imports, so this cannot test a second copy.
import { starterCondition } from "./starter-condition";

function spec(id: string, impliesDirection: boolean): ConditionSpec {
  return { id, doc: "", params: {}, impliesDirection };
}

// The real library, as the server describes it: six that point at a side and
// six that only say when.
const LIBRARY: Record<string, ConditionSpec> = Object.fromEntries(
  [
    ["atr", false], ["bollinger", true], ["ma_cross", true], ["macd", true],
    ["max_positions", false], ["price_vs_ma", true], ["rsi", true],
    ["session", false], ["spread_limit", false], ["stochastic", true],
    ["time_window", false], ["weekday", false],
  ].map(([id, dir]) => [id as string, spec(id as string, dir as boolean)]),
);

describe("the condition the rule builder opens with", () => {
  it("implies a direction, so the rule can actually trade", () => {
    const picked = starterCondition(LIBRARY);
    expect(picked).toBeDefined();
    expect(LIBRARY[picked!].impliesDirection).toBe(true);
  });

  it("is NOT simply the alphabetically first one", () => {
    const alphabetical = Object.keys(LIBRARY).sort()[0];
    expect(alphabetical).toBe("atr");
    expect(LIBRARY[alphabetical].impliesDirection).toBe(false);
    // The bug, stated directly: picking alphabetically picks a filter.
    expect(starterCondition(LIBRARY)).not.toBe(alphabetical);
  });

  it("is chosen from the server's answer, not a list kept here", () => {
    // Flip the server's answer and the choice must follow it. A hardcoded
    // list of directional ids in the browser would ignore this.
    const flipped: Record<string, ConditionSpec> = Object.fromEntries(
      Object.entries(LIBRARY).map(([id, s]) => [
        id,
        { ...s, impliesDirection: id === "atr" },
      ]),
    );
    expect(starterCondition(flipped)).toBe("atr");
  });

  it("falls back to the first condition when the server marks none", () => {
    // The product must still open a usable form if the field is absent — an
    // older API, say. Worse than ideal, never broken.
    const none: Record<string, ConditionSpec> = Object.fromEntries(
      Object.entries(LIBRARY).map(([id, s]) => [
        id,
        { ...s, impliesDirection: false },
      ]),
    );
    expect(starterCondition(none)).toBe("atr");

    const missing: Record<string, ConditionSpec> = Object.fromEntries(
      Object.entries(LIBRARY).map(([id, s]) => {
        const { impliesDirection: _drop, ...rest } = s;
        return [id, rest as ConditionSpec];
      }),
    );
    expect(starterCondition(missing)).toBe("atr");
  });

  it("returns nothing for an empty library rather than throwing", () => {
    expect(starterCondition({})).toBeUndefined();
  });
});
