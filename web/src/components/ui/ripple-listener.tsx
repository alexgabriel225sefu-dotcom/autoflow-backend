"use client";
import { useEffect } from "react";
import { rippleTarget, spawnRipple } from "@/lib/use-ripple";

/**
 * One delegated listener, mounted once: every .btn and .mkt-btn ripples from
 * the pointer point without editing any button. Keyboard activation (a click
 * with detail 0) ripples from the centre. Renders nothing.
 */
export function RippleListener() {
  useEffect(() => {
    const down = (e: PointerEvent) => {
      if (e.button > 0) return;
      const el = rippleTarget(e.target);
      if (el) spawnRipple(el, e.clientX, e.clientY);
    };
    const key = (e: MouseEvent) => {
      if (e.detail !== 0) return;
      const el = rippleTarget(e.target);
      if (el) spawnRipple(el, 0, 0, true);
    };
    document.addEventListener("pointerdown", down, { passive: true });
    document.addEventListener("click", key, { passive: true });
    return () => {
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("click", key);
    };
  }, []);
  return null;
}
