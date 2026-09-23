/**
 * The Apex4Traders brand lockup.
 *
 * Drawn as vectors rather than shipped as a raster: it has to stay crisp at
 * 20px in a sidebar and at 40px on a sign-in screen, and it has to inherit
 * colour so the same file works on a dark surface, on a teal fill and in a
 * disabled state.
 *
 * The monogram is a geometric A: two strokes rising to an apex, with the
 * crossbar broken into four segments for the "4". No mountain, no rocket, no
 * bull, no chart arrow and no AI motif — every one of those is a claim about
 * outcomes, and this product does not make claims about outcomes.
 */

export function BrandMark({
  size = 22, title,
}: { size?: number; title?: string }) {
  return (
    <svg
      className="mark"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role={title ? "img" : "presentation"}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
    >
      {title ? <title>{title}</title> : null}
      <rect
        x="0.75" y="0.75" width="30.5" height="30.5" rx="8"
        fill="var(--a4t-accent, #0B5960)"
        stroke="var(--a4t-accent-strong, #0E6E77)"
        strokeWidth="1.5"
      />
      {/* The apex: two strokes meeting at the top, open at the base. */}
      <path
        d="M9 24 L16 8 L23 24"
        stroke="var(--a4t-on-accent, #F4F0E8)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* The crossbar, broken into four — the 4 in Apex4Traders, read as
          rhythm rather than spelled out. */}
      <path
        d="M12.4 18.4 h2.1 M16.6 18.4 h2.1"
        stroke="var(--a4t-long, #A5E7C5)"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * Mark plus wordmark. `iconOnly` gives the mark with an accessible name, for
 * places too narrow for the word.
 */
export function BrandLockup({
  size = 22, iconOnly = false, className,
}: { size?: number; iconOnly?: boolean; className?: string }) {
  if (iconOnly) {
    return (
      <span className={className ? `brand-lockup ${className}` : "brand-lockup"}>
        <BrandMark size={size} title="Apex4Traders" />
      </span>
    );
  }
  return (
    <span className={className ? `brand-lockup ${className}` : "brand-lockup"}>
      <BrandMark size={size} />
      {/* One text node, so a screen reader reads "Apex4Traders" rather than
          "Apex", "4", "Traders" as three fragments. */}
      <span className="word">Apex4Traders</span>
    </span>
  );
}
