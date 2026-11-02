"use client";

import { useCallback, useEffect, useRef, type ReactNode } from "react";
import styles from "./magnifier-card.module.css";

/**
 * A feature card with a magnifying glass over a cloud of labels.
 *
 * Pattern: "Magnified Bento" by 0xUrvish (21st.dev): a card whose top half is
 * a field of pills, a lens that follows the pointer and enlarges whatever it
 * is over, and a title and a sentence underneath. Written natively here, in
 * the landing tokens, with no animation library.
 *
 * HOW THE LENS WORKS. The glass holds a second copy of the same pills, scaled
 * up and shifted so the point under the lens sits at the lens centre. The
 * position goes straight into inline styles on three nodes and never into React
 * state, so moving the pointer re-renders nothing. The copy is aria-hidden: a
 * screen reader meets each label once.
 *
 * TOUCH. The stage allows vertical scrolling (`touch-action: pan-y`), so a
 * finger dragging sideways moves the lens and one dragging down scrolls. At
 * rest, and after the pointer leaves, the lens sits in the middle of the stage,
 * so the card reads the same with no pointer at all.
 */

const R = 40;   // lens radius, px  (the CSS reads it from --lens)
const S = 1.9;  // magnification

export function MagnifierCard({
  rows, title, children,
}: { rows: string[][]; title: string; children: ReactNode }) {
  const stage = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const zoom = useRef<HTMLDivElement>(null);

  const place = useCallback((x: number, y: number) => {
    const st = stage.current;
    if (!st || !wrap.current || !zoom.current) return;
    const w = st.clientWidth, h = st.clientHeight;
    const cx = Math.min(Math.max(x, 0), w), cy = Math.min(Math.max(y, 0), h);
    st.style.setProperty("--w", `${w}px`);
    st.style.setProperty("--h", `${h}px`);
    wrap.current.style.transform = `translate(${cx - R}px, ${cy - R}px)`;
    zoom.current.style.transform = `translate(${R - cx * S}px, ${R - cy * S}px) scale(${S})`;
  }, []);

  const rest = useCallback(() => {
    const st = stage.current;
    if (!st) return;
    st.setAttribute("data-idle", "");
    place(st.clientWidth * 0.5, st.clientHeight * 0.52);
  }, [place]);

  useEffect(() => {
    rest();
    const st = stage.current;
    if (!st || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => { if (st.hasAttribute("data-idle")) rest(); });
    ro.observe(st);
    return () => ro.disconnect();
  }, [rest]);

  function move(e: React.PointerEvent<HTMLDivElement>) {
    const st = stage.current;
    if (!st) return;
    st.removeAttribute("data-idle");
    const r = st.getBoundingClientRect();
    place(e.clientX - r.left, e.clientY - r.top);
  }

  return (
    <article className={styles.card}>
      <div
        ref={stage}
        className={styles.stage}
        style={{ ["--lens" as string]: `${R}px` }}
        onPointerEnter={move}
        onPointerMove={move}
        onPointerLeave={rest}
        onPointerCancel={rest}
        onPointerUp={(e) => { if (e.pointerType !== "mouse") rest(); }}
      >
        <Pills rows={rows} className={styles.base} />
        <div ref={wrap} className={styles.lens} aria-hidden>
          <div className={styles.glass}>
            <div ref={zoom} className={styles.zoom}>
              <Pills rows={rows} className={styles.big} />
            </div>
          </div>
          <span className={styles.handle} />
        </div>
      </div>
      <div className={styles.copy}>
        <h3>{title}</h3>
        <p>{children}</p>
      </div>
    </article>
  );
}

function Pills({ rows, className }: { rows: string[][]; className: string }) {
  return (
    <div className={`${styles.layer} ${className}`}>
      {rows.map((row, i) => (
        <div className={styles.row} data-row={i % 3} key={i}>
          {row.map((label) => <span className={styles.pill} key={label}>{label}</span>)}
        </div>
      ))}
    </div>
  );
}
