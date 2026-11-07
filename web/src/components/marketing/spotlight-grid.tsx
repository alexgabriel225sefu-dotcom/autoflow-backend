"use client";

import { useRef, type ReactNode } from "react";

/**
 * A grid whose cells are lit by a soft light that follows the pointer.
 *
 * The pattern comes from the pointer-spotlight feature grids on 21st.dev,
 * written here against the landing tokens rather than installed. The pointer
 * position goes into two CSS variables on the hovered cell and never into
 * React state, so moving the mouse does not re-render anything.
 */
export function SpotlightGrid({
  children, className = "", label,
}: { children: ReactNode; className?: string; label?: string }) {
  const ref = useRef<HTMLDivElement>(null);

  function move(e: React.PointerEvent<HTMLDivElement>) {
    if (e.pointerType === "touch") return;
    const cell = (e.target as HTMLElement).closest<HTMLElement>("[data-spot]");
    if (!cell) return;
    const r = cell.getBoundingClientRect();
    cell.style.setProperty("--mx", `${e.clientX - r.left}px`);
    cell.style.setProperty("--my", `${e.clientY - r.top}px`);
  }

  return (
    <div
      ref={ref}
      className={`mkt-spot ${className}`}
      onPointerMove={move}
      aria-label={label}
    >
      {children}
    </div>
  );
}
