import type { Metadata } from "next";
import Link from "next/link";
import { BrandLockup } from "@/components/brand/logo";

export const metadata: Metadata = { title: "Terms of Service — Apex4Traders" };

/**
 * Terms of Service.
 *
 * These describe what the software does and does not do, which is a factual
 * question this project can answer. They do NOT state a legal entity, a
 * jurisdiction, a refund policy or a contact address, because those are the
 * owner's to decide and inventing them would be worse than leaving them
 * blank. Each is marked `[TO BE CONFIRMED]` and listed in
 * docs/LEGAL_LAUNCH_BLOCKERS.md.
 *
 * The previous version described a one-time purchase of cryptocurrency
 * trading bot source code. None of that describes this product.
 */
export default function TermsPage() {
  return (
    <main className="a4t">
      <div className="legacy">
        <div style={{ marginBottom: "var(--sp-5)" }}>
          <Link href="/"><BrandLockup size={24} /></Link>
        </div>

        <h1>Terms of Service</h1>
        <p className="dim" style={{ fontSize: ".8rem" }}>
          Last updated: [TO BE CONFIRMED — date of the owner-approved version]
        </p>

        <div className="legacy-flag" style={{ marginTop: "var(--sp-4)" }}>
          This document is not final. The items marked
          &ldquo;[TO BE CONFIRMED]&rdquo; require the operator&rsquo;s decision
          and are listed in the project&rsquo;s legal launch blockers. Until
          they are filled in, these terms should not be relied on as complete.
        </div>

        <section>
          <h2>1. What Apex4Traders is</h2>
          <p>
            Apex4Traders is software. You describe a trading rule from named
            conditions, the platform evaluates that rule against market data,
            and — when you switch it on — it places orders according to the
            rule you configured. It executes your configuration. It does not
            decide what you should trade.
          </p>
        </section>

        <section>
          <h2>2. Your broker account</h2>
          <p>
            Orders are placed on a cTrader account that you choose, that you
            open with your own broker, and that you connect to the platform
            yourself. That relationship is between you and your broker. You can
            disconnect the account at any time from the Accounts page, which
            removes the platform&rsquo;s access tokens. Revoking access inside
            cTrader is a separate step that you control.
          </p>
        </section>

        <section>
          <h2>3. We do not hold your funds</h2>
          <p>
            Apex4Traders never takes custody of your money. It holds no client
            balances, it cannot deposit to or withdraw from your broker
            account, and it does not read your account&rsquo;s cash flow
            history. It can open and close trades on the account you connected,
            and nothing else.
          </p>
        </section>

        <section>
          <h2>4. Demo only in this release</h2>
          <p>
            Live trading is not available in this release. Automation runs on
            demo accounts, and the platform refuses to start it on any account
            that is not a demo account. Running on a demo account first is
            strongly recommended in every case: a rule that behaves as you
            expect on demo is the only evidence you have about it.
          </p>
        </section>

        <section>
          <h2>5. No financial advice</h2>
          <p>
            Apex4Traders is not a financial adviser, a broker, or a portfolio
            manager. Nothing in the platform is a recommendation to buy or sell
            anything. The conditions, thresholds, position sizes and limits are
            chosen by you. We make no claim, express or implied, about the
            returns any rule will produce.
          </p>
        </section>

        <section>
          <h2>6. Risk</h2>
          <p>
            Trading carries risk, including the loss of all of your capital.
            Leveraged trading can lose more than the amount initially
            committed. Past behaviour of a rule, on demo or otherwise, does not
            indicate future results. Markets gap, spreads widen, and orders can
            fill at prices worse than the one requested — a configured stop
            loss is not a guarantee of the exit price.
          </p>
        </section>

        <section>
          <h2>7. Availability</h2>
          <p>
            The platform depends on services outside its control, including
            your broker&rsquo;s API and your own connectivity. It is provided
            without a guarantee of uninterrupted availability. When the
            platform cannot reach your broker it stops and records why, rather
            than guessing.
          </p>
        </section>

        <section>
          <h2>8. Your account with us</h2>
          <p>
            You are responsible for keeping your sign-in credentials
            confidential and for what happens under your account. Tell us
            promptly if you believe it has been used without your permission.
          </p>
        </section>

        <section>
          <h2>9. Licensing and payment</h2>
          <p>
            Access to the platform may require a licence. Pricing, billing
            period and the terms of any refund are
            <strong> [TO BE CONFIRMED — pricing, billing period and refund
            policy] </strong>
            and are not set by this document.
          </p>
        </section>

        <section>
          <h2>10. Who provides this service, and under which law</h2>
          <p>
            <strong>[TO BE CONFIRMED — legal entity name, registered address,
            company registration number, and the governing law and
            jurisdiction for these terms.]</strong>
          </p>
        </section>

        <section>
          <h2>11. Contact</h2>
          <p>
            <strong>[TO BE CONFIRMED — support contact address.]</strong>
          </p>
        </section>

        <p style={{ marginTop: "var(--sp-6)" }}>
          <Link href="/privacy">Privacy Policy</Link>
        </p>
      </div>
    </main>
  );
}
