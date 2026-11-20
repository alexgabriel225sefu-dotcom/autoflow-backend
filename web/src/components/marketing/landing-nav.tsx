"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BrandLockup } from "@/components/brand/logo";

/**
 * Sticky top bar. Transparent over the hero; after a few pixels of scroll it
 * gets a blurred surface and a hairline, so the links stay readable over
 * whatever is under them. Nothing else about it moves.
 */
export function LandingNav() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className="lp-nav" data-scrolled={scrolled ? "true" : "false"}>
      <div className="mkt-wrap lp-nav-in">
        <Link href="/" aria-label="Apex4Traders, home" className="lp-nav-brand">
          <BrandLockup size={24} />
        </Link>
        <nav className="lp-nav-links" aria-label="Sections">
          <a href="#tour">Product</a>
          <a href="#how-it-works">How it works</a>
          <a href="#pricing">Pricing</a>
          <a href="#faq">FAQ</a>
        </nav>
        <div className="lp-nav-actions">
          <a className="lp-nav-login" href="/login">Log in</a>
          <a className="mkt-btn" href="/signup">Try free for 14 days</a>
        </div>
      </div>
    </header>
  );
}
