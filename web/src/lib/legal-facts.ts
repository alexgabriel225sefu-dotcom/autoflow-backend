import { SITE_URL } from "./site";
import { SUPPORT_EMAIL } from "./support";

/**
 * Every fact the legal pages state about who operates Apex4Traders.
 *
 * ONE FILE. /terms, /privacy, /refunds and /tax read from here and from
 * nowhere else. A field is either a real value or `null`. While it is
 * `null` the page says, in one plain sentence, that the detail is not
 * published yet. It never prints a marker or a template token.
 *
 * TO THE OWNER: replace a `null` below with the real value, as a string.
 * Nothing else needs to change. Do not enter a guess. Filling these in does
 * not publish the documents: that is still A4T_LEGAL_PUBLISH, and it does
 * not open checkout.
 *
 * Only values the repository itself proves are filled in. A vendor is named
 * only where the code calls it. No data region is stated, because no file
 * here can verify one.
 */
export type Fact = string | null;

export interface LegalFacts {
  productName: string;
  siteUrl: string;
  companyName: Fact;
  registeredAddress: Fact;
  registrationNumber: Fact;
  vatNumber: Fact;
  jurisdiction: Fact;
  governingLaw: Fact;
  disputeForum: Fact;
  supportEmail: Fact;
  privacyEmail: Fact;
  approvedVersionDate: Fact;
  retentionAccountData: Fact;
  retentionJournal: Fact;
  retentionBrokerLinks: Fact;
  dataSubjectRights: Fact;
  authProvider: Fact;
  paymentProvider: Fact;
  hostingProvider: Fact;
  emailProvider: Fact;
  dataRegion: Fact;
  subProcessorList: Fact;
  taxTreatment: Fact;
}

export type OwnerFactKey = Exclude<keyof LegalFacts, "productName" | "siteUrl">;

export const LEGAL_FACTS: LegalFacts = {
  productName: "Apex4Traders",
  siteUrl: SITE_URL,

  // The operator. Not known to this repository.
  companyName: null,
  registeredAddress: null,
  registrationNumber: null,
  vatNumber: null,
  jurisdiction: null,
  governingLaw: null,
  disputeForum: null,

  // Contact. The support address has its own constant in lib/support.ts,
  // because the app screens read it too. Set it there.
  supportEmail: SUPPORT_EMAIL,
  privacyEmail: null,

  approvedVersionDate: null,

  retentionAccountData: null,
  retentionJournal: null,
  retentionBrokerLinks: null,
  dataSubjectRights: null,

  // Vendors the code calls. Supabase: src/lib/supabase. Stripe: the
  // `stripe` dependency and apex/platform/stripe_checkout.py. Render:
  // src/lib/canonical-host.ts. Resend: apex/platform/waitlist.py.
  authProvider: "Supabase",
  paymentProvider: "Stripe",
  hostingProvider: "Render",
  emailProvider: "Resend",
  dataRegion: null,
  subProcessorList: null,

  taxTreatment: null,
};

/** What the owner has to supply for each field, in the owner's words. */
export const OWNER_FACT_REQUESTS: Record<OwnerFactKey, string> = {
  companyName: "Full legal name of the entity that operates Apex4Traders.",
  registeredAddress: "Registered address of that entity.",
  registrationNumber: "Company registration number, and the register it is in.",
  vatNumber: "VAT or tax registration number, or a statement that the entity is not registered.",
  jurisdiction: "Country or jurisdiction where the entity is established.",
  governingLaw: "The law that governs the terms.",
  disputeForum: "The courts or forum that hear a dispute under the terms.",
  supportEmail: "A support mailbox the owner reads. Set SUPPORT_EMAIL in lib/support.ts.",
  privacyEmail: "The address for privacy requests and for removal from the early-access list.",
  approvedVersionDate: "The date the owner approved this version of the documents.",
  retentionAccountData: "How long account data is kept.",
  retentionJournal: "How long journal entries are kept.",
  retentionBrokerLinks: "How long a disconnected broker link is kept.",
  dataSubjectRights: "The data rights that apply under the governing law, and how to exercise them.",
  authProvider: "The authentication provider.",
  paymentProvider: "The payment provider.",
  hostingProvider: "The hosting provider.",
  emailProvider: "The provider that delivers the early-access email.",
  dataRegion: "The region where account data is stored and processed.",
  subProcessorList: "The complete list of sub-processors with their locations.",
  taxTreatment: "Whether the price includes tax, and which taxes the payment provider collects.",
};

/** The tokens the drafts used to print, and the field each one became. */
export const PLACEHOLDER_FACTS = {
  COMPANY_NAME: "companyName",
  REGISTRATION_NUMBER: "registrationNumber",
  ADDRESS: "registeredAddress",
  JURISDICTION: "jurisdiction",
  VAT: "vatNumber",
} as const satisfies Record<string, OwnerFactKey>;

const NOT_A_VALUE = /\{\{|\}\}|TO BE CONFIRM/i;

/** True for a real value. Empty text and a pasted template token are not one. */
export function hasFact(value: Fact | undefined): value is string {
  return typeof value === "string" && value.trim() !== "" && !NOT_A_VALUE.test(value);
}

/** The fields the owner still has to supply. */
export function missingLegalFacts(facts: LegalFacts = LEGAL_FACTS): OwnerFactKey[] {
  return (Object.keys(OWNER_FACT_REQUESTS) as OwnerFactKey[]).filter(
    (key) => !hasFact(facts[key]),
  );
}
