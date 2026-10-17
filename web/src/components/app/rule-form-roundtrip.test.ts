/**
 * A rule must survive being edited.
 *
 * WHY THIS FILE EXISTS
 *
 * The UI could not edit a rule at all — not a new draft, not a new version.
 * Adding the editor means every stored rule now makes a round trip through
 * the form: `fromDoc` loads it, the client changes one field, `toDoc` sends
 * it back. Anything the pair cannot carry is deleted, quietly, at the moment
 * somebody believed they were editing something unrelated.
 *
 * So the test is not "fromDoc returns a draft". It is: take a document with
 * every field set to a non-default value, round-trip it, and assert the
 * result equals what went in. A field added to RuleDoc and forgotten in
 * `fromDoc` fails here rather than in somebody's account.
 */
import { describe, expect, it } from "vitest";
import { fromDoc, toDoc, BLANK } from "./rule-form";
import type { RuleDoc } from "@/lib/api";

/** Every field non-default, so a dropped one cannot hide behind a default. */
const FULL = {
  ruleDocId: "r1", version: 3, state: "draft", userId: "u1", accountId: "501",
  createdAt: 111, updatedAt: 222, activatedAt: null,
  name: "Edited rule",
  symbols: ["EURUSD", "GBPUSD"],
  timeframe: "4h",
  sides: "SELL",
  evaluateOn: "intrabar",
  entry: { combine: "OR", conditions: [{ id: "rsi", period: 21, op: "below", value: 30 }] },
  exit: { combine: "AND", conditions: [{ id: "macd", fast: 12 }] },
  order: { type: "MARKET", maxSlippagePoints: 7, expiresAfterSec: 90 },
  sizing: { mode: "fixed_volume", fixedVolume: 0.25, riskPercent: null },
  stopLoss: { mode: "pips", pips: 33, atrMultiple: null },
  takeProfit: { mode: "pips", pips: 66, rr: null },
  trailingStop: { enabled: true, atrMultiple: 2.5 },
  breakEven: { enabled: true, atR: 1.25 },
  limits: {
    maxOpenPositions: 4, maxDailyTrades: 6, maxExposurePercent: 12,
    maxSpreadPips: 3, onLimit: "flatten",
  },
  schedule: { timezone: "UTC", days: [1, 2, 5], windows: [{ from: "08:00", to: "17:30" }] },
} as unknown as RuleDoc;

describe("a rule survives the editor", () => {
  it("round-trips every field the form owns", () => {
    const loaded = fromDoc(FULL);
    expect(loaded.ok, "a single-window rule must be editable").toBe(true);
    if (!loaded.ok) return;

    const back = toDoc(loaded.draft) as Record<string, unknown>;

    // Field by field, so a failure names the one that was lost.
    expect(back.name).toBe(FULL.name);
    expect(back.symbols).toEqual(FULL.symbols);
    expect(back.timeframe).toBe(FULL.timeframe);
    expect(back.sides).toBe(FULL.sides);
    expect(back.evaluateOn).toBe(FULL.evaluateOn);
    expect(back.entry).toEqual(FULL.entry);
    expect(back.exit).toEqual(FULL.exit);
    expect(back.order).toEqual(FULL.order);
    expect(back.sizing).toEqual(FULL.sizing);
    expect(back.stopLoss).toEqual(FULL.stopLoss);
    expect(back.takeProfit).toEqual(FULL.takeProfit);
    expect(back.trailingStop).toEqual(FULL.trailingStop);
    expect(back.breakEven).toEqual(FULL.breakEven);
    expect(back.limits).toEqual(FULL.limits);
    expect(back.schedule).toEqual(FULL.schedule);
  });

  it("sends nothing the form does not own, so the server keeps it", () => {
    // version, createdAt, accountId and the owner are the server's. They are
    // absent from the patch rather than echoed back, which is what makes the
    // partial PUT safe — the server re-asserts them from the stored document.
    const loaded = fromDoc(FULL);
    if (!loaded.ok) throw new Error("fixture must be editable");
    const back = toDoc(loaded.draft) as Record<string, unknown>;
    for (const k of ["version", "createdAt", "activatedAt", "userId",
                     "accountId", "ruleDocId", "state"]) {
      expect(back[k], `${k} must not be sent by the editor`).toBeUndefined();
    }
  });

  it("'no take profit' survives as none, not as a default target", () => {
    // The server writes mode: null. Mapping that to the form's default would
    // hand the rule a target it never had.
    const doc = { ...FULL, takeProfit: { mode: null, rr: null, pips: null } } as unknown as RuleDoc;
    const loaded = fromDoc(doc);
    if (!loaded.ok) throw new Error("must be editable");
    expect(loaded.draft.tpMode).toBe("none");
    expect((toDoc(loaded.draft) as Record<string, unknown>).takeProfit)
      .toEqual({ mode: null, rr: null, pips: null });
  });

  it("refuses the one shape it cannot carry, by name", () => {
    const twoWindows = {
      ...FULL,
      schedule: { timezone: "UTC", days: [1],
                  windows: [{ from: "08:00", to: "12:00" }, { from: "14:00", to: "18:00" }] },
    } as unknown as RuleDoc;
    const loaded = fromDoc(twoWindows);
    expect(loaded.ok, "silently flattening two windows into one is the bug").toBe(false);
    if (loaded.ok) return;
    expect(loaded.reason).toMatch(/more than one trading window/i);
  });

  it("an empty document loads as the blank form rather than crashing", () => {
    const loaded = fromDoc({} as RuleDoc);
    expect(loaded.ok).toBe(true);
    if (!loaded.ok) return;
    expect(loaded.draft.timeframe).toBe(BLANK.timeframe);
    expect(loaded.draft.entry).toEqual([]);
  });
});
