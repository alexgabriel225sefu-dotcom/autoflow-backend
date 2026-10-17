"use client";
/**
 * What Apex4Traders charges, as the server states it.
 *
 * There is ONE offer — billing.py keeps it (sku `founder_lifetime`), and
 * offer_drift() reports on /readyz when a deployment moves off the approved
 * values. This section therefore states no figure of its own: it reads
 * billing/offer and formats what comes back.
 *
 * The three states it can be in are kept distinct, because this screen is
 * read by somebody deciding whether to pay:
 *
 *   answered     the price, from the server
 *   still asking a skeleton, never a placeholder price
 *   could not    a plain sentence saying so, and a retry — never a price we
 *                guessed, and never silence that reads as "free"
 */
import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import {
  formatOfferPrice,
  publicApi,
  type ApiResult,
  type PublicOffer,
} from "@/lib/api";
import { PricingCards, type PricingPlan } from "@/components/ui/pricing-cards";

/** What the paid plan includes. Capability, never outcome. */
const FOUNDER_FEATURES = [
  "Connect a cTrader account",
  "Build rules from indicators and price levels",
  "Preview a rule against real candles before it runs",
  "Start, pause and stop automation yourself",
  "Full journal of every decision and why",
  "Risk limits you set, enforced server-side",
  "Email support",
];

const DEMO_FEATURES = [
  "Connect a cTrader demo account",
  "Build and preview rules",
  "Run automation on the demo account",
  "Full journal",
];

function planFor(offer: PublicOffer): PricingPlan[] {
  const lifetime = offer.periodDays === null;
  return [
    {
      id: "demo",
      name: "Demo",
      description: "Practice accounts, at no cost. No card, no expiry.",
      palette: "neutral",
      price: "Free",
      // The only plan anybody can act on today, so it carries the filled
      // button. The paid card below is disabled, and a prominent button that
      // refuses to be pressed is worse than a quiet one.
      ctaLabel: "Create an account",
      ctaHref: "/signup",
      features: DEMO_FEATURES,
      footerNote: "No payment details required",
      footerDesc:
        "Demo accounts stay free. Nothing on a practice account can move real money.",
    },
    {
      id: offer.sku,
      name: "Founder",
      description:
        "Real-money account access, for when live execution is enabled.",
      palette: "accent",
      price: formatOfferPrice(offer),
      priceNote: lifetime
        ? "One-time payment, no renewal"
        : `One-time payment, access for ${offer.periodDays} days`,
      ctaQuiet: !offer.checkoutEnabled,
      featuredLabel: lifetime ? "Lifetime access" : undefined,
      ctaLabel: offer.checkoutEnabled ? "Get Founder access" : "Not on sale yet",
      ctaHref: offer.checkoutEnabled ? "/license" : undefined,
      ctaDisabled: !offer.checkoutEnabled,
      // Said on the card rather than discovered at a checkout that refuses.
      ctaNote: offer.checkoutEnabled
        ? undefined
        : "Live execution is not enabled in this release, so this plan is not on sale yet.",
      features: FOUNDER_FEATURES,
      footerNote: lifetime ? "No renewal, ever" : "Renewal terms apply",
      footerDesc:
        "Live trading is not available in this release. This plan is listed so the price is public, not to take money for something that does not run yet.",
    },
  ];
}

export function PricingSection() {
  const [result, setResult] = useState<ApiResult<PublicOffer> | null>(null);

  const load = useCallback(async () => {
    setResult(null);
    setResult(await publicApi<PublicOffer>("billing/offer"));
  }, []);

  useEffect(() => {
    // Queued, not called from the effect body: `load` clears the result
    // before it awaits, and doing that synchronously during commit is a
    // cascading render. Same reason use-api.ts queues its own first read.
    queueMicrotask(() => void load());
  }, [load]);

  const offer = result?.ok ? result.data : null;

  return (
    <section id="pricing" className="w-full">
      {offer ? (
        <PricingCards
          title="Pricing"
          subtitle="Demo accounts are free. One paid plan, bought once."
          groups={[{ key: "all", label: "Plans", plans: planFor(offer) }]}
        />
      ) : result && !result.ok ? (
        <div className="space-y-2">
          <h2 className="text-3xl font-bold tracking-tight">Pricing</h2>
          {/* No figure here. A price we could not read must not be replaced
              by one we remember, and an empty section would read as free. */}
          <p className="text-sm text-muted-foreground">
            The price could not be loaded just now. Demo accounts are free; the
            paid plan&rsquo;s price is set on the server and is shown here once
            it answers.
          </p>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void load()}>
            <RefreshCw className="ico" aria-hidden /> Try again
          </button>
        </div>
      ) : (
        <div className="space-y-2" aria-busy="true">
          <h2 className="text-3xl font-bold tracking-tight">Pricing</h2>
          <p className="text-sm text-muted-foreground">Loading the current price&hellip;</p>
        </div>
      )}
    </section>
  );
}

export default PricingSection;
