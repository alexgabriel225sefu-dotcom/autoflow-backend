import type { Metadata } from "next";

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
      <div className="shell">
        <header className="card-head" style={{ paddingTop: "1rem" }}>
          <span className="brand">Apex4Traders</span>
          <span className="btn-row">
            <a className="btn btn-ghost" href="/login">Sign in</a>
            <a className="btn" href="/signup">Create account</a>
          </span>
        </header>

        <section style={{ padding: "3rem 0 2rem" }}>
          <h1 style={{ fontSize: "clamp(2rem, 7vw, 3.2rem)", maxWidth: "18ch" }}>
            Trading rules you can read, test and switch off.
          </h1>
          <p className="muted" style={{ fontSize: "1.05rem", maxWidth: "58ch" }}>
            Build a rule from named conditions — moving averages, RSI, MACD,
            ATR, Bollinger Bands, Stochastic, sessions, weekdays, spread and
            position limits. See exactly what it would decide before it runs.
            Execute on a cTrader account you connect yourself.
          </p>
          <p className="btn-row" style={{ marginTop: "1.5rem" }}>
            <a className="btn" href="/signup">Create your account</a>
            <a className="btn btn-ghost" href="/login">Sign in</a>
          </p>
        </section>

        <section className="grid grid-3">
          <div className="card">
            <h2>Every decision is recorded</h2>
            <p className="muted">
              Including the ones that do nothing. The journal answers &ldquo;why
              did nothing happen today?&rdquo;, condition by condition, not just
              &ldquo;why did this trade open?&rdquo;
            </p>
          </div>
          <div className="card">
            <h2>It refuses rather than guesses</h2>
            <p className="muted">
              If an indicator has too little history, or a limit you set cannot
              be honoured, the rule stops and says so. It never quietly
              substitutes a different strategy or a different stop.
            </p>
          </div>
          <div className="card">
            <h2>Demo first</h2>
            <p className="muted">
              Automation runs on demo accounts. Live trading is not enabled in
              this release, and nothing starts because you connected an account
              — starting is a separate, deliberate step.
            </p>
          </div>
        </section>

        <section className="card">
          <h2>What this is not</h2>
          <p className="muted">
            Apex4Traders is software that executes rules you configure. It is
            not financial advice, it does not manage money for you, and it
            makes no claim about returns. Trading carries risk, including the
            loss of your capital. Orders are placed through a cTrader account
            that you connect and can disconnect at any time.
          </p>
        </section>

        <footer className="muted" style={{ padding: "2rem 0" }}>
          <a href="/terms">Terms</a> · <a href="/privacy">Privacy</a>
        </footer>
      </div>
    </main>
  );
}
