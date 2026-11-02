import type { Metadata } from "next";
import { CompanyBlock, DraftShell } from "@/components/legal/draft-shell";
import { LegalSection, LegalSections } from "@/components/legal/legal-section";

export const metadata: Metadata = { title: "Tax notice — Apex4Traders" };

export const dynamic = "force-dynamic";

/**
 * Tax notice, version 2026-10-24.
 *
 * DRAFT - requires legal review. The owner has no registered company and
 * no VAT number yet. This page says so, and it does not invent a rate.
 */
export default function TaxPage() {
  return (
    <DraftShell title="Tax notice">
      <div className="legacy-flag" style={{ marginTop: "var(--sp-4)" }}>
        DRAFT - requires legal review. This document is not final. It is not
        tax advice. [TO BE CONFIRMED]
      </div>

      <LegalSections>
<LegalSection>
        <h2>1. No tax registration is in place</h2>
        <CompanyBlock />
        <p>
          {"{{VAT}}"} is a placeholder, not a VAT number. No company has been
          registered for this product, so no VAT number, sales-tax permit or
          equivalent registration is stated here. A number must not be
          inferred from this page.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>2. What the price does and does not include</h2>
        <p>
          The price a visitor sees is the figure the server publishes for the
          one-time founder licence. This page deliberately does not repeat
          it. Whether that figure includes tax, and which tax, is
          <strong> [TO BE CONFIRMED — tax inclusive or exclusive, and which
          taxes the payment provider is configured to collect]</strong>.
          Until that is decided, this notice does not say that tax is
          included and does not say that a further tax will be added.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>3. Your own tax position</h2>
        <p>
          You are responsible for any tax you owe on your trading or on your
          purchase, under the rules that apply to you. Apex4Traders does not
          calculate that tax, does not file it, and does not advise you on
          it. Nothing here is a statement of your liability.
        </p>
      </LegalSection>

      <LegalSection>
        <h2>4. Jurisdiction</h2>
        <p>
          Which tax regime applies depends on {"{{JURISDICTION}}"} and on
          where you live. Both are
          <strong> [TO BE CONFIRMED]</strong>. The platform does not choose
          a country in order to make this notice look complete.
        </p>
      </LegalSection>
</LegalSections>
    </DraftShell>
  );
}
