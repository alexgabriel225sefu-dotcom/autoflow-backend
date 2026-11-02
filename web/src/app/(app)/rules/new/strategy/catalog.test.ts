/**
 * The strategy picker's two browser-side decisions.
 *
 * WHY THIS FILE EXISTS
 *
 * The platform exposed one way to trade — write a rule — while the engine
 * ships fifteen ready-made strategies a Telegram client could pick from a
 * menu. The picker closes that, and there are exactly two places the browser
 * can get it wrong on its own.
 *
 * ONE: LOSING A STRATEGY. The list is grouped for display, and grouping by a
 * known-families list is the obvious way to do it — which silently drops a
 * family the server grows later. The symptom is a strategy the client cannot
 * find and nobody can account for, which is the shape of the bug this whole
 * feature exists to fix.
 *
 * TWO: SENDING A DOCUMENT THAT CANNOT WORK. A preset rule must carry the
 * strategy and NO conditions. With conditions, the server refuses it. With
 * neither, the saved draft cannot be activated at all — "at least one
 * condition is required" — and the client is looking at a rule that is
 * already a dead end.
 *
 * The module under test is the one the page imports, so this cannot be
 * testing a second copy of it.
 */
import { describe, expect, it } from "vitest";
import type { RuleDoc, StrategyPreset } from "@/lib/api";
import {
  FAMILY_ORDER, familyLabel, groupByFamily, NoStrategyChosen,
  presetRuleBody,
} from "./catalog";

function preset(id: string, family: string): StrategyPreset {
  return {
    id, family, label: id, version: "1.0.0",
    what: "w", decides: "d", refuses: "r", source: "s",
  };
}

// The catalogue as the server serves it: fifteen strategies across seven
// families, already sorted by family then id.
const SERVED: StrategyPreset[] = [
  preset("auto", "adaptive"),
  preset("breakout", "breakout"),
  preset("opening_range", "breakout"),
  preset("session_breakout", "breakout"),
  preset("momentum", "momentum"),
  preset("mean_reversion", "reversion"),
  preset("vol_regime", "statistical"),
  preset("zscore", "statistical"),
  preset("evc", "structure"),
  preset("fibonacci", "structure"),
  preset("fvg", "structure"),
  preset("ifvg", "structure"),
  preset("liquidity_sweep", "structure"),
  preset("supply_demand", "structure"),
  preset("trend", "trend"),
];

describe("grouping the catalogue for display", () => {
  it("keeps every strategy the server sent", () => {
    const grouped = groupByFamily(SERVED);
    const ids = grouped.flatMap((g) => g.strategies.map((s) => s.id));
    expect(ids.sort()).toEqual(SERVED.map((s) => s.id).sort());
    expect(ids).toHaveLength(15);
  });

  it("does NOT drop a family this release has never heard of", () => {
    // The regression that matters. A strategy added to the engine in a new
    // family must appear, under its own name, or the catalogue's whole
    // reason for being read from the registry is undone in the browser.
    const grown = [...SERVED, preset("carry_trade", "macro")];
    const grouped = groupByFamily(grown);
    const ids = grouped.flatMap((g) => g.strategies.map((s) => s.id));
    expect(ids).toContain("carry_trade");
    expect(grouped.map((g) => g.family)).toContain("macro");
    // And it is shown under its raw name rather than something invented.
    expect(grouped.find((g) => g.family === "macro")!.label).toBe("macro");
  });

  it("shows the known families in this file's order, unknown ones last", () => {
    const grouped = groupByFamily([...SERVED, preset("carry_trade", "macro")]);
    const families = grouped.map((g) => g.family);
    const knownPart = families.filter((f) => f !== "macro");
    expect(knownPart).toEqual(
      FAMILY_ORDER.filter((f) => knownPart.includes(f)),
    );
    expect(families[families.length - 1]).toBe("macro");
    // Adaptive first: it is the one a client who does not know what to pick
    // should pick, and burying it under an alphabetical heading hides it.
    expect(families[0]).toBe("adaptive");
  });

  it("leaves the order inside a family exactly as the server sent it", () => {
    // The server sorts by family then id. Re-sorting here would be a second
    // copy of that decision.
    const structure = groupByFamily(SERVED)
      .find((g) => g.family === "structure")!;
    expect(structure.strategies.map((s) => s.id)).toEqual(
      ["evc", "fibonacci", "fvg", "ifvg", "liquidity_sweep", "supply_demand"],
    );
  });

  it("names no family that was not served", () => {
    const grouped = groupByFamily([preset("auto", "adaptive")]);
    expect(grouped).toHaveLength(1);
    expect(grouped[0].family).toBe("adaptive");
  });

  it("survives an empty or malformed answer rather than throwing", () => {
    expect(groupByFamily([])).toEqual([]);
    const nameless = [{ ...preset("x", ""), family: "" }];
    const grouped = groupByFamily(nameless as StrategyPreset[]);
    expect(grouped.flatMap((g) => g.strategies.map((s) => s.id)))
      .toEqual(["x"]);
  });

  it("gives known families a readable heading", () => {
    expect(familyLabel("reversion")).toBe("Mean reversion");
    expect(familyLabel("structure")).toBe("Market structure");
  });
});

