"use client";
import { useEffect } from "react";

/**
 * What you press lights up, and cards lean toward the pointer a little.
 *
 * One delegated listener, mounted once, like the ripple. It only sets
 * attributes and custom properties; the colour, the glow and the tilt all live
 * in the stylesheet and follow the accent. Renders nothing, does nothing for
 * visitors who asked for less motion, and never touches a disabled control.
 */
const GLOW = ".ovb-tile, .duo-card, .jrn-step, .card, .chip, .tab, .side a, .ins-card, .wc-swatch";
const TILT = ".ovb-tile, .duo-card";
const MAX_TILT = 5;

const reduced = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function"
  && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function PressGlowListener() {
  useEffect(() => {
    if (reduced()) return;
    const timers = new WeakMap<Element, number>();

    const down = (e: PointerEvent) => {
      if (e.button > 0 || !(e.target instanceof Element)) return;
      const el = e.target.closest<HTMLElement>(GLOW);
      if (!el || el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true") return;
      const r = el.getBoundingClientRect();
      el.style.setProperty("--gx", `${e.clientX - r.left}px`);
      el.style.setProperty("--gy", `${e.clientY - r.top}px`);
      el.removeAttribute("data-glow");
      void el.offsetWidth; // restart the animation on a quick second press
      el.setAttribute("data-glow", "true");
      window.clearTimeout(timers.get(el));
      timers.set(el, window.setTimeout(() => el.removeAttribute("data-glow"), 900));
    };

    const move = (e: PointerEvent) => {
      if (e.pointerType === "touch" || !(e.target instanceof Element)) return;
      const el = e.target.closest<HTMLElement>(TILT);
      if (!el) return;
      const r = el.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5;
      const py = (e.clientY - r.top) / r.height - 0.5;
      el.style.setProperty("--ry", `${(px * MAX_TILT * 2).toFixed(2)}deg`);
      el.style.setProperty("--rx", `${(-py * MAX_TILT * 2).toFixed(2)}deg`);
    };
    const leave = (e: PointerEvent) => {
      if (!(e.target instanceof Element)) return;
      const el = e.target.closest<HTMLElement>(TILT);
      if (el) { el.style.removeProperty("--rx"); el.style.removeProperty("--ry"); }
    };

    document.addEventListener("pointerdown", down, { passive: true });
    document.addEventListener("pointermove", move, { passive: true });
    document.addEventListener("pointerout", leave, { passive: true });
    return () => {
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerout", leave);
    };
  }, []);
  return null;
}
