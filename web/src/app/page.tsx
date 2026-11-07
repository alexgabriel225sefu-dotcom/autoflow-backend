import type { Metadata } from "next";
import {
  ArrowUpRight,
  Eye,
  GaugeCircle,
  Link2,
  ListChecks,
  PlayCircle,
  ShieldCheck,
} from "lucide-react";
import { PLAN_NOTICE } from "@/lib/api";
import { BrandLockup } from "@/components/brand/logo";
import { SpotlightGrid } from "@/components/marketing/spotlight-grid";
import { RuleSentenceHero } from "@/components/marketing/rule-sentence-hero";
import { HeroProduct } from "@/components/marketing/hero-product";
import { ProductShowcase } from "@/components/marketing/product-showcase";
import { PricingSection } from "@/components/blocks/pricing-section";

export const metadata: Metadata = {
  title: "Apex4Traders: clear rules for your trading",
  description:
    "Connect your cTrader account, choose a rule and test it on demo before you automate it.",
};

const steps = [
  ["01", "Connect your account", "Choose your cTrader account and see its state before you continue."],
  ["02", "Choose a rule", "Start with a clear method or build conditions that match your plan."],
  ["03", "Test on demo", "Review what the rule would do with demo data before automation."],
] as const;

const features = [
  { icon: Link2, title: "Connect your own account", body: "You authorise your cTrader account yourself and can disconnect it at any time. We never ask for your broker password." },
  { icon: ListChecks, title: "Build rules from conditions", body: "Combine moving averages, RSI, MACD, sessions and more, then read the rule back in plain language before you test it." },
  { icon: Eye, title: "Review before it runs", body: "See which conditions passed, which failed and what the rule would decide. A preview never places an order." },
  { icon: GaugeCircle, title: "Set your limits", body: "Risk per trade, stop distance, target and the number of open positions stay next to the rule you are testing." },
  { icon: PlayCircle, title: "Start, pause or stop", body: "One panel shows the current state. If something cannot be read, it says so instead of guessing." },
  { icon: ShieldCheck, title: "Keep a decision journal", body: "Every evaluation records what the rule saw, what it decided and why, so you can review it later." },
] as const;

const faqs = [
  ["Do I need a broker account?", "Yes. You connect your own cTrader account so the platform can read the market and account context you choose."],
  ["Does it place real orders?", "This release is for demo accounts. A preview and a test do not place an order."],
  ["What happens if data is unavailable?", "The screen says when a read is unavailable and names the next step. It does not fill in a guess."],
  ["Can I write my own rules?", "Yes. You can combine named conditions and read the rule back before testing it."],
] as const;

