import type { Metadata } from "next";
import Link from "next/link";
import { BrandLockup } from "@/components/brand/logo";

export const metadata: Metadata = { title: "Privacy Policy — Apex4Traders" };

/**
 * Privacy Policy.
 *
 * What is described below is what the code actually does — the processors are
 * named because they are in the dependency list, and the broker token
 * handling is described because apex/platform/ctrader_link.py behaves that
 * way. What is left as `[TO BE CONFIRMED]` is the controller's identity,
 * jurisdiction, retention periods and contact, which are the owner's.
 *
 * The previous version described collecting a name and email "when you make a
 * purchase" to "deliver your product", and gave a support address at a
 * different brand's domain.
 */
export default function PrivacyPage() {
  return (
    <main className="a4t">
      <div className="legacy">
        <div style={{ marginBottom: "var(--sp-5)" }}>
          <Link href="/"><BrandLockup size={24} /></Link>
        </div>

        <h1>Privacy Policy</h1>
        <p className="dim" style={{ fontSize: ".8rem" }}>
          Last updated: [TO BE CONFIRMED — date of the owner-approved version]
        </p>

        <div className="legacy-flag" style={{ marginTop: "var(--sp-4)" }}>
          This document is not final. The items marked
          &ldquo;[TO BE CONFIRMED]&rdquo; require the operator&rsquo;s decision
          and are listed in the project&rsquo;s legal launch blockers.
        </div>

        <section>
          <h2>1. What we collect</h2>
          <p>
            Your email address and password, held by our authentication
            provider; the trading rules you create and their versions; the
            journal of what the platform evaluated and decided on your behalf;
            your notifications; your licence state; and, if you connect one,
            the identifier and mode of your cTrader account together with the
            access tokens needed to reach it.
          </p>
        </section>

        <section>
          <h2>2. Your broker tokens</h2>
          <p>
            cTrader access and refresh tokens are encrypted at rest on the
            server and are never sent to your browser. No part of the web
            application receives them and no API endpoint returns them.
            Disconnecting your account from the Accounts page removes them from
            the platform.
          </p>
        </section>

        <section>
          <h2>3. What we do not collect</h2>
          <p>
            We do not read your broker account&rsquo;s cash flow history —
            deposits, withdrawals, swaps and commissions are not requested, and
            a test in the codebase prevents that request from being added
            without a deliberate decision. There is no advertising or analytics
            tracking in the platform, and no third-party script or iframe runs
            on the pages you use while signed in.
          </p>
        </section>

        <section>
          <h2>4. Processors</h2>
          <p>
            Authentication and account storage are provided by Supabase. Market
            data and order execution go through cTrader and the broker you
            chose. If and when paid access is enabled, payments are processed
            by Stripe and card details are never stored on our servers.
            <strong> [TO BE CONFIRMED — hosting provider, data region, and the
            full list of sub-processors with their locations.]</strong>
          </p>
        </section>

        <section>
          <h2>5. Why we hold it</h2>
          <p>
            To sign you in, to run the rules you configured, to show you what
            the platform decided and why, and to tell whether your account is
            licensed. The journal exists so that a decision can be explained
            afterwards; that is its purpose and it is kept for that reason.
          </p>
        </section>

        <section>
          <h2>6. How long</h2>
          <p>
            <strong>[TO BE CONFIRMED — retention periods for account data,
            journal entries and disconnected broker links.]</strong>
          </p>
        </section>

        <section>
          <h2>7. Your rights</h2>
          <p>
            You can disconnect your broker account at any time. For access,
            correction, export or deletion of your data,
            <strong> [TO BE CONFIRMED — the rights that apply under the
            governing jurisdiction, and how to exercise them.]</strong>
          </p>
        </section>

        <section>
          <h2>8. Cookies</h2>
          <p>
            Session cookies are used to keep you signed in. There are no
            advertising or tracking cookies.
          </p>
        </section>

        <section>
          <h2>9. Who is responsible, and how to reach us</h2>
          <p>
            <strong>[TO BE CONFIRMED — data controller name, registered
            address, and a contact address for privacy requests.]</strong>
          </p>
        </section>

        <p style={{ marginTop: "var(--sp-6)" }}>
          <Link href="/terms">Terms of Service</Link>
        </p>
      </div>
    </main>
  );
}
