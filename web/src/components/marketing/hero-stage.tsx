import { ArrowRight } from "lucide-react";
import { HeroProduct } from "./hero-product";
import styles from "./hero-stage.module.css";

/**
 * The hero says what the product is, and shows it: the real journal on a
 * laptop-sized window and the dashboard on a phone, both captured from the
 * live app on a demo account. Nothing here is a mock-up and nothing promises
 * a result.
 */
export function HeroStage() {
  return (
    <section className={styles.section} id="product">
      <div className={styles.glow} aria-hidden="true" />
      <div className={styles.copy}>
        <p className={`${styles.pill} ${styles.rise}`} style={{ ["--d" as string]: "0ms" }}>
          <i className={styles.pulse} aria-hidden="true" />
          cTrader works today. More platforms are on the roadmap.
        </p>
        <p className={`mkt-kicker ${styles.rise}`} style={{ ["--d" as string]: "40ms" }}>RULES YOU CAN READ</p>
        <h1 className={styles.rise} style={{ ["--d" as string]: "90ms" }}>
          Trade by rules <span className={styles.shine}>you can read.</span>
        </h1>
        <p className={`mkt-lede ${styles.rise}`} style={{ ["--d" as string]: "200ms" }}>
          Write your trading plan in plain words, test it on a demo account
          for 14 days, and keep a stop button within reach. You connect your
          own cTrader account.
        </p>
        <div className={`mkt-hero-cta ${styles.rise}`} style={{ ["--d" as string]: "310ms" }}>
          <a className="mkt-btn mkt-btn-lg" href="/signup">
            Try free for 14 days <ArrowRight className="mkt-ico" aria-hidden />
          </a>
          <a className="mkt-btn mkt-btn-outline mkt-btn-lg" href="#tour">
            See the platform
          </a>
        </div>
        <p className={`${styles.fine} ${styles.rise}`} style={{ ["--d" as string]: "400ms" }}>
          No card needed. Demo accounts only in this release.
        </p>
      </div>
      <div className={`${styles.visual} ${styles.rise}`} style={{ ["--d" as string]: "250ms" }}>
        <HeroProduct />
      </div>
    </section>
  );
}
