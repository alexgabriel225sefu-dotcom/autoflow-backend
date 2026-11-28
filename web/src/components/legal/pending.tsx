import type { ReactNode } from "react";
import {
  LEGAL_FACTS,
  hasFact,
  type LegalFacts,
  type OwnerFactKey,
} from "@/lib/legal-facts";

/**
 * One plain sentence for a detail the operator has not supplied.
 *
 * The attribute names the unset fields in lib/legal-facts.ts, so a test or
 * a search can find every open item without the visitor being shown a
 * marker.
 */
export function Pending({
  fact,
  children,
}: {
  fact: OwnerFactKey | OwnerFactKey[];
  children: ReactNode;
}) {
  const keys = Array.isArray(fact) ? fact.join(" ") : fact;
  return <span data-legal-pending={keys}>{children}</span>;
}

const COMPANY_ROWS: [OwnerFactKey, string][] = [
  ["companyName", "legal name"],
  ["registrationNumber", "registration number"],
  ["registeredAddress", "registered address"],
  ["jurisdiction", "jurisdiction"],
  ["vatNumber", "VAT number"],
];

function list(words: string[]): string {
  if (words.length < 2) return words.join("");
  return `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
}

function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Who operates the product: the supplied details, and what is still missing. */
export function CompanyBlock({ facts = LEGAL_FACTS }: { facts?: LegalFacts }) {
  const known = COMPANY_ROWS.filter(([key]) => hasFact(facts[key]));
  const missing = COMPANY_ROWS.filter(([key]) => !hasFact(facts[key]));
  return (
    <p>
      {known.map(([key, label]) => (
        <span key={key}>
          {capital(label)} of the operator of {facts.productName}: {facts[key]}.{" "}
        </span>
      ))}
      {missing.length > 0 ? (
        <Pending fact={missing.map(([key]) => key)}>
          The operator&rsquo;s {list(missing.map(([, label]) => label))}{" "}
          {missing.length > 1 ? "are" : "is"} not published yet. The missing
          company details will be published here before any paid licence is
          sold.
        </Pending>
      ) : null}
    </p>
  );
}
