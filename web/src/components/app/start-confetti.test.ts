import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fire = vi.fn();
const create = vi.fn(() => fire);
vi.mock("canvas-confetti", () => ({ default: { create } }));

import { fireStartConfetti } from "./start-confetti";

function motion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: reduce && q.includes("reduce") }));
}

describe("fireStartConfetti", () => {
  beforeEach(() => {
    fire.mockClear(); create.mockClear();
    vi.stubGlobal("requestAnimationFrame", () => 0);
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML = "";
  });

  it("fires from both bottom corners", async () => {
    motion(false);
    await fireStartConfetti();
    expect(fire.mock.calls.map((c) => c[0].origin.x).sort()).toEqual([0, 1]);
  });

  it("builds its own instance with no worker, which the site's CSP refuses", async () => {
    motion(false);
    await fireStartConfetti();
    expect(create).toHaveBeenCalledTimes(1);
    expect((create.mock.calls[0] as unknown[])[1]).toMatchObject({ useWorker: false });
  });

  it("draws on a canvas that takes no clicks and removes it afterwards", async () => {
    motion(false);
    await fireStartConfetti();
    const canvas = document.querySelector("canvas")!;
    expect(canvas.style.pointerEvents).toBe("none");
    vi.advanceTimersByTime(4000);
    expect(document.querySelector("canvas")).toBeNull();
  });

  it("stays still when reduced motion is asked for", async () => {
    motion(true);
    await fireStartConfetti();
    expect(create).not.toHaveBeenCalled();
    expect(document.querySelector("canvas")).toBeNull();
  });

  it("never throws, and leaves no canvas behind, if the library cannot run", async () => {
    motion(false);
    create.mockImplementationOnce(() => { throw new Error("no canvas"); });
    await expect(fireStartConfetti()).resolves.toBeUndefined();
    expect(document.querySelector("canvas")).toBeNull();
  });
});
