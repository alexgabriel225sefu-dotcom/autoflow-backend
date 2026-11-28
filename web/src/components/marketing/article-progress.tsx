"use client";

import { useEffect, useRef } from "react";
import styles from "./article-view.module.css";

/**
 * A thin reading-progress bar fixed to the top of the viewport.
 * It tracks how far the element with `targetId` has scrolled past. Updates are
 * batched on animation frames, and no easing is applied, so there is no motion
 * beyond the bar's own width (and `prefers-reduced-motion` removes even that
 * transition in the stylesheet).
 */
export function ArticleProgress({ targetId }: { targetId: string }) {
  const bar = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const target = document.getElementById(targetId);
      const el = bar.current;
      if (!target || !el) return;
      const rect = target.getBoundingClientRect();
      const span = Math.max(rect.height - window.innerHeight * 0.6, 1);
      const ratio = Math.min(Math.max(-rect.top / span, 0), 1);
      el.style.transform = `scaleX(${ratio})`;
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [targetId]);

  return (
    <div className={styles.progress} aria-hidden="true">
      <div ref={bar} className={styles.progressBar} />
    </div>
  );
}
