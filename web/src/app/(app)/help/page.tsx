import Link from "next/link";
import { AUTOMATION_LEVELS } from "@/components/app/plain";
import { supportMailto } from "@/lib/support";

/**
 * Plain answers to the questions a first-time client asks.
 *
 * Static on purpose: nothing here reads an account, and nothing here promises
 * a result. Where the product has a limit (demo only, no live trading, a
 * broker minimum order size) the answer says so.
 */
export default function HelpPage() {
  const mail = supportMailto("Apex4Traders support");
  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Help</h1>
          <span className="sub">How Apex4Traders works, and what to do when something is refused.</span>
        </div>
      </div>

      <section className="card">
        <div className="card-head"><h2>What does demo mean?</h2></div>
        <p className="muted">
          Automation runs on a cTrader <strong>demo</strong> account in this
          release: an account with practice money at your broker. Orders go to
          that account and no real money moves. Live trading is not available
          in this release.
        </p>
      </section>

      <section className="card">
        <div className="card-head"><h2>What is cTrader?</h2></div>
        <p className="muted">
          cTrader is the trading platform your broker provides. Apex4Traders
          connects to a cTrader account that you authorise yourself, and never
          asks for your broker password. You can disconnect at any time from{" "}
          <Link href="/accounts">Accounts</Link>.
        </p>
      </section>

      <section className="card">
        <div className="card-head"><h2>How do I open a cTrader demo account?</h2></div>
        <ol className="muted" style={{ paddingLeft: "1.2rem" }}>
          <li>Choose a broker that offers cTrader and open a free demo account with them.</li>
          <li>Make sure you pick cTrader as the platform, not another one.</li>
          <li>
            Come back and press <Link href="/connect">Connect cTrader</Link>,
            sign in with your cTrader ID and approve access.
          </li>
          <li>Then choose that demo account on <Link href="/accounts">Accounts</Link>.</li>
        </ol>
      </section>

      <section className="card">
        <div className="card-head"><h2>What does each automation level do?</h2></div>
        <ul className="muted" style={{ paddingLeft: "1.2rem" }}>
          {AUTOMATION_LEVELS.map((l) => (
            <li key={l.id}>
              <strong>{l.label}.</strong> {l.does} {l.doesNot}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <div className="card-head"><h2>What does Stop do, and not do?</h2></div>
        <p className="muted">
          Stop ends the rule&rsquo;s watching: no new trade is proposed or
          placed. It closes nothing. Anything already open stays at your broker
          with the stop-loss and target it was given. To close positions, use
          the emergency close on the Dashboard or close them in cTrader. Pause
          also stops managing open trades until you resume.
        </p>
      </section>

      <section className="card">
        <div className="card-head"><h2>Why was a trade refused?</h2></div>
        <ul className="muted" style={{ paddingLeft: "1.2rem" }}>
          <li>The rule&rsquo;s conditions were not met, so nothing was placed. The Journal records every check, including these.</li>
          <li>A risk limit was reached, such as the daily loss limit or the maximum open positions.</li>
          <li>The market was closed or the broker did not answer.</li>
          <li>
            Your broker&rsquo;s <strong>minimum lot</strong> (minimum order
            size) would risk more than the amount you chose. The platform
            never rounds a trade up past your risk, so it declines instead.
            Lower the stop distance, raise the risk amount, or pick another
            instrument.
          </li>
          <li>The account is not a demo account, or the cTrader authorisation has expired and needs reconnecting.</li>
        </ul>
        <p className="muted">
          The Journal shows the exact reason for each refusal.
        </p>
      </section>

      <section className="card">
        <div className="card-head"><h2>How does licensing work?</h2></div>
        <p className="muted">
          Demo automation is free for a 14-day trial. A one-time paid plan is
          planned for real-money accounts, and live purchase is not open yet.
          Your status and any trial days left are on the{" "}
          <Link href="/license">Licence</Link> page. Nothing is granted from
          the browser; access changes only when the operator records it.
        </p>
      </section>

      <section className="card">
        <div className="card-head"><h2>Still stuck?</h2></div>
        <p className="muted">
          {mail ? (
            <>Email <a href={mail}>support</a> and include your User ID from Settings.</>
          ) : (
            <>
              A direct support address has not been published yet. When you ask
              for help, include the User ID shown in{" "}
              <Link href="/settings">Settings</Link> and any reference shown
              on the error.
            </>
          )}
        </p>
        <p className="dim" style={{ fontSize: ".78rem" }}>
          Trading involves risk. No profit is guaranteed. Apex4Traders is not
          financial advice.
        </p>
      </section>
    </main>
  );
}
