/**
 * What the rule page claims about a rule that runs a ready-made strategy.
 *
 * WHY THIS FILE EXISTS
 *
 * A client can now pick one of the engine's own strategies instead of writing
 * conditions, and such a rule has NO conditions by construction — the server
 * refuses a preset document that carries any, because a condition on it would
 * be a term the client can read and the engine will never consult.
 *
 * The terms table rendered that as `Entry: no entry condition` and
 * `Exit: managed by stop and target only`. Both are the truth about the
 * document and a lie about the rule: the first describes a complete,
 * activatable rule as one missing the field that makes it work, and sends the
 * client off to add a condition that would then be rejected. The second
 * claims the stop and the target are the only exit when the strategy's own
 * exit runs as well.
 *
 * So a preset rule is described as a preset rule. These assertions are the
 * ones that fail if that regresses to showing condition rows.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RuleDoc } from "@/lib/api";
import { presetOf, RuleTerms } from "./rule-summary";

const BASE = {
  ruleDocId: "r1", name: "n", state: "draft", version: 1,
  symbols: ["EURUSD"], timeframe: "1h", updatedAt: 0,
  sides: "BOTH",
  entry: { combine: "AND", conditions: [] },
  exit: { combine: "OR", conditions: [] },
  sizing: { mode: "risk_percent", riskPercent: 1 },
  stopLoss: { mode: "atr", atrMultiple: 1.5 },
  takeProfit: { mode: "rr", rr: 2 },
  trailingStop: { enabled: false },
  breakEven: { enabled: false },
  limits: { maxOpenPositions: 1, onLimit: "block" },
  schedule: { timezone: "UTC", days: [], windows: [] },
  order: { type: "MARKET" },
} as unknown as RuleDoc;

const PRESET = { ...BASE, strategy: "trend" } as unknown as RuleDoc;

const row = (k: string) =>
  screen.queryByRole("rowheader", { name: k })
  ?? [...document.querySelectorAll("th")].find((th) => th.textContent === k)
  ?? null;

describe("presetOf", () => {
  it("reads the field, and is the only place that names it", () => {
    expect(presetOf(PRESET)).toBe("trend");
    expect(presetOf(BASE)).toBe("");
    expect(presetOf({ strategy: "  zscore  " } as unknown as RuleDoc))
      .toBe("zscore");
    // A non-string is not a strategy. Fail closed: the rule is treated as a
    // condition rule, which is the shape that has a stop and a direction.
    expect(presetOf({ strategy: 7 } as unknown as RuleDoc)).toBe("");
    expect(presetOf({} as RuleDoc)).toBe("");
  });
});

describe("the terms table for a preset rule", () => {
  it("names what decides, instead of reporting a missing condition", () => {
    render(<RuleTerms doc={PRESET} />);
    expect(row("Decided by")).not.toBeNull();
    expect(screen.getByText("trend")).toBeTruthy();
    // The two rows that were lying.
    expect(row("Entry")).toBeNull();
    expect(row("Exit")).toBeNull();
    expect(screen.queryByText("no entry condition")).toBeNull();
    expect(screen.queryByText("managed by stop and target only")).toBeNull();
  });

  it("says the sides field is recorded and not acted on", () => {
    // The evaluator reads `sides` to decide which way satisfied conditions
    // point. A strategy picks its own direction, so for a preset this field
    // governs nothing — and a field on screen that governs nothing is the
    // defect this product was rewritten to stop.
    render(<RuleTerms doc={PRESET} />);
    expect(screen.getByText(/recorded and not acted on/)).toBeTruthy();
  });

  it("still shows the terms that DO govern the position", () => {
    render(<RuleTerms doc={PRESET} />);
    // These are what the risk gates act on, and they are as real for a preset
    // as for a hand-built rule. That is the whole argument for a preset being
    // a RuleDoc rather than a second kind of thing.
    for (const k of ["Instruments", "Timeframe", "Sizing", "Stop loss",
                     "Take profit", "Max open positions", "Schedule"]) {
      expect(row(k), `${k} row is missing`).not.toBeNull();
    }
  });
});

describe("the terms table for a rule built from conditions", () => {
  it("is unchanged — it still shows Entry and Exit", () => {
    // The preset branch must not have swallowed the ordinary one.
    render(<RuleTerms doc={BASE} />);
    expect(row("Entry")).not.toBeNull();
    expect(row("Exit")).not.toBeNull();
    expect(row("Decided by")).toBeNull();
    expect(screen.getByText("no entry condition")).toBeTruthy();
    expect(screen.queryByText(/recorded and not acted on/)).toBeNull();
  });
});
