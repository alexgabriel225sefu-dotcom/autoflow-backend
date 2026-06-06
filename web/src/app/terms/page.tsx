import type { Metadata } from "next";

export const metadata: Metadata = { title: "Terms of Service — Apex Trade Bot" };

export default function TermsPage() {
  return (
    <main className="min-h-screen px-6 py-20 max-w-3xl mx-auto" style={{ background: "var(--background)" }}>
      <h1 className="text-3xl font-extrabold mb-8 tracking-tight">Terms of Service</h1>
      <div className="space-y-6 text-white/60 text-sm leading-relaxed">
        <section>
          <h2 className="text-white font-semibold text-base mb-2">1. Digital Product Sale</h2>
          <p>Apex Trade Bot is sold as a one-time purchase of software source code. All sales are final after digital delivery.</p>
        </section>
        <section>
          <h2 className="text-white font-semibold text-base mb-2">2. Risk Disclosure</h2>
          <p>Cryptocurrency trading involves significant financial risk. Past performance does not guarantee future results. You may lose all invested capital.</p>
        </section>
        <section>
          <h2 className="text-white font-semibold text-base mb-2">3. No Financial Advice</h2>
          <p>This software is for educational and informational purposes only. It does not constitute financial advice. Always consult a qualified financial advisor.</p>
        </section>
        <section>
          <h2 className="text-white font-semibold text-base mb-2">4. License</h2>
          <p>You receive a personal, non-transferable license to use the source code. Redistribution or resale of the source code is prohibited.</p>
        </section>
        <section>
          <h2 className="text-white font-semibold text-base mb-2">5. Refund Policy</h2>
          <p>Due to the nature of digital products, all sales are final once the source code has been delivered. No refunds are provided after delivery.</p>
        </section>
      </div>
    </main>
  );
}
