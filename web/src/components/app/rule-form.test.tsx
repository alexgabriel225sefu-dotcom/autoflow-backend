/**
 * The builder's contract with the RuleDoc.
 *
 * The regression this guards against shipped: the builder submitted name,
 * symbols, timeframe, sides, entry and exit, and everything else silently
 * took a server default — 1% risk, a 1.5x ATR stop, a 2R target, one open
 * position. The client could not see those numbers and could not change them,
 * in a product whose promise is to respect the limits the client switched on.
 *
 * So the first test compares what `toDoc` emits against the field list the
 * backend's `_create` copies. It reads that list out of the Python source, so
 * a field added to the API and forgotten here fails the test rather than
 * quietly reverting to a default.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BLANK, RuleForm, STEPS, fromDoc, toDoc, type Draft } from "./rule-form";
import { ruleSentence } from "./rule-summary";
import type { ConditionSpec } from "@/lib/api";

const SPECS: Record<string, ConditionSpec> = {
  rsi: {
    id: "rsi", doc: "RSI against a threshold.",
    params: {
      period: { type: "int", default: 14, choices: null, min: 2, max: 200, required: true },
      relation: { type: "str", default: "above", choices: ["above", "below"], min: null, max: null, required: true },
      value: { type: "float", default: 55, choices: null, min: 0, max: 100, required: true },
    },
  },
  price_vs_ma: {
    id: "price_vs_ma", doc: "Close against a moving average.",
    params: {
      indicator: { type: "str", default: "ema", choices: ["ema", "sma"], min: null, max: null, required: true },
      period: { type: "int", default: 50, choices: null, min: 2, max: 400, required: true },
      relation: { type: "str", default: "above", choices: ["above", "below"], min: null, max: null, required: true },
    },
  },
};

const API_PY = join(__dirname, "..", "..", "..", "..", "apex-forex-bot", "apex", "platform", "api.py");

describe("toDoc — no field is silently dropped", () => {
  it("emits every field the backend's _create copies from the payload", () => {
    const src = readFileSync(API_PY, "utf8");
    // The literal tuple in _create. Read, not remembered.
    const block = src.slice(src.indexOf("def _create("));
    const tuple = block.slice(block.indexOf("for field in ("), block.indexOf("):", block.indexOf("for field in (")));
    const fields = [...tuple.matchAll(/"([a-zA-Z]+)"/g)].map((m) => m[1]);
    expect(fields.length, "could not read the field list out of api.py").toBeGreaterThan(8);

    const doc = toDoc(BLANK) as Record<string, unknown>;
    for (const f of fields) {
      expect(doc, `${f} is accepted by the API but never sent by the builder`)
        .toHaveProperty(f);
    }
    // And the three the blank supplies separately.
    for (const f of ["symbols", "timeframe", "name"]) expect(doc).toHaveProperty(f);
  });

  it("sends the defaults as values rather than leaving them to the server", () => {
    const doc = toDoc(BLANK) as Record<string, Record<string, unknown>>;
    expect(doc.sizing).toMatchObject({ mode: "risk_percent", riskPercent: 1 });
    expect(doc.stopLoss).toMatchObject({ mode: "atr", atrMultiple: 1.5 });
    expect(doc.takeProfit).toMatchObject({ mode: "rr", rr: 2 });
    expect(doc.limits).toMatchObject({ maxOpenPositions: 1, onLimit: "block" });
    expect(doc.order).toMatchObject({ type: "MARKET" });
    expect(doc.schedule).toMatchObject({ timezone: "UTC" });
  });

  it("round-trips the selected automation level", () => {
    const doc = toDoc({ ...BLANK, automationLevel: "approval" }) as Record<string, unknown>;
    expect(doc.automationLevel).toBe("approval");
    const loaded = fromDoc({ ...doc, ruleDocId: "r1", state: "draft", version: 1,
      name: "Demo", symbols: ["EURUSD"], timeframe: "1h", updatedAt: 1 } as never);
    expect(loaded.ok).toBe(true);
    if (loaded.ok) expect(loaded.draft.automationLevel).toBe("approval");
  });

  it("an empty optional stays null rather than becoming a number", () => {
    const doc = toDoc({ ...BLANK, maxSpreadPips: "", maxDailyTrades: "" }) as Record<string, Record<string, unknown>>;
    expect(doc.limits.maxSpreadPips).toBeNull();
    expect(doc.limits.maxDailyTrades).toBeNull();
    // A cap of 0 is not "no cap", and must survive as 0.
    const zero = toDoc({ ...BLANK, maxSpreadPips: "0" }) as Record<string, Record<string, unknown>>;
    expect(zero.limits.maxSpreadPips).toBe(0);
  });

  it("switching the stop mode does not carry the other mode's value across", () => {
    const pips = toDoc({ ...BLANK, slMode: "pips", slPips: "20" }) as Record<string, Record<string, unknown>>;
    expect(pips.stopLoss).toMatchObject({ mode: "pips", pips: 20, atrMultiple: null });
    const atr = toDoc({ ...BLANK, slMode: "atr" }) as Record<string, Record<string, unknown>>;
    expect(atr.stopLoss).toMatchObject({ mode: "atr", pips: null });
  });

  it("no take profit is expressed as no take profit, not as zero", () => {
    const doc = toDoc({ ...BLANK, tpMode: "none" }) as Record<string, Record<string, unknown>>;
    expect(doc.takeProfit).toMatchObject({ mode: null, rr: null, pips: null });
  });

  it("a schedule window is only sent when both ends are given", () => {
    const half = toDoc({ ...BLANK, windowFrom: "07:00", windowTo: "" }) as Record<string, Record<string, unknown>>;
    expect(half.schedule.windows).toEqual([]);
    const full = toDoc({ ...BLANK, windowFrom: "07:00", windowTo: "16:00" }) as Record<string, Record<string, unknown>>;
    expect(full.schedule.windows).toEqual([{ from: "07:00", to: "16:00" }]);
  });
});

describe("the natural-language summary", () => {
  it("reads back the whole rule, in the shape the brief asked for", () => {
    const d: Draft = {
      ...BLANK, sides: "BOTH", symbols: "EURUSD", timeframe: "1h",
      riskPercent: "1.0", slAtrMultiple: "1.5", tpRr: "2.0",
      entry: [{ id: "rsi", params: { period: 14, relation: "above", value: 55 } }],
      exit: [],
    };
    const s = ruleSentence(toDoc(d), SPECS);
    expect(s).toContain("Buy or sell EURUSD on 1h");
    expect(s).toContain("RSI(14, above, 55)");
    expect(s).toContain("risk 1% per trade");
    expect(s).toContain("stop 1.5× ATR");
    expect(s).toContain("target 2R");
  });

  it("says a missing stop is missing rather than saying nothing", () => {
    const s = ruleSentence({ ...toDoc(BLANK), stopLoss: {} } as never, SPECS);
    expect(s).toContain("stop not set");
  });

  it("says a rule with no entry condition has none", () => {
    const s = ruleSentence(toDoc({ ...BLANK, entry: [] }), SPECS);
    expect(s).toContain("no entry condition set");
  });

  /**
   * A rule that names one of the engine's ready-made strategies has no
   * conditions BY CONSTRUCTION — the server refuses a preset document that
   * carries any, because a condition on it would be a term the client can
   * read and the engine will never consult.
   *
   * The sentence read "— no entry condition set" over such a rule, which is
   * the one description that sends a client off to fix something that is not
   * broken. It names the strategy instead.
   */
  it("describes a preset rule by its strategy, not as one missing its "
     + "conditions", () => {
    const doc = {
      ...toDoc({ ...BLANK, entry: [], exit: [] }),
      strategy: "trend",
    } as never;
    const s = ruleSentence(doc, SPECS);
    expect(s).toContain("using the trend strategy");
    expect(s).toContain("decides its own entries and exits");
    expect(s).not.toContain("no entry condition set");
    // The terms that DO govern the position are still said out loud.
    expect(s).toContain("risk 1% per trade");
    expect(s).toContain("stop 1.5× ATR");
  });

  it("still reads a condition-built rule the same way as before", () => {
    // The preset branch must not have swallowed the ordinary one.
    const s = ruleSentence(
      toDoc({ ...BLANK, entry: [{ id: "rsi", params: { period: 14, relation: "above", value: 55 } }] }),
      SPECS);
    expect(s).toContain("when RSI(14, above, 55)");
    expect(s).not.toContain("strategy");
  });
});

