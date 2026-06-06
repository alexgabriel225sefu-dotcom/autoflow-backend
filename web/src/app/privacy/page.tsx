import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy Policy — Apex Trade Bot" };

export default function PrivacyPage() {
  return (
    <main className="min-h-screen px-6 py-20 max-w-3xl mx-auto" style={{ background: "var(--background)" }}>
      <h1 className="text-3xl font-extrabold mb-8 tracking-tight">Privacy Policy</h1>
      <div className="space-y-6 text-white/60 text-sm leading-relaxed">
        <section>
          <h2 className="text-white font-semibold text-base mb-2">1. Data We Collect</h2>
          <p>We collect your name and email address when you make a purchase. This information is used solely to deliver your product and send transaction receipts.</p>
        </section>
        <section>
          <h2 className="text-white font-semibold text-base mb-2">2. Payment Processing</h2>
          <p>Payments are processed by Stripe. We do not store card details on our servers. Stripe&apos;s privacy policy applies to payment data.</p>
        </section>
        <section>
          <h2 className="text-white font-semibold text-base mb-2">3. Data Sharing</h2>
          <p>We do not sell, trade, or share your personal information with third parties except as required by law or to fulfill your order.</p>
        </section>
        <section>
          <h2 className="text-white font-semibold text-base mb-2">4. Cookies</h2>
          <p>We use minimal session cookies required for the checkout process. No tracking or advertising cookies are used.</p>
        </section>
        <section>
          <h2 className="text-white font-semibold text-base mb-2">5. Contact</h2>
          <p>For privacy-related questions, contact us at support@aicashsystem.space.</p>
        </section>
      </div>
    </main>
  );
}
