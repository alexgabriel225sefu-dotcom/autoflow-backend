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
 */
import { useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AvatarOrb, type AvatarColor } from "@/components/ui/avatar-orb";

export type PricingPalette =
  | "blue" | "purple" | "amber" | "teal" | "rose" | "slate";

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
  /** Shown under the button. The place to say why a CTA is inert. */
  ctaNote?: string;
  featuredLabel?: string;
  features: string[];
  footerNote?: string;
  footerDesc?: string;
  ctaDark?: boolean;
};

export type PricingGroup = {
  key: string;
  label: string;
  plans: PricingPlan[];
};

/**
 * Card tints.
 *
 * Only the deep ones. The vendored palette carried a light base with a
 * `dark:` override, which assumes a page that switches; this app does not —
 * globals.css defines one theme (--a4t-bg #111322, --a4t-text #F4F0E8) and
 * no light variant. Keeping the light bases meant off-white text at 45-60%
 * alpha painted onto `bg-sky-50`, which is invisible rather than subtle.
 */
const CARD_PALETTES: Record<
  PricingPalette,
  { base: string; blobA: string; blobB: string; avatarColor: AvatarColor }
> = {
  blue: {
    base: "bg-blue-950",
    blobA: "bg-blue-500",
    blobB: "bg-sky-600",
    avatarColor: "blue",
  },
  purple: {
    base: "bg-violet-950",
    blobA: "bg-violet-500",
    blobB: "bg-fuchsia-600",
    avatarColor: "purple",
  },
  amber: {
    base: "bg-amber-950",
    blobA: "bg-amber-500",
    blobB: "bg-yellow-600",
    avatarColor: "yellow",
  },
  teal: {
    base: "bg-teal-950",
    blobA: "bg-teal-500",
    blobB: "bg-emerald-600",
    avatarColor: "turquoise",
  },
  rose: {
    base: "bg-rose-950",
    blobA: "bg-rose-500",
    blobB: "bg-pink-600",
    avatarColor: "red",
  },
  slate: {
    base: "bg-slate-900",
    blobA: "bg-slate-500",
    blobB: "bg-zinc-600",
    avatarColor: "blue",
  },
};

