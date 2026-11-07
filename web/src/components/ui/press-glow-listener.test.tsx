// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { PressGlowListener } from "./press-glow-listener";

afterEach(cleanup);

const press = (el: Element) => el.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, clientX: 12, clientY: 8, button: 0 }));

describe("PressGlowListener", () => {
  it("lights up the card that was pressed and records where", () => {
    const { container } = render(<><PressGlowListener /><div className="ovb-tile"><span>Running</span></div></>);
    const tile = container.querySelector(".ovb-tile") as HTMLElement;
    press(tile.querySelector("span")!);
    expect(tile.getAttribute("data-glow")).toBe("true");
    expect(tile.style.getPropertyValue("--gx")).toBe("12px");
  });

  it("ignores things that are not on the list and disabled controls", () => {
    const { container } = render(<><PressGlowListener /><p className="plain">text</p><button className="chip" disabled>x</button></>);
    press(container.querySelector(".plain")!);
    press(container.querySelector(".chip")!);
    expect(container.querySelector("[data-glow]")).toBeNull();
  });
});
