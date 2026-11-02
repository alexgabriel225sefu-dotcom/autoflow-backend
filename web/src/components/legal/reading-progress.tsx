"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./reading-progress.module.css";

/**
 * Reading Progress, after the 21st.dev component of the same name by
 * ddoemonn. Written natively for this codebase: no dependencies.
 */

/** Fraction (0..1) of the scrollable distance already travelled. */
export function readingProgress(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
): number {
  const distance = scrollHeight - clientHeight;
  if (!Number.isFinite(distance) || distance <= 0) return 1;
  // Sub-pixel rounding at the very bottom should still read as 100%.
  if (distance - scrollTop <= 1) return 1;
  const fraction = scrollTop / distance;
  if (!Number.isFinite(fraction)) return 0;
  return Math.min(1, Math.max(0, fraction));
}

export function ReadingProgress({ label = "Reading progress" }: { label?: string }) {
  const barRef = useRef<HTMLDivElement>(null);
  const [percent, setPercent] = useState(0);

  useEffect(() => {
    let frame = 0;
    const measure = () => {
      frame = 0;
      const el = document.documentElement;
      const fraction = readingProgress(
        window.scrollY || el.scrollTop,
        el.scrollHeight,
        el.clientHeight,
      );
      if (barRef.current) barRef.current.style.transform = `scaleX(${fraction})`;
      setPercent(Math.round(fraction * 100));
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    // Sections expanding or collapsing change the page height.
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    observer?.observe(document.body);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      observer?.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div
      className={styles.track}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-valuetext={`${percent}% read`}
    >
      <div ref={barRef} className={styles.bar} />
    </div>
  );
}
