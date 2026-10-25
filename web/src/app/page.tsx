import type { Metadata } from "next";
import {
  ArrowRight,
  ArrowUpRight,
  Eye,
  GaugeCircle,
  Link2,
  ListChecks,
  PlayCircle,
  ShieldCheck,
} from "lucide-react";
import { PLAN_NOTICE } from "@/lib/api";
import { BrandLockup } from "@/components/brand/logo";
import { SpotlightGrid } from "@/components/marketing/spotlight-grid";
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

        <section className="mkt-hero mkt-hero2 mkt-hero-mark" id="product">
          {/* The brand mark, large, behind the copy. Decoration only. */}
          <span className="mkt-mark-bg" aria-hidden />
          <div className="mkt-hero-copy">
            <p className="mkt-kicker">YOUR RULES, YOUR BROKER</p>
            <h1>Trade like you planned&nbsp;to.</h1>
            <p className="mkt-lede">
              Connect your cTrader account, then set your market, method and
              risk. Automation follows your rules and stops when you say.
            </p>
            <div className="mkt-hero-cta">
              <a className="mkt-btn mkt-btn-lg" href="/signup">
                Get started <ArrowRight className="mkt-ico" aria-hidden />
              </a>
              <a className="mkt-btn mkt-btn-outline mkt-btn-lg" href="#features">
                See how it works
              </a>
            </div>
          </div>
        </section>

        <section className="mkt-partners" id="partners" aria-label="Broker integrations">
          <SpotlightGrid className="mkt-partner-grid">
            <div className="mkt-partner mkt-partner-live" data-spot>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/ctrader-logo-light.svg" alt="cTrader" height={34} />
              <span className="mkt-partner-status">Available now</span>
              <a href="/signup">Connect cTrader <ArrowUpRight size={15} aria-hidden /></a>
            </div>
            <div className="mkt-partner mkt-partner-soon" data-spot>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/metatrader-4-light.png" alt="MetaTrader 4" height={34} />
              <span className="mkt-partner-status">Coming soon</span>
            </div>
            <div className="mkt-partner mkt-partner-soon" data-spot>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/metatrader-5-light.png" alt="MetaTrader 5" height={34} />
              <span className="mkt-partner-status">Coming soon</span>
            </div>
          </SpotlightGrid>
          <p className="mkt-partner-note">
            No install path promised yet for MetaTrader. No signals, no profit
            guarantees. Automation runs on demo accounts in this release.
          </p>
        </section>

        <section id="features" className="mkt-section">
          <h2>What it actually does</h2>
          <p>
            Six things, all of them checkable by using it. None of them is a
            prediction.
          </p>

          <SpotlightGrid className="mkt-rails" label="What it does">
            <article className="mkt-rail mkt-rail-7" data-spot>
              <span className="mkt-card-ico"><Link2 size={17} aria-hidden /></span>
              <h3>Connect your own account</h3>
              <p>
                You authorise your cTrader account yourself and can disconnect it at any time. We never ask for your broker password, and the access token never reaches your browser.
              </p>
            </article>
            <article className="mkt-rail mkt-rail-5" data-spot>
              <span className="mkt-card-ico"><ListChecks size={17} aria-hidden /></span>
              <h3>Write rules in named conditions</h3>
              <p>
                Moving averages, RSI, MACD, ATR, Bollinger Bands, Stochastic, sessions, weekdays, spread and position limits.
              </p>
            </article>
            <article className="mkt-rail mkt-rail-5" data-spot>
              <span className="mkt-card-ico"><Eye size={17} aria-hidden /></span>
              <h3>Preview before it runs</h3>
              <p>
                Read which conditions passed, which failed, and what the rule would decide. Nothing is placed by a preview.
              </p>
            </article>
            <article className="mkt-rail mkt-rail-7" data-spot>
              <span className="mkt-card-ico"><GaugeCircle size={17} aria-hidden /></span>
              <h3>Risk limits you set</h3>
              <p>
                Risk per trade, stop distance, target, and a cap on open positions are enforced on the server.
              </p>
            </article>
            <article className="mkt-rail mkt-rail-6" data-spot>
              <span className="mkt-card-ico"><PlayCircle size={17} aria-hidden /></span>
              <h3>Start, pause, stop</h3>
              <p>
                Automation runs only while you have started it. The panel says unknown rather than guessing when it cannot tell.
              </p>
            </article>
            <article className="mkt-rail mkt-rail-6" data-spot>
              <span className="mkt-card-ico"><ShieldCheck size={17} aria-hidden /></span>
              <h3>A journal of every decision</h3>
              <p>
                Each evaluation is recorded with the reason it acted or did not. When nothing happens, the journal tells you which condition stopped it.
              </p>
            </article>
          </SpotlightGrid>
        </section>

        <section id="resources" className="mkt-section mkt-flow">
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

        <section id="pricing" className="mkt-section">
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
