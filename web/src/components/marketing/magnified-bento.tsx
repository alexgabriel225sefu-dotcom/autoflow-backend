"use client";

import { useRef, type ReactNode } from "react";
import { SpotlightGrid } from "./spotlight-grid";
import styles from "./magnified-bento.module.css";

/**
 * The feature grid with a magnifying cell: the cell under the pointer (or
 * focus, or the last tap on touch) grows slightly while the others recede.
 *
 * Pattern: "Magnified Bento" by 0xUrvish (21st.dev), written natively here.
 * The state lives in data attributes on DOM nodes, not React state, so moving
 * between cells re-renders nothing. The effect is transform-only in CSS (no
 * layout shift) and is highlight-only under prefers-reduced-motion.
 */
export function MagnifiedBento({
  children, className = "", label,
}: { children: ReactNode; className?: string; label?: string }) {
  const rootRef = useRef<HTMLDivElement>(null);

  function light(cell: HTMLElement | null) {
    const root = rootRef.current;
    if (!root) return;
    root.querySelectorAll<HTMLElement>("[data-lit]").forEach((n) => {
      if (n !== cell) n.removeAttribute("data-lit");
    });
    if (cell) {
      cell.setAttribute("data-lit", "");
      root.setAttribute("data-engaged", "");
    } else {
      root.removeAttribute("data-engaged");
    }
  }

  const cellOf = (t: EventTarget | null) =>
    (t as HTMLElement | null)?.closest?.<HTMLElement>("[data-spot]") ?? null;

  return (
    <div
      ref={rootRef}
      className={styles.root}
      onPointerOver={(e) => { if (e.pointerType === "mouse") light(cellOf(e.target)); }}
      onPointerLeave={(e) => { if (e.pointerType === "mouse") light(null); }}
      // A tap holds the effect on that cell until another cell is tapped.
      onPointerDown={(e) => { if (e.pointerType !== "mouse") light(cellOf(e.target)); }}
      onFocus={(e) => light(cellOf(e.target))}
      onBlur={(e) => {
        if (!rootRef.current?.contains(e.relatedTarget as Node | null)) light(null);
      }}
    >
      <SpotlightGrid className={className} label={label}>{children}</SpotlightGrid>
    </div>
  );
}
