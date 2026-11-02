import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MagnifierCard } from "./magnifier-card";

const rows = [["RSI", "MACD"], ["ATR"]];

function setup() {
  const utils = render(<MagnifierCard title="Rules" rows={rows}>Body text.</MagnifierCard>);
  const stage = utils.container.querySelector<HTMLElement>("[class*='stage']")!;
  const lens = utils.container.querySelector<HTMLElement>("[class*='lens']")!;
  return { ...utils, stage, lens };
}

describe("MagnifierCard", () => {
  it("shows the title and text, and each label once to assistive tech", () => {
    setup();
    expect(screen.getByRole("heading", { name: "Rules" })).toBeTruthy();
    expect(screen.getByText("Body text.")).toBeTruthy();
    // Two copies exist in the DOM (the lens holds a magnified one) ...
    expect(screen.getAllByText("RSI")).toHaveLength(2);
    // ... but the magnified copy is hidden from the accessibility tree.
    expect(screen.getByText("RSI", { selector: "[aria-hidden] span" })).toBeTruthy();
    expect(screen.getAllByText("RSI").filter((n) => !n.closest("[aria-hidden]"))).toHaveLength(1);
  });

  it("moves the lens to the pointer and leaves idle state", () => {
    const { stage, lens } = setup();
    expect(stage.hasAttribute("data-idle")).toBe(true);
    fireEvent.pointerMove(stage, { clientX: 100, clientY: 60, pointerType: "mouse" });
    expect(stage.hasAttribute("data-idle")).toBe(false);
    expect(lens.style.transform).toContain("translate(");
  });

  it("returns to rest when the pointer leaves", () => {
    const { stage } = setup();
    fireEvent.pointerMove(stage, { clientX: 20, clientY: 20, pointerType: "mouse" });
    fireEvent.pointerLeave(stage);
    expect(stage.hasAttribute("data-idle")).toBe(true);
  });
});
