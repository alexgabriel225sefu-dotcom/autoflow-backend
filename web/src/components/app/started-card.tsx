"use client";
import { useEffect } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";

/**
 * Shown once, right after the server has accepted Start.
 *
 * The motion follows the order-confirmation and confetti components on
 * 21st.dev (a ring that springs in, a check that draws itself, content that
 * rises in turn, a short burst), written here against the app's tokens so no
 * new dependency comes with it.
 *
 * What it SAYS is deliberately smaller than what it shows: starting
 * automation is not placing a trade. The rule decides that, later, and it may
 * decide nothing for days. So the card announces that the loop is running and
 * that a trade happens only if the rule fires, never that one was placed.
 */
const BURST = Array.from({ length: 14 }, (_, i) => {
  const a = (i / 14) * Math.PI * 2;
  const r = 78 + (i % 3) * 14;
  return { x: Math.cos(a) * r, y: Math.sin(a) * r, d: 0.18 + (i % 4) * 0.04, big: i % 3 === 0 };
});

export function StartedCard({
  summary, onClose,
}: { summary: string; onClose: () => void }) {
  const calm = useReducedMotion();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rise = (delay: number) => calm ? {} : {
    initial: { opacity: 0, y: 14 },
    animate: { opacity: 1, y: 0 },
    transition: { type: "spring" as const, stiffness: 140, damping: 18, delay },
  };

  return (
    <div className="started-backdrop" onClick={onClose}>
      <motion.div
        className="started-card"
        role="dialog"
        aria-modal="true"
        aria-label="Automation started"
        onClick={(e) => e.stopPropagation()}
        initial={calm ? false : { opacity: 0, scale: 0.94 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.28, ease: "easeOut" }}
      >
        <div className="started-mark" aria-hidden>
          {!calm ? BURST.map((p, i) => (
            <motion.span
              key={i}
              className={`started-dot${p.big ? " big" : ""}`}
              initial={{ x: 0, y: 0, opacity: 0, scale: 0.4 }}
              animate={{ x: p.x, y: p.y, opacity: [0, 1, 0], scale: [0.4, 1, 0.6] }}
              transition={{ duration: 0.95, delay: 0.32 + p.d, ease: "easeOut" }}
            />
          )) : null}
          <motion.span
            className="started-ring"
            initial={calm ? false : { scale: 0.4, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", stiffness: 180, damping: 14 }}
          />
          <svg viewBox="0 0 52 52" width="56" height="56" fill="none">
            <motion.path
              d="M15 27.5l8 8 15-17"
              stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"
              initial={calm ? false : { pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.45, delay: 0.22, ease: "easeOut" }}
            />
          </svg>
        </div>

        <motion.h2 {...rise(0.3)}>Automation started</motion.h2>
        <motion.p className="started-summary" {...rise(0.38)}>{summary}</motion.p>
        <motion.p className="muted started-note" {...rise(0.46)}>
          It is watching the market now and follows your rule. A trade is
          placed only if the rule fires; you can stop it at any time from the
          dashboard.
        </motion.p>
        <motion.div className="started-actions" {...rise(0.54)}>
          <Link className="btn btn-primary" href="/dashboard">Go to dashboard</Link>
          <button type="button" className="btn" onClick={onClose}>Close</button>
        </motion.div>
      </motion.div>
    </div>
  );
}
