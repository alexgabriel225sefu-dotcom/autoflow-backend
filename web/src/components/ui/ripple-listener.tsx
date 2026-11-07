"use client";
import { useEffect } from "react";
import { releaseRipple, rippleTarget, spawnRipple } from "@/lib/use-ripple";

/**
 * One delegated listener, mounted once: every .btn and .mkt-btn ripples from
 * the pointer point without editing any button. Keyboard activation (a click
 * with detail 0) ripples from the centre. Renders nothing.
 */
export function RippleListener() {
  useEffect(() => {
    // Held presses by pointer: the ripple grows while the finger is down and
    // fades when it lifts, as in the original "Ripple Button" (ddoemonn).
    const held = new Map<number, HTMLElement | null>();
    const down = (e: PointerEvent) => {
      if (e.button > 0) return;
      const el = rippleTarget(e.target);
      if (el) held.set(e.pointerId, spawnRipple(el, e.clientX, e.clientY));
    };
    const up = (e: PointerEvent) => {
      releaseRipple(held.get(e.pointerId));
      held.delete(e.pointerId);
    };
    const key = (e: MouseEvent) => {
      if (e.detail !== 0) return;
      const el = rippleTarget(e.target);
      if (el) releaseRipple(spawnRipple(el, 0, 0, true));
    };
    document.addEventListener("pointerdown", down, { passive: true });
    document.addEventListener("pointerup", up, { passive: true });
    document.addEventListener("pointercancel", up, { passive: true });
    document.addEventListener("click", key, { passive: true });
    return () => {
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      document.removeEventListener("click", key);
    };
  }, []);
  return null;
}
