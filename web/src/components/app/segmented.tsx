"use client";
import { useRef } from "react";

export type SegmentOption<T extends string> = { value: T; label: string; icon?: React.ReactNode };

/**
 * A segmented control: one of N, with a thumb that slides to the choice.
 *
 * It is a radio group, not a row of toggle buttons: exactly one is chosen,
 * arrow keys move the choice, and only the chosen one is in the tab order.
 * The thumb is positioned from the chosen index in CSS (`--i`, `--n`), so it
 * needs no measuring and no layout effect, and `prefers-reduced-motion` turns
 * the slide into a jump.
 */
export function SegmentedControl<T extends string>({
  label, value, options, onChange,
}: { label: string; value: T; options: SegmentOption<T>[]; onChange: (v: T) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = Math.max(0, options.findIndex((o) => o.value === value));

  function onKey(e: React.KeyboardEvent, i: number) {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1
      : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (i + step + options.length) % options.length;
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div
      className="segc"
      role="radiogroup"
      aria-label={label}
      style={{ "--n": options.length, "--i": index } as React.CSSProperties}
    >
      <span className="segc-thumb" aria-hidden />
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={(el) => { refs.current[i] = el; }}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1}
          onClick={() => onChange(o.value)}
          onKeyDown={(e) => onKey(e, i)}
        >
          {o.icon}
          <span>{o.label}</span>
        </button>
      ))}
    </div>
  );
}
