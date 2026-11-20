/**
 * The chart's colours, read from the app's own CSS variables.
 *
 * A canvas cannot use `var(--a4t-long)`; it needs the resolved colour. So the
 * variables are read from the document and handed to the library, and read
 * again whenever the theme could have changed (see `watchTheme`). That keeps
 * one source of truth for colour — the stylesheet — instead of a second
 * palette in TypeScript that drifts from it.
 *
 * A variable that does not resolve is left OUT, not replaced with a colour
 * chosen here. The library then falls back to its own default, which is
 * visibly "not themed" rather than quietly the wrong shade.
 */

export type ChartTheme = {
  up?: string;
  down?: string;
  text?: string;
  grid?: string;
  border?: string;
  background?: string;
  crosshair?: string;
  entry?: string;
  overlay?: string;
  rsi?: string;
  fontFamily?: string;
};

const TOKENS: Record<Exclude<keyof ChartTheme, "fontFamily">, string> = {
  up: "--a4t-long",
  down: "--a4t-short",
  text: "--a4t-dim",
  grid: "--a4t-line-soft",
  border: "--a4t-line",
  background: "--a4t-bg-2",
  crosshair: "--a4t-link",
  entry: "--a4t-text",
  overlay: "--a4t-link",
  rsi: "--a4t-link-strong",
};

export function readTheme(root: HTMLElement = document.documentElement): ChartTheme {
  const cs = getComputedStyle(root);
  const out: ChartTheme = {};
  for (const [key, token] of Object.entries(TOKENS) as [keyof typeof TOKENS, string][]) {
    const v = cs.getPropertyValue(token).trim();
    if (v) out[key] = v;
  }
  const font = getComputedStyle(document.body).fontFamily.trim();
  if (font) out.fontFamily = font;
  return out;
}

/** Calls `onChange` when the document's theme may have changed. Returns a cleanup. */
export function watchTheme(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class", "data-theme", "style"],
  });
  const media = typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;
  media?.addEventListener?.("change", onChange);
  return () => {
    observer.disconnect();
    media?.removeEventListener?.("change", onChange);
  };
}

/** An object without its undefined values, so "unknown" is not passed on as a setting. */
export function defined<T extends Record<string, unknown>>(o: T): Partial<T> {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined)) as Partial<T>;
}
