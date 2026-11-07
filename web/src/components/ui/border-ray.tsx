import styles from "./border-ray.module.css";

/**
 * Animated Border by kevingirelli (21st.dev), written natively: a ray of
 * light travels around the border of its parent. The parent must be
 * `position: relative` (the strategy cards are `.spot`). Render it only on the
 * element that should animate. Static ring under prefers-reduced-motion.
 */
export function BorderRay() {
  return <span className={styles.ray} aria-hidden="true" />;
}
