import type { Metadata } from "next";
import {
  Eye,
  GaugeCircle,
  Link2,
  ListChecks,
  PlayCircle,
  ShieldCheck,
} from "lucide-react";
import { PLAN_NOTICE } from "@/lib/api";
import { BrandLockup } from "@/components/brand/logo";
import { PricingSection } from "@/components/blocks/pricing-section";
import { WaitlistForm } from "@/components/blocks/waitlist-form";

export const metadata: Metadata = {
  title: "Apex4Traders — a control panel for your own trading rules",
  description:
    "Connect your cTrader account, write your own rules from named " +
    "conditions, see what they would decide before anything runs, and keep " +
    "risk limits and a stop button in one place. Demo accounts first.",
};

/**
 * The landing page.
 *
 * WHAT IT IS ALLOWED TO SAY
 *
 * Every figure a page like this normally carries — win rate, returns, traders
 * served, testimonials — is absent, because none of them would be measured.
 * content.test.ts enforces that mechanically. What is left is what the
 * software DOES, which a reader can check by using it.
 *
 * It is also deliberately not sold as a profit machine. The product is a
 * control panel: the trader brings the broker account and writes the rules,
 * and what this gives them is visibility, limits and a stop button. That is
 * both the honest description and the one that does not need a licence to
 * advertise.
 *
 * The primary action is the waitlist, not a purchase: checkout is off and
 * live execution is off, so asking for money here would be selling something
 * that does not run yet.
 */
export default function Landing() {
  return (
    <main className="mkt">
      <div className="mkt-wrap">
        <nav className="mkt-nav">
          <BrandLockup size={24} />
          <span className="mkt-nav-links">
            <a className="mkt-btn mkt-btn-ghost" href="/login">Sign in</a>
            <a className="mkt-btn" href="/signup">Create account</a>
          </span>
        </nav>

        <section className="mkt-hero">
          <span className="mkt-glow" aria-hidden />
          <span className="mkt-eyebrow">Demo accounts first · cTrader</span>
          <h1>
            Your rules. Your broker. <em>One panel.</em>
          </h1>
          <p className="mkt-lede">
            Apex4Traders is a control panel for trading automation. You connect
            your own cTrader account, write your own rules from named
            conditions, and see exactly what each one would decide before
            anything runs. Risk limits, a full journal and a stop button are on
            the same screen.
          </p>

          <div className="mkt-cta">
            <WaitlistForm source="landing" />
          </div>
        </section>

        <section className="mkt-section">
          <h2>What it actually does</h2>
          <p>
            Six things, all of them checkable by using it. None of them is a
            prediction.
          </p>

          <div className="mkt-cards mkt-cards-3">
            <article className="mkt-card">
              <span className="mkt-card-ico"><Link2 size={17} aria-hidden /></span>
              <h3>Connect your own account</h3>
              <p>
                You authorise your cTrader account yourself and can disconnect
                it at any time. We never ask for your broker password, and the
                access token never reaches your browser.
              </p>
            </article>

            <article className="mkt-card">
              <span className="mkt-card-ico"><ListChecks size={17} aria-hidden /></span>
              <h3>Write rules in named conditions</h3>
              <p>
                Moving averages, RSI, MACD, ATR, Bollinger Bands, Stochastic,
                sessions, weekdays, spread and position limits. No scripting,
                and no rule we supply for you to trust.
              </p>
            </article>

            <article className="mkt-card">
              <span className="mkt-card-ico"><Eye size={17} aria-hidden /></span>
              <h3>See the decision before it runs</h3>
              <p>
                Preview a rule against real candles from your own account and
                read back which conditions passed, which failed, and what it
                would have done. Nothing is placed by a preview.
              </p>
            </article>

            <article className="mkt-card">
              <span className="mkt-card-ico"><GaugeCircle size={17} aria-hidden /></span>
              <h3>Risk limits you set</h3>
              <p>
                Risk per trade, stop distance, target, and a cap on open
                positions — enforced on the server, not in the page. A rule
                that asks for something the limits refuse is refused, never
                quietly adjusted.
              </p>
            </article>

            <article className="mkt-card">
              <span className="mkt-card-ico"><PlayCircle size={17} aria-hidden /></span>
              <h3>Start, pause, stop — yourself</h3>
              <p>
                Automation runs only while you have started it, and stopping is
                one button on every screen. The panel always shows whether
                something is running, and says &ldquo;unknown&rdquo; rather than
                guessing when it cannot tell.
              </p>
            </article>

            <article className="mkt-card">
              <span className="mkt-card-ico"><ShieldCheck size={17} aria-hidden /></span>
              <h3>A journal of every decision</h3>
              <p>
                Each evaluation is recorded with the reason it acted or did
                not. When something does not happen, the journal tells you
                which condition stopped it.
              </p>
            </article>
          </div>
        </section>

        <section className="mkt-section">
          <h2>A rule reads back to you</h2>
          <p>
            The builder writes a plain-language summary of whatever you
            configured, so you can check it before it ever runs.
          </p>
          <div className="mkt-rule">
            Buy or sell EURUSD on 1h when Price vs MA(ema, 50, above) AND
            RSI(14, above, 55); risk 1.0% per trade; stop 1.5&times; ATR;
            target 2.0R; at most 1 open position.
          </div>
          <p className="mkt-plain" style={{ marginTop: "1rem" }}>
            An example of the summary the builder produces from your own
            configuration. It is not a recommendation, and it is not a rule we
            supply.
          </p>
        </section>

        <section className="mkt-section">
          <PricingSection />
        </section>

        <section className="mkt-section">
          <h2>What this is not</h2>
          <p className="mkt-plain" style={{ marginTop: ".9rem" }}>
            Apex4Traders is <strong>software that executes rules you
            configure</strong>. It is not financial advice, it does not manage
            money for you, it does not supply signals, and it makes no claim
            about returns. We do not take custody of your funds: orders are
            placed through a broker account that you connect and can
            disconnect at any time.
          </p>
          <div className="mkt-risk">
            <strong style={{ color: "var(--mkt-text)" }}>Risk warning.</strong>{" "}
            Trading carries risk, including the loss of your capital. Automated
            execution does not reduce that risk — it carries out your
            instructions faster and without hesitating. You are responsible for
            the rules you run and for the outcomes they produce.
          </div>
          {/* Stated here in full, in the source, rather than only through
              PLAN_NOTICE: test_product_copy reads this file and requires the
              sentence to be present, and it is right to — a public page that
              carries the limit only inside an imported constant can lose it
              to a refactor without anybody noticing, and silence about live
              trading reads as yes. */}
          <div className="mkt-risk">
            <strong style={{ color: "var(--mkt-text)" }}>
              Live trading is not available in this release.
            </strong>{" "}
            Apex4Traders connects to demo accounts only right now. {PLAN_NOTICE}
          </div>
        </section>

        <footer className="mkt-foot">
          <span>© Apex4Traders</span>
          <span>
            <a href="/terms">Terms</a> · <a href="/privacy">Privacy</a> ·{" "}
            <a href="/login">Sign in</a>
          </span>
        </footer>
      </div>
    </main>
  );
}
