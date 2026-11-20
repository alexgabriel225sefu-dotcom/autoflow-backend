import Link from "next/link";
import { BrandLockup } from "@/components/brand/logo";

/** Navigation and footer shared by the public content pages. */
export function ContentShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mkt">
      <div className="mkt-wrap">
        <nav className="mkt-nav">
          <Link href="/" aria-label="Apex4Traders home"><BrandLockup size={24} /></Link>
          <span className="mkt-nav-mid">
            <Link href="/#product">Product</Link>
            <Link href="/faq">FAQ</Link>
            <Link href="/guide/test-a-rule-on-demo">Guide</Link>
            <Link href="/pricing">Pricing</Link>
          </span>
          <span className="mkt-nav-links">
            <a className="mkt-navlink" href="/login">Log in</a>
            <a className="mkt-btn" href="/signup">Get started</a>
          </span>
        </nav>
        {children}
        <footer className="mkt-foot">
          <span>© Apex4Traders</span>
          <span>
            <Link href="/faq">FAQ</Link> · <Link href="/pricing">Pricing</Link> ·{" "}
            <Link href="/terms">Terms</Link> · <Link href="/privacy">Privacy</Link> ·{" "}
            <Link href="/">Home</Link>
          </span>
        </footer>
      </div>
    </main>
  );
}
