import type { Metadata } from "next";
import Link from "next/link";
import { BrandLockup } from "@/components/brand/logo";
import { PricingSection } from "@/components/blocks/pricing-section";

export const metadata: Metadata = {
  title: "Pricing — Apex4Traders",
  description:
    "Demo accounts are free. The paid plan's price is the one the server " +
    "publishes. Live purchase is not open in this release.",
};

/**
 * The price, on its own URL.
 *
 * The landing page links here. A visitor who opens /pricing directly — from
 * an advertisement, a receipt, or a shared link — used to get the platform's
 * 404. The section is the same one the landing page renders: it reads
 * billing/offer and does not state a price of its own.
 */
export default function PricingPage() {
  return (
    <main className="mkt">
      <div className="mkt-wrap">
        <nav className="mkt-nav">
          <Link href="/" aria-label="Apex4Traders home"><BrandLockup size={24} /></Link>
          <span className="mkt-nav-mid">
            <Link href="/#product">Product</Link>
            <Link href="/#features">Features</Link>
            <Link href="/pricing" aria-current="page">Pricing</Link>
            <Link href="/#resources">Resources</Link>
          </span>
          <span className="mkt-nav-links">
            <a className="mkt-navlink" href="/login">Log in</a>
            <a className="mkt-btn" href="/signup">Get started</a>
          </span>
        </nav>

        <section className="mkt-section">
          <PricingSection />
        </section>

        <footer className="mkt-foot">
          <span>© Apex4Traders</span>
          <span>
            <Link href="/terms">Terms</Link> · <Link href="/privacy">Privacy</Link> ·{" "}
            <Link href="/">Home</Link>
          </span>
        </footer>
      </div>
    </main>
  );
}
