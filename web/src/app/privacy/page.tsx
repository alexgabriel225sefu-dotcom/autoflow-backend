import type { Metadata } from "next";
import Link from "next/link";
import { BrandLockup } from "@/components/brand/logo";
import { LegalSection, LegalSections } from "@/components/legal/legal-section";
import { ReadingProgress } from "@/components/legal/reading-progress";
import { ApprovedDate } from "@/components/legal/draft-shell";
import { Pending } from "@/components/legal/pending";
import { LEGAL_FACTS, hasFact } from "@/lib/legal-facts";

export const metadata: Metadata = { title: "Privacy Policy — Apex4Traders" };

/**
 * Privacy Policy.
 *
 * What is described below is what the code actually does — the processors are
 * named because they are in the dependency list, and the broker token
 * handling is described because apex/platform/ctrader_link.py behaves that
 * way. The controller's identity, jurisdiction, retention periods and
 * contact are the owner's. They come from lib/legal-facts.ts, and an unset
 * one is stated as missing.
 *
 * The previous version described collecting a name and email "when you make a
 * purchase" to "deliver your product", and gave a support address at a
 * different brand's domain.
 *
 * SECTION 2 EXISTS BECAUSE EVERY SECTION BUT THAT ONE IS ABOUT A SIGNED-IN
 * CLIENT. The early-access form on the landing page takes an email address
 * from somebody who has no account, no password, no rules and no journal —
 * and this page, which is the one link under that form, described none of
 * their data. That is the reader an advertisement pays to send here, and the
 * only reader who has given us something before they have anything back.
 */
