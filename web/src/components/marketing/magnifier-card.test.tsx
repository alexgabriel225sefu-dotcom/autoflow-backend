import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Eye } from "lucide-react";
import { MagnifierCard } from "./magnifier-card";

const rows = [["RSI", "MACD"], ["ATR"]];

function setup() {
  const utils = render(<MagnifierCard icon={<Eye size={14} aria-hidden />} title="Rules" rows={rows}>Body text.</MagnifierCard>);
  const stage = utils.container.querySelector<HTMLElement>("[class*='stage']")!;
  const lens = utils.container.querySelector<HTMLElement>("[class*='lens']")!;
  return { ...utils, stage, lens };
}

describe("MagnifierCard", () => {
  it("shows the title and text, and hides the decorative stage from assistive tech", () => {
    const { stage } = setup();
    expect(screen.getByRole("heading", { name: "Rules" })).toBeTruthy();
    expect(screen.getByText("Body text.")).toBeTruthy();
    // Each label is drawn on two layers (base and magnified) ...
    expect(screen.getAllByText("RSI").length).toBeGreaterThanOrEqual(2);
    // ... and none of them is in the accessibility tree.
    expect(screen.getAllByText("RSI").every((n) => n.closest("[aria-hidden]"))).toBe(true);
    expect(stage.querySelector("[aria-hidden]")).toBeTruthy();
  });

  it("repeats each row three times so the strip loops without a seam", () => {
    setup();
    // two layers x ("RSI","MACD" per row) x 3 copies
    expect(screen.getAllByText("RSI")).toHaveLength(6);
  });

  it("moves the lens circle when the lens is dragged, and stops on release", () => {
    const { stage, lens } = setup();
    Object.defineProperty(stage, "clientWidth", { value: 300, configurable: true });
    Object.defineProperty(stage, "clientHeight", { value: 200, configurable: true });
    lens.setPointerCapture = () => {};
    fireEvent.pointerDown(lens, { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(lens, { pointerId: 1, clientX: 140, clientY: 90 });
    expect(stage.style.getPropertyValue("--lx")).toBe("40px");
    expect(stage.style.getPropertyValue("--ly")).toBe("-10px");
    fireEvent.pointerUp(lens, { pointerId: 1 });
    fireEvent.pointerMove(lens, { pointerId: 1, clientX: 200, clientY: 200 });
    expect(stage.style.getPropertyValue("--lx")).toBe("40px");
  });

  it("keeps the lens inside the stage", () => {
    const { stage, lens } = setup();
    Object.defineProperty(stage, "clientWidth", { value: 300, configurable: true });
    Object.defineProperty(stage, "clientHeight", { value: 200, configurable: true });
    lens.setPointerCapture = () => {};
    fireEvent.pointerDown(lens, { pointerId: 2, clientX: 0, clientY: 0 });
    fireEvent.pointerMove(lens, { pointerId: 2, clientX: 5000, clientY: -5000 });
    // half the stage minus half the lens (46px)
    expect(stage.style.getPropertyValue("--lx")).toBe("104px");
    expect(stage.style.getPropertyValue("--ly")).toBe("-54px");
  });
});