/**
 * A FRESH draft per test, not one shared constant.
 *
 * This was a shared object, and it made the no-mutation test worthless: an
 * earlier test in this file had already called `presetRuleBody` on it, so a
 * mutating implementation corrupted the constant before the mutation test
 * ran, and that test compared a dirty object against itself and passed.
 * Found by deliberately making the implementation mutate — it was the one
 * break in this file that no assertion caught.
 */
function draft(): Partial<RuleDoc> {
  return {
    name: "My rule",
    symbols: ["EURUSD"],
    timeframe: "1h",
    sides: "BOTH",
    entry: { combine: "AND", conditions: [{ id: "rsi", params: {} }] },
    exit: { combine: "OR", conditions: [{ id: "macd", params: {} }] },
    sizing: { mode: "risk_percent", riskPercent: 1 },
    stopLoss: { mode: "atr", atrMultiple: 1.5 },
  } as Partial<RuleDoc>;
}

describe("the document sent when a strategy is picked", () => {
  it("names the strategy", () => {
    expect(presetRuleBody(draft(), "momentum").strategy).toBe("momentum");
  });

  it("clears conditions the client had already built", () => {
    // The server REFUSES a preset document that carries conditions, because a
    // condition on it is a term the client can read and the engine will never
    // consult. Sending them would make the save fail; worse, a server that
    // allowed them would show the client terms that do nothing.
    const body = presetRuleBody(draft(), "momentum") as Record<string, {
      combine: string; conditions: unknown[];
    }>;
    expect(body.entry.conditions).toEqual([]);
    expect(body.exit.conditions).toEqual([]);
  });

  it("keeps the combine choice, so switching back does not lose it", () => {
    const body = presetRuleBody(draft(), "momentum") as Record<string, {
      combine: string;
    }>;
    expect(body.entry.combine).toBe("AND");
    expect(body.exit.combine).toBe("OR");
  });

  it("keeps every other term — these are what the risk gates read", () => {
    const body = presetRuleBody(draft(), "trend");
    expect(body.symbols).toEqual(["EURUSD"]);
    expect(body.timeframe).toBe("1h");
    expect(body.sizing).toEqual({ mode: "risk_percent", riskPercent: 1 });
    expect(body.stopLoss).toEqual({ mode: "atr", atrMultiple: 1.5 });
    expect(body.name).toBe("My rule");
  });

  it("does not mutate the draft it was handed", () => {
    // The page holds this object in React state and re-renders the risk form
    // from it. A wrap that emptied the client's conditions in place would
    // wipe what they had built the moment they clicked a strategy.
    const mine = draft();
    const before = JSON.stringify(mine);
    presetRuleBody(mine, "trend");
    expect(JSON.stringify(mine)).toBe(before);
    // Stated separately, because the nested arrays are what a shallow copy
    // shares and what an in-place clear would empty.
    expect((mine.entry as { conditions: unknown[] }).conditions)
      .toHaveLength(1);
    expect((mine.exit as { conditions: unknown[] }).conditions)
      .toHaveLength(1);
  });

  it("refuses to send a document with no strategy on it", () => {
    // Without a strategy AND without conditions the draft saves and can never
    // be activated, so the client ends up looking at a rule that is already a
    // dead end. Throwing is reportable; saving that is not.
    for (const bad of ["", "   ", undefined as unknown as string]) {
      expect(() => presetRuleBody(draft(), bad)).toThrow(NoStrategyChosen);
    }
  });

  it("trims the id, so a stray space cannot become an unknown strategy", () => {
    expect(presetRuleBody(draft(), " zscore ").strategy).toBe("zscore");
  });

  it("works on a document with no condition blocks at all", () => {
    const body = presetRuleBody({ symbols: ["GBPUSD"] }, "auto") as Record<
      string, { conditions: unknown[] }
    >;
    expect(body.entry.conditions).toEqual([]);
    expect(body.exit.conditions).toEqual([]);
  });
});
