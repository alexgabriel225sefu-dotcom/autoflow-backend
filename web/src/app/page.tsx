import type { Metadata } from "next";
import {
  Eye,
  GaugeCircle,
  Link2,
  ListChecks,
  PlayCircle,
  ShieldCheck,
} from "lucide-react";
import { PLAN_NOTICE } from "@/lib/api";
import { BrandLockup } from "@/components/brand/logo";
import { LandingNav } from "@/components/marketing/landing-nav";
import { HeroStage } from "@/components/marketing/hero-stage";
import { ProductShowcase } from "@/components/marketing/product-showcase";
import { ProductGuide } from "@/components/marketing/product-guide";
import { JsonLd } from "@/components/marketing/json-ld";
import { ORGANIZATION_LD, WEBSITE_LD } from "@/lib/json-ld";
import { PricingSection } from "@/components/blocks/pricing-section";
import "./landing.css";

export const metadata: Metadata = {
  title: "Apex4Traders: clear rules for your trading",
  description:
    "Connect your cTrader account, choose a rule and test it on demo before you automate it.",
};

const features = [
  { icon: ShieldCheck, title: "Keep a journal", body: "The journal records when automation starts, pauses and stops, and any signal found at the Signals Only level. Orders and closed trades are listed in Positions and Closed trades." },
  { icon: GaugeCircle, title: "Set your limits", body: "Risk per trade, stop distance, target and the number of open positions stay next to the rule you are testing." },
  { icon: Link2, title: "Connect your own account", body: "You authorise your cTrader account yourself and can disconnect it at any time. We never ask for your broker password." },
  { icon: ListChecks, title: "Build rules from conditions", body: "Combine moving averages, RSI, MACD, sessions and more, then read the rule back in plain language before you test it." },
  { icon: Eye, title: "Review before it runs", body: "See which conditions passed, which failed and what the rule would decide. A preview never places an order." },
  { icon: PlayCircle, title: "Start, pause or stop", body: "One panel shows the current state. If something cannot be read, it says so instead of guessing." },
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
      <JsonLd data={ORGANIZATION_LD} />
      <JsonLd data={WEBSITE_LD} />
      <LandingNav />

      <div className="mkt-wrap">
        <HeroStage />
      </div>

      <section id="platforms" className="lp-strip" aria-labelledby="platforms-title">
        <div className="mkt-wrap lp-strip-in">
          <h2 id="platforms-title">Works with</h2>
          <div className="lp-strip-row">
            <div className="lp-plat lp-plat-live">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/ctrader-logo-light.svg" alt="cTrader" height={28} />
              <span className="lp-plat-status">Available now</span>
            </div>
            <div className="lp-plat lp-plat-soon">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/metatrader-4-light.png" alt="MetaTrader 4" height={28} />
              <span className="lp-plat-status">Coming soon</span>
            </div>
            <div className="lp-plat lp-plat-soon">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/metatrader-5-light.png" alt="MetaTrader 5" height={28} />
              <span className="lp-plat-status">Coming soon</span>
            </div>
          </div>
          <p className="lp-strip-note">cTrader works today. More platforms are on the roadmap. No install path promised yet for MetaTrader.</p>
        </div>
      </section>

      <section id="tour" className="lp-sec" aria-labelledby="tour-title">
        <div className="mkt-wrap">
          <div className="lp-head">
            <p className="lp-eyebrow">The platform</p>
            <h2 id="tour-title">See it before you sign up.</h2>
            <p>Real screens from a demo account, from the first setup step to the journal of what it did.</p>
          </div>
          <ProductShowcase />
        </div>
      </section>

      <section id="how-it-works" className="lp-sec" aria-labelledby="guide-title">
        <div className="mkt-wrap">
          <div className="lp-head">
            <p className="lp-eyebrow">How it works</p>
            <h2 id="guide-title">Three steps. Everything explained on screen.</h2>
            <p>Real screens from the platform. The highlights show where to look.</p>
          </div>
          <ProductGuide />
        </div>
      </section>

      <section id="features" className="lp-sec" aria-labelledby="features-title">
        <div className="mkt-wrap">
          <div className="lp-head">
            <p className="lp-eyebrow">Features</p>
            <h2 id="features-title">Everything you need to test a rule.</h2>
            <p>One workspace to connect your account, review the rule and keep your limits in view.</p>
          </div>
          <div className="lp-grid lp-grid-3">
            {features.map(({ icon: Icon, title, body }) => (
              <article className="lp-card" key={title}>
                <span className="lp-card-icon"><Icon size={18} aria-hidden /></span>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-sec" aria-labelledby="audience-title">
        <div className="mkt-wrap">
          <div className="lp-head">
            <p className="lp-eyebrow">Who it is for</p>
            <h2 id="audience-title">A calmer starting point for two kinds of trader.</h2>
          </div>
          <div className="lp-grid">
            <article className="lp-card lp-card-plain"><h3>Starting out</h3><p>Learn what each setting means, test a simple rule on demo and build confidence in the process.</p></article>
            <article className="lp-card lp-card-plain"><h3>Already trading</h3><p>Turn an existing plan into named conditions, review the edge cases and keep account context nearby.</p></article>
          </div>
        </div>
      </section>

      <section id="pricing" className="lp-sec"><div className="mkt-wrap"><PricingSection /></div></section>

      <section id="faq" className="lp-sec" aria-labelledby="faq-title">
        <div className="mkt-wrap">
          <div className="lp-head">
            <p className="lp-eyebrow">Questions</p>
            <h2 id="faq-title">Questions, answered plainly.</h2>
          </div>
          <div className="lp-faq">
            {faqs.map(([question, answer]) => (
              <details key={question}>
                <summary>{question}</summary>
                <p>{answer}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <div className="lp-final-wrap">
        <div className="mkt-wrap">
          <section className="lp-final" aria-labelledby="final-title">
            <h2 id="final-title">Start on a demo account.</h2>
            <p>Write the rule in plain words, read it back, and test it for 14 days. No card needed.</p>
            <div className="lp-cta">
              <a className="mkt-btn mkt-btn-lg" href="/signup">Try free for 14 days</a>
              <a className="mkt-btn mkt-btn-outline mkt-btn-lg" href="#tour">See the platform</a>
            </div>
          </section>
        </div>
      </div>

      <section className="lp-disclosure" aria-labelledby="disclosure-title">
        <div className="mkt-wrap lp-disclosure-in">
          <div>
            <h2 id="disclosure-title">Built for rules, not predictions.</h2>
            <p>
              Apex4Traders is software that executes rules you configure. It is
              not financial advice, does not manage money for you and does not
              supply signals. We do not take custody of your funds.
            </p>
          </div>
          <div>
            <p>
              <strong>Risk warning.</strong>{" "}
              Leveraged trading carries a high risk of loss. Past results do not
              guarantee future results. You are responsible for the rules you run.
            </p>
            <p>
              <strong>Demo accounts first.</strong>{" "}
              Live trading is not available in this release. {PLAN_NOTICE}
            </p>
          </div>
        </div>
      </section>

      <footer className="lp-foot">
        <div className="mkt-wrap">
          <div className="lp-foot-grid">
            <div className="lp-foot-brand">
              <BrandLockup size={24} />
              <p>Clear rules for your trading.</p>
            </div>
            <div>
              <h3>Product</h3>
              <ul>
                <li><a href="#tour">Platform</a></li>
                <li><a href="#how-it-works">How it works</a></li>
                <li><a href="#features">Features</a></li>
              </ul>
            </div>
            <div>
              <h3>Resources</h3>
              <ul>
                <li><a href="/guide/test-a-rule-on-demo">Test a rule on demo</a></li>
                <li><a href="/faq">FAQ</a></li>
                <li><a href="/pricing">Pricing</a></li>
              </ul>
            </div>
            <div>
              <h3>Legal</h3>
              <ul>
                <li><a href="/terms">Terms</a></li>
                <li><a href="/privacy">Privacy</a></li>
                <li><a href="/refunds">Refunds</a></li>
              </ul>
            </div>
            <div>
              <h3>Account</h3>
              <ul>
                <li><a href="/login">Log in</a></li>
                <li><a href="/signup">Sign up</a></li>
              </ul>
            </div>
          </div>
          <div className="lp-foot-bar">© Apex4Traders</div>
        </div>
      </footer>
    </main>
  );
}
