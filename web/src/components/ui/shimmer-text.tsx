"use client";
import { GradientShimmer } from "gradient-shimmer";

/**
 * Gradient Shimmer by mona_biasia (21st.dev): the published `gradient-shimmer`
 * package (MIT), used as it ships. A multi-stop gradient band sweeps across the
 * text; it pauses off screen, while scrolling and under prefers-reduced-motion.
 * Used only on "running" states. The text is real DOM text, so assistive tech
 * reads it normally. `children` must be a string.
 */
export function ShimmerText({ children, className }: { children: string; className?: string }) {
  return <GradientShimmer className={className}>{children}</GradientShimmer>;
}