describe("the step rail", () => {
  const noop = vi.fn();

  it("covers every section of the document and ends at Review", () => {
    expect(STEPS[STEPS.length - 1].id).toBe("review");
    for (const id of ["basics", "entry", "exit", "risk", "stop", "target",
                      "management", "limits", "schedule", "order"]) {
      expect(STEPS.map((s) => s.id), `${id} has no step`).toContain(id);
    }
  });

  it("renders one step at a time, and all of them for review", () => {
    const { unmount } = render(<RuleForm draft={BLANK} set={noop} specs={SPECS} step="stop" />);
    expect(screen.getByText("Stop loss")).toBeDefined();
    expect(screen.queryByText("Limits")).toBeNull();
    unmount();

    render(<RuleForm draft={BLANK} set={noop} specs={SPECS} step="all" />);
    expect(screen.getByText("Stop loss")).toBeDefined();
    expect(screen.getByText("Limits")).toBeDefined();
    expect(screen.getByText("Schedule")).toBeDefined();
  });
});

describe("the condition editor is generated from the registry", () => {
  it("offers exactly the conditions the backend declared, by their own ids", () => {
    render(<RuleForm draft={{ ...BLANK, entry: [{ id: "rsi", params: {} }] }}
                     set={vi.fn()} specs={SPECS} step="entry" />);
    const select = screen.getByRole("combobox", { name: /Condition/i }) as HTMLSelectElement;
    const values = [...select.options].map((o) => o.value).sort();
    expect(values).toEqual(Object.keys(SPECS).sort());
    // Humanised for the reader, but the VALUE stays the registry id.
    expect([...select.options].map((o) => o.textContent)).toContain("Price vs MA");
  });

  it("shows the backend's own explanation of a condition", () => {
    render(<RuleForm draft={{ ...BLANK, entry: [{ id: "rsi", params: {} }] }}
                     set={vi.fn()} specs={SPECS} step="entry" />);
    expect(screen.getByText("RSI against a threshold.")).toBeDefined();
  });

  it("states a parameter's permitted range next to it", () => {
    render(<RuleForm draft={{ ...BLANK, entry: [{ id: "rsi", params: { period: 14 } }] }}
                     set={vi.fn()} specs={SPECS} step="entry" />);
    expect(screen.getByText("(2–200)")).toBeDefined();
  });
});

