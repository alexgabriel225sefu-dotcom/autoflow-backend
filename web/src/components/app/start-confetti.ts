/**
 * Confetti when the server has accepted Start, and nothing else: no card, no
 * words. The words are the ConfirmAction result that is already on screen.
 *
 * The library and the side-cannon pattern come from the Confetti component on
 * 21st.dev. It is loaded on demand so it is not part of the Trade page's
 * first load, it skips itself when the person has asked for reduced motion,
 * and it draws on a canvas of its own above the page that takes no clicks and
 * is removed when the last piece has fallen.
 *
 * It makes its own instance because the library's default one draws in a
 * blob: worker, which the site's Content-Security-Policy refuses: with the
 * default, nothing is drawn at all and nothing says why.
 */
const COLOURS = ["#F7F6F2", "#FF9484", "#D93A2B", "#18A35C"];
const SHOOT_MS = 1400;
const SETTLE_MS = 3200;

export async function fireStartConfetti(): Promise<void> {
  if (typeof window === "undefined") return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  let canvas: HTMLCanvasElement | null = null;
  try {
    const { default: confetti } = await import("canvas-confetti");
    canvas = document.createElement("canvas");
    canvas.setAttribute("aria-hidden", "true");
    canvas.style.cssText =
      "position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:70";
    document.body.appendChild(canvas);
    const fire = confetti.create(canvas, { resize: true, useWorker: false });

    const end = Date.now() + SHOOT_MS;
    const cannon = (angle: number, x: number) => fire({
      particleCount: 3, angle, spread: 62, startVelocity: 58,
      origin: { x, y: 0.85 }, colors: COLOURS,
    });
    const frame = () => {
      cannon(60, 0);
      cannon(120, 1);
      if (Date.now() < end) requestAnimationFrame(frame);
    };
    frame();

    const mine = canvas;
    window.setTimeout(() => mine.remove(), SETTLE_MS);
  } catch {
    // A decoration that fails to load must never turn a successful Start into
    // an error. The result text is already shown.
    canvas?.remove();
  }
}
