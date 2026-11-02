/**
 * The interaction pieces adapted from the chosen references.
 *
 * They keep the app's tokens: the glow uses the accent, the ticker prints the
 * amount, and an error notice is a halo rather than a flat red box.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CurrencyTicker, formatMoney } from "./currency-ticker";
import { OverviewBand } from "./overview-band";
import { ErrorNotice } from "./state";
import { spotAt } from "./spotlight";

describe("currency ticker", () => {
  it("prints the amount, and a dash when there is no amount", () => {
    expect(formatMoney(123.45)).toBe("$123.45");
    expect(formatMoney(-12.5)).toBe("−$12.50");
    const { rerender } = render(<CurrencyTicker value={123.45} />);
    expect(screen.getByLabelText("$123.45").textContent).toBe("$123.45");
    rerender(<CurrencyTicker value={null} />);
    expect(screen.getByText("—")).toBeDefined();
  });
});

describe("spotlight card", () => {
  it("parks the glow on the pointer without changing the value", () => {
    render(<OverviewBand tiles={[{ label: "State", value: "Market closed", tone: "neutral" }]} />);
    const tile = screen.getByText("Market closed").closest(".spot") as HTMLElement;
    expect(tile).toBeTruthy();
    tile.getBoundingClientRect = () => ({
      left: 10, top: 20, right: 110, bottom: 80, width: 100, height: 60,
      x: 10, y: 20, toJSON() { return {}; },
    });
    fireEvent.pointerMove(tile, { clientX: 40, clientY: 50 });
    expect(tile.style.getPropertyValue("--spot-x")).toBe("30px");
    expect(tile.style.getPropertyValue("--spot-y")).toBe("30px");
    expect(screen.getByText("Market closed")).toBeDefined();
  });

  it("spotAt is a no-op when motion is reduced", () => {
    const prev = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: query.includes("reduce"),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
      onchange: null,
    })) as typeof window.matchMedia;
    const el = document.createElement("div");
    spotAt(el, 10, 10);
    expect(el.style.getPropertyValue("--spot-x")).toBe("");
    window.matchMedia = prev;
  });
});

describe("halo alert", () => {
  it("uses the glowing error notice and hides the warning emoji", () => {
    render(<ErrorNotice error={{
      ok: false, status: 500, code: "ENGINE_REFUSED",
      message: "the trading engine refused to start this loop (another instance already owns this loop)",
    }} />);
    const alert = screen.getByRole("alert");
    expect(alert.className).toContain("notice-error");
    expect(alert.textContent).toContain("another instance already owns this loop");
    expect(alert.querySelector("[aria-hidden='true']")?.textContent).toBe("⚠️");
  });
});