export default function Landing() {
  return (
    <main className="mkt">
      <div className="mkt-wrap">
        <nav className="mkt-nav">
          <BrandLockup size={24} />
          <span className="mkt-nav-mid">
            <a href="#product">Product</a>
            <a href="#how-it-works">How it works</a>
            <a href="#platforms">Platforms</a>
            <a href="/pricing">Pricing</a>
            <a href="#faq">FAQ</a>
          </span>
          <span className="mkt-nav-links">
            <a className="mkt-navlink" href="/login">Log in</a>
            <a className="mkt-btn" href="/signup">Try free for 14 days</a>
          </span>
        </nav>

        <RuleSentenceHero />

        <section className="mkt-section" aria-label="The platform in use" style={{ paddingTop: 0 }}>
          <HeroProduct />
        </section>

        <section id="tour" className="mkt-section" aria-labelledby="tour-title">
          <span className="mkt-eyebrow">The platform</span>
          <h2 id="tour-title">See it before you sign up.</h2>
          <p>Real screens from a demo account, from the first setup step to the journal of every decision.</p>
          <ProductShowcase />
        </section>

        <section id="how-it-works" className="mkt-section mkt-flow" aria-labelledby="how-title">
          <div>
            <span className="mkt-eyebrow">How it works</span>
            <h2 id="how-title">A simple path from idea to demo.</h2>
            <p>Each step shows you what is connected, what the rule checks and what happens next.</p>
          </div>
          <div className="mkt-flow-steps">
            {steps.map(([number, title, body]) => (
              <div className="mkt-flow-step" key={number}>
                <span>{number}</span>
                <strong>{title}</strong>
                <p>{body}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="platforms" className="mkt-partners" aria-labelledby="platforms-title">
          <div className="mkt-section-heading">
            <span className="mkt-eyebrow">Platforms</span>
            <h2 id="platforms-title">Connect the platform you use.</h2>
            <p>cTrader is available today. MetaTrader connections are on the roadmap.</p>
          </div>
          <SpotlightGrid className="mkt-partner-grid">
            <div className="mkt-partner mkt-partner-live" data-spot>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/ctrader-logo-light.svg" alt="cTrader" height={34} />
              <span className="mkt-partner-status">Available now</span>
              <a href="/signup">Connect cTrader <ArrowUpRight size={15} aria-hidden /></a>
            </div>
            <div className="mkt-partner mkt-partner-soon" data-spot>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/metatrader-4-light.png" alt="MetaTrader 4" height={34} />
              <span className="mkt-partner-status">Coming soon</span>
            </div>
            <div className="mkt-partner mkt-partner-soon" data-spot>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/metatrader-5-light.png" alt="MetaTrader 5" height={34} />
              <span className="mkt-partner-status">Coming soon</span>
            </div>
          </SpotlightGrid>
          <p className="mkt-partner-note">No install path promised yet for MetaTrader.</p>
        </section>

        <section id="features" className="mkt-section">
          <span className="mkt-eyebrow">Features</span>
          <h2>Everything you need to test a rule.</h2>
          <p>One workspace to connect your account, review the rule and keep your limits in view.</p>
          <div className="mkt-feature-grid">
            {features.map(({ icon: Icon, title, body }) => (
              <article className="mkt-feature" key={title}>
                <span className="mkt-feature-icon"><Icon size={18} aria-hidden /></span>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="mkt-section" aria-labelledby="audience-title">
          <span className="mkt-eyebrow">Who it is for</span>
          <h2 id="audience-title">A calmer starting point for two kinds of trader.</h2>
          <div className="mkt-audience-grid">
            <article className="mkt-audience-card"><h3>Starting out</h3><p>Learn what each setting means, test a simple rule on demo and build confidence in the process.</p></article>
            <article className="mkt-audience-card"><h3>Already trading</h3><p>Turn an existing plan into named conditions, review the edge cases and keep account context nearby.</p></article>
          </div>
        </section>

        <section id="faq" className="mkt-section mkt-faq" aria-labelledby="faq-title">
          <span className="mkt-eyebrow">Questions</span>
          <h2 id="faq-title">Questions, answered plainly.</h2>
          <div className="mkt-faq-list">
            {faqs.map(([question, answer]) => (
              <details key={question}>
                <summary>{question}</summary>
                <p>{answer}</p>
              </details>
            ))}
          </div>
        </section>

        <section id="pricing" className="mkt-section"><PricingSection /></section>

        <section className="mkt-section">
          <h2>Built for rules, not predictions.</h2>
          <p className="mkt-plain" style={{ marginTop: ".9rem" }}>
            Apex4Traders is software that executes rules you configure. It is
            not financial advice, does not manage money for you and does not
            supply signals. We do not take custody of your funds.
          </p>
          <div className="mkt-risk">
            <strong style={{ color: "var(--mkt-text)" }}>Risk warning.</strong>{" "}
            Leveraged trading carries a high risk of loss. Past results do not
            guarantee future results. You are responsible for the rules you run.
          </div>
          <div className="mkt-risk">
            <strong style={{ color: "var(--mkt-text)" }}>Demo accounts first.</strong>{" "}
            Live trading is not available in this release. {PLAN_NOTICE}
          </div>
        </section>

        <footer className="mkt-foot">
          <span>© Apex4Traders</span>
          <span><a href="/terms">Terms</a> · <a href="/privacy">Privacy</a> · <a href="/login">Sign in</a></span>
        </footer>
      </div>
    </main>
  );
}
