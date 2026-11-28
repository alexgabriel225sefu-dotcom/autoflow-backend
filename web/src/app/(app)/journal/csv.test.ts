import { describe, expect, it } from "vitest";
import type { JournalEntry } from "@/lib/api";
import { csvCell, journalToCsv } from "./csv";

const entry = (over: Partial<JournalEntry> = {}): JournalEntry => ({
  entryId: "e1", kind: "evaluation", status: "signal", ts: 1760000000,
  symbol: "EURUSD", accountId: "901", ruleDocId: "rule-1", correlationId: "c",
  snapshot: { symbol: "EURUSD", price: 1.08421 },
  decision: {
    verdict: "BUY", reason: "RSI 28, price above the 200 EMA", conditions: [],
    executable: false, refusalCode: null, confidence: 72,
  },
  ...over,
});

describe("journalToCsv", () => {
  it("has a header and one line per loaded row", () => {
    const lines = journalToCsv([entry(), entry({ entryId: "e2" })]).trim().split("\r\n");
    expect(lines).toHaveLength(3);
    expect(lines[0]).toBe(
      "time_utc,symbol,status,verdict,reason,refusal_code,error,entry_price,confidence,rule_id,account_id,entry_id");
    expect(lines[1]).toBe(
      '2025-10-09T08:53:20.000Z,EURUSD,signal,BUY,"RSI 28, price above the 200 EMA",,,1.08421,72,rule-1,901,e1');
  });

  it("is just the header for no rows", () => {
    expect(journalToCsv([]).trim().split("\r\n")).toHaveLength(1);
  });

  it("quotes commas, quotes and newlines", () => {
    expect(csvCell('say "hi", ok\nnow')).toBe('"say ""hi"", ok\nnow"');
  });

  it("defuses spreadsheet formulas but leaves plain negative numbers alone", () => {
    expect(csvCell("=HYPERLINK(\"http://x\")")).toBe("\"'=HYPERLINK(\"\"http://x\"\")\"");
    expect(csvCell("@SUM(A1)")).toBe("'@SUM(A1)");
    expect(csvCell("-5")).toBe("-5");
    expect(csvCell(null)).toBe("");
  });

  it("keeps an error entry's error and refusal code", () => {
    const csv = journalToCsv([entry({
      status: "broker_error", error: "broker said no",
      decision: { verdict: "HOLD", reason: "", conditions: [], executable: false, refusalCode: "MIN_LOT" } as never,
      snapshot: null,
    })]);
    expect(csv).toContain("MIN_LOT,broker said no,,");
  });
});