describe("fields that would be refused at execution say so at the input", () => {
  it.each([
    [{ orderType: "LIMIT" }, /refused at execution/],
    [{ maxSlippagePoints: "5" }, /cannot honour this yet/],
    [{ expiresAfterSec: "60" }, /cannot honour this yet/],
  ])("warns for %o", (patch, expected) => {
    render(<RuleForm draft={{ ...BLANK, ...patch } as Draft} set={vi.fn()} specs={SPECS} step="order" />);
    expect(screen.getByText(expected)).toBeDefined();
  });

  // WAS "does not apply these yet" — which was false. The engine DOES switch
  // trailing on or off from the rule and does use the break-even trigger; only
  // the trail DISTANCE is its own. The screen now says exactly that, because a
  // note claiming a working setting does nothing is as wrong as the opposite.
  it("says what the engine does and does not take from the management terms", () => {
    render(<RuleForm draft={{ ...BLANK, trailEnabled: true }} set={vi.fn()} specs={SPECS} step="management" />);
    const text = document.body.textContent ?? "";
    expect(text).toContain("switched on or off by this rule");
    expect(text).toContain("break-even trigger is used exactly");
    expect(text).toContain("trail distance is the engine's own");
    expect(text).not.toContain("does not apply these yet");
  });

  it("does not claim the daily cap is unenforced, and says what an empty one means", () => {
    render(<RuleForm draft={BLANK} set={vi.fn()} specs={SPECS} step="limits" />);
    const text = document.body.textContent ?? "";
    expect(text).toContain("account's own daily limit still applies");
    // Max exposure really is not enforced in this release, and still says so.
    expect(text).toContain("Recorded on the rule; not enforced by the engine yet.");
  });

  it("does not promise that flatten closes anything", () => {
    render(<RuleForm draft={{ ...BLANK, onLimit: "flatten" }} set={vi.fn()} specs={SPECS} step="limits" />);
    const text = document.body.textContent ?? "";
    expect(text).toContain("Not applied yet");
    expect(text).not.toContain("Close open positions as well as refusing new entries");
  });
});

describe("the form never changes a value behind the user", () => {
  it("edits go through the caller's setter, one field at a time", () => {
    const set = vi.fn();
    render(<RuleForm draft={BLANK} set={set} specs={SPECS} step="risk" />);
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "2.5" } });
    expect(set).toHaveBeenCalledWith("riskPercent", "2.5");
    // Exactly one field touched.
    expect(set).toHaveBeenCalledTimes(1);
  });
});