export function PlanCard({ plan }: { plan: PricingPlan }) {
  const pal = CARD_PALETTES[plan.palette] ?? CARD_PALETTES.slate;
  const grainId = `pricing-grain-${plan.id}`;

  // The `!` is load-bearing, for the same reason the layout below uses the
  // house grid classes: globals.css:196 sets `.a4t :where(a) { color:
  // var(--a4t-link) }` unlayered, and unlayered CSS beats @layer utilities
  // whatever the specificity. `asChild` renders this button as an <a>, so
  // without the override the label came out lilac on a glass button —
  // measured as rgb(199,184,255) where the token says #f4f0e8.
  const ctaClass = cn(
    "w-full rounded-full font-semibold",
    plan.ctaDark
      ? "bg-foreground text-background! hover:bg-foreground/85"
      : "bg-white/15 text-foreground! backdrop-blur-sm hover:bg-white/25",
  );

  return (
    <div className="flex flex-col rounded-2xl border bg-card p-1">
      <div
        className={cn(
          "relative overflow-hidden rounded-xl border border-white/10 p-5",
          pal.base,
        )}
      >
        <div
          className={cn(
            "pointer-events-none absolute -top-12 -right-12 size-52 rounded-full opacity-70 blur-3xl",
            pal.blobA,
          )}
        />
        <div
          className={cn(
            "pointer-events-none absolute top-1/3 -left-8 size-60 rounded-full opacity-35 blur-3xl",
            pal.blobB,
          )}
        />

        <svg
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 h-full w-full opacity-10 mix-blend-overlay"
          xmlns="http://www.w3.org/2000/svg"
        >
          <filter id={grainId}>
            <feTurbulence type="fractalNoise" baseFrequency="0.68" numOctaves="3" stitchTiles="stitch" />
            <feColorMatrix type="saturate" values="0" />
          </filter>
          <rect width="100%" height="100%" filter={`url(#${grainId})`} />
        </svg>

        <div className="relative z-10 flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <AvatarOrb shape="squircle" size="sm" color={pal.avatarColor} />
            {plan.featuredLabel ? (
              <span className="rounded-full bg-white/15 px-2.5 py-0.5 text-xs font-medium text-foreground/70 backdrop-blur-sm">
                {plan.featuredLabel}
              </span>
            ) : null}
          </div>

          <div className="space-y-0.5">
            <h3 className="text-xl font-bold tracking-tight">{plan.name}</h3>
            <p className="text-sm text-foreground/60">{plan.description}</p>
          </div>

          <div className="space-y-0.5">
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold tracking-tight">{plan.price}</span>
              {plan.originalPrice ? (
                <span className="text-base text-foreground/45 line-through">
                  {plan.originalPrice}
                </span>
              ) : null}
            </div>
            {plan.priceNote ? (
              <p className="text-xs text-foreground/50">{plan.priceNote}</p>
            ) : null}
          </div>

          {/* A CTA with nowhere to go is a button, not a link. It is disabled
              rather than hidden, so the reader can see that the plan exists
              and that buying it is not open yet — hiding it would read as the
              plan not existing. */}
          {plan.ctaDisabled || !plan.ctaHref ? (
            <Button className={ctaClass} disabled aria-disabled="true">
              {plan.ctaLabel}
            </Button>
          ) : (
            <Button className={ctaClass} asChild>
              <Link href={plan.ctaHref}>{plan.ctaLabel}</Link>
            </Button>
          )}

          {plan.ctaNote ? (
            <p className="-mt-1 text-xs text-foreground/60">{plan.ctaNote}</p>
          ) : null}
        </div>
      </div>

      <div className="flex flex-col gap-5 px-1 pt-5">
        <ul className="space-y-2.5">
          {plan.features.map((f) => (
            <li key={f} className="flex items-center gap-2 text-sm">
              <Check className="size-3.5 shrink-0 text-foreground/40" aria-hidden />
              {f}
            </li>
          ))}
        </ul>

        {plan.footerNote || plan.footerDesc ? (
          <div className="space-y-0.5 border-t border-border p-2">
            {plan.footerNote ? (
              <p className="text-xs font-semibold">{plan.footerNote}</p>
            ) : null}
            {plan.footerDesc ? (
              <p className="text-xs text-muted-foreground">{plan.footerDesc}</p>
            ) : null}
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
    <div className="w-full space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        {title || subtitle ? (
          <div className="space-y-1">
            {title ? (
              <h2 className="text-3xl font-bold tracking-tight">{title}</h2>
            ) : null}
            {subtitle ? (
              <p className="text-sm text-muted-foreground">{subtitle}</p>
            ) : null}
          </div>
        ) : null}

        {/* One group needs no switch. The vendored component always drew the
            tab row, which with a single group is a control that does nothing
            and implies choices that do not exist. */}
        {groups.length > 1 ? (
          <div className="flex items-center gap-0.5 rounded-full border border-border bg-muted p-1">
            {groups.map((g) => (
              <button
                key={g.key}
                type="button"
                onClick={() => setActive(g.key)}
                aria-pressed={active === g.key}
                className={cn(
                  "rounded-full px-4 py-1.5 text-sm font-medium transition-all duration-200",
                  active === g.key
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
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
        className={cn(
          "grid",
          plans.length === 1 && "mx-auto max-w-md",
          plans.length === 2 && "grid-2",
          plans.length >= 3 && "grid-3",
        )}
      >
        {plans.map((plan) => (
          <PlanCard key={plan.id} plan={plan} />
        ))}
      </div>
    </div>
  );
}

export default PricingCards;
