import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy Policy — Apex Trade Bot" };

export default function PrivacyPage() {
  return (
    <main className="a4t"><div className="legacy">
      <h1>Privacy Policy</h1>
      <div>
        <section>
          <h2>1. Data We Collect</h2>
          <p>We collect your name and email address when you make a purchase. This information is used solely to deliver your product and send transaction receipts.</p>
        </section>
        <section>
          <h2>2. Payment Processing</h2>
          <p>Payments are processed by Stripe. We do not store card details on our servers. Stripe&apos;s privacy policy applies to payment data.</p>
        </section>
        <section>
          <h2>3. Data Sharing</h2>
          <p>We do not sell, trade, or share your personal information with third parties except as required by law or to fulfill your order.</p>
        </section>
        <section>
          <h2>4. Cookies</h2>
          <p>We use minimal session cookies required for the checkout process. No tracking or advertising cookies are used.</p>
        </section>
        <section>
          <h2>5. Contact</h2>
          <p>For privacy-related questions, contact us at support@aicashsystem.space.</p>
        </section>
      </div>
    </div></main>
  );
}
