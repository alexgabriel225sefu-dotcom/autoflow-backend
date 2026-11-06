import { ArrowRight, Check, Circle } from "lucide-react";
import styles from "./perspective-tunnel-hero.module.css";

export function PerspectiveTunnelHero() {
  return (
    <section className={styles.section} id="product">
      <div className={styles.layout}>
        <div className={styles.copy}>
          <p className="mkt-kicker">YOUR RULES, YOUR BROKER</p>
          <h1>Clear rules for your trading.</h1>
          <p className="mkt-lede">
            Connect your account, choose how you want to trade, and check the
            rule on demo before you automate it.
          </p>
          <div className="mkt-hero-cta">
            <a className="mkt-btn mkt-btn-lg" href="/signup">
              Try free for 14 days <ArrowRight className="mkt-ico" aria-hidden />
            </a>
            <a className="mkt-btn mkt-btn-outline mkt-btn-lg" href="#how-it-works">
              See how it works
            </a>
          </div>
        </div>

        <div className={styles.stage} role="region" aria-label="Product preview">
          <div className={styles.stageHeader}>
            <span className={styles.windowDots} aria-hidden>
              <i /> <i /> <i />
            </span>
            <span>Example rule</span>
            <span className={styles.stageStatus}>Demo workspace</span>
          </div>
          <div className={styles.previewGrid}>
            <div className={styles.rulePanel}>
              <div className={styles.panelHeading}>
                <div>
                  <span className={styles.panelEyebrow}>EURUSD · 1h</span>
                  <strong>Moving average plan</strong>
                </div>
                <span className={styles.reviewBadge}><Circle size={8} fill="currentColor" aria-hidden /> Ready to review</span>
              </div>
              <div className={styles.conditionList}>
                <div><Check size={15} aria-hidden /><span>Price is above the moving average</span><b>Entry</b></div>
                <div><Check size={15} aria-hidden /><span>Market is open for this rule</span><b>Allowed</b></div>
                <div className={styles.mutedCondition}><Circle size={15} aria-hidden /><span>Risk guard checks the account</span><b>On review</b></div>
              </div>
              <div className={styles.ruleFooter}><span>Preview only</span><span>No order placed</span></div>
            </div>
            <aside className={styles.statePanel}>
              <span className={styles.panelEyebrow}>Account state</span>
              <strong>Demo account</strong>
              <div className={styles.stateRow}><span>Connection</span><b>Connected</b></div>
              <div className={styles.stateRow}><span>Risk per trade</span><b>1%</b></div>
              <div className={styles.stateRow}><span>Daily stop</span><b>On</b></div>
              <div className={styles.stateRow}><span>Next step</span><b>Test on demo</b></div>
              <div className={styles.controls} aria-label="Controls shown in the platform">
                <span>Start</span><span>Pause</span><span className={styles.stop}>Stop</span>
              </div>
            </aside>
          </div>
          <p className={styles.stageNote}>Example screen with demo data.</p>
        </div>
      </div>
    </section>
  );
}
