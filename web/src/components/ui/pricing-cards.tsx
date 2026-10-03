"use client";
/**
 * Pricing cards. Presentation only — it states nothing of its own.
 *
 * Vendored from a component library that shipped with six example plans at
 * invented prices as DEFAULT props. Those are gone on purpose: a default
 * price is a price the product will eventually show by accident, and this
 * codebase already keeps one approved offer on the server with a readiness
 * gate (billing.offer_drift) watching for a deployment that moves off it. A
 * number typed in here would be a second source of truth that no gate can
 * see — the same mistake as a component deciding for itself whether live
 * execution is on.
 *
 * So `groups` is required, and every figure in it comes from the caller.
 *
 * WHY THIS NO LONGER USES THE VENDORED TINTS
 *
 * It arrived with a six-colour palette, two blurred colour blobs and a
 * coloured orb per card. Rendered on the marketing page that meant a
 * turquoise card beside an orange one, on a page that is black and one red,
 * with the lower half of each card inheriting the APP's surface tokens
 * instead of the marketing page's. It read as two components borrowed from
 * somewhere else, at the exact point a reader decides whether to pay.
 *
 * Now there are two treatments and they carry meaning: `neutral` for a plan
 * that costs nothing, `accent` for the one that costs money. The colours are
 * --mkt-* tokens in globals.css, which is what lets contrast.test.ts assert
 * the ratios instead of somebody judging them by eye.
 */
import { useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";

/** `accent` is the plan being argued for. At most one card should wear it. */
export type PricingPalette = "neutral" | "accent";

export type PricingPlan = {
  id: string;
  name: string;
  description: string;
  palette: PricingPalette;
  /** Already formatted for display. This component does no currency maths. */
  price: string;
  /** Omit when there is nothing to strike through. No invented discounts. */
  originalPrice?: string;
  priceNote?: string;
  ctaLabel: string;
  /** Omit together with `ctaDisabled` when there is nowhere to send anyone. */
  ctaHref?: string;
  ctaDisabled?: boolean;
  /**
   * Draw the call to action as an outline rather than a filled button.
   *
   * Which card gets the filled one is a decision about what the page wants
   * next, not about which plan is dearest — so it is stated by the caller
   * rather than derived from `palette`. Today the free plan is the only one
   * that can actually be acted on, and it is the filled one.
   */
  ctaQuiet?: boolean;
  /** Shown under the button. The place to say why a CTA is inert. */
  ctaNote?: string;
  featuredLabel?: string;
  features: string[];
  footerNote?: string;
  footerDesc?: string;
};

export type PricingGroup = {
  key: string;
  label: string;
  plans: PricingPlan[];
};

export function PlanCard({ plan }: { plan: PricingPlan }) {
  const ctaClass = `pc-cta${plan.ctaQuiet ? " pc-cta-quiet" : ""}`;

  return (
    <div className={`pc-card${plan.palette === "accent" ? " pc-card-accent" : ""}`}>
      <div className="pc-top">
        {plan.featuredLabel ? (
          <span className="pc-badge">{plan.featuredLabel}</span>
        ) : null}

        <h3 className="pc-name">{plan.name}</h3>
        <p className="pc-desc">{plan.description}</p>

        <div className="pc-price-row">
          <span className="pc-price">{plan.price}</span>
          {plan.originalPrice ? (
            <span className="pc-was">{plan.originalPrice}</span>
          ) : null}
        </div>
        {plan.priceNote ? (
          <p className="pc-price-note">{plan.priceNote}</p>
        ) : null}

        {/* A CTA with nowhere to go is a button, not a link. It is disabled
            rather than hidden, so the reader can see that the plan exists
            and that buying it is not open yet — hiding it would read as the
            plan not existing. */}
        {plan.ctaDisabled || !plan.ctaHref ? (
          <button type="button" className={ctaClass} disabled aria-disabled="true">
            {plan.ctaLabel}
          </button>
        ) : (
          <Link className={ctaClass} href={plan.ctaHref}>
            {plan.ctaLabel}
          </Link>
        )}

        {plan.ctaNote ? <p className="pc-cta-note">{plan.ctaNote}</p> : null}
      </div>

      <div className="pc-body">
        <ul className="pc-features">
          {plan.features.map((f) => (
            <li key={f}>
              <Check className="ico" size={15} aria-hidden />
              {f}
            </li>
          ))}
        </ul>

        {plan.footerNote || plan.footerDesc ? (
          <div className="pc-foot">
            {plan.footerNote ? <strong>{plan.footerNote}</strong> : null}
            {plan.footerDesc ? <p>{plan.footerDesc}</p> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function PricingCards({
  groups,
  title,
  subtitle,
  defaultGroup,
}: {
  groups: PricingGroup[];
  title?: string;
  subtitle?: string;
  defaultGroup?: string;
}) {
  const [active, setActive] = useState(defaultGroup ?? groups[0]?.key ?? "");
  const current = groups.find((g) => g.key === active) ?? groups[0];
  const plans = current?.plans ?? [];

  return (
    <div className="pc">
      <div className="pc-head-row">
        {title ? <h2>{title}</h2> : null}
        {subtitle ? <p>{subtitle}</p> : null}

        {/* One group needs no switch. The vendored component always drew the
            tab row, which with a single group is a control that does nothing
            and implies choices that do not exist. */}
        {groups.length > 1 ? (
          <div className="pc-tabs" role="tablist">
            {groups.map((g) => (
              <button
                key={g.key}
                type="button"
                onClick={() => setActive(g.key)}
                aria-pressed={active === g.key}
                className={`mkt-btn${active === g.key ? "" : " mkt-btn-ghost"}`}
              >
                {g.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {/* THE `grid` CLASS IS NOT TAILWIND'S HERE
          globals.css:535 defines `.grid { display:grid; grid-template-columns:
          1fr }` as a plain, unlayered rule. Tailwind v4 emits its utilities
          inside @layer utilities, and unlayered CSS beats layered CSS whatever
          the specificity — so `md:grid-cols-2` loses to it silently and every
          card stacks into one column. Measured: grid-template-columns computed
          to a single 1030px track at a 1280px viewport.
          So the layout uses the house classes, which is what `.grid` is for in
          this codebase, and `grid-2`/`grid-3` carry their own breakpoints. */}
      <div
        className={[
          "grid",
          plans.length === 2 ? "grid-2" : "",
          plans.length >= 3 ? "grid-3" : "",
        ].filter(Boolean).join(" ")}
      >
        {plans.map((plan) => (
          <PlanCard key={plan.id} plan={plan} />
        ))}
      </div>
    </div>
  );
}

export default PricingCards;
