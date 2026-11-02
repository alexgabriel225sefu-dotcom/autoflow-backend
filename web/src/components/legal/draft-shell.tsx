import Link from "next/link";
import type { ReactNode } from "react";
import { BrandLockup } from "@/components/brand/logo";
import { ReadingProgress } from "./reading-progress";
import {
  DRAFT_NOTICE,
  LEGAL_VERSION,
  legalPublished,
} from "@/content/legal-publication";

/**
 * Chrome for a public legal draft.
 *
 * The draft notice is rendered whenever this version is not the one named
 * by A4T_LEGAL_PUBLISH. The default is unpublished. The notice text is also
 * written into each page so a source check can see it without rendering.
 */
export function DraftShell({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const published = legalPublished();
  return (
    <main className="a4t">
      <ReadingProgress />
      <div className="legacy">
        <div style={{ marginBottom: "var(--sp-5)" }}>
          <Link href="/"><BrandLockup size={24} /></Link>
        </div>
        <h1>{title}</h1>
        <p className="dim" style={{ fontSize: ".8rem" }}>
          Version {LEGAL_VERSION}. Last updated: [TO BE CONFIRMED — date of the
          owner-approved version]
        </p>
        {published ? (
          <p className="dim" style={{ fontSize: ".8rem" }}>
            Published version {LEGAL_VERSION}. Placeholders in braces are still
            unfilled until the owner replaces them.
          </p>
        ) : (
          <div className="legacy-flag" style={{ marginTop: "var(--sp-4)" }} role="status">
            {DRAFT_NOTICE}. This document is not final. It has not been
            published, and it must be reviewed by a qualified lawyer before
            anyone relies on it.
          </div>
        )}
        {children}
        <p style={{ marginTop: "var(--sp-6)" }}>
          <Link href="/terms">Terms</Link>
          {" · "}
          <Link href="/refunds">Refunds</Link>
          {" · "}
          <Link href="/tax">Tax</Link>
          {" · "}
          <Link href="/privacy">Privacy</Link>
        </p>
      </div>
    </main>
  );
}

/** The company facts the owner has not supplied. Rendered as tokens. */
export function CompanyBlock() {
  return (
    <p>
      <strong>[TO BE CONFIRMED — </strong>
      provider {"{{COMPANY_NAME}}"}, registration number{" "}
      {"{{REGISTRATION_NUMBER}}"}, address {"{{ADDRESS}}"}, jurisdiction{" "}
      {"{{JURISDICTION}}"}, VAT {"{{VAT}}"}.
      <strong>]</strong> These tokens are placeholders. They are not a
      company, a registration, or a tax number.
    </p>
  );
}
