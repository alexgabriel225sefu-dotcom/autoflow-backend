// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { InstrumentCard, describeInstrument } from "./instrument-art";

describe("describeInstrument", () => {
  it("names a currency pair by both currencies", () => {
    expect(describeInstrument("EURUSD")).toEqual({ title: "EUR/USD", subtitle: "Euro against the US Dollar", kind: "pair" });
    expect(describeInstrument("nzdusd").subtitle).toBe("New Zealand Dollar against the US Dollar");
  });
  it("knows the metals", () => {
    expect(describeInstrument("XAUUSD")).toMatchObject({ kind: "metal", detail: "gold", title: "Gold" });
    expect(describeInstrument("XAGUSD").title).toBe("Silver");
    expect(describeInstrument("XPTUSD").detail).toBe("platinum");
  });
  it("knows well-known indices, oil, gas and digital coins", () => {
    expect(describeInstrument("US30")).toMatchObject({ kind: "index", subtitle: "Dow Jones 30", detail: "USD" });
    expect(describeInstrument("GER40").subtitle).toBe("DAX 40");
    expect(describeInstrument("XTIUSD").kind).toBe("oil");
    expect(describeInstrument("XNGUSD").kind).toBe("gas");
    expect(describeInstrument("BTCUSD")).toMatchObject({ kind: "token", subtitle: "Bitcoin" });
  });
  it("covers more currencies and crosses", () => {
    expect(describeInstrument("EURGBP").subtitle).toBe("Euro against the British Pound");
    expect(describeInstrument("USDSEK").kind).toBe("pair");
  });
  it("does not invent a name for what it has not heard of", () => {
    expect(describeInstrument("ABCDEF")).toEqual({ title: "ABCDEF", subtitle: "Instrument from your broker", kind: "other" });
    expect(describeInstrument("AAPL", "stock")).toEqual({ title: "AAPL", subtitle: "Share from your broker", kind: "stock" });
    expect(describeInstrument("XYZ500", "index")).toEqual({ title: "XYZ500", subtitle: "Index from your broker", kind: "index" });
  });
  it("lets the broker's class win over a lookalike", () => {
    expect(describeInstrument("EURUSD", "stock").kind).toBe("stock");
  });
});

describe("InstrumentCard", () => {
  it("says which instrument is selected and draws two flags for a pair", () => {
    const { container } = render(<InstrumentCard symbol="EURUSD" />);
    expect(screen.getByRole("group", { name: "Selected instrument: EUR/USD" })).toBeDefined();
    expect(container.querySelectorAll("svg.ins-disc")).toHaveLength(2);
    expect(screen.getByText("Euro against the US Dollar")).toBeDefined();
  });
  it("draws something for every kind of instrument, never a blank", () => {
    for (const [sym, cls] of [["EURSEK", "forex_cross"], ["US500", "index"], ["XTIUSD", "other"], ["XNGUSD", "other"], ["ETHUSD", "other"], ["AAPL", "stock"], ["ZZZ", undefined], ["EURXYZ", "forex_cross"]] as const) {
      const { container, unmount } = render(<InstrumentCard symbol={sym} cls={cls} />);
      expect(container.querySelectorAll("svg").length, sym).toBeGreaterThan(0);
      unmount();
    }
  });
  it("draws bars for gold", () => {
    const { container } = render(<InstrumentCard symbol="XAUUSD" />);
    expect(container.querySelector("svg.ins-bars")).not.toBeNull();
  });
});
