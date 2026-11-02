"use client";
/**
 * Appearance: the theme (Black or Light) and a personal accent colour.
 *
 * Both are per-browser preferences, kept in localStorage and mirrored onto
 * <html> as `data-theme` and `data-accent`. The stylesheet does the rest: the
 * tokens in globals.css are redefined under those attributes, so no component
 * has to know which theme it is in.
 *
 * The attributes are written by a tiny inline script before first paint
 * (NO_FLASH_SCRIPT, rendered in the root layout), because applying them from
 * an effect would paint the default for one frame on every load.
 *
 * The accent is deliberately a short, fixed list rather than a colour picker.
 * Every entry is held to the contrast rules and kept clear of the two hues the
 * product spends on meaning (long green, short red) by appearance.test.ts; a
 * free picker could not make either promise.
 */
import { useSyncExternalStore } from "react";

export const THEMES = [
  { id: "dark", label: "Black" },
  { id: "light", label: "Light" },
] as const;
export type ThemeId = (typeof THEMES)[number]["id"];

export const ACCENTS = [
  { id: "cream", label: "Cream" },
  { id: "ice", label: "Ice" },
  { id: "lilac", label: "Lilac" },
  { id: "orchid", label: "Orchid" },
  { id: "volt", label: "Volt" },
] as const;
export type AccentId = (typeof ACCENTS)[number]["id"];

export const DEFAULT_THEME: ThemeId = "dark";
export const DEFAULT_ACCENT: AccentId = "cream";

const THEME_KEY = "a4t-theme";
const ACCENT_KEY = "a4t-accent";
const EVENT = "a4t-appearance";
let accentFlashTimer: number | undefined;

const isTheme = (v: unknown): v is ThemeId => THEMES.some((t) => t.id === v);
const isAccent = (v: unknown): v is AccentId => ACCENTS.some((a) => a.id === v);

/**
 * Runs in <head> before the body is parsed. Self-contained (no imports, no
 * closures over this module) and wrapped in try/catch: storage can throw in a
 * private window, and a page that cannot read a preference must still render.
 * The allowed values are inlined from the lists above so a hand-edited
 * localStorage entry can never put an arbitrary string into an attribute.
 */
export const NO_FLASH_SCRIPT =
  `(function(){try{var d=document.documentElement,s=localStorage,` +
  `t=s.getItem(${JSON.stringify(THEME_KEY)}),a=s.getItem(${JSON.stringify(ACCENT_KEY)});` +
  `if(${JSON.stringify(THEMES.map((x) => x.id))}.indexOf(t)>-1)d.setAttribute("data-theme",t);` +
  `if(a&&a!==${JSON.stringify(DEFAULT_ACCENT)}&&${JSON.stringify(ACCENTS.map((x) => x.id))}.indexOf(a)>-1)d.setAttribute("data-accent",a);` +
  `}catch(e){}})();`;

function readTheme(): ThemeId {
  if (typeof document === "undefined") return DEFAULT_THEME;
  const v = document.documentElement.getAttribute("data-theme");
  return isTheme(v) ? v : DEFAULT_THEME;
}
function readAccent(): AccentId {
  if (typeof document === "undefined") return DEFAULT_ACCENT;
  const v = document.documentElement.getAttribute("data-accent");
  return isAccent(v) ? v : DEFAULT_ACCENT;
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb);
  return () => window.removeEventListener(EVENT, cb);
}

function remember(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* the choice still applies to this page */ }
}

export function setTheme(id: ThemeId) {
  if (!isTheme(id)) return;
  document.documentElement.setAttribute("data-theme", id);
  remember(THEME_KEY, id);
  window.dispatchEvent(new Event(EVENT));
}

export function setAccent(id: AccentId) {
  if (!isAccent(id)) return;
  if (id === DEFAULT_ACCENT) document.documentElement.removeAttribute("data-accent");
  else document.documentElement.setAttribute("data-accent", id);
  remember(ACCENT_KEY, id);
  // Give the user a short, unmistakable confirmation that the accent changed.
  // The attribute drives a CSS-only corner wash, so it does not add a render
  // loop or repaint every component. It is deliberately transient; the logo
  // keeps the chosen accent's quiet glow after the transition ends.
  document.documentElement.setAttribute("data-accent-flash", "true");
  if (accentFlashTimer !== undefined) window.clearTimeout(accentFlashTimer);
  accentFlashTimer = window.setTimeout(() => {
    document.documentElement.removeAttribute("data-accent-flash");
    accentFlashTimer = undefined;
  }, 900);
  window.dispatchEvent(new Event(EVENT));
}

export function useAppearance() {
  // The server snapshot is the default, so hydration agrees with the markup
  // the server sent; the real value arrives on the next render.
  const theme = useSyncExternalStore(subscribe, readTheme, () => DEFAULT_THEME);
  const accent = useSyncExternalStore(subscribe, readAccent, () => DEFAULT_ACCENT);
  return {
    theme, accent,
    setTheme,
    setAccent,
  };
}
