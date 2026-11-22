"use client";
/**
 * What Apex4Traders charges, as the server states it.
 *
 * There is ONE offer — billing.py keeps it (sku `founder_lifetime`), and
 * offer_drift() reports on /readyz when a deployment moves off the approved
 * values. This section therefore states no figure of its own: it reads
 * billing/offer and formats what comes back.
 *
 * A PRICE IS SHOWN ONLY WHILE IT CAN BE PAID.
 *
 * Until the server says purchase is open (checkout on AND implemented), the
 * paid card carries no figure at all: it is the live-trading waitlist card,
 * "Waitlist" where the price would be, and nothing is for sale. The same goes
 * while the offer is still loading and when it could not be read: the closed
 * state is the safe default, so a price can never appear that cannot be paid,
 * and a failed read can never be mistaken for "free".
 */
import { useEffect, useState } from "react";
import {
  formatOfferPrice,
  publicApi,
  type ApiResult,
  type PublicOffer,
} from "@/lib/api";
import { PricingCards, type PricingPlan } from "@/components/ui/pricing-cards";
import { RefundPolicyNote } from "@/components/legal/refund-policy-note";

/** What the paid plan includes. Capability, never outcome. */
const FOUNDER_FEATURES = [
  "Connect a cTrader account",
  "Build rules from indicators and price levels",
  "Preview a rule against real candles before it runs",
  "Start, pause and stop automation yourself",
  "Journal of starts, stops, pauses and signals",
  "Risk limits you set, enforced server-side",
  "Email support",
];

const DEMO_FEATURES = [
  "Connect a cTrader demo account",
  "Build and preview rules",
  "Run automation on the demo account",
  "Full journal",
];

const DEMO_PLAN: PricingPlan = {
  id: "demo",
  name: "Demo",
  description: "Practice accounts, at no cost. No card. Free for 14 days.",
  palette: "neutral",
  price: "Free",
  // The only plan anybody can act on today, so it carries the filled button.
  ctaLabel: "Create an account",
  ctaHref: "/signup",
  features: DEMO_FEATURES,
  footerNote: "No payment details required",
  footerDesc:
    "The free demo trial lasts 14 days, then demo automation pauses. Nothing on a practice account can move real money.",
};

/** The paid card while nothing can be bought: no price, a way to be told. */
const LIVE_WAITLIST_PLAN: PricingPlan = {
  id: "live_waitlist",
  name: "Live trading",
  description: "Real-money account access, for when live execution is enabled.",
  palette: "accent",
  price: "Waitlist",
  priceNote: "Not open yet. No payment is taken.",
  statusBadge: "Coming later",
  ctaLabel: "Join the waitlist",
  ctaHref: "#waitlist",
  features: FOUNDER_FEATURES,
  footerNote: "No payment is taken now",
  footerDesc:
    "Live trading is not available yet. Leaving your email costs nothing: we write to you once, when early access opens.",
};

/**
 * Both have to be true. checkoutEnabled alone has meant "the flags are on"
 * while POST billing/checkout still answers 501.
 */
export function purchaseOpen(offer: PublicOffer): boolean {
  return offer.checkoutEnabled && offer.checkoutImplemented === true;
}

export function planFor(offer: PublicOffer): PricingPlan[] {
  if (!purchaseOpen(offer)) return [DEMO_PLAN, LIVE_WAITLIST_PLAN];
  const lifetime = offer.periodDays === null;
  return [
    DEMO_PLAN,
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
      featuredLabel: lifetime ? "Lifetime access" : undefined,
      variant: lifetime ? "lifetime" : undefined,
      ctaLabel: "Get Founder access",
      ctaHref: "/license",
      features: FOUNDER_FEATURES,
      footerNote: lifetime ? "No renewal, ever" : "Renewal terms apply",
      footerDesc:
        "Live trading is not available in this release. This plan is listed so the price is public, not to take money for something that does not run yet.",
    },
  ];
}

export function PricingSection() {
  const [result, setResult] = useState<ApiResult<PublicOffer> | null>(null);

  useEffect(() => {
    // Queued, not called from the effect body: setting state synchronously
    // during commit is a cascading render. Same reason use-api.ts queues its
    // own first read.
    queueMicrotask(() => {
      void publicApi<PublicOffer>("billing/offer").then(setResult);
    });
  }, []);

  // Closed unless the server has said otherwise. Loading and failure both
  // land here, deliberately: see the header.
  const offer = result?.ok ? result.data : null;
  const open = offer ? purchaseOpen(offer) : false;
  const plans = offer ? planFor(offer) : [DEMO_PLAN, LIVE_WAITLIST_PLAN];

  return (
    <section className="w-full" aria-label="Plans">
      <PricingCards
        eyebrow={open ? "Pricing" : "Plans"}
        title={
          open
            ? offer!.periodDays === null ? "One price. Lifetime access." : "Pricing"
            : "Free demo now. Live trading next."
        }
        subtitle={
          open
            ? offer!.periodDays === null
              ? "Pay once. No subscriptions and no renewals. Demo accounts are free."
              : "Demo accounts are free. One paid plan, bought once."
            : "Practice on a demo account at no cost. Live trading is not open yet: leave your email and we will write to you once, when it opens."
        }
        groups={[{ key: "all", label: "Plans", plans }]}
      />
      <RefundPolicyNote className="mt-6 text-sm text-muted-foreground" />
    </section>
  );
}

export default PricingSection;
