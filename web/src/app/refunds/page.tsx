import type { Metadata } from "next";
import { CompanyBlock, DraftShell } from "@/components/legal/draft-shell";
import { LegalSection, LegalSections } from "@/components/legal/legal-section";
import {
  DEMO_CONDITIONS_NOTE,
  DEMO_IS_NOT_LIVE,
  DURABLE_MEDIUM,
  PURCHASE_NOTE,
  REFUND_POLICY_VERSION,
  WITHDRAWAL_CONSENT_LABEL,
} from "@/content/refund-policy";

export const metadata: Metadata = { title: "Refund policy — Apex4Traders" };

export const dynamic = "force-dynamic";

/**
 * Refund policy, version 2026-11-09.
 *
 * The commercial rule is decided: the free 14-day demo is the trial, and a
 * licence purchase is final once access is granted, except where the law
 * requires otherwise. Company identity is still unfilled. The draft mark
 * is about that, not about whether a refund can be requested.
 */
export default function RefundsPage() {
  return (
    <DraftShell title="Refund policy">
      <div className="legacy-flag" style={{ marginTop: "var(--sp-4)" }}>
        DRAFT - requires legal review of the company identity in section 4.
        Those company details are not final. The refund rule in the sections
        below is decided.
      </div>

      <LegalSections>
<LegalSection>
        <h2>1. What you are paying for</h2>
        <p>
          A payment, when the purchase is on sale, is for a software licence
          on this platform. It is not a deposit, not a managed account, and
          not an investment in any market. Apex4Traders never takes custody
          of the money on your broker account. A loss on that account is not
          a charge this policy can return.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>2. What a refund does to the licence</h2>
        <p>
          If the payment provider tells us a charge was refunded in full, or
          disputed, the licence recorded for that payment is withdrawn. Rules
          cannot stay entitled to a plan that the payment no longer covers.
          A partial refund does not, by itself, withdraw the licence: the
          remainder of the charge is still a payment for the same licence.
          Withdrawing a licence does not close positions at your broker and
          does not move money. This includes a refund the law requires and a
          refund we choose to make.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>3. Refund policy</h2>
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
          consented, and refund policy version {REFUND_POLICY_VERSION}.
        </p>
        <p>
          Checkout cannot start until you tick this statement yourself.
          It is not ticked for you: {WITHDRAWAL_CONSENT_LABEL}
        </p>
        <p>
          A trading loss on your broker account is not a charge this policy
          returns. Demo fills, spreads and slippage can differ from live
          trading, and a difference of that kind is not a ground for undoing
          the licence.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>4. Who to write to</h2>
        <CompanyBlock />
        <p>
          <strong>[TO BE CONFIRMED — support contact address.]</strong> There
          is no registered company and no support address on this page yet.
          A message about a right the law still gives you has nowhere listed
          to go until that address is published.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>5. Chargebacks</h2>
        <p>
          A card dispute is treated as a full withdrawal of the licence while
          the dispute stands. Opening a dispute with the card issuer is
          between you and the payment provider. It does not move funds on
          your broker account.
        </p>
      </LegalSection>
</LegalSections>
    </DraftShell>
  );
}
