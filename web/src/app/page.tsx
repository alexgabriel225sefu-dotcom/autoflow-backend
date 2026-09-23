import type { Metadata } from "next";
import { BookOpen, ShieldCheck, SlidersHorizontal, Sparkles } from "lucide-react";

export const metadata: Metadata = {
  title: "Apex4Traders — rule-based automation for your cTrader account",
  description:
    "Build trading rules from named, testable conditions, preview what they " +
    "would decide, and run them on a demo cTrader account you connect yourself.",
};

/**
 * The landing page.
 *
 * Every number a landing page like this normally carries — win rate, returns,
 * "traders served" — is absent, because none of them would be measured. The
 * claims below are all about what the software DOES, which is checkable by
 * using it.
 */
export default function Landing() {
  return (
    <main className="a4t">
      <div className="lp">
        <nav className="lp-nav">
          <span style={{ display: "flex", alignItems: "center", gap: ".55rem", fontWeight: 700, letterSpacing: "-.03em" }}>
            <span className="side-mark" aria-hidden />
            Apex4Traders
          </span>
          <span className="btn-row">
            <a className="btn btn-ghost" href="/login">Sign in</a>
            <a className="btn" href="/signup">Create account</a>
          </span>
        </nav>

        <section className="lp-hero">
          <span className="lp-glow" aria-hidden />
          <span className="pill pill-accent" style={{ marginBottom: "1.1rem" }}>
            Demo-first · cTrader
          </span>
          <h1>Trading rules you can read, test and switch off.</h1>
          <p>
            Build a rule from named conditions — moving averages, RSI, MACD,
            ATR, Bollinger Bands, Stochastic, sessions, weekdays, spread and
            position limits. See exactly what it would decide before it runs.
            Execute on a cTrader account you connect yourself.
          </p>
          <p className="btn-row" style={{ marginTop: "1.6rem" }}>
            <a className="btn btn-lg" href="/signup">Create your account</a>
            <a className="btn btn-ghost btn-lg" href="/login">Sign in</a>
          </p>
        </section>

        <section className="grid grid-3">
          <div className="card">
            <h2 style={{ display: "flex", alignItems: "center", gap: ".45rem", marginBottom: ".5rem" }}>
              <BookOpen className="ico" aria-hidden style={{ width: 15, height: 15, color: "var(--a4t-accent)" }} />
              Every decision is recorded
            </h2>
            <p className="muted" style={{ fontSize: ".875rem", lineHeight: 1.65 }}>
              Including the ones that do nothing. The journal answers &ldquo;why
              did nothing happen today?&rdquo;, condition by condition, not just
              &ldquo;why did this trade open?&rdquo;
            </p>
          </div>
          <div className="card">
            <h2 style={{ display: "flex", alignItems: "center", gap: ".45rem", marginBottom: ".5rem" }}>
              <ShieldCheck className="ico" aria-hidden style={{ width: 15, height: 15, color: "var(--a4t-accent)" }} />
              It refuses rather than guesses
            </h2>
            <p className="muted" style={{ fontSize: ".875rem", lineHeight: 1.65 }}>
              If an indicator has too little history, or a limit you set cannot
              be honoured, the rule stops and says so. It never quietly
              substitutes a different strategy or a different stop.
            </p>
          </div>
          <div className="card">
            <h2 style={{ display: "flex", alignItems: "center", gap: ".45rem", marginBottom: ".5rem" }}>
              <SlidersHorizontal className="ico" aria-hidden style={{ width: 15, height: 15, color: "var(--a4t-accent)" }} />
              Demo first
            </h2>
            <p className="muted" style={{ fontSize: ".875rem", lineHeight: 1.65 }}>
              Automation runs on demo accounts. Live trading is not enabled in
              this release, and nothing starts because you connected an account
              — starting is a separate, deliberate step.
            </p>
          </div>
        </section>

        {/* The rule, in the product's own words. Not a screenshot of results
            — there are none to show, and inventing them is the thing this
            product exists to not do. */}
        <section className="card" style={{ marginTop: ".85rem" }}>
          <div className="card-head">
            <h2 style={{ display: "flex", alignItems: "center", gap: ".45rem" }}>
              <Sparkles className="ico" aria-hidden style={{ width: 15, height: 15, color: "var(--a4t-accent)" }} />
              A rule reads back to you
            </h2>
          </div>
          <p className="summary-line">
            Buy or sell EURUSD on 1h when Price vs MA(ema, 50, above) AND
            RSI(14, above, 55); risk 1.0% per trade; stop 1.5× ATR; target 2.0R;
            at most 1 open position.
          </p>
          <p className="dim" style={{ fontSize: ".78rem", marginTop: ".6rem" }}>
            An example of the summary the builder writes from your own
            configuration. It is not a recommendation, and it is not a rule we
            supply.
          </p>
        </section>

        <section className="card">
          <div className="card-head"><h2>What this is not</h2></div>
          <p className="muted" style={{ fontSize: ".875rem", lineHeight: 1.7 }}>
            Apex4Traders is software that executes rules you configure. It is
            not financial advice, it does not manage money for you, and it
            makes no claim about returns. Trading carries risk, including the
            loss of your capital. Orders are placed through a cTrader account
            that you connect and can disconnect at any time.
          </p>
        </section>

        <footer className="lp-foot">
          <span>© Apex4Traders</span>
          <span><a href="/terms">Terms</a> · <a href="/privacy">Privacy</a></span>
        </footer>
      </div>
    </main>
  );
}
