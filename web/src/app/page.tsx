import type { Metadata } from "next";
import {
  ArrowRight,
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

export const metadata: Metadata = {
  title: "Apex4Traders: a control panel for your own trading rules",
  description:
    "Connect your cTrader account, write your own rules from named " +
    "conditions, see what they would decide before anything runs, and keep " +
    "risk limits and a stop button in one place. Demo accounts first.",
};

/**
 * The landing page.
 *
 * No win rate, return, testimonial or account-balance claim appears here.
 * The product is positioned as a control panel: the trader connects the
 * broker, writes the rules, tests on demo, and keeps risk controls visible.
 */
export default function Landing() {
  return (
    <main className="mkt">
      <div className="mkt-wrap">
        <nav className="mkt-nav">
          <BrandLockup size={24} />
          {/* Product, features and resources are sections of this page.
              Pricing is a route: /pricing used to 404, including for anyone
              sent here by an advertisement or a shared link. */}
          <span className="mkt-nav-mid">
            <a href="#product">Product</a>
            <a href="#features">Features</a>
            <a href="/pricing">Pricing</a>
            <a href="#resources">Resources</a>
          </span>
          <span className="mkt-nav-links">
            <a className="mkt-navlink" href="/login">Log in</a>
            <a className="mkt-btn" href="/signup">Get started</a>
          </span>
        </nav>

        <section className="mkt-hero mkt-hero2 mkt-hero-terminal" id="product">
          <span className="mkt-glow" aria-hidden />
          <div className="mkt-hero-copy">
            <p className="mkt-kicker">YOUR RULES · YOUR BROKER</p>
            <h1>Trade like you planned&nbsp;to.</h1>
            <p className="mkt-lede">
              Get your licence, connect your cTrader account, then choose your
              market, your method and your risk. Automation follows your rules,
              and you can stop it any time.
            </p>
            <div className="mkt-hero-cta">
              <a className="mkt-btn mkt-btn-lg" href="/signup">
                Get started <ArrowRight className="mkt-ico" aria-hidden />
              </a>
              <a className="mkt-btn mkt-btn-outline mkt-btn-lg" href="#features">
                See how it works
              </a>
            </div>
            <p className="mkt-foot-note">
              No signals. No profit guarantees. Automation runs on demo accounts in this release.
            </p>
          </div>

          <div className="mkt-rulecard" aria-label="Illustrative preview of a rule check">
            <div className="rc-bar"><i /><i /><i /><span>Illustrative preview</span></div>
            <h3>Rule check</h3>
            <div className="rc-row"><b>EMA (21)</b><em>crosses above</em><b>EMA (55)</b><u /></div>
            <div className="rc-row"><b>RSI (14)</b><em>greater than</em><b>50</b><u /></div>
            <div className="rc-row"><b>Stop-loss</b><em>set</em><b>1.0% risk</b><u /></div>
            <div className="rc-foot"><span>● Conditions met</span><b>■ Emergency stop</b></div>
          </div>
        </section>

        {/* Directly under the hero rather than inside it: the hero is the
            promise, this is the platform list. Kept apart so the first screen
            carries a headline, one sentence, the buttons and the disclosure,
            and nothing competing with them. */}
        <div className="mkt-works mkt-works-band">
          <div className="mkt-works-row">
            <span>WORKS WITH</span>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/ctrader-logo-light.svg" alt="cTrader" width={98} height={24} />
          </div>
          <div className="mkt-works-row">
            <span>COMING SOON</span>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/metatrader-4-light.png" alt="MetaTrader 4" />
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/metatrader-5-light.png" alt="MetaTrader 5" />
          </div>
        </div>

        <section className="mkt-section">
          <h2>What it actually does</h2>
          <p>
            Six things, all of them checkable by using it. None of them is a
            prediction.
          </p>

          <div className="mkt-bento">
            <article className="mkt-card mkt-bento-large">
              <span className="mkt-card-ico"><Link2 size={17} aria-hidden /></span>
              <h3>Connect your own account</h3>
              <p>
                You authorise your cTrader account yourself and can disconnect
                it at any time. We never ask for your broker password, and the
                access token never reaches your browser.
              </p>
            </article>

            <article className="mkt-card mkt-bento-large">
              <span className="mkt-card-ico"><ListChecks size={17} aria-hidden /></span>
              <h3>Write rules in named conditions</h3>
              <p>
                Moving averages, RSI, MACD, ATR, Bollinger Bands, Stochastic,
                sessions, weekdays, spread and position limits.
              </p>
            </article>

            <article className="mkt-card">
              <span className="mkt-card-ico"><Eye size={17} aria-hidden /></span>
              <h3>Preview before it runs</h3>
              <p>
                Read which conditions passed, which failed, and what the rule
                would decide. Nothing is placed by a preview.
              </p>
            </article>

            <article className="mkt-card">
              <span className="mkt-card-ico"><GaugeCircle size={17} aria-hidden /></span>
              <h3>Risk limits you set</h3>
              <p>
                Risk per trade, stop distance, target, and a cap on open
                positions are enforced on the server.
              </p>
            </article>

            <article className="mkt-card">
              <span className="mkt-card-ico"><PlayCircle size={17} aria-hidden /></span>
              <h3>Start, pause, stop</h3>
              <p>
                Automation runs only while you have started it. The panel says
                unknown rather than guessing when it cannot tell.
              </p>
            </article>

            <article className="mkt-card mkt-bento-wide">
              <span className="mkt-card-ico"><ShieldCheck size={17} aria-hidden /></span>
              <h3>A journal of every decision</h3>
              <p>
                Each evaluation is recorded with the reason it acted or did
                not. When nothing happens, the journal tells you which condition
                stopped it.
              </p>
            </article>
          </div>
        </section>

        <section className="mkt-section mkt-flow">
          <div>
            <span className="mkt-eyebrow">Launch flow</span>
            <h2>From licence to controlled automation.</h2>
          </div>
          <div className="mkt-flow-steps">
            {[
              ["01", "Get your licence", "One licence unlocks the platform for your account."],
              ["02", "Connect cTrader", "Approve access in cTrader; the page shows which account is selected before any action."],
              ["03", "Choose market, method, risk", "Named conditions and visible risk controls."],
              ["04", "Preview decision", "Read the decision before starting automation."],
              ["05", "Start, pause, stop", "Controls are explicit and recorded in the journal."],
            ].map(([n, title, body]) => (
              <div className="mkt-flow-step" key={n}>
                <span>{n}</span>
                <strong>{title}</strong>
                <p>{body}</p>
              </div>
            ))}
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
            placed through a broker account that you connect and can disconnect
            at any time.
          </p>
          <div className="mkt-risk">
            <strong style={{ color: "var(--mkt-text)" }}>Risk warning.</strong>{" "}
            Trading carries risk, including the loss of your capital. Automated
            execution does not reduce that risk. It carries out your
            instructions faster and without hesitating. You are responsible for
            the rules you run and for the outcomes they produce.
          </div>
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
            <a href="/terms">Terms</a> · <a href="/refunds">Refunds</a> ·{" "}
            <a href="/tax">Tax</a> · <a href="/privacy">Privacy</a> ·{" "}
            <a href="/login">Sign in</a>
          </span>
        </footer>
      </div>
    </main>
  );
}
