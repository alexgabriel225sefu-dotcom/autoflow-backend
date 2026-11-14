"use client";

import { useEffect, useState } from "react";
import { ProductWindow } from "./product-window";
import styles from "./product.module.css";

const tabs = [
  {
    id: "setup", label: "Set up",
    title: "Pick an instrument and a strategy.",
    body: "Fifteen ready-made strategies, each one says what it will not trade. Choose your risk, your account and review everything before you press start.",
    src: "/product/wizard.webp", ratio: "16 / 10",
    alt: "The automation setup, step two: choosing a ready-made strategy such as Trend Following.",
  },
  {
    id: "run", label: "Run",
    title: "Start on demo. The state is always on screen.",
    body: "Running, paused or stopped, the account, the rule and the Risk Guard are one glance away. Pause or stop whenever you like.",
    src: "/product/dash.webp", ratio: "16 / 8.4",
    alt: "The dashboard with automation running on a demo account.",
  },
  {
    id: "review", label: "Review",
    title: "What happened, and when.",
    body: "Each entry says when automation started, paused or stopped, or what signal was found. Orders and closed trades are in Positions and Closed trades.",
    src: "/product/journal.webp", ratio: "16 / 9.6",
    alt: "The journal: a buy decision and two hold decisions, each with its reason.",
  },
  {
    id: "track", label: "Track",
    title: "Your open positions, at your broker.",
    body: "Side, size, entry, stop and target for every open position on the demo account you connected.",
    src: "/product/positions.webp", ratio: "16 / 6.2",
    alt: "The positions page with one open EURUSD position on a demo account.",
  },
  {
    id: "look", label: "Make it yours",
    title: "Dark or light, five accent colours.",
    body: "Set the platform up the way you like to read it. Your choice follows you on every screen.",
    src: "/product/settings.webp", ratio: "16 / 10",
    alt: "Settings with the theme and accent colour choices.",
  },
] as const;

export function ProductShowcase() {
  const [active, setActive] = useState<(typeof tabs)[number]["id"]>("setup");
  // Moves through the tabs on its own until the visitor picks one.
  const [auto, setAuto] = useState(true);
  const tab = tabs.find((t) => t.id === active) ?? tabs[0];

  useEffect(() => {
    if (!auto) return;
    if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) return;
    const timer = window.setTimeout(() => {
      const i = tabs.findIndex((t) => t.id === active);
      setActive(tabs[(i + 1) % tabs.length].id);
    }, 5500);
    return () => window.clearTimeout(timer);
  }, [active, auto]);
  return (
    <div>
      <div className={styles.tabs} role="tablist" aria-label="Parts of the platform">
        {tabs.map((t) => (
          <button
            key={t.id} type="button" role="tab" id={`tab-${t.id}`}
            aria-selected={t.id === active} aria-controls="showcase-panel"
            className={styles.tab} data-auto={auto && t.id === active ? "true" : undefined} onClick={() => { setAuto(false); setActive(t.id); }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div id="showcase-panel" role="tabpanel" aria-labelledby={`tab-${tab.id}`} className={styles.panel}>
        <div>
          <h3>{tab.title}</h3>
          <p>{tab.body}</p>
        </div>
        <ProductWindow key={tab.id} src={tab.src} alt={tab.alt} ratio={tab.ratio} />
      </div>
    </div>
  );
}
