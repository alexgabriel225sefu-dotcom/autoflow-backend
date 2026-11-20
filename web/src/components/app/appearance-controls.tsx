"use client";
import { Check, Moon, Sun } from "lucide-react";
import { ACCENTS, THEMES, useAppearance } from "@/lib/appearance";
import { SegmentedControl } from "./segmented";

/** Theme + accent, as used on the Settings page and in the logo popover. */
export function AppearanceControls() {
  const { theme, accent, setTheme, setAccent } = useAppearance();
  return (
    <div className="appearance">
      <div className="appearance-row">
        <span className="label-xs">Theme</span>
        <SegmentedControl
          label="Theme"
          value={theme}
          onChange={setTheme}
          options={THEMES.map((t) => ({
            value: t.id,
            label: t.label,
            icon: t.id === "dark"
              ? <Moon className="ico" aria-hidden />
              : <Sun className="ico" aria-hidden />,
          }))}
        />
      </div>
      <div className="appearance-row">
        <span className="label-xs">Accent</span>
        <div className="swatches" role="radiogroup" aria-label="Accent colour">
          {ACCENTS.map((a) => (
            <button
              key={a.id}
              type="button"
              role="radio"
              aria-checked={accent === a.id}
              aria-label={a.label}
              title={a.label}
              className="sw"
              data-accent={a.id}
              onClick={() => setAccent(a.id)}
            >
              <Check className="ico" aria-hidden />
            </button>
          ))}
        </div>
        <p className="muted appearance-note">
          The accent colours buttons, the menu and the logo. Gains and losses keep
          their own colours.
        </p>
      </div>
    </div>
  );
}
