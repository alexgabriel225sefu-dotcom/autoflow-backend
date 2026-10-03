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
          <span className="mkt-nav-links">
            <a className="mkt-btn mkt-btn-ghost" href="/login">Sign in</a>
            <a className="mkt-btn" href="/signup">Create account</a>
          </span>
        </nav>

        <section className="mkt-hero mkt-hero-terminal">
          <span className="mkt-glow" aria-hidden />
          <div className="mkt-hero-copy">
            <span className="mkt-eyebrow">Demo accounts first · cTrader private beta</span>
            <h1>
              Your rules. Your broker. <em>One control panel.</em>
            </h1>
            <p className="mkt-lede">
              Apex4Traders lets traders connect their own cTrader account,
              build rules from named conditions, preview decisions on demo, and
              keep risk limits, account state and automation controls in one
              workspace.
            </p>
            <div className="mkt-cta">
              <WaitlistForm source="landing" />
            </div>
          </div>

          <div className="mkt-terminal" aria-label="Apex4Traders demo terminal preview">
            <div className="mkt-terminal-top">
              <span />
              <span />
              <span />
              <strong>Apex4Traders / demo control</strong>
            </div>
            <div className="mkt-terminal-grid">
              <div className="mkt-terminal-panel mkt-terminal-wide">
                <small>Broker link</small>
                <b>cTrader connected</b>
                <p>Demo account selected · encrypted tokens · no custody</p>
              </div>
              <div className="mkt-terminal-panel">
                <small>Execution mode</small>
                <b className="mkt-terminal-safe">Demo only</b>
                <p>Live unavailable in this release</p>
              </div>
              <div className="mkt-terminal-panel">
                <small>Automation</small>
                <b>Stopped</b>
                <p>Start requires explicit confirmation</p>
              </div>
              <div className="mkt-terminal-panel mkt-terminal-wide">
                <small>Rule preview</small>
                <div className="mkt-terminal-rule">
                  EURUSD · 15m · RSI + moving average · risk 1% · stop required
                </div>
                <p>User-configured summary, not a recommendation.</p>
              </div>
              <div className="mkt-terminal-panel mkt-terminal-accent">
                <small>Risk guard</small>
                <b>Refuse if unsafe</b>
                <p>No silent substitution</p>
              </div>
              <div className="mkt-terminal-panel">
                <small>Journal</small>
                <b>Every decision</b>
                <p>Including no-action outcomes</p>
              </div>
            </div>
          </div>
        </section>

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

            <article className="mkt-card">
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

            <article className="mkt-card mkt-bento-large">
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
            <h2>From broker connection to controlled demo automation.</h2>
          </div>
          <div className="mkt-flow-steps">
            {[
              ["01", "Connect cTrader", "Approve access in cTrader and return to the platform."],
              ["02", "Select demo account", "The page shows which account is selected before any action."],
              ["03", "Build your rule", "Use named conditions and visible risk controls."],
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
            execution does not reduce that risk — it carries out your
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
            <a href="/terms">Terms</a> · <a href="/privacy">Privacy</a> ·{" "}
            <a href="/login">Sign in</a>
          </span>
        </footer>
      </div>
    </main>
  );
}
