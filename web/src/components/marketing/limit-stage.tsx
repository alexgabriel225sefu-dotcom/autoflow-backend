"use client";

import dynamic from "next/dynamic";
import styles from "./limit-stage.module.css";

const StopPathScene = dynamic(() => import("./stop-path-scene").then((m) => m.StopPathScene), {
  ssr: false,
  loading: () => null,
});

// Without WebGL the same idea is drawn flat: the path and the stop line.
function Flat() {
  return (
    <svg className={styles.flat} viewBox="0 0 600 220" fill="none" aria-hidden="true">
      <line x1="30" y1="178" x2="590" y2="178" stroke="var(--mkt-accent, #ff4fa3)" strokeWidth="2" />
      <polyline
        points="20,120 90,100 150,124 210,92 290,70 370,98 440,150 520,178"
        stroke="var(--mkt-text, #f7f6f2)"
        strokeWidth="3"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx="520" cy="178" r="6" fill="var(--mkt-accent, #ff4fa3)" />
    </svg>
  );
}

export function LimitStage() {
  return (
    <div
      className={styles.stage}
      role="img"
      aria-label="A price path drawn in chrome comes down onto a pink line, the rule's stop, and stops there"
    >
      <StopPathScene fallback={<Flat />} />
    </div>
  );
}
