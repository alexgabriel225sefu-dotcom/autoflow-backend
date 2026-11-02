/**
 * Ripple, headless. Pattern: "Ripple Button" by ddoemonn (21st.dev), written
 * natively: no markup of its own, only a geometry helper, a spawner and a hook.
 *
 * CSP-safe: no inline script. The overlay carries element classes and CSS
 * custom properties set through style.setProperty; colour comes from the
 * stylesheet (currentColor), never from here.
 */
import { useCallback } from "react";
import styles from "./ripple.module.css";

export const RIPPLE_SELECTOR = ".btn, .mkt-btn";

export function prefersReducedMotion(): boolean {
  try {
    return typeof window !== "undefined" && typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** Circle centre (relative to the element) and diameter that covers it all. */
export function rippleGeometry(
  rect: Pick<DOMRect, "left" | "top" | "width" | "height">,
  clientX: number, clientY: number, centre = false,
) {
  const x = centre ? rect.width / 2 : clientX - rect.left;
  const y = centre ? rect.height / 2 : clientY - rect.top;
  const far = Math.hypot(Math.max(x, rect.width - x), Math.max(y, rect.height - y));
  return { x, y, size: far * 2 };
}

/** The ripple-able button for an event target, or null (disabled, none). */
export function rippleTarget(t: EventTarget | null): HTMLElement | null {
  if (!(t instanceof Element)) return null;
  const el = t.closest<HTMLElement>(RIPPLE_SELECTOR);
  if (!el) return null;
  if (el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true") return null;
  return el;
}

/** Add one ripple to `el`. Returns the overlay, or null when skipped. */
export function spawnRipple(
  el: HTMLElement, clientX: number, clientY: number, centre = false,
): HTMLElement | null {
  if (prefersReducedMotion()) return null;
  const rect = el.getBoundingClientRect();
  const g = rippleGeometry(rect, clientX, clientY, centre);
  if (typeof getComputedStyle === "function" && getComputedStyle(el).position === "static") {
    el.style.setProperty("position", "relative");
  }
  const host = document.createElement("span");
  host.className = styles.host;
  host.setAttribute("data-ripple", "");
  host.setAttribute("aria-hidden", "true");
  const dot = document.createElement("span");
  dot.className = styles.dot;
  dot.style.setProperty("--ripple-x", `${g.x}px`);
  dot.style.setProperty("--ripple-y", `${g.y}px`);
  dot.style.setProperty("--ripple-size", `${g.size}px`);
  host.appendChild(dot);
  el.appendChild(host);
  const done = () => host.remove();
  dot.addEventListener("animationend", done, { once: true });
  window.setTimeout(done, 900);
  return host;
}

/** For a single element: spread the returned handler onto it. */
export function useRipple() {
  const onPointerDown = useCallback((e: React.PointerEvent<HTMLElement>) => {
    const el = rippleTarget(e.currentTarget) ?? null;
    if (el) spawnRipple(el, e.clientX, e.clientY);
  }, []);
  return { onPointerDown };
}
