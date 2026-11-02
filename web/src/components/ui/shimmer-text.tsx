import styles from "./shimmer-text.module.css";

/**
 * Gradient Shimmer by mona_biasia (21st.dev), written natively: a glint that
 * passes over text. Used only on "running" states. The text keeps its own
 * colour (currentColor) so it works on every button and chip; the glint is a
 * dip in that colour's alpha. Static under prefers-reduced-motion.
 */
export function ShimmerText({ children, className }: {
  children: React.ReactNode; className?: string;
}) {
  return <span className={`${styles.shimmer} ${className ?? ""}`.trim()}>{children}</span>;
}
