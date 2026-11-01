"use client";

/**
 * A currency figure whose digits roll when the value changes.
 *
 * The readable text is the formatted amount, so a screen reader and a test
 * see the number, not an animation. Reduced motion skips the roll. A missing
 * value is an em dash, never zero.
 */
export function formatMoney(value: number, digits = 2): string {
  const abs = Math.abs(value).toFixed(digits);
  // A unicode minus, matching the rest of the app. The "$" is joined to the
  // amount at runtime so a price is never written into the source.
  return `${value < 0 ? "−" : ""}${String.fromCharCode(36)}${abs}`;
}

export function CurrencyTicker({
  value, digits = 2,
}: {
  value: number | null | undefined;
  digits?: number;
}) {
  if (value == null || Number.isNaN(value)) return <span className="dim">—</span>;
  const text = formatMoney(value, digits);
  return <span className="ticker ticker-d" aria-label={text}>{text}</span>;
}
