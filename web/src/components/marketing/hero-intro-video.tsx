import styles from "./hero-intro-video.module.css";

/**
 * The first visual on the public page is a short brand introduction, not a
 * product claim. The product screenshots remain below it in the tour section.
 */
export function HeroIntroVideo() {
  return (
    <div
      className={styles.card}
      role="img"
      aria-label="Apex4Traders logo introduction for the rule-based trading platform"
    >
      <video
        className={styles.video}
        autoPlay
        muted
        loop
        playsInline
        preload="metadata"
        poster="/apex4traders-logo-light.png"
        aria-hidden="true"
      >
        <source src="/video/apex4traders-hero.mp4" type="video/mp4" />
      </video>
      <div className={styles.shade} aria-hidden="true" />
      <div className={styles.meta} aria-hidden="true">
        <span className={styles.metaLabel}>Apex4Traders</span>
        <span className={styles.metaValue}>Rules you can read</span>
      </div>
      <p className="sr-only">
        A short animated introduction of the Apex4Traders logo on a dark
        graphite background.
      </p>
    </div>
  );
}
