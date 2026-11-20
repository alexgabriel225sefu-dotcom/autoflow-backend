"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./reading-progress.module.css";

/**
 * Reading Progress, after the 21st.dev component of the same name by
 * ddoemonn. Written natively for this codebase: no dependencies.
 */

const WORDS_PER_MINUTE = 220;
/** The fill moves in 24 steps, as in the original Reading Progress (interior). */
const STEPS = 24;

/** Whole minutes still to read at `fraction` read, or 0 when finished. */
export function minutesLeft(words: number, fraction: number): number {
  if (!Number.isFinite(words) || words <= 0 || fraction >= 0.995) return 0;
  return Math.max(1, Math.ceil((words * (1 - fraction)) / WORDS_PER_MINUTE));
}

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
  const [left, setLeft] = useState(0);
  const [total, setTotal] = useState(0);
  const words = useRef(0);

  useEffect(() => {
    let frame = 0;
    const measure = () => {
      frame = 0;
      const el = document.documentElement;
      const fraction = Math.round(readingProgress(
        window.scrollY || el.scrollTop,
        el.scrollHeight,
        el.clientHeight,
      ) * STEPS) / STEPS;
      if (barRef.current) barRef.current.style.transform = `scaleX(${fraction})`;
      words.current = (document.querySelector("main")?.innerText ?? "").split(/\s+/).filter(Boolean).length;
      setPercent(Math.round(fraction * 100));
      setLeft(minutesLeft(words.current, fraction));
      setTotal(Math.max(1, Math.ceil(words.current / WORDS_PER_MINUTE)));
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

  const done = percent >= 100;
  return (
    <div className={styles.strip}>
      <div className={styles.inner}>
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
        <span className={styles.time} aria-hidden>
          {done ? (
            <>
              <svg width="12" height="12" viewBox="0 0 256 256" fill="none" aria-hidden>
                <polyline points="216 72 104 184 48 128" stroke="currentColor" strokeWidth="16" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              End · {total} min
            </>
          ) : left > 0 ? `${left} min left` : ""}
        </span>
      </div>
    </div>
  );
}
