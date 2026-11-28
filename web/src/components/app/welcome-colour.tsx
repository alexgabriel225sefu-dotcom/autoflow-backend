"use client";
/**
 * "Make it yours": shown once, on the first visit to the dashboard, so the
 * accent colour is chosen at the start instead of being found in Settings.
 *
 * The choice applies live (the card itself is drawn in it), is remembered in
 * this browser like every other appearance setting, and can be changed later
 * in Settings. A browser that already has a stored accent never sees this.
 */
import { useState, useSyncExternalStore } from "react";
import { Check, Moon, Sun } from "lucide-react";
import { ACCENTS, THEMES, useAppearance } from "@/lib/appearance";

const SEEN_KEY = "a4t-welcome-colour";
const ACCENT_KEY = "a4t-accent";

/** What a person calls each colour, not the stylesheet's name for it. */
const NAMES: Record<string, string> = {
  cream: "Cream", ice: "Blue", lilac: "Purple", orchid: "Pink", volt: "Yellow",
};

/**
 * Decided once per page load. Choosing a colour writes the accent to storage,
 * so asking again would close the card the moment a colour was picked.
 */
let decided: boolean | null = null;
function shouldShow(): boolean {
  if (decided === null) {
    try {
      decided = localStorage.getItem(SEEN_KEY) == null && localStorage.getItem(ACCENT_KEY) == null;
    } catch {
      decided = false;
    }
  }
  return decided;
}
const subscribe = () => () => {};

/** Test hook: forget the decision so the next render asks storage again. */
export function resetWelcomeColour() { decided = null; }

export function WelcomeColour() {
  const eligible = useSyncExternalStore(subscribe, shouldShow, () => false);
  const [closed, setClosed] = useState(false);
  const { theme, accent, setTheme, setAccent } = useAppearance();

  if (!eligible || closed) return null;

  const done = () => {
    try { localStorage.setItem(SEEN_KEY, "1"); } catch { /* it will simply show once more */ }
    setClosed(true);
  };

  return (
    <section className="wc" aria-labelledby="wc-title">
      <div className="wc-orb" aria-hidden="true" />
      <div className="wc-body">
        <p className="label-xs">Welcome</p>
        <h2 id="wc-title">Pick the colour you want to see.</h2>
        <p className="muted">It colours buttons, highlights and the menu. You can change it any time in Settings.</p>
        <div className="wc-swatches" role="radiogroup" aria-label="Colour">
          {ACCENTS.map((a) => (
            <button
              key={a.id} type="button" role="radio" aria-checked={accent === a.id}
              className="wc-swatch" data-accent={a.id} onClick={() => setAccent(a.id)}
            >
              <span className="sw wc-dot" data-accent={a.id}><Check className="ico" aria-hidden /></span>
              <span>{NAMES[a.id] ?? a.label}</span>
            </button>
          ))}
        </div>
        <div className="wc-row">
          <div className="wc-theme" role="radiogroup" aria-label="Theme">
            {THEMES.map((t) => (
              <button
                key={t.id} type="button" role="radio" aria-checked={theme === t.id}
                className="wc-chip" onClick={() => setTheme(t.id)}
              >
                {t.id === "dark" ? <Moon size={14} aria-hidden /> : <Sun size={14} aria-hidden />} {t.label}
              </button>
            ))}
          </div>
          <button type="button" className="btn" onClick={done}>Continue</button>
        </div>
      </div>
    </section>
  );
}