export default function PrivacyPage() {
  const facts = LEGAL_FACTS;
  const retention: [string, string | null][] = [
    ["Account data", facts.retentionAccountData],
    ["Journal entries", facts.retentionJournal],
    ["Disconnected broker links", facts.retentionBrokerLinks],
  ];
  return (
    <main className="a4t">
      <ReadingProgress />
      <div className="legacy">
        <div style={{ marginBottom: "var(--sp-5)" }}>
          <Link href="/"><BrandLockup size={24} /></Link>
        </div>

        <h1>Privacy Policy</h1>
        <p className="dim" style={{ fontSize: ".8rem" }}>
          <ApprovedDate />
        </p>

        <div className="legacy-flag" style={{ marginTop: "var(--sp-4)" }}>
          This document is not final. Where a section needs a detail the
          operator has not supplied, the section says so.
        </div>

        <LegalSections>
<LegalSection>
          <h2>1. What we collect when you have an account</h2>
          <p>
            Your email address and password, held by our authentication
            provider; the trading rules you create and their versions; the
            journal of what the platform evaluated and decided on your behalf;
            your notifications; your licence state; and, if you connect one,
            the identifier and mode of your cTrader account together with the
            access tokens needed to reach it.
          </p>
        </LegalSection>

        <LegalSection>
          <h2>2. If you join the early-access list</h2>
          <p>
            You do not need an account to join, and joining does not create
            one. We keep your email address and the moment it arrived, and
            nothing else: no name, no IP address, no referring page, no
            tracking identifier. The address is encrypted where it is stored,
            and it is stored under a keyed hash of itself, so the list cannot
            be read by someone who can see the storage keys.
          </p>
          <p>
            After you have joined, the form asks which platform you trade on
            and which broker you use. Both are optional, both are stored only
            if you answer, and they are used to decide which platform the
            product supports next.
          </p>
          <p>
            We will use the address to send you one email when early access
            opens. There is no newsletter, the list is not shared or sold, and
            the email carries no tracking pixel and no click tracking. Ask us
            and we will take your address off the list.{" "}
            {hasFact(facts.privacyEmail) ? (
              <>
                Write to{" "}
                <a href={`mailto:${facts.privacyEmail}`}>{facts.privacyEmail}</a>{" "}
                to be removed.
              </>
            ) : (
              <Pending fact="privacyEmail">
                The address to write to in order to be removed is not
                published yet.
              </Pending>
            )}
          </p>
        </LegalSection>

        <LegalSection>
          <h2>3. Your broker tokens</h2>
          <p>
            cTrader access and refresh tokens are encrypted at rest on the
            server and are never sent to your browser. No part of the web
            application receives them and no API endpoint returns them.
            Disconnecting your account from the Accounts page removes them from
            the platform.
          </p>
        </LegalSection>

        <LegalSection>
          <h2>4. What we do not collect</h2>
          <p>
            We do not read your broker account&rsquo;s cash flow history —
            deposits, withdrawals, swaps and commissions are not requested, and
            a test in the codebase prevents that request from being added
            without a deliberate decision. There is no advertising or analytics
            tracking in the platform, and no third-party script or iframe runs
            on the pages you use while signed in.
          </p>
        </LegalSection>

        <LegalSection>
          <h2>5. Processors</h2>
          <p>
            {hasFact(facts.authProvider)
              ? `Authentication and account storage are provided by ${facts.authProvider}. `
              : null}
            Market data and order execution go through cTrader and the broker
            you chose.{" "}
            {hasFact(facts.paymentProvider)
              ? `If and when paid access is enabled, payments are processed by ${facts.paymentProvider} and card details are never stored on our servers. `
              : null}
            {hasFact(facts.hostingProvider)
              ? `The application is hosted on ${facts.hostingProvider}. `
              : null}
            The early-access email, when it is sent, will be delivered by{" "}
            {hasFact(facts.emailProvider) ? facts.emailProvider : "an email provider"},
            which will see the address it is sent to.
          </p>
          <p>
            {hasFact(facts.dataRegion) ? (
              <>Data region: {facts.dataRegion}. </>
            ) : null}
            {hasFact(facts.subProcessorList) ? (
              <>Sub-processors and their locations: {facts.subProcessorList}.</>
            ) : null}
            {hasFact(facts.dataRegion) && hasFact(facts.subProcessorList) ? null : (
              <Pending fact={["dataRegion", "subProcessorList"]}>
                {hasFact(facts.dataRegion) ? "" : "The data region "}
                {hasFact(facts.dataRegion) || hasFact(facts.subProcessorList) ? "" : "and "}
                {hasFact(facts.subProcessorList)
                  ? ""
                  : "the complete list of sub-processors with their locations "}
                {hasFact(facts.dataRegion) || hasFact(facts.subProcessorList) ? "is" : "are"}{" "}
                not published yet.
              </Pending>
            )}
          </p>
        </LegalSection>

        <LegalSection>
          <h2>6. Why we hold it</h2>
          <p>
            To sign you in, to run the rules you configured, to show you what
            the platform decided and why, and to tell whether your account is
            licensed. The journal exists so that a decision can be explained
            afterwards; that is its purpose and it is kept for that reason.
          </p>
        </LegalSection>

        <LegalSection>
          <h2>7. How long</h2>
          <p>
            {retention
              .filter(([, value]) => hasFact(value))
              .map(([label, value]) => (
                <span key={label}>
                  {label}: {value}.{" "}
                </span>
              ))}
            {retention.every(([, value]) => hasFact(value)) ? null : (
              <Pending
                fact={["retentionAccountData", "retentionJournal", "retentionBrokerLinks"]}
              >
                Retention periods for{" "}
                {retention
                  .filter(([, value]) => !hasFact(value))
                  .map(([label]) => label.toLowerCase())
                  .join(", ")}{" "}
                have not been set yet, so none is stated here.
              </Pending>
            )}
          </p>
        </LegalSection>

        <LegalSection>
          <h2>8. Your rights</h2>
          <p>
            You can disconnect your broker account at any time, and you can ask
            to be taken off the early-access list.{" "}
            {hasFact(facts.dataSubjectRights) ? (
              facts.dataSubjectRights
            ) : (
              <Pending fact="dataSubjectRights">
                The rights that apply to access, correction, export or
                deletion of your data, and how to exercise them, are not
                stated yet. They depend on the governing law, which is not
                published yet.
              </Pending>
            )}
          </p>
        </LegalSection>

        <LegalSection>
          <h2>9. Cookies</h2>
          <p>
            Session cookies are used to keep you signed in. There are no
            advertising or tracking cookies.
          </p>
        </LegalSection>

        <LegalSection>
          <h2>10. Who is responsible, and how to reach us</h2>
          <p>
            {hasFact(facts.companyName) && hasFact(facts.registeredAddress) ? (
              <>
                The data controller is {facts.companyName},{" "}
                {facts.registeredAddress}.{" "}
              </>
            ) : (
              <Pending fact={["companyName", "registeredAddress"]}>
                The data controller&rsquo;s name and registered address are
                not published yet. They will be published here before any
                paid licence is sold.{" "}
              </Pending>
            )}
            {hasFact(facts.privacyEmail) ? (
              <>
                For privacy requests write to{" "}
                <a href={`mailto:${facts.privacyEmail}`}>{facts.privacyEmail}</a>.
              </>
            ) : (
              <Pending fact="privacyEmail">
                A contact address for privacy requests is not published yet.
              </Pending>
            )}
          </p>
        </LegalSection>
</LegalSections>

        <p style={{ marginTop: "var(--sp-6)" }}>
          <Link href="/terms">Terms of Service</Link>
          {" · "}
          <Link href="/refunds">Refunds</Link>
          {" · "}
          <Link href="/tax">Tax</Link>
        </p>
      </div>
    </main>
  );
}
