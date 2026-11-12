import Link from "next/link";
import type { ReactNode } from "react";
import { BrandLockup } from "@/components/brand/logo";
import { ReadingProgress } from "./reading-progress";
import { LEGAL_FACTS, hasFact, missingLegalFacts } from "@/lib/legal-facts";
import { Pending } from "./pending";
import {
  DRAFT_NOTICE,
  LEGAL_VERSION,
  legalPublished,
} from "@/content/legal-publication";

/** The approval date of this version, or a plain statement that there is none. */
export function ApprovedDate() {
  const date = LEGAL_FACTS.approvedVersionDate;
  return hasFact(date) ? (
    <>Last updated: {date}</>
  ) : (
    <Pending fact="approvedVersionDate">
      The operator has not approved this version yet, so it carries no
      approval date.
    </Pending>
  );
}

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
          Version {LEGAL_VERSION}. <ApprovedDate />
        </p>
        {published ? (
          <p className="dim" style={{ fontSize: ".8rem" }}>
            Published version {LEGAL_VERSION}.
            {missingLegalFacts().length > 0
              ? " Details the operator has not supplied yet are stated as missing in the sections below."
              : null}
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

export { CompanyBlock } from "./pending";
