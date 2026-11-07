import { ArrowRight } from "lucide-react";
import styles from "./rule-sentence-hero.module.css";

/**
 * The hero says what the product does in the product's own words: a trading
 * rule written as a sentence anyone can read. Everything in the example card
 * is sample data and is labelled as such.
 */
export function RuleSentenceHero() {
  return (
    <section className={styles.section} id="product">
      <div className={styles.copy}>
        <p className="mkt-kicker">RULES YOU CAN READ</p>
        <h1>Trade by rules you can read.</h1>
        <p className="mkt-lede">
          Write your trading plan as a sentence, test it on a demo account for
          14 days, and keep a stop button within reach. You connect your own
          cTrader account.
        </p>
        <div className="mkt-hero-cta">
          <a className="mkt-btn mkt-btn-lg" href="/signup">
            Try free for 14 days <ArrowRight className="mkt-ico" aria-hidden />
          </a>
          <a className="mkt-btn mkt-btn-outline mkt-btn-lg" href="#how-it-works">
            See how it works
          </a>
        </div>
        <p className={styles.fine}>No card needed. Demo accounts only in this release.</p>
      </div>

      <div className={styles.card} role="region" aria-label="Product preview">
        <div className={styles.cardHead}>
          <span>Example rule</span>
          <span className={styles.tag}>Sample data</span>
        </div>
        <p className={styles.sentence}>
          When <b>EURUSD</b> closes <b>one hour</b> above its <b>50-period average</b>
          , and the market is <b>open</b>, buy with <b>1% risk</b> and a stop
          <b> 20 pips</b> away.
        </p>
        <dl className={styles.facts}>
          <div><dt>Account</dt><dd>Demo, cTrader</dd></div>
          <div><dt>Risk guard</dt><dd>On</dd></div>
          <div><dt>Daily stop</dt><dd>On</dd></div>
          <div><dt>This preview</dt><dd>Places no order</dd></div>
        </dl>
        <div className={styles.controls} aria-label="Controls in the platform">
          <span>Start</span><span>Pause</span><span className={styles.stop}>Stop</span>
        </div>
      </div>
    </section>
  );
}
