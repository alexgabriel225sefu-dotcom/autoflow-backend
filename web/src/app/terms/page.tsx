import type { Metadata } from "next";
import { CompanyBlock, DraftShell } from "@/components/legal/draft-shell";

export const metadata: Metadata = { title: "Terms of Service — Apex4Traders" };

// Read A4T_LEGAL_PUBLISH on each request. A static build would freeze the
// draft banner even after the owner sets the variable.
export const dynamic = "force-dynamic";

/**
 * Terms of Service and risk disclosure, version 2026-10-24.
 *
 * DRAFT - requires legal review. Unpublished unless A4T_LEGAL_PUBLISH is
 * exactly this version. Company facts stay as {{COMPANY_NAME}} and the
 * other tokens until the owner fills them in. Nothing here promises a
 * return.
 */
export default function TermsPage() {
  return (
    <DraftShell title="Terms of Service">
      <div className="legacy-flag" style={{ marginTop: "var(--sp-4)" }}>
        DRAFT - requires legal review. This document is not final. Items
        marked &ldquo;[TO BE CONFIRMED]&rdquo; are the owner&rsquo;s to
        supply. Until they are filled in, these terms should not be relied
        on as complete.
      </div>

      <section>
        <h2>1. What Apex4Traders is</h2>
        <p>
          Apex4Traders is software. You describe a trading rule from named
          conditions, the platform evaluates that rule against market data,
          and — when you switch it on — it places orders according to the
          rule you configured. It executes your configuration. It does not
          decide what you should trade, and it does not promise a profit, a
          return, or a particular outcome.
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
          and nothing else. Trading losses are losses on your broker account.
          They are not a balance this platform holds and cannot refund.
        </p>
      </section>

      <section>
        <h2>4. Demo only in this release</h2>
        <p>
          Live trading is not available in this release. Automation runs on
          demo accounts, and the platform refuses to start it on any account
          that is not a demo account. Running on a demo account first is
          strongly recommended in every case: a rule that behaves as you
          expect on demo is the only evidence you have about it. Demo results
          are not a forecast of live results.
        </p>
      </section>

      <section>
        <h2>5. No financial advice and no promise of returns</h2>
        <p>
          Apex4Traders is not a financial adviser, a broker, or a portfolio
          manager. Nothing in the platform is a recommendation to buy or sell
          anything. The conditions, thresholds, position sizes and limits are
          chosen by you. We make no claim, express or implied, about the
          returns any rule will produce. Past results, back-tests, previews
          and demo runs are not a promise of future results. There is no
          promised income and no promised performance.
        </p>
      </section>

      <section>
        <h2>6. Risk disclosure</h2>
        <p>
          Trading carries risk, including the loss of all of your capital.
          Leveraged forex and CFD trading can lose more than the amount
          initially committed. You can lose money quickly. Markets gap,
          spreads widen, quotes go stale, and orders can fill at prices worse
          than the one requested — a configured stop loss is not a guarantee
          of the exit price. A stop, a take-profit, a risk limit or an
          emergency stop can fail to fire when the broker, the network or
          this platform is unavailable. Automation makes those outcomes
          faster, not safer. You can lose the entire balance of the account
          you connect, and you should not trade money you cannot afford to
          lose.
        </p>
        <p>
          Nothing on this site, in the product, or in a conversation with us
          is an offer to manage your money or a statement that any strategy
          will be profitable. If you do not accept that you can lose all of
          the capital on the account you connect, do not use the software.
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
          Access to the paid plan may require a licence. The price is the
          figure the server publishes for the one-time founder licence. It is
          not stated in this document, so this page cannot drift from the
          offer. Whether a charge can be refunded, and on what conditions, is
          the refund policy. That policy is a draft and is
          <strong> [TO BE CONFIRMED — refund policy]</strong> until a lawyer
          has reviewed it and it has been published.
        </p>
      </section>

      <section>
        <h2>10. Who provides this service, and under which law</h2>
        <CompanyBlock />
        <p>
          <strong>[TO BE CONFIRMED — legal entity name, registered address,
          company registration number, and the governing law and jurisdiction
          for these terms.]</strong> No company is registered for this
          product yet. These terms do not create a contract with an unnamed
          entity.
        </p>
      </section>

      <section>
        <h2>11. Contact</h2>
        <p>
          <strong>[TO BE CONFIRMED — support contact address.]</strong>
        </p>
      </section>
    </DraftShell>
  );
}
