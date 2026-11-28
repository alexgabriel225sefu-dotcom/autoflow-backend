import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RippleListener } from "@/components/ui/ripple-listener";
import { rippleGeometry, rippleTarget, spawnRipple } from "./use-ripple";

const rect = { left: 10, top: 20, width: 100, height: 40 } as DOMRect;

function mockMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: reduce && q.includes("reduce"), media: q,
    addEventListener() {}, removeEventListener() {},
  }));
}
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("rippleGeometry", () => {
  it("centres on the pointer and covers the farthest corner", () => {
    const g = rippleGeometry(rect, 20, 30);
    expect(g.x).toBe(10);
    expect(g.y).toBe(10);
    expect(g.size).toBeCloseTo(2 * Math.hypot(90, 30), 5);
  });
  it("falls back to the centre for keyboard clicks", () => {
    const g = rippleGeometry(rect, 0, 0, true);
    expect(g.x).toBe(50);
    expect(g.y).toBe(20);
  });
});

describe("rippleTarget", () => {
  it("finds .btn and .mkt-btn ancestors", () => {
    document.body.innerHTML = `<button class="btn"><span id="a">x</span></button>
      <a class="mkt-btn mkt-btn-ghost"><b id="b">y</b></a><div id="c"></div>`;
    expect(rippleTarget(document.getElementById("a"))?.className).toBe("btn");
    expect(rippleTarget(document.getElementById("b"))?.tagName).toBe("A");
    expect(rippleTarget(document.getElementById("c"))).toBeNull();
  });
  it("skips disabled and aria-disabled buttons", () => {
    document.body.innerHTML = `<button class="btn" disabled id="a"></button>
      <a class="btn" aria-disabled="true" id="b"></a>`;
    expect(rippleTarget(document.getElementById("a"))).toBeNull();
    expect(rippleTarget(document.getElementById("b"))).toBeNull();
  });
});

describe("spawnRipple", () => {
  it("adds one overlay with custom properties and no inline colour", () => {
    mockMotion(false);
    document.body.innerHTML = `<button class="btn">Go</button>`;
    const el = document.querySelector("button") as HTMLElement;
    el.getBoundingClientRect = () => rect;
    const node = spawnRipple(el, 30, 30);
    expect(node).not.toBeNull();
    expect(el.querySelectorAll("[data-ripple]").length).toBe(1);
    const dot = node!.firstElementChild as HTMLElement;
    expect(dot.style.getPropertyValue("--ripple-size")).toMatch(/px$/);
    expect(dot.style.getPropertyValue("--ripple-x")).toBe("20px");
    expect(el.getAttribute("style") ?? "").not.toMatch(/color|#/);
  });
  it("does nothing under reduced motion", () => {
    mockMotion(true);
    document.body.innerHTML = `<button class="btn">Go</button>`;
    const el = document.querySelector("button") as HTMLElement;
    expect(spawnRipple(el, 1, 1)).toBeNull();
    expect(el.querySelector("[data-ripple]")).toBeNull();
  });
});

describe("RippleListener", () => {
  it("ripples a delegated pointerdown on a .btn child, not a disabled one", () => {
    mockMotion(false);
    render(
      <>
        <RippleListener />
        <button className="btn" data-testid="a"><span data-testid="in">Go</span></button>
        <button className="btn" disabled data-testid="d">No</button>
      </>,
    );
    const a = document.querySelector('[data-testid="a"]') as HTMLElement;
    a.getBoundingClientRect = () => rect;
    const inner = document.querySelector('[data-testid="in"]') as HTMLElement;
    inner.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, clientX: 30, clientY: 30 }));
    expect(a.querySelectorAll("[data-ripple]").length).toBe(1);
    document.querySelector('[data-testid="d"]')!
      .dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    expect(document.querySelectorAll("[data-ripple]").length).toBe(1);
  });
});
