import { describe, expect, it } from "vitest";
import { plainDecision } from "./plain";

// The journal is append-only evidence. Entries written before engine errors had
// their own status carry "broker_error" for something the BROKER never did, and
// the stored status is not rewritten — only the words shown for it are.
describe("plainDecision — engine refusals filed before engine_error existed", () => {
  it("labels the old engine-refusal entry as an Engine error, keeping its text", () => {
    const p = plainDecision({
      status: "broker_error",
      error: "the engine refused to start this loop",
    });
    expect(p.label).toBe("Engine error");
    expect(p.detail).toBe("the engine refused to start this loop");
    expect(p.tone).toBe("short");
  });

  it("also covers the longer sentence the current code writes", () => {
    const p = plainDecision({
      status: "broker_error",
      error: "the engine refused to start this loop — it may already be owned by another instance",
    });
    expect(p.label).toBe("Engine error");
  });

  it("is not fooled by case or surrounding whitespace", () => {
    expect(plainDecision({ status: "broker_error", error: "  The Engine refused to start this loop " }).label)
      .toBe("Engine error");
  });

  it.each([
    ["a real provider failure", "ctrader error: INVALID_REQUEST"],
    ["a timeout", "request timed out"],
    ["the phrase appearing mid-sentence", "cTrader said the engine refused to start this loop"],
    ["an empty message", ""],
    ["no message", null],
  ])("keeps 'Broker error' for %s", (_name, error) => {
    expect(plainDecision({ status: "broker_error", error }).label).toBe("Broker error");
  });

  it("leaves an entry that is already an engine_error alone", () => {
    expect(plainDecision({ status: "engine_error", error: "x" }).label).toBe("Engine error");
  });
});
