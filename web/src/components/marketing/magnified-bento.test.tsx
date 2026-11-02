import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MagnifiedBento } from "./magnified-bento";

function setup() {
  const utils = render(
    <MagnifiedBento className="mkt-rails" label="x">
      <article data-spot data-testid="a"><p>one</p></article>
      <article data-spot data-testid="b"><p>two</p></article>
    </MagnifiedBento>,
  );
  const root = utils.container.firstElementChild as HTMLElement;
  return { ...utils, root, a: utils.getByTestId("a"), b: utils.getByTestId("b") };
}

describe("MagnifiedBento", () => {
  it("lights the hovered cell and clears on leave", () => {
    const { root, a, b, getByText } = setup();
    fireEvent.pointerOver(getByText("one"), { pointerType: "mouse" });
    expect(a.hasAttribute("data-lit")).toBe(true);
    expect(root.hasAttribute("data-engaged")).toBe(true);
    fireEvent.pointerOver(getByText("two"), { pointerType: "mouse" });
    expect(a.hasAttribute("data-lit")).toBe(false);
    expect(b.hasAttribute("data-lit")).toBe(true);
    fireEvent.pointerLeave(root, { pointerType: "mouse" });
    expect(b.hasAttribute("data-lit")).toBe(false);
    expect(root.hasAttribute("data-engaged")).toBe(false);
  });

  it("holds the effect after a tap until another cell is tapped", () => {
    const { a, b, getByText } = setup();
    fireEvent.pointerDown(getByText("one"), { pointerType: "touch" });
    expect(a.hasAttribute("data-lit")).toBe(true);
    fireEvent.pointerDown(getByText("two"), { pointerType: "touch" });
    expect(a.hasAttribute("data-lit")).toBe(false);
    expect(b.hasAttribute("data-lit")).toBe(true);
  });

  it("follows focus for keyboard users", () => {
    const { a, getByText } = setup();
    fireEvent.focus(getByText("one"));
    expect(a.hasAttribute("data-lit")).toBe(true);
  });
});
