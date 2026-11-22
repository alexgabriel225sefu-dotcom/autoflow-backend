"use client";

import { useRef, useState } from "react";

const ACCENTS = [
  { name: "White", rgb: [247, 246, 242], deep: "#FFFFFF" },
  { name: "Blue", rgb: [138, 206, 253], deep: "#B3DEFE" },
  { name: "Purple", rgb: [178, 147, 251], deep: "#CBB5FC" },
  { name: "Pink", rgb: [233, 131, 207], deep: "#F0A6DD" },
  { name: "Lime", rgb: [206, 255, 85], deep: "#DDFF8A" },
] as const;

/**
 * Picks the accent for this page, live. It sets the same landing tokens the
 * buttons and chips already use, on the page root, so everything that follows
 * the accent changes together. It stores nothing and sends nothing.
 */
export function AccentPicker() {
  const ref = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);

  function choose(i: number) {
    setActive(i);
    const root = ref.current?.closest<HTMLElement>(".mkt");
    if (!root) return;
    const { rgb, deep } = ACCENTS[i];
    const c = rgb.join(", ");
    root.style.setProperty("--mkt-accent", `rgb(${c})`);
    root.style.setProperty("--mkt-accent-deep", deep);
    root.style.setProperty("--mkt-accent-text", `rgb(${c})`);
    root.style.setProperty("--mkt-accent-wash", `rgba(${c}, 0.07)`);
    root.style.setProperty("--mkt-accent-line", `rgba(${c}, 0.16)`);
  }

  return (
    <div className="lp-accent" ref={ref}>
      <div className="lp-accent-sw" role="radiogroup" aria-label="Accent colour">
        {ACCENTS.map((a, i) => (
          <button
            key={a.name}
            type="button"
            role="radio"
            aria-checked={active === i}
            aria-label={a.name}
            className="lp-accent-dot"
            data-on={active === i}
            style={{ background: `rgb(${a.rgb.join(", ")})` }}
            onClick={() => choose(i)}
          />
        ))}
        <span className="lp-accent-name">{ACCENTS[active].name}</span>
      </div>
      <div className="lp-accent-card" aria-hidden>
        <div className="lp-accent-side">
          <span data-on>Dashboard</span><span>Rules</span><span>Journal</span>
        </div>
        <div className="lp-accent-main">
          <p className="lp-accent-chip"><i /> Automation running</p>
          <div className="lp-accent-bar"><b /></div>
          <div className="lp-accent-btns">
            <span className="mkt-btn">Start</span>
            <span className="mkt-btn mkt-btn-outline">Pause</span>
          </div>
        </div>
      </div>
      <p className="lp-accent-note">
        The accent colours buttons, the menu and the logo. Gains and losses keep their own colours.
      </p>
    </div>
  );
}
