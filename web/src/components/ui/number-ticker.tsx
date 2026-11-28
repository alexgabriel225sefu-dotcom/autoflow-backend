"use client";
/**
 * Number Ticker, from 21st.dev (danielpetho/basic-number-ticker), adapted:
 * it tweens from where the number was to where it is now, not only on mount,
 * and it renders the final value at once for visitors who asked for less
 * motion.
 */
import { useEffect, useRef } from "react";
import { animate, motion, useMotionValue, useTransform } from "motion/react";
import { cn } from "@/lib/utils";

export function NumberTicker({
  value, className, duration = 0.9,
}: { value: number; className?: string; duration?: number }) {
  const count = useMotionValue(value);
  const rounded = useTransform(count, (v) => Math.round(v));
  const first = useRef(true);

  useEffect(() => {
    const reduced = typeof window !== "undefined"
      && window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (reduced) { count.set(value); return; }
    // The first paint counts up from zero; later changes tween from the last value.
    if (first.current) { first.current = false; count.set(0); }
    const controls = animate(count, value, { duration, type: "tween", ease: "easeOut" });
    return () => controls.stop();
  }, [value, duration, count]);

  return <motion.span className={cn("tabular-nums", className)}>{rounded}</motion.span>;
}
