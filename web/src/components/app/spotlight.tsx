"use client";
import type { PointerEvent } from "react";

/**
 * Coloured glow that follows the pointer, in the user's accent.
 *
 * The card does not move and does not change size. Reduced motion leaves
 * the card as it was. Touch sets the glow where the finger landed.
 */
export function spotAt(el: HTMLElement, clientX: number, clientY: number) {
  const media = typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : null;
  if (media?.matches) return;
  const rect = el.getBoundingClientRect();
  el.style.setProperty("--spot-x", `${clientX - rect.left}px`);
  el.style.setProperty("--spot-y", `${clientY - rect.top}px`);
}

export function onSpot(event: PointerEvent<HTMLElement>) {
  spotAt(event.currentTarget, event.clientX, event.clientY);
}
