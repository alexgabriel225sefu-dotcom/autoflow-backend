import type { Metadata } from "next";
import Link from "next/link";
import { CompanyBlock, DraftShell } from "@/components/legal/draft-shell";
import { Pending } from "@/components/legal/pending";
import { LEGAL_FACTS, hasFact } from "@/lib/legal-facts";
import { HELP_PATH } from "@/lib/support";
import { LegalSection, LegalSections } from "@/components/legal/legal-section";
import {
  DEMO_CONDITIONS_NOTE,
  DEMO_IS_NOT_LIVE,
  DURABLE_MEDIUM,
  PURCHASE_NOTE,
  REFUND_POLICY_VERSION,
  WITHDRAWAL_CONSENT_LABEL,
} from "@/content/refund-policy";

export const metadata: Metadata = { title: "Terms of Service — Apex4Traders" };

// Read A4T_LEGAL_PUBLISH on each request. A static build would freeze the
// draft banner even after the owner sets the variable.
export const dynamic = "force-dynamic";

/**
 * Terms of Service and risk disclosure, version 2026-10-24.
 *
 * DRAFT - requires legal review. Unpublished unless A4T_LEGAL_PUBLISH is
 * exactly this version. Company facts come from lib/legal-facts.ts. An
 * unset fact is stated as missing; it is never printed as a token. Nothing here promises a
 * return.
 */
export default function TermsPage() {
  const facts = LEGAL_FACTS;
  return (
    <DraftShell title="Terms of Service">
      <div className="legacy-flag" style={{ marginTop: "var(--sp-4)" }}>
        DRAFT - requires legal review. This document is not final. Where a
        section needs a company or contact detail the operator has not
        supplied, the section says so. Until every such detail is published,
        these terms should not be relied on as a complete contract. The refund rule in
        section 12 is decided.
      </div>

      <LegalSections>
<LegalSection>
        <h2>1. What Apex4Traders is</h2>
        <p>
          Apex4Traders is software. You describe a trading rule from named
          conditions, the platform evaluates that rule against market data,
          and — when you switch it on — it places orders according to the
          rule you configured. It executes your configuration. It does not
          decide what you should trade, and it does not promise a profit, a
          return, or a particular outcome.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>2. Your broker account</h2>
        <p>
          Orders are placed on a cTrader account that you choose, that you
          open with your own broker, and that you connect to the platform
          yourself. That relationship is between you and your broker. You can
          disconnect the account at any time from the Accounts page, which
          removes the platform&rsquo;s access tokens. Revoking access inside
          cTrader is a separate step that you control.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>3. We do not hold your funds</h2>
        <p>
          Apex4Traders never takes custody of your money. It holds no client
          balances, it cannot deposit to or withdraw from your broker
          account, and it does not read your account&rsquo;s cash flow
          history. It can open and close trades on the account you connected,
          and nothing else. Trading losses are losses on your broker account.
          They are not a balance this platform holds and cannot refund.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>4. Demo only in this release</h2>
        <p>
          Live trading is not available in this release. Automation runs on
          demo accounts, and the platform refuses to start it on any account
          that is not a demo account. Running on a demo account first is
          strongly recommended in every case: a rule that behaves as you
          expect on demo is the only evidence you have about it. Demo results
          are not a forecast of live results.
        </p>
      </LegalSection>

      <LegalSection>
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
      </LegalSection>

      <LegalSection>
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
      </LegalSection>

      <LegalSection>
        <h2>7. Availability</h2>
        <p>
          The platform depends on services outside its control, including
          your broker&rsquo;s API and your own connectivity. It is provided
          without a guarantee of uninterrupted availability. When the
          platform cannot reach your broker it stops and records why, rather
          than guessing.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>8. Your account with us</h2>
        <p>
          You are responsible for keeping your sign-in credentials
          confidential and for what happens under your account. Tell us
          promptly if you believe it has been used without your permission.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>9. Licensing and payment</h2>
        <p>
          Access to the paid plan may require a licence. The price is the
          figure the server publishes for the one-time founder licence. It is
          not stated in this document, so this page cannot drift from the
          offer. The refund rule is section 12 of these terms and the{" "}
          <Link href="/refunds">Refunds page</Link>. It is decided there,
          including the free 14-day demo trial and the withdrawal
          acknowledgement checkout requires.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>10. Who provides this service, and under which law</h2>
        <CompanyBlock />
        <p>
          {hasFact(facts.governingLaw) && hasFact(facts.disputeForum) ? (
            <>
              Governing law for these terms: {facts.governingLaw}. Forum for
              a dispute under these terms: {facts.disputeForum}.
            </>
          ) : (
            <Pending fact={["governingLaw", "disputeForum"]}>
              The governing law and the forum for a dispute under these terms
              are not stated yet.
            </Pending>
          )}
          {hasFact(facts.companyName)
            ? null
            : " No company is registered for this product yet. These terms do not create a contract with an unnamed entity."}
        </p>
      </LegalSection>

      <LegalSection>
        <h2>11. Contact</h2>
        <p>
          {hasFact(facts.supportEmail) ? (
            <>
              Write to{" "}
              <a href={`mailto:${facts.supportEmail}`}>{facts.supportEmail}</a>.
            </>
          ) : (
            <Pending fact="supportEmail">
              A support contact address is not published yet. Signed-in
              clients can use the <Link href={HELP_PATH}>Help page</Link>.
            </Pending>
          )}
        </p>
      </LegalSection>

      <LegalSection>
        <h2>12. Refund policy</h2>
        <p>Refund policy version {REFUND_POLICY_VERSION}.</p>
        <p>{PURCHASE_NOTE}</p>
        <p>
          {DEMO_CONDITIONS_NOTE} {DEMO_IS_NOT_LIVE}
        </p>
        <p>
          Under the EU Consumer Rights Directive 2011/83/EU, article 16(m),
          the 14-day right of withdrawal for digital content is lost only
          when all of the following are true. You request immediate access
          before checkout starts. You acknowledge that you lose that right
          once access is granted. We confirm that consent on a durable
          medium. {DURABLE_MEDIUM} It names your account, the time you
          consented, and refund policy version {REFUND_POLICY_VERSION}. The
          same words are on the <Link href="/refunds">Refunds page</Link>.
        </p>
        <p>
          Checkout cannot start until you tick this statement yourself.
          It is not ticked for you: {WITHDRAWAL_CONSENT_LABEL}
        </p>
        <p>
          A refund the law requires, or one we choose to make, still
          withdraws the licence for that payment. A trading loss on your
          broker account is not a charge this policy returns.
        </p>
      </LegalSection>
</LegalSections>
    </DraftShell>
  );
}
