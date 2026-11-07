"use client";

import { useRef, type ReactNode } from "react";
import styles from "./magnifier-card.module.css";

/**
 * "Magnified Bento" by 0xUrvish (21st.dev, MIT), rebuilt with the same
 * construction and numbers, minus its animation library.
 *
 * THREE LAYERS, ONE LENS. Rows of pills scroll sideways forever. The BASE layer
 * is masked so it is empty inside a 30px circle; the REVEAL layer is clipped to
 * that same circle and draws every pill 25% larger and in full colour; the LENS,
 * a magnifying-glass drawing, is dragged by hand and moves the circle with it.
 * The hole sits 10px up and left of the lens centre, which is where the glass of
 * the drawing is.
 *
 * Both layers run the same CSS animation from the same instant, so a pill under
 * the lens is the same pill in both. The lens position goes into two CSS
 * variables on the stage and never into React state.
 *
 * The icon arrives as an element, not a component: the page is a server
 * component and a function cannot cross into a client component.
 *
 * Every pill is a plain label for sighted users; the whole stage is aria-hidden
 * because the card's title and sentence say the same thing in words.
 */

const LENS = 92;       // lens drawing size, px
const HALF = LENS / 2;

export function MagnifierCard({
  rows, icon, title, children,
}: { rows: string[][]; icon: ReactNode; title: string; children: ReactNode }) {
  const stage = useRef<HTMLDivElement>(null);
  const grab = useRef<{ id: number; sx: number; sy: number; x0: number; y0: number } | null>(null);
  const pos = useRef({ x: 0, y: 0 });

  function set(x: number, y: number) {
    const st = stage.current;
    if (!st) return;
    // The lens may travel until its edge meets the stage edge (dragConstraints).
    const mx = Math.max(0, st.clientWidth / 2 - HALF);
    const my = Math.max(0, st.clientHeight / 2 - HALF);
    pos.current = { x: Math.min(mx, Math.max(-mx, x)), y: Math.min(my, Math.max(-my, y)) };
    st.style.setProperty("--lx", `${pos.current.x}px`);
    st.style.setProperty("--ly", `${pos.current.y}px`);
  }

  return (
    <article className={styles.card}>
      <div ref={stage} className={styles.stage}>
        <div className={styles.fieldBox} aria-hidden>
          <Field rows={rows} icon={icon} className={styles.base} />
          <Field rows={rows} icon={icon} className={styles.reveal} />
        </div>
        <div
          className={styles.lens}
          aria-hidden
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            grab.current = { id: e.pointerId, sx: e.clientX, sy: e.clientY, x0: pos.current.x, y0: pos.current.y };
          }}
          onPointerMove={(e) => {
            const g = grab.current;
            if (g && g.id === e.pointerId) set(g.x0 + e.clientX - g.sx, g.y0 + e.clientY - g.sy);
          }}
          onPointerUp={() => { grab.current = null; }}
          onPointerCancel={() => { grab.current = null; }}
        >
          <Glass />
          <span className={styles.sheen} />
        </div>
        <span className={`${styles.fade} ${styles.fadeL}`} aria-hidden />
        <span className={`${styles.fade} ${styles.fadeR}`} aria-hidden />
      </div>
      <div className={styles.copy}>
        <h3>{title}</h3>
        <p>{children}</p>
      </div>
    </article>
  );
}

function Field({ rows, icon, className }: { rows: string[][]; icon: ReactNode; className: string }) {
  return (
    <div className={`${styles.field} ${className}`}>
      {rows.map((row, i) => (
        // Three copies, and the strip slides by one copy, so it loops without a seam.
        <div className={styles.row} data-dir={i % 2 === 0 ? "ltr" : "rtl"} key={i}>
          {[...row, ...row, ...row].map((label, j) => (
            <span className={styles.pill} key={`${label}-${j}`}>
              <span className={styles.pillIcon}>{icon}</span>
              <span>{label}</span>
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

/** The magnifying glass drawing from the original (paths unchanged). */
function Glass() {
  return (
    <svg width={LENS} height={LENS} viewBox="0 0 512 512" fill="none" aria-hidden>
      <path d="M365.424 335.392L342.24 312.192L311.68 342.736L334.88 365.936L365.424 335.392Z" fill="#B0BDC6" />
      <path d="M358.08 342.736L334.88 319.552L319.04 335.392L342.24 358.584L358.08 342.736Z" fill="#DFE9EF" />
      <path d="M352.368 321.808L342.752 312.192L312.208 342.752L321.824 352.36L352.368 321.808Z" fill="#B0BDC6" />
      <path d="M332 332C260 404 142.4 404 69.6001 332C-2.3999 260 -2.3999 142.4 69.6001 69.6C141.6 -3.20003 259.2 -2.40002 332 69.6C404.8 142.4 404.8 260 332 332ZM315.2 87.2C252 24 150.4 24 88.0001 87.2C24.8001 150.4 24.8001 252 88.0001 314.4C151.2 377.6 252.8 377.6 315.2 314.4C377.6 252 377.6 150.4 315.2 87.2Z" fill="#DFE9EF" />
      <path d="M319.2 319.2C254.4 384 148.8 384 83.2001 319.2C18.4001 254.4 18.4001 148.8 83.2001 83.2C148 18.4 253.6 18.4 319.2 83.2C384 148.8 384 254.4 319.2 319.2ZM310.4 92C250.4 32 152 32 92.0001 92C32.0001 152 32.0001 250.4 92.0001 310.4C152 370.4 250.4 370.4 310.4 310.4C370.4 250.4 370.4 152 310.4 92Z" fill="#7A858C" />
      <path d="M484.104 428.784L373.8 318.472L318.36 373.912L428.672 484.216L484.104 428.784Z" fill="#333333" />
      <path d="M471.664 441.224L361.344 330.928L330.8 361.48L441.12 471.76L471.664 441.224Z" fill="#575B5E" />
      <path d="M495.2 423.2C504 432 432.8 504 423.2 495.2L417.6 489.6C408.8 480.8 480 408.8 489.6 417.6L495.2 423.2Z" fill="#B0BDC6" />
      <path d="M483.2 435.2C492 444 444.8 492 435.2 483.2L429.6 477.6C420.8 468.8 468 420.8 477.6 429.6L483.2 435.2Z" fill="#DFE9EF" />
    </svg>
  );
}
