import type { Metadata } from "next";
import { CompanyBlock, DraftShell } from "@/components/legal/draft-shell";
import { LegalSection, LegalSections } from "@/components/legal/legal-section";

export const metadata: Metadata = { title: "Refund policy — Apex4Traders" };

export const dynamic = "force-dynamic";

/**
 * Refund policy, version 2026-10-24.
 *
 * DRAFT - requires legal review. Describes what the webhook already does
 * with a refund, and leaves the customer's entitlement as TO BE CONFIRMED.
 * It does not promise that a purchase can be undone.
 */
export default function RefundsPage() {
  return (
    <DraftShell title="Refund policy">
      <div className="legacy-flag" style={{ marginTop: "var(--sp-4)" }}>
        DRAFT - requires legal review. This document is not final. It is not
        a promise that any payment will be refunded. [TO BE CONFIRMED]
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
          does not move money.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>3. Whether you can ask for a refund</h2>
        <p>
          <strong>[TO BE CONFIRMED — whether a customer may request a refund,
          the time window, and any conditions.]</strong> That decision is not
          one this software can make. Until it is written down by the owner
          and reviewed by a lawyer, do not read this page as saying that a
          refund is available, or that a refund is refused.
        </p>
        <p>
          Trading losses, demo results, and a rule that behaved differently
          from what you expected are not a stated ground for a refund in this
          draft. The software carries out the configuration you switch on.
          It does not promise a result that a refund could be measured
          against.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>4. How to ask, once a contact exists</h2>
        <CompanyBlock />
        <p>
          <strong>[TO BE CONFIRMED — the address a refund request is sent
          to.]</strong> There is no registered company and no support address
          on this draft. Sending a request to an address that is not listed
          here will not reach anyone.
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
