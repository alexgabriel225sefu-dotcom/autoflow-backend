// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { InstrumentCard, describeInstrument } from "./instrument-art";

describe("describeInstrument", () => {
  it("names a currency pair by both currencies", () => {
    expect(describeInstrument("EURUSD")).toEqual({ title: "EUR/USD", subtitle: "Euro against the US Dollar", kind: "pair" });
    expect(describeInstrument("nzdusd").subtitle).toBe("New Zealand Dollar against the US Dollar");
  });
  it("knows gold and silver", () => {
    expect(describeInstrument("XAUUSD").kind).toBe("gold");
    expect(describeInstrument("XAGUSD").title).toBe("Silver");
  });
  it("does not guess for an instrument it has not heard of", () => {
    expect(describeInstrument("US30")).toEqual({ title: "US30", subtitle: "Instrument from your broker", kind: "other" });
    expect(describeInstrument("ABCDEF").kind).toBe("other");
  });
});

describe("InstrumentCard", () => {
  it("says which instrument is selected and draws two flags for a pair", () => {
    const { container } = render(<InstrumentCard symbol="EURUSD" />);
    expect(screen.getByRole("group", { name: "Selected instrument: EUR/USD" })).toBeDefined();
    expect(container.querySelectorAll("svg.ins-disc")).toHaveLength(2);
    expect(screen.getByText("Euro against the US Dollar")).toBeDefined();
  });
  it("draws bars for gold", () => {
    const { container } = render(<InstrumentCard symbol="XAUUSD" />);
    expect(container.querySelector("svg.ins-bars")).not.toBeNull();
  });
});
