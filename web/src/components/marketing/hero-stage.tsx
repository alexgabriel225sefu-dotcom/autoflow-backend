import { ProductFrame } from "./product-frame";
import { TrustpilotWidget } from "./trustpilot-widget";

/**
 * The hero says what the product is, once, and shows it: the real dashboard
 * from a demo account, directly under the buttons so the first scroll reveals
 * the interface. Nothing here is a mock-up and nothing promises a result.
 */
export function HeroStage() {
  return (
    <section className="lp-hero" id="product" aria-labelledby="hero-title">
      <div className="lp-hero-copy">
        <p className="lp-chip">Rules you can read</p>
        <h1 id="hero-title">Trade by rules you can read.</h1>
        <p className="lp-lead">
          Write your trading plan in plain words, test it on a demo account for
          14 days, and keep a stop button within reach. You connect your own
          cTrader account.
        </p>
        <div className="lp-cta">
          <a className="mkt-btn mkt-btn-lg" href="/signup">Try free for 14 days</a>
          <a className="mkt-btn mkt-btn-outline mkt-btn-lg" href="#tour">See the platform</a>
        </div>
        <p className="lp-caption">No card needed. Demo accounts only in this release.</p>
        <TrustpilotWidget />
      </div>
      <ProductFrame
        src="/product/dash.webp"
        alt="The Apex4Traders dashboard on a demo account: automation running, Risk Guard active, cTrader linked."
        caption="Demo account screens."
        priority
      />
    </section>
  );
}
